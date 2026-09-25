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
VERSION = '0.6.0'
PREVIDENCIA = {
    'base_empresa_total': 'Total da base empresa',
    'previdencia_empresa_total': 'Total de previdência empresa',
    'rat_total': 'RAT — valor total',
    'segurados_total': 'Contribuições descontadas dos segurados',
}
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
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(s or '')).upper() if not unicodedata.combining(c)).split())

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
    doc={'hash':digest,'arquivo':name,'path':str(path),'rubricas':[],'totais':{},'bases':{},'previdencia':{},'alertas':[],'versao':VERSION}
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
                    for label,key in [('TOTAL DA BASE EMPRESA','base_empresa_total'),('TOTAL DE PREVIDENCIA EMPRESA','previdencia_empresa_total'),('VALOR TOTAL DO RAT','rat_total'),('TOTAL DAS CONTRIBUICOES DESCONTADAS','segurados_total')]:
                        if n.startswith(label) and monetary:
                            doc['previdencia'][key]={'valor_centavos':cents(monetary[-1]['text']),'pagina':pn,'rotulo_original':text}
                    if n.startswith('BASE EMPRESA') and monetary:
                        label=' '.join(w['text'] for w in ws if w['x0']<monetary[-1]['x0'])
                        key='13' if 'SOBRE 13' in norm(label) else 'mensal'
                        doc['bases'][key]=doc['bases'].get(key,0)+cents(monetary[-1]['text'])
        if not doc['rubricas']: raise ValueError('Nenhuma rubrica extraída; revisão do layout necessária.')
    doc['grupos_empresa']=extract_company_groups(content)
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

def brl(value):
    """Format cents for display only; calculations and XLSX retain numeric values."""
    if value is None: return 'Não informado'
    amount=Decimal(int(value))/100
    return 'R$ '+format(amount,',.2f').replace(',','X').replace('.',',').replace('X','.')


from functools import lru_cache

@lru_cache(maxsize=2048)
def similar_descriptions(description, choices):
    from difflib import SequenceMatcher
    target=norm(description)
    return tuple(code+' — '+name for code,name in choices if SequenceMatcher(None,target,norm(name)).ratio()>=0.9)[:5]


