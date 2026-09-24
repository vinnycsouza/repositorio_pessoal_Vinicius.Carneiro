import io, json
from pathlib import Path
import pandas as pd
import streamlit as st
import core

st.set_page_config(page_title='Levantamento de folhas',page_icon='📋',layout='wide')
st.title('Levantamento de rubricas')
st.caption('Folhas RH3 • Conferência de bases • Relatórios em Excel')

def display(rows):
    df=pd.DataFrame(rows)
    for c in list(df.columns):
        if c.endswith('_centavos'):
            df[c]=pd.to_numeric(df[c],errors='coerce')/100
            df=df.rename(columns={c:c.replace('_centavos',' (R$)')})
    return df

with st.sidebar:
    st.header('Análises salvas')
    options=core.saved()
    if options:
        selected=st.selectbox('Abrir análise',options,format_func=lambda x:f'{x[0]} · {x[1]}')
        if st.button('Carregar análise'):
            st.session_state.analysis=core.load(selected[0]); st.rerun()
    if st.button('Nova análise'):
        st.session_state.pop('analysis',None); st.rerun()
    st.caption('Dados e revisões ficam salvos localmente na pasta dados do aplicativo.')

tabs=st.tabs(['1 · Documentos','2 · Rubricas e critérios','3 · Conferência','4 · Levantamento'])
with tabs[0]:
    if 'analysis' not in st.session_state:
        name=st.text_input('Nome da análise','Teste das folhas')
        if st.button('Criar análise'):
            a={'name':name,'docs':[],'errors':[],'decisions':{},'catalog':None}
            core.save(a); st.session_state.analysis=a; st.rerun()
    else:
        a=st.session_state.analysis
        st.subheader(a['name'])
        uploads=st.file_uploader('Folhas PDF, ZIP ou RAR',type=['pdf','zip','rar'],accept_multiple_files=True)
        paths=st.text_area('Ou caminhos locais, um por linha',help='Informe arquivos; pastas não são importadas recursivamente.')
        if st.button('Importar e extrair folhas',type='primary'):
            inputs=[(u.name,u.getvalue()) for u in uploads]
            for p in paths.splitlines():
                p=p.strip().strip('"')
                if not p: continue
                try:
                    src=Path(p)
                    if src.suffix.lower() not in ['.pdf','.zip','.rar']: raise ValueError('Formato não suportado.')
                    if src.stat().st_size>250*1024**2: raise ValueError('Entrada maior que 250 MB.')
                    inputs.append((src.name,src.read_bytes()))
                except Exception as e: a['errors'].append({'arquivo':p,'erro':str(e)})
            seen={d['hash'] for d in a['docs']}; count=0; duplicates=0
            progress=st.empty()
            for name,content in inputs:
                try:
                    for source,pdf in core.unpack(name,content):
                        import hashlib
                        if hashlib.sha256(pdf).hexdigest() in seen: duplicates+=1; continue
                        progress.info('Processando '+source)
                        try:
                            d=core.extract(source,pdf)
                            if any(x['cnpj']==d['cnpj'] and x['competencia']==d['competencia'] and x['tipo']==d['tipo'] for x in a['docs']):
                                d['alertas'].append('Outro documento da mesma empresa/competência/tipo: verificar sobreposição antes de consolidar.')
                            a['docs'].append(d); seen.add(d['hash']); count+=1
                        except Exception as e: a['errors'].append({'arquivo':source,'erro':str(e)})
                except Exception as e: a['errors'].append({'arquivo':name,'erro':str(e)})
            core.save(a,'Importação de documentos'); progress.empty()
            st.success(f'{count} documentos adicionados; {duplicates} duplicatas exatas ignoradas. Consulte eventuais erros abaixo.')
        st.dataframe(pd.DataFrame([{k:d.get(k) for k in ['arquivo','empresa','cnpj','competencia','tipo','paginas','alertas']} for d in a['docs']]),hide_index=True)
        if a['errors']: st.warning('Há arquivos não processados.'); st.dataframe(a['errors'])
        with st.expander('Retirar documento da análise (o original será preservado)'):
            if a['docs']:
                removal=st.selectbox('Documento',a['docs'],format_func=lambda d:d['arquivo'],key='remove')
                if st.button('Retirar documento selecionado'):
                    a['docs']=[d for d in a['docs'] if d['hash']!=removal['hash']]
                    core.save(a,'Documento retirado: '+removal['arquivo']); st.rerun()

