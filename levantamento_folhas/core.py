from __future__ import annotations
import hashlib, io, json, re, sqlite3, subprocess, tempfile, unicodedata, zipfile
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import pdfplumber
import openpyxl
from contextlib import contextmanager
import uuid

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'dados'
VERSION = '0.1.0'
MONEY = re.compile(r'^-?\d[\d.]*,\d{2}$')
INTEREST = {'8015','8007','0265','0260','0276','0871','8008','0175','0177','0116','0504','0810','PRNO','7945','0222','0543','0600','0811'}

@contextmanager
def archive_workspace():
    # Ordinary mkdir preserves inherited Windows ACLs, unlike mode-0700 temp dirs.
    root=DATA/'temporarios'; root.mkdir(parents=True,exist_ok=True)
    folder=root/uuid.uuid4().hex; folder.mkdir()
    try: yield folder
    finally:
        for name in ('input.rar','member.bin'):
            (folder/name).unlink(missing_ok=True)
        folder.rmdir()

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s or '')).upper() if not unicodedata.combining(c))

def cents(s):
    return int(Decimal(str(s).replace('.', '').replace(',', '.')) * 100)

def db():
    DATA.mkdir(exist_ok=True)
    c = sqlite3.connect(DATA / 'analises.sqlite')
    c.execute('CREATE TABLE IF NOT EXISTS analyses (id INTEGER PRIMARY KEY, name TEXT, created TEXT, payload TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, analysis_id INTEGER, created TEXT, note TEXT, payload TEXT)')
    return c

def save(a, note='Processamento'):
    with db() as c:
        payload = json.dumps(a, ensure_ascii=False)
        if a.get('id'):
            c.execute('UPDATE analyses SET payload=? WHERE id=?', (payload,a['id']))
        else:
            a['id'] = c.execute('INSERT INTO analyses(name,created,payload) VALUES(?,?,?)',(a['name'],datetime.now().isoformat(),payload)).lastrowid
            c.execute('UPDATE analyses SET payload=? WHERE id=?',(json.dumps(a,ensure_ascii=False),a['id']))
        c.execute('INSERT INTO audit(analysis_id,created,note,payload) VALUES(?,?,?,?)',(a['id'],datetime.now().isoformat(),note,json.dumps(a,ensure_ascii=False)))

def saved():
    with db() as c:
        return c.execute('SELECT id,name,created FROM analyses ORDER BY id DESC').fetchall()

def load(i):
    with db() as c:
        return json.loads(c.execute('SELECT payload FROM analyses WHERE id=?',(i,)).fetchone()[0])

def unpack(name, content, depth=0, budget=None):
    budget = budget if budget is not None else [0,0]
    if depth > 4: raise ValueError('Compactação excede quatro níveis.')
    budget[0] += len(content); budget[1] += 1
    if budget[0] > 1024**3 or budget[1] > 2500: raise ValueError('Limite de 1 GB expandido ou 2.500 arquivos excedido.')
    ext = Path(name).suffix.lower()
    if ext == '.pdf':
        yield name, content
    elif ext == '.zip':
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for item in z.infolist():
                if item.is_dir(): continue
                if item.file_size > 250*1024**2: raise ValueError('Arquivo interno maior que 250 MB.')
                yield from unpack(name+' :: '+item.filename,z.read(item),depth+1,budget)
    elif ext == '.rar':
        # Stream each member to stdout: never extract archive paths to the filesystem.
        (DATA/'temporarios').mkdir(parents=True,exist_ok=True)
        with archive_workspace() as tmp:
            src=Path(tmp)/'input.rar'; src.write_bytes(content)
            listing=subprocess.run(['tar','-tf',str(src)],capture_output=True,check=True,timeout=60).stdout.decode('utf-8',errors='replace')
            for member in listing.splitlines():
                if not member.lower().endswith(('.pdf','.zip','.rar')): continue
                if member.startswith(('/','\\','-')) or '..' in Path(member.replace('\\','/')).parts or ':' in member:
                    raise ValueError('Caminho inseguro no RAR.')
                target=Path(tmp)/'member.bin'
                with target.open('wb') as out:
                    proc=subprocess.Popen(['tar','-xOf',str(src),member],stdout=out,stderr=subprocess.PIPE)
                    import time
                    start=time.monotonic()
                    while proc.poll() is None:
                        if target.stat().st_size>250*1024**2 or time.monotonic()-start>60:
                            proc.kill(); proc.wait(); raise ValueError('Limite de extração RAR excedido.')
                        time.sleep(.05)
                    if proc.returncode: raise ValueError('Não foi possível ler membro RAR: '+member)
                yield from unpack(name+' :: '+member,target.read_bytes(),depth+1,budget)