def classify(d,r,catalog,decisions):
    key=key_for(d,r)
    base={'chave':key,'selecionada':False,'rating':'Sem classificação','efeito':'Pendente',
          'base':'Não determinada','justificativa':'','origem':'Sem relatório de incidência','codIncCP':'',
          'descricao_relatorio':'','vigencia_relatorio':'','correspondencia':'Sem relatório',
          'motivo':'Importe o relatório de incidência da empresa.','efeito_relatorio':'Pendente',
          'referencia':'Não determinada','fonte_referencia':'','natureza':'A conferir',
          'base_candidata':'','sinal_candidato':0,'criterio_candidato':''}
    employer=re.sub(r'\D','',d['cnpj'])[:8]
    if catalog and employer!=catalog['empresa_raiz']:
        base.update(correspondencia='Empresa diferente',origem='Relatório pertence a outro CNPJ',motivo='Importe o relatório da empresa desta folha.')
    elif catalog:
        code_rows=[x for x in catalog['rubricas'] if x['cod_rubr']==r['codigo']]
        valid=[x for x in code_rows if x['ini_valid'] and x['ini_valid']<=d['competencia'] and (not x['fim_valid'] or x['fim_valid']>=d['competencia'])]
        candidates=valid or code_rows
        historical=not valid
        if not candidates:
            base.update(correspondencia='Não localizada',origem='Código não localizado no relatório',motivo='Não há correspondência para este código.')
            labels=similar_descriptions(r['descricao'],tuple(sorted({(x['cod_rubr'],x['dsc_rubr']) for x in catalog['rubricas']})))
            if labels: base.update(correspondencia='Descrição semelhante; código diferente',descricao_relatorio=' | '.join(labels),motivo='Sugestões por descrição, sem correspondência confirmada nem projeção numérica.')
        else:
            codes={x['cod_inc_cp'] for x in candidates}; types={x['tp_rubr'] for x in candidates}
            tables={x['ide_tab_rubr'] for x in candidates}
            exact=[x for x in candidates if norm(x['dsc_rubr'])==norm(r['descricao'])]
            base.update(codIncCP=' / '.join(sorted(codes)),descricao_relatorio=' | '.join(sorted({x['dsc_rubr'] for x in candidates})),
                        vigencia_relatorio=' | '.join(sorted({x['ini_valid']+' a '+(x['fim_valid'] or 'sem fim informado') for x in candidates})),
                        fonte_referencia=' | '.join(sorted({x.get('arquivo_origem','') for x in candidates})))
            identity=bool(exact) and len(tables)==1
            expected_type='1' if r['lado']=='Provento' else '2'
            # Different descriptions do not override a fiscal disagreement. One exact
            # identity and agreement across ALL candidate fiscal records are required.
            concordant=len(codes)==1 and len(types)==1
            insured=identity and types=={'2'} and r['lado']=='Desconto' and bool(codes & {'31','32'}) and codes <= {'00','31','32'}
            if identity and (concordant or insured):
                def distance(item):
                    def month(value):
                        try: return int(value[:4])*12+int(value[5:7])
                        except (ValueError,TypeError): return None
                    target=month(d['competencia']); start=month(item['ini_valid']); end=month(item['fim_valid'])
                    if start is None: return 999999
                    if target<start: return start-target
                    if end is not None and target>end: return target-end
                    return 0
                chosen=min(exact,key=lambda x:(distance(x),x['ini_valid'],x.get('arquivo_origem','')))
                code=chosen['cod_inc_cp']
                variants=len({norm(x['dsc_rubr']) for x in candidates})>1
                base.update(origem='S-1010: '+chosen['dsc_rubr'],
                            correspondencia='Código e descrição: projeção histórica' if historical else 'Código e vigência compatíveis',
                            referencia='Projeção pelo cadastro disponível' if historical else 'Cadastro compatível com o período',
                            vigencia_relatorio=chosen['ini_valid']+' a '+(chosen['fim_valid'] or 'sem fim informado'))
                if insured:
                    base.update(efeito='Não integra (sugestão)',base='Não se aplica',natureza='Contribuição do segurado',
                                motivo='Registros 31/32 e eventuais 00 representam desconto do segurado sem composição da base patronal. Divergência cadastral preservada em Código CP.')
                elif types!={expected_type}:
                    base['motivo']='Tipo do cadastro diverge do lado provento/desconto do PDF ou é informativo; conferir tratamento.'
                elif code=='00':
                    base.update(efeito='Não integra (sugestão)',base='Não se aplica',natureza='Sem incidência no cadastro',motivo='Código 00 no cadastro correspondente; não comprova tratamento histórico.')
                elif code in ('11','12'):
                    base.update(efeito='Acrescenta (sugestão)' if expected_type=='1' else 'Reduz (sugestão)',
                                base='Mensal' if code=='11' else '13º',natureza='Provento' if expected_type=='1' else 'Redução indicada no cadastro',
                                motivo='Código '+code+' e tipo '+expected_type+' concordantes em todos os registros candidatos.')
                elif code in ('21','22','25','26'):
                    base.update(base='13º' if code in ('22','26') else 'Mensal',natureza='Tratamento patronal específico',motivo='Maternidade: validar período e tratamento patronal; não somada automaticamente.')
                else:
                    base.update(natureza='Tratamento específico',motivo='Código técnico ou tratamento específico; não incluído automaticamente.')
                if variants:
                    base['motivo']+=' Há variações de descrição no cadastro, mas uma corresponde exatamente à folha após uniformizar espaços e acentos.'
            else:
                if len(tables)>1 or not concordant:
                    base.update(correspondencia='Conflito no histórico' if historical else 'Cadastro ambíguo',origem='Versões/tabelas divergentes',motivo='Incidência, tipo ou tabela divergentes; nenhuma versão escolhida para fechar a base.')
                else:
                    base.update(correspondencia='Descrição diferente',motivo='Incidência e tipo concordantes, mas nenhuma descrição corresponde à folha; conferir identidade.')
                # A conflict may support a separate what-if diagnostic, never an
                # automatic adopted effect or a subset-sum search against a target.
                positive=codes & {'11','12'}
                if identity and types=={expected_type} and len(positive)==1 and codes <= positive | {'00'}:
                    code=next(iter(positive))
                    base.update(base_candidata='Mensal' if code=='11' else '13º',sinal_candidato=1 if expected_type=='1' else -1,
                                criterio_candidato='Mesmo código, descrição e tipo; versões divergem entre incidência '+code+' e 00. Cenário condicionado à validação do cadastro.')
    if base['referencia']=='Projeção pelo cadastro disponível':
        base['motivo']+=' Referência de outra época; tratamento da competência não comprovado.'
    if base['efeito']=='Pendente' and base['referencia']!='Não determinada':
        base['referencia']='Tratamento específico — referência histórica' if base['referencia'].startswith('Projeção') else 'Tratamento específico — cadastro do período'
    base['efeito_relatorio']=base['efeito']
    base.update(decisions.get(key,{}))
    if key in decisions: base['motivo']+=' Critério manual preservado: '+base.get('justificativa','')
    return base