if 'analysis' not in st.session_state: st.stop()
a=st.session_state.analysis
with tabs[1]:
    st.subheader('Cadastro de incidência e revisão')
    st.info('O cadastro da AJ só é aplicado ao CNPJ correspondente. As sugestões respeitam vigência e não são confirmação de exclusão.')
    catalog_path=st.text_input('Caminho do relatório de incidência XLSX')
    catalog_file=st.file_uploader('Ou envie o relatório de incidência',type=['xlsx'])
    if st.button('Ler cadastro S-1010'):
        try:
            with st.spinner('Lendo somente cadastro e identificação do relatório…'):
                a['catalog']=core.import_catalog(io.BytesIO(catalog_file.getvalue()) if catalog_file else catalog_path.strip().strip('"'))
            core.save(a,'Importação de cadastro de incidência'); st.success(f"{len(a['catalog']['rubricas'])} registros históricos importados.")
        except Exception as e: st.error(str(e))
    if a.get('catalog'): st.caption('CNPJ raiz do cadastro: '+a['catalog']['empresa_raiz'])
    rows=core.details(a)
    if rows:
        company=st.selectbox('Empresa',sorted({r['cnpj'] for r in rows}))
        period=st.selectbox('Competência para revisar',sorted({r['competencia'] for r in rows if r['cnpj']==company}))
        subset=[r for r in rows if r['cnpj']==company and r['competencia']==period]
        unique={r['chave']:r for r in subset}
        fields=['chave','codigo','descricao','lado','codIncCP','origem','selecionada','rating','efeito','base','justificativa']
        frame=pd.DataFrame([{k:r[k] for k in fields} for r in unique.values()])
        edited=st.data_editor(frame,hide_index=True,key=f'edit_{a["id"]}_{company}_{period}',disabled=['chave','codigo','descricao','lado','codIncCP','origem'],column_config={
            'chave':None,
            'rating':st.column_config.SelectboxColumn(options=['Sem classificação','Verde','Amarelo']),
            'efeito':st.column_config.SelectboxColumn(options=['Pendente','Acrescenta (sugestão)','Reduz (sugestão)','Não integra (sugestão)','Acrescenta','Reduz','Não integra']),
            'base':st.column_config.SelectboxColumn(options=['Mensal','13º'])},width='stretch')
        reviewer=st.text_input('Responsável pela revisão')
        if st.button('Salvar revisão desta competência'):
            changes=[]; invalid=False
            for row in edited.to_dict('records'):
                original=unique[row['chave']]
                keys=['selecionada','rating','efeito','base','justificativa']
                if any(row[k]!=original[k] for k in keys):
                    if not reviewer.strip() or not str(row['justificativa']).strip(): invalid=True
                    changes.append(row)
            if invalid: st.error('Informe responsável e justificativa nas linhas alteradas.')
            else:
                for row in changes:
                    a['decisions'][row['chave']]={k:row[k] for k in ['selecionada','rating','efeito','base','justificativa']}
                    a['decisions'][row['chave']]['responsavel']=reviewer
                core.save(a,'Revisão por '+reviewer); st.success('Revisão salva. Conferências e exportações serão calculadas com as decisões atuais.')

with tabs[2]:
    st.subheader('Conferência por documento')
    st.caption('Fechar o total demonstra consistência aritmética, não comprova isoladamente a incidência de cada rubrica.')
    if a['docs']:
        d=st.selectbox('Folha',a['docs'],format_func=lambda x:f"{x['cnpj']} · {x['competencia']} · {x['tipo']} · {Path(x['arquivo']).name}")
        st.dataframe(display(d['checagens']),hide_index=True)
        checks=[r for r in core.reconciliation(a) if r['arquivo']==d['arquivo']]
        st.dataframe(display(checks),hide_index=True)
        data=[r for r in core.details(a) if r['documento']==d['hash']]
        st.dataframe(display([{k:r[k] for k in ['codigo','descricao','lado','valor_centavos','efeito','base','origem','pagina']} for r in data]),hide_index=True)
        if d['alertas']: st.warning(' | '.join(d['alertas']))
        page=st.number_input('Página do PDF',1,d['paginas'],1)
        if st.checkbox('Visualizar página'):
            import pdfplumber
            with pdfplumber.open(d['path']) as p: st.image(p.pages[page-1].to_image(resolution=110).original)
        st.download_button('Abrir/baixar PDF original',Path(d['path']).read_bytes(),file_name=Path(d['arquivo']).name,mime='application/pdf')

with tabs[3]:
    st.subheader('Valores das rubricas selecionadas')
    st.warning('Relatório preliminar: valores encontrados não equivalem a crédito nem a exclusão confirmada. Não inclui cálculo de CPP, GILRAT ou Selic.')
    rows=[r for r in core.details(a) if r['selecionada']]
    if rows:
        companies=st.multiselect('Filtrar empresas',sorted({r['cnpj'] for r in rows}),default=sorted({r['cnpj'] for r in rows}))
        periods=st.multiselect('Filtrar competências',sorted({r['competencia'] for r in rows}),default=sorted({r['competencia'] for r in rows}))
        filtered=[r for r in rows if r['cnpj'] in companies and r['competencia'] in periods]
        st.dataframe(display([{k:r[k] for k in ['cnpj','competencia','tipo','codigo','descricao','valor_centavos','efeito','rating','arquivo','pagina']} for r in filtered]),hide_index=True)
        st.caption('A exportação considera todas as rubricas dos documentos das empresas e competências filtradas; a seleção de interesse é preservada nas abas de levantamento.')
        if st.button('Preparar relatório Excel',type='primary'):
            export_a={**a,'docs':[d for d in a['docs'] if d['cnpj'] in companies and d['competencia'] in periods]}
            st.session_state.excel=core.export_excel(export_a)
            st.session_state.excel_signature=json.dumps(a,sort_keys=True)+str(companies)+str(periods)
        signature=json.dumps(a,sort_keys=True)+str(companies)+str(periods)
        if st.session_state.get('excel_signature')==signature:
            st.download_button('Baixar levantamento.xlsx',st.session_state.excel,'levantamento.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else: st.info('Importe documentos e selecione rubricas na etapa 2.')