def lines(words):
    groups=[]
    for w in sorted(words,key=lambda w:(w['top'],w['x0'])):
        if not groups or abs(groups[-1][0]-w['top'])>2.5: groups.append([w['top'],[]])
        groups[-1][1].append(w)
    return [(y,sorted(ws,key=lambda w:w['x0'])) for y,ws in groups]

def extract(name, content):
    digest=hashlib.sha256(content).hexdigest()
    (DATA/'pdfs').mkdir(parents=True,exist_ok=True)
    path=DATA/'pdfs'/f'{digest}.pdf'; path.write_bytes(content)
    doc={'hash':digest,'arquivo':name,'path':str(path),'rubricas':[],'totais':{},'bases':{},'alertas':[],'versao':VERSION}
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        doc['paginas']=len(pdf.pages)
        first=pdf.pages[0].extract_text() or ''
        if 'RESUMO DA HIERARQUIA EMPRESARIAL' not in first: raise ValueError('Layout não reconhecido como resumo RH3.')
        cnpj=re.search(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}',first)
        doc['cnpj']=cnpj.group() if cnpj else ''
        doc['empresa']=first.splitlines()[0].split('CNPJ:')[0].strip()
        dt=re.search(r'\b\d{2}/(\d{2})/(20\d{2})\b',next((l for l in first.splitlines() if 'Período' in l),''))
        if not dt: raise ValueError('Competência não identificada no período do cabeçalho.')
        doc['competencia']=dt[2]+'-'+dt[1]
        header=next((l for l in first.splitlines() if 'Período' in l),'')
        doc['cabecalho']=header
        nh=norm(header)
        doc['tipo']='Complementar' if 'COMPLEMENTAR' in nh else 'Adiantamento 13º' if 'ADIANT' in nh else '13º final' if '13' in nh.split('PAGTO')[0].split(':')[1] else 'Mensal'
        years=re.findall(r'20\d{2}',Path(name).name)
        if years and years[-1]!=dt[2]: doc['alertas'].append('Ano do nome diverge do período interno.')
        if 'DECIMO' in norm(name) or '13' in Path(name).name:
            if doc['tipo']=='Complementar': doc['alertas'].append('Nome indica 13º, cabeçalho indica complementar.')
        for pn,page in enumerate(pdf.pages,1):
            words=page.extract_words(x_tolerance=1.5,y_tolerance=2)
            split=page.width/2
            for side,left,right in [('Provento',0,split),('Desconto',split,page.width)]:
                ls=lines([w for w in words if left<=w['x0']<right])
                qty_x=None; ref_x=None; active=False
                for y,ws in ls:
                    text=' '.join(w['text'] for w in ws); n=norm(text)
                    if 'EVENTO' in n and 'DESCR' in n:
                        qty_x=next((w['x0'] for w in ws if w['text'].startswith('Qtd')),None)
                        ref_x=next((w['x0'] for w in ws if w['text'].startswith('Refer')),None)
                        active=True; continue
                    if n.startswith('TOTAL DE PROVENTOS') or 'TOTAL DE DESCONTOS' in n: active=False
                    monetary=[w for w in ws if MONEY.match(w['text'])]
                    if active and ws and re.fullmatch(r'\d{4}|[A-Z]{4}',ws[0]['text']) and monetary:
                        value=monetary[-1]
                        desc=[w['text'] for w in ws[1:] if qty_x is not None and w['x0']<qty_x-5]
                        qty=[w['text'] for w in ws[1:] if qty_x is not None and ref_x is not None and qty_x-5<=w['x0']<ref_x-5]
                        doc['rubricas'].append({'codigo':ws[0]['text'],'descricao':' '.join(desc),'lado':side,'quantidade':' '.join(qty),'valor_centavos':cents(value['text']),'pagina':pn,'linha':text})
                    for label,key in [('TOTAL DE PROVENTOS','proventos'),('TOTAL DE DESCONTOS','descontos'),('TOTAL LIQUIDO','liquido'),('ARREDONDAMENTO','arredondamento')]:
                        if label in n and monetary: doc['totais'][key]=cents(monetary[-1]['text'])
                    if '(+) SALARIO FAMILIA' in n and monetary: doc['totais']['familia']=cents(monetary[-1]['text'])
                    if n.startswith('BASE EMPRESA') and monetary:
                        label=' '.join(w['text'] for w in ws if w['x0']<monetary[-1]['x0'])
                        key='13' if 'SOBRE 13' in norm(label) else 'mensal'
                        doc['bases'][key]=doc['bases'].get(key,0)+cents(monetary[-1]['text'])
        if not doc['rubricas']: raise ValueError('Nenhuma rubrica extraída; revisão do layout necessária.')
    doc['checagens']=[]
    for side,key in [('Provento','proventos'),('Desconto','descontos')]:
        actual=sum(r['valor_centavos'] for r in doc['rubricas'] if r['lado']==side)
        expected=doc['totais'].get(key)
        doc['checagens'].append({'teste':key,'informado_centavos':expected,'extraido_centavos':actual,'diferenca_centavos':None if expected is None else actual-expected})
    t=doc['totais']
    if all(k in t for k in ['proventos','descontos','liquido','familia','arredondamento']):
        calc=t['proventos']-t['descontos']+t['familia']+t['arredondamento']
        doc['checagens'].append({'teste':'liquido','informado_centavos':t['liquido'],'extraido_centavos':calc,'diferenca_centavos':calc-t['liquido']})
    return doc