def participation_group(row):
    effect=row['efeito']
    if effect.startswith('Acrescenta'): return 'Possíveis acréscimos'
    if effect.startswith('Reduz'): return 'Reduções da base'
    if effect.startswith('Não integra'): return 'Fora da base segundo cadastro'
    return 'Não determinado'


def selection_key(row):
    # Selection is per document, independent of a shared rule for the competence.
    return row['documento']+'|'+row['chave']


def details(a):
    out=[]
    for d in a['docs']:
        for r in d['rubricas']:
            cl=classify(d,r,a.get('catalog'),a.get('decisions',{}))
            row={'cnpj':d['cnpj'],'empresa':d['empresa'],'competencia':d['competencia'],'tipo':d['tipo'],**r,**cl,'arquivo':d['arquivo'],'documento':d['hash']}
            row['grupo']=participation_group(row)
            row['selecionada']=a.get('selections',{}).get(selection_key(row),row['selecionada'])
            row['situacao_patronal']=a.get('regimes',{}).get(d['cnpj']+'|'+d['competencia'],'Não verificada')
            out.append(row)
    return out

PREVIDENCIA_FILTERS = ['Todas','Maior que zero','Igual a zero','Não localizado','Menor que zero']


def previdencia_status(document):
    value=document.get('previdencia',{}).get('previdencia_empresa_total',{}).get('valor_centavos')
    if value is None: return 'Não localizado'
    if value>0: return 'Maior que zero'
    if value<0: return 'Menor que zero'
    return 'Igual a zero'


def filter_previdencia(documents, choice):
    if choice not in PREVIDENCIA_FILTERS: raise ValueError('Filtro previdenciário inválido.')
    return [d for d in documents if choice=='Todas' or previdencia_status(d)==choice]


