"""Read only payroll catalog sheets and their referenced strings from large XLSX files."""
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
FIELDS={'cnpj_empregador','cod_rubr','ide_tab_rubr','dsc_rubr','cod_inc_cp','tp_rubr','ini_valid','fim_valid','arquivo_origem'}

def family(names,base):
    matches=[n for n in names if re.fullmatch(re.escape(base)+r'(?:_\d+)?',n.strip(),re.I)]
    return sorted(matches,key=lambda n:(0 if n.strip().lower()==base else int(n.strip().rsplit('_',1)[1]),n))

def elements(z,path,tag):
    # Remove completed rows/strings from their parents to keep memory bounded.
    with z.open(path) as stream:
        stack=[]
        for event,node in ET.iterparse(stream,events=('start','end')):
            if event=='start':stack.append(node)
            else:
                if node.tag==NS+tag:
                    yield node
                    if len(stack)>1:stack[-2].remove(node)
                    node.clear()
                stack.pop()

def rows(z,path):
    for row in elements(z,path,'row'):
        values={}
        for c in row.findall(NS+'c'):
            col=re.sub(r'\d','',c.get('r',''))
            kind=c.get('t');v=c.find(NS+'v')
            if kind=='inlineStr':values[col]=('text',''.join(t.text or '' for t in c.iter(NS+'t')))
            elif v is not None:values[col]=('s' if kind=='s' else 'text',v.text or '')
        yield values

def strings(z,needed,path):
    if not needed:return {}
    if path is None:raise ValueError('O XLSX referencia textos compartilhados, mas a tabela de textos está ausente.')
    result={};maximum=max(needed)
    for index,node in enumerate(elements(z,path,'si')):
        if index in needed:result[index]=''.join(t.text or '' for t in node.iter(NS+'t'))
        if index>=maximum:break
    if len(result)!=len(needed):raise ValueError('O XLSX contém referências de texto inválidas.')
    return result

def decode(token,shared):
    return shared[int(token[1])] if token[0]=='s' else token[1]

class Sheet:
    def __init__(self,values):self.values=values
    def iter_rows(self,values_only=True):return iter(self.values)

class CatalogWorkbook(dict):
    def close(self):pass

def load_workbook(path_or_bytes):
    if hasattr(path_or_bytes,'seek'):path_or_bytes.seek(0)
    with zipfile.ZipFile(path_or_bytes) as z:
        workbook=ET.fromstring(z.read('xl/workbook.xml'))
        relations=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        targets={r.get('Id'):posixpath.normpath('xl/'+r.get('Target','')) if not r.get('Target','').startswith('/') else r.get('Target').lstrip('/') for r in relations if r.get('TargetMode')!='External'}
        shared_path=next((targets[r.get('Id')] for r in relations if r.get('Type','').endswith('/sharedStrings') and r.get('Id') in targets),None)
        paths={s.get('name'):targets[s.get(REL+'id')] for s in workbook.find(NS+'sheets') if s.get(REL+'id') in targets}
        identity=family(paths,'00_empresa')
        catalog=family(paths,'apoio_s1010') or family(paths,'02_rubricas_cp')
        selected=identity+catalog
        header_tokens={}
        for name in selected:
            it=rows(z,paths[name])
            try:header_tokens[name]=next(it,{})
            finally:it.close()
        needed={int(v) for row in header_tokens.values() for typ,v in row.values() if typ=='s'}
        shared=strings(z,needed,shared_path)
        headers={name:{col:decode(t,shared).strip() for col,t in h.items()} for name,h in header_tokens.items()}
        raw={};needed=set()
        for name in selected:
            cols={col:field for col,field in headers[name].items() if field in ({'cnpj_empregador'} if name in identity else FIELDS)}
            records=[];seen=set()
            it=rows(z,paths[name]);next(it,None)
            try:
                for row in it:
                    record={field:row[col] for col,field in cols.items() if col in row}
                    if name in identity:
                        value=record.get('cnpj_empregador')
                        if value is None or value in seen:continue
                        seen.add(value)
                    records.append(record)
                    needed.update(int(v) for typ,v in record.values() if typ=='s')
            finally:it.close()
            raw[name]=records
        shared=strings(z,needed,shared_path)
        result=CatalogWorkbook()
        for name in selected:
            fields=[field for field in headers[name].values() if field in ({'cnpj_empregador'} if name in identity else FIELDS)]
            result[name]=Sheet([fields]+[[decode(r[field],shared) if field in r else None for field in fields] for r in raw[name]])
        return result