def import_catalog(path_or_bytes):
    w=openpyxl.load_workbook(path_or_bytes,read_only=True,data_only=True)
    try:
        if '00_empresa' not in w: raise ValueError('Relatório sem identificação 00_empresa.')
        it=w['00_empresa'].iter_rows(values_only=True); headers=next(it); ident=dict(zip(headers,next(it)))
        employer=re.sub(r'\D','',str(ident.get('cnpj_empregador','')))
        if len(employer) not in (8,14): raise ValueError('CNPJ do relatório não identificado.')
        sheet='apoio_s1010' if 'apoio_s1010' in w else '02_rubricas_cp'
        it=w[sheet].iter_rows(values_only=True); hdr=next(it); result=[]
        for row in it:
            r=dict(zip(hdr,row))
            if not r.get('cod_rubr'): continue
            result.append({k:str(r.get(k) or '') for k in ['cod_rubr','ide_tab_rubr','dsc_rubr','cod_inc_cp','tp_rubr','ini_valid','fim_valid','arquivo_origem']})
        return {'empresa_raiz':employer[:8],'rubricas':result,'fonte':sheet}
    finally: w.close()

def key_for(d,r):
    return '|'.join([d['cnpj'],d['competencia'],d['tipo'],r['codigo'],r['descricao'],r['lado']])

def classify(d,r,catalog,decisions):
    key=key_for(d,r)
    base={'chave':key,'selecionada':r['codigo'] in INTEREST,'rating':'Sem classificação','efeito':'Pendente','base':'Mensal','justificativa':'','origem':'Sem cadastro válido','codIncCP':''}
    if catalog and re.sub(r'\D','',d['cnpj'])[:8]==catalog['empresa_raiz']:
        matches=[x for x in catalog['rubricas'] if x['cod_rubr']==r['codigo'] and x['ini_valid'] and x['ini_valid']<=d['competencia'] and (not x['fim_valid'] or x['fim_valid']>=d['competencia'])]
        signatures={(x['ide_tab_rubr'],x['dsc_rubr'],x['cod_inc_cp'],x['tp_rubr']) for x in matches}
        if len(signatures)==1:
            x=matches[0]; code=x['cod_inc_cp']; base['codIncCP']=code; base['origem']='S-1010: '+x['dsc_rubr']
            base['base']='13º' if code in ('12','14','16','22','26') else 'Mensal'
            # Conservative prototype: only exact semantic matches and ordinary provento/desconto suggest a base effect.
            same=norm(x['dsc_rubr'])==norm(r['descricao'])
            if same and code=='00': base['efeito']='Não integra (sugestão)'
            elif same and code in ('11','12') and x['tp_rubr'] in ('1','2'):
                expected='Provento' if x['tp_rubr']=='1' else 'Desconto'
                if expected==r['lado']: base['efeito']='Acrescenta (sugestão)' if expected=='Provento' else 'Reduz (sugestão)'
            elif code in ('21','22','25','26'): base['origem']+=' — maternidade: validar tratamento patronal e período'
        elif len(signatures)>1: base['origem']='Cadastro ambíguo: versões/tabelas divergentes'
    base.update(decisions.get(key,{}))
    return base

def details(a):
    out=[]
    for d in a['docs']:
        for r in d['rubricas']:
            cl=classify(d,r,a.get('catalog'),a.get('decisions',{}))
            out.append({'cnpj':d['cnpj'],'empresa':d['empresa'],'competencia':d['competencia'],'tipo':d['tipo'],**r,**cl,'arquivo':d['arquivo'],'documento':d['hash']})
    return out