def previdencia_rows(d):
    result=[]
    for key,label in PREVIDENCIA.items():
        item=d.get('previdencia',{}).get(key,{})
        result.append({'cnpj':d['cnpj'],'competencia':d['competencia'],'tipo':d['tipo'],
                       'indicador':label,'valor_centavos':item.get('valor_centavos'),
                       'situacao':'Informado no PDF' if item else 'Não localizado no PDF',
                       'pagina':item.get('pagina'),'arquivo':d['arquivo']})
    return result

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
                    for c in col: c.number_format='[$R$-416] #,##0.00'
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
    sheet('Resumo',[{'indicador':'Análise','valor':a['name']},{'indicador':'Filtro total previdência empresa','valor':a.get('filtro_previdencia','Todas')},{'indicador':'Situação','valor':'Preliminar: valores encontrados não equivalem a exclusão confirmada ou crédito.'},{'indicador':'Gerado em','valor':datetime.now().isoformat(timespec='seconds')},{'indicador':'PDFs processados','valor':len(a['docs'])},{'indicador':'Documentos com erro','valor':len(a.get('errors',[]))}])
    sheet('Consolidado',[dict(zip(['cnpj','codigo','descricao','rating','efeito'],k),valor_centavos=v) for k,v in sorted(grouped.items())])
    sheet('Por competencia',[{k:r[k] for k in ['cnpj','competencia','tipo','codigo','descricao','valor_centavos','efeito','rating','arquivo','pagina']} for r in selected])
    view_fields=['cnpj','competencia','tipo','codigo','descricao','valor_centavos','grupo','base','codIncCP','descricao_relatorio','vigencia_relatorio','referencia','fonte_referencia','correspondencia','motivo','natureza','base_candidata','criterio_candidato','efeito_relatorio','efeito','selecionada','rating','situacao_patronal','arquivo','pagina']
    sheet('Cruzamento por folha',[{k:r[k] for k in view_fields} for r in rows])
    sheet('Possiveis acrescimos',[{k:r[k] for k in view_fields} for r in rows if r['grupo']=='Possíveis acréscimos'])
    sheet('Reducoes da base',[{k:r[k] for k in view_fields} for r in rows if r['grupo']=='Reduções da base'])
    sheet('Pendencias',[{k:r[k] for k in view_fields} for r in rows if r['grupo']=='Não determinado'])
    sheet('Rubricas detalhadas',rows)
    sheet('Resumo previdenciario',[r for d in a['docs'] for r in previdencia_rows(d)])
    sheet('Grupos base empresa',[r for d in a['docs'] for r in company_group_rows(d)])
    sheet('Referencias base empresa',[{'cnpj':d['cnpj'],'competencia':d['competencia'],'tipo':d['tipo'],**r,'arquivo':d['arquivo']} for d in a['docs'] for r in company_summary(d)])
    sheet('Conferencia bases',reconciliation(a))
    sheet('Memoria composicao',composition_trace(a,rows))
    sheet('Indicios por quantidade',[r for d in a['docs'] for r in relationship_hints(d,rows)])
    sheet('Panorama das bases',global_overview(a['docs']))
    sheet('Conferencia extracao',[{'arquivo':d['arquivo'],**c} for d in a['docs'] for c in d['checagens']])
    sheet('Documentos',[{k:d.get(k) for k in ['arquivo','cnpj','competencia','tipo','paginas','hash','alertas']} for d in a['docs']])
    sheet('Erros',a.get('errors',[]))
    sheet('Criterios',[{'criterio':'Versão','valor':VERSION},{'criterio':'Incidências','valor':'Sugestões por S-1010, com vigência e empresa. Tratamentos específicos permanecem pendentes.'},{'criterio':'Rating','valor':'Classificação atribuída pela equipe; não representa validação jurídica automática.'},{'criterio':'Revisão','valor':'Decisões manuais registradas por empresa, competência, tipo, código, descrição e lado.'}])
    sheet('Situacao patronal',[{'empresa_competencia':k,'situacao':v,'suporte':a.get('regime_evidence',{}).get(k,'')} for k,v in a.get('regimes',{}).items()])
    sheet('Decisoes',[{'chave':k,**v} for k,v in a.get('decisions',{}).items()])
    b=io.BytesIO(); w.save(b); return b.getvalue()