def reconciliation(a):
    rows=details(a); out=[]
    for d in a['docs']:
        items=[r for r in rows if r['documento']==d['hash']]
        pending=sum(r['efeito']=='Pendente' for r in items)
        unconfirmed=sum('sugestão' in r['efeito'] for r in items)
        for target,key in [('Mensal','mensal'),('13º','13')]:
            selected=[r for r in items if r['base']==target]
            value=sum(r['valor_centavos']*(1 if r['efeito'].startswith('Acrescenta') else -1 if r['efeito'].startswith('Reduz') else 0) for r in selected)
            expected=d['bases'].get(key)
            difference=None if expected is None else value-expected
            status='Pendente' if pending else 'Hipótese com sugestões' if unconfirmed else 'Sem base informada' if expected is None else 'Confere aritmeticamente' if abs(difference)<=1 else 'Divergente'
            out.append({'cnpj':d['cnpj'],'competencia':d['competencia'],'tipo':d['tipo'],'base':target,'informada_centavos':expected,'reconstruida_centavos':value,'diferenca_centavos':difference,'rubricas_pendentes':pending,'sugestoes':unconfirmed,'estado':status,'arquivo':d['arquivo']})
    return out

def export_excel(a):
    from openpyxl.styles import Font, PatternFill, Alignment
    w=openpyxl.Workbook(); w.remove(w.active)
    def sheet(name,rows):
        s=w.create_sheet(name)
        if not rows: s.append(['Sem registros']); return
        headers=list(rows[0]); s.append([h.replace('_centavos',' (R$)') for h in headers])
        for row in rows:
            vals=[]
            for h in headers:
                value=row.get(h)
                if h.endswith('_centavos') and value is not None: value=value/100
                if isinstance(value,(dict,list)): value=json.dumps(value,ensure_ascii=False)
                if isinstance(value,str) and value.startswith(('=','+','-','@')): value="'"+value
                vals.append(value)
            s.append(vals)
        s.freeze_panes='A2'; s.auto_filter.ref=s.dimensions
        for cell in s[1]: cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='17324D')
        for i,h in enumerate(headers,1):
            s.column_dimensions[openpyxl.utils.get_column_letter(i)].width=min(60,max(16,len(h)+3))
            if h.endswith('_centavos'):
                for col in s.iter_cols(min_col=i,max_col=i,min_row=2):
                    for c in col: c.number_format='#,##0.00'
        if 'rating' in headers:
            col=headers.index('rating')+1
            for row in s.iter_rows(min_row=2):
                c=row[col-1]
                color={'Verde':'D9EAD3','Amarelo':'FFF2CC'}.get(c.value)
                if color: c.fill=PatternFill('solid',fgColor=color)
    rows=details(a); selected=[r for r in rows if r['selecionada']]
    grouped={}
    for r in selected:
        k=(r['cnpj'],r['codigo'],r['descricao'],r['rating'],r['efeito'])
        grouped[k]=grouped.get(k,0)+r['valor_centavos']
    sheet('Resumo',[{'indicador':'Análise','valor':a['name']},{'indicador':'Situação','valor':'Preliminar: valores encontrados não equivalem a exclusão confirmada ou crédito.'},{'indicador':'Gerado em','valor':datetime.now().isoformat(timespec='seconds')},{'indicador':'PDFs processados','valor':len(a['docs'])},{'indicador':'Documentos com erro','valor':len(a.get('errors',[]))}])
    sheet('Consolidado',[dict(zip(['cnpj','codigo','descricao','rating','efeito'],k),valor_centavos=v) for k,v in sorted(grouped.items())])
    sheet('Por competencia',[{k:r[k] for k in ['cnpj','competencia','tipo','codigo','descricao','valor_centavos','efeito','rating','arquivo','pagina']} for r in selected])
    sheet('Rubricas detalhadas',rows)
    sheet('Conferencia bases',reconciliation(a))
    sheet('Conferencia extracao',[{'arquivo':d['arquivo'],**c} for d in a['docs'] for c in d['checagens']])
    sheet('Documentos',[{k:d.get(k) for k in ['arquivo','cnpj','competencia','tipo','paginas','hash','alertas']} for d in a['docs']])
    sheet('Erros',a.get('errors',[]))
    sheet('Criterios',[{'criterio':'Versão','valor':VERSION},{'criterio':'Incidências','valor':'Sugestões por S-1010, com vigência e empresa. Tratamentos específicos permanecem pendentes.'},{'criterio':'Rating','valor':'Classificação atribuída pela equipe; não representa validação jurídica automática.'},{'criterio':'Revisão','valor':'Decisões manuais registradas por empresa, competência, tipo, código, descrição e lado.'}])
    sheet('Decisoes',[{'chave':k,**v} for k,v in a.get('decisions',{}).items()])
    b=io.BytesIO(); w.save(b); return b.getvalue()