def extract_company_groups(content):
    """Pair base and contribution by physical PDF row, never by amount or count."""
    result=[]
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for pn,page in enumerate(pdf.pages,1):
            for y,ws in lines(page.extract_words(x_tolerance=1.5,y_tolerance=2)):
                left=[w['text'] for w in ws if w['x0']<page.width/2]
                right=[w['text'] for w in ws if w['x0']>=page.width/2]
                label=' '.join(left); counterpart=' '.join(right)
                if not norm(label).startswith('BASE EMPRESA'): continue
                amounts=[i for i,t in enumerate(left) if MONEY.fullmatch(t)]
                if not amounts: continue
                pos=amounts[-1]
                qty=int(left[pos-1]) if pos and left[pos-1].isdigit() else None
                matched=norm(counterpart).startswith(('VALOR DA PREVIDENCIA EMPRESA','VALOR PREV. EMPRESA'))
                values=[t for t in right if MONEY.fullmatch(t)] if matched else []
                contribution=cents(values[-1]) if values else None
                rates=[t for t in right if re.fullmatch(r'\d+(?:,\d+)?%',t)] if matched else []
                rate=Decimal(rates[-1][:-1].replace(',','.')) if rates else None
                group=('Contribuição zerada' if contribution==0 else 'Alíquota de 20%' if rate==20 and contribution is not None else 'Outra alíquota' if rate is not None and contribution is not None else 'Não determinado')
                result.append({'base':'13º' if 'SOBRE 13' in norm(label) else 'Mensal',
                    'grupo':group,'quantidade_base':qty,'aliquota_percentual':float(rate) if rate is not None else None,
                    'base_centavos':cents(left[pos]),'contribuicao_centavos':contribution,
                    'pagina':pn,'linha_base':label,'linha_contribuicao':counterpart if matched else ''})
    return result


def validated_company_groups(d):
    """Assess saved raw lines on read; never reorder pairs or rewrite evidence."""
    result=[]
    from decimal import ROUND_HALF_UP
    for raw in d.get('grupos_empresa',[]):
        g=dict(raw)
        match=re.search(r'(\d+)\s+(?:\d+(?:,\d+)?%\s+)?-?\d[\d.]*,\d{2}\s*$',g.get('linha_contribuicao',''))
        qty=int(match[1]) if match else None
        amount=g.get('contribuicao_centavos');rate=g.get('aliquota_percentual');base=g.get('base_centavos')
        g.update(quantidade_contribuicao=qty,diferenca_aritmetica_centavos=None,limite_triagem_centavos=None,validacao='A conferir',motivo_validacao='Contribuição ou alíquota não identificada.')
        if amount==0 and g.get('grupo')=='Contribuição zerada':
            g.update(validacao='Zero informado',motivo_validacao='Zero transcrito do PDF; não comprova desoneração ou pagamento.')
        elif amount is not None and rate is not None and base is not None:
            expected=int((Decimal(base)*Decimal(str(rate))/100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
            delta=amount-expected
            # Screening bound, not a claim about the payroll's rounding algorithm.
            bound=max(1,g.get('quantidade_base') or 1)
            g.update(diferenca_aritmetica_centavos=delta,limite_triagem_centavos=bound)
            if qty is None or g.get('quantidade_base') is None:
                g['motivo_validacao']='Quantidade de um dos lados não identificada; vínculo não validado.'
            elif qty!=g['quantidade_base']:
                g['motivo_validacao']='Quantidades diferentes entre base e contribuição; conferir vínculo das linhas.'
            elif abs(delta)>bound:
                g['motivo_validacao']='Diferença excede o limite de triagem de um centavo por quantidade; conferir memória do cálculo.'
            else:
                g.update(validacao='Coerência aritmética' if delta==0 else 'Pequena diferença aritmética',
                         motivo_validacao='Quantidade e cálculo agregados compatíveis; não comprova composição por rubrica.' if delta==0 else 'Diferença dentro do limite de triagem de um centavo por quantidade. Arredondamento individual é hipótese, não confirmação.')
        result.append(g)
    return result


def company_group_rows(d):
    return [{'cnpj':d['cnpj'],'competencia':d['competencia'],'tipo':d['tipo'],**g,'arquivo':d['arquivo']} for g in validated_company_groups(d)]


def company_summary(d):
    groups=validated_company_groups(d);out=[]
    for target,key in [('Mensal','mensal'),('13º','13')]:
        items=[g for g in groups if g['base']==target]
        total=d.get('bases',{}).get(key)
        difference=sum(g['base_centavos'] for g in items)-total if items and total is not None else None
        unsafe=any(g['validacao']=='A conferir' for g in items) or difference not in (None,0)
        row={'base':target,'total_informado_centavos':total}
        for label,field in [('Alíquota de 20%','base_20_centavos'),('Contribuição zerada','base_zerada_centavos'),('Outra alíquota','base_outra_aliquota_centavos')]:
            row[field]=sum(g['base_centavos'] for g in items if g['grupo']==label) if items and not unsafe else None
        row['base_nao_determinada_centavos']=sum(g['base_centavos'] for g in items) if unsafe else 0 if items else None
        row['diferenca_extracao_centavos']=difference
        if not items:status='Grupos não localizados'
        elif unsafe:status='Vínculo entre base e contribuição a conferir'
        elif row['base_outra_aliquota_centavos']:status='Outra alíquota informada'
        elif row['base_20_centavos'] and row['base_zerada_centavos']:status='Grupos mistos'
        elif row['base_20_centavos']:status='Somente linhas com 20%'
        elif row['base_zerada_centavos']:status='Somente contribuição zerada'
        else:status='Valores zerados no PDF'
        row['situacao_grupos']=status
        row['observacao']='Distribuição entre grupos suspensa por inconsistência; valores originais preservados no detalhamento.' if unsafe else 'Referência documental, sem identificação individual ou comprovação do regime tributário.'
        out.append(row)
    return out


def composition_trace(a,rows=None):
    rows=details(a) if rows is None else rows
    out=[]
    for r in rows:
        target=r['base'];role='Não entra na composição';signed=0;criterion=r['motivo']
        if r['efeito'].startswith(('Acrescenta','Reduz')) and target in ('Mensal','13º'):
            role='Acréscimo indicado' if r['efeito'].startswith('Acrescenta') else 'Redução indicada'
            signed=r['valor_centavos']*(1 if role=='Acréscimo indicado' else -1)
        elif r['efeito']=='Pendente':
            role='Pendente sem valor atribuído';signed=None
            if r.get('base_candidata'):
                role='Candidata condicionada';target=r['base_candidata']
                signed=r['valor_centavos']*r['sinal_candidato'];criterion=r['criterio_candidato']
        out.append({'cnpj':r['cnpj'],'competencia':r['competencia'],'tipo':r['tipo'],'documento':r['documento'],
                    'codigo':r['codigo'],'descricao':r['descricao'],'lado':r['lado'],'base':target,'papel':role,
                    'valor_centavos':r['valor_centavos'],'parcela_centavos':signed,'codIncCP':r['codIncCP'],
                    'referencia':r['referencia'],'criterio':criterion,'arquivo':r['arquivo'],'pagina':r['pagina']})
    return out


def relationship_hints(d,rows):
    hints=[]
    for g in validated_company_groups(d):
        if g['validacao']=='A conferir' or g['grupo']!='Alíquota de 20%' or g['base_centavos']<=0:continue
        for r in rows:
            qty=str(r.get('quantidade','')).strip()
            if (r['documento']==d['hash'] and r['base']==g['base'] and r['efeito'].startswith('Acrescenta')
                and r['valor_centavos']==g['base_centavos'] and qty.isdigit() and int(qty)==g['quantidade_base']):
                hints.append({'cnpj':d['cnpj'],'competencia':d['competencia'],'tipo':d['tipo'],'base':g['base'],
                              'codigo':r['codigo'],'descricao':r['descricao'],'valor_centavos':r['valor_centavos'],
                              'quantidade':int(qty),'pagina_rubrica':r['pagina'],'pagina_base':g['pagina'],
                              'indicio':'Valor e quantidade coincidem com o grupo de 20%; correspondência individual não comprovada.',
                              'arquivo':d['arquivo']})
    return hints


def reconciliation(a):
    rows=details(a);trace=composition_trace(a,rows);out=[]
    for d in a['docs']:
        items=[r for r in rows if r['documento']==d['hash']]
        parts=[r for r in trace if r['documento']==d['hash']]
        for reference in company_summary(d):
            target=reference['base'];expected=reference['total_informado_centavos']
            picked=[r for r in parts if r['base']==target]
            additions=sum(r['parcela_centavos'] for r in picked if r['papel']=='Acréscimo indicado')
            reductions=-sum(r['parcela_centavos'] for r in picked if r['papel']=='Redução indicada')
            value=additions-reductions
            candidates=[r for r in picked if r['papel']=='Candidata condicionada']
            candidate_value=sum(r['parcela_centavos'] for r in candidates)
            pending=sum(r['efeito']=='Pendente' and (r['base']==target or r['base']=='Não determinada') for r in items)
            unknown=sum(r['efeito']=='Pendente' and r['base']=='Não determinada' for r in items)
            suggestions=sum('sugestão' in r['efeito'] for r in items if r['base']==target)
            difference=None if expected is None else value-expected
            residual=None if expected is None else expected-value
            after=None if expected is None or not candidates else expected-value-candidate_value
            status='Sem base informada' if expected is None else 'Pendente' if pending else 'Hipótese com sugestões' if suggestions else 'Confere aritmeticamente' if difference==0 else 'Divergente'
            composition='Base não informada' if expected is None else 'Fechamento aritmético; não comprova participação' if residual==0 else 'Fechamento condicionado às candidatas' if after==0 and candidates else 'Diferença ainda não explicada'
            out.append({'cnpj':d['cnpj'],'competencia':d['competencia'],'tipo':d['tipo'],'base':target,
                        'informada_centavos':expected,'referencia_20_centavos':reference['base_20_centavos'],
                        'referencia_zerada_centavos':reference['base_zerada_centavos'],'situacao_grupos':reference['situacao_grupos'],
                        'acrescimos_centavos':additions,'reducoes_centavos':reductions,'reconstruida_centavos':value,
                        'diferenca_centavos':difference,'saldo_sem_explicacao_centavos':residual,
                        'candidatas':len(candidates),'candidatas_centavos':candidate_value if candidates else None,
                        'saldo_apos_todas_candidatas_centavos':after,'conclusao_composicao':composition,
                        'rubricas_pendentes':pending,'pendentes_sem_base_definida':unknown,'sugestoes':suggestions,'estado':status,
                        'completude':'Projeção parcial' if pending else 'Rubricas com efeito indicado; validar tratamento',
                        'projecoes_historicas':sum(r.get('referencia')=='Projeção pelo cadastro disponível' for r in items if r['base']==target),
                        'arquivo':d['arquivo'],'documento':d['hash']})
    return out


def global_overview(docs):
    result=[];previous={}
    for d in sorted(docs,key=lambda x:(x['cnpj'],x['competencia'],x['tipo'],x['hash'])):
        for s in company_summary(d):
            if s['total_informado_centavos'] is None:continue
            key=(d['cnpj'],d['tipo'],s['base']);old=previous.get(key)
            result.append({'cnpj':d['cnpj'],'competencia':d['competencia'],'tipo':d['tipo'],**s,
                           'mudanca_no_recorte':bool(old and old!=s['situacao_grupos']),'arquivo':d['arquivo']})
            previous[key]=s['situacao_grupos']
    return result
