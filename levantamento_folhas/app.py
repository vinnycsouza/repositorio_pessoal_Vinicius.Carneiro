import io, json
from pathlib import Path
import pandas as pd
import streamlit as st
import core

st.set_page_config(page_title='Levantamento de folhas',page_icon='📋',layout='wide')
st.title('Levantamento de rubricas')
st.caption('O que pode compor a base do INSS empresa, por folha · Sem cálculo dos 20%')

def display(rows):
    df=pd.DataFrame(rows)
    for c in list(df.columns):
        if c.endswith('_centavos'):
            df[c]=df[c].map(lambda value: core.brl(value) if pd.notna(value) else 'Não informado')
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

# Refresh newly extracted fields in existing browser sessions without losing decisions.
if 'analysis' in st.session_state:
    current=st.session_state.analysis
    if any('previdencia' not in d for d in current['docs']):
        stored=core.load(current['id']) if current.get('id') else None
        indexed={d['hash']:d for d in stored['docs']} if stored else {}
        with st.spinner('Atualizando os campos previdenciários da análise existente…'):
            for document in current['docs']:
                if 'previdencia' in document: continue
                fresh=indexed.get(document['hash'],{})
                if 'previdencia' not in fresh:
                    fresh=core.extract(document['arquivo'],Path(document['path']).read_bytes())
                document['previdencia']=fresh['previdencia']
                document['versao']=core.VERSION
            core.save(current,'Atualização de campos previdenciários em sessão anterior')
        st.session_state.pop('excel_signature',None)

tabs=st.tabs(['Documentos e incidência','Base do INSS empresa','Relatórios Excel'])
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
with tabs[0]:
    st.subheader('Relatório de incidência')
    catalog_path=st.text_input('Caminho do relatório de incidência XLSX')
    catalog_file=st.file_uploader('Ou envie o relatório de incidência',type=['xlsx'])
    if st.button('Ler cadastro S-1010'):
        try:
            with st.spinner('Lendo o cadastro de incidência…'):
                a['catalog']=core.import_catalog(io.BytesIO(catalog_file.getvalue()) if catalog_file else catalog_path.strip().strip('"'))
            core.save(a,'Importação do relatório de incidência')
            st.success(f"{len(a['catalog']['rubricas'])} registros históricos importados.")
        except Exception as e: st.error(str(e))
    if a.get('catalog'): st.caption('CNPJ raiz do relatório: '+a['catalog']['empresa_raiz'])

rows=core.details(a)
with tabs[1]:
    if not a['docs']:
        st.info('Importe uma folha para iniciar o cruzamento.')
    else:
        company=st.selectbox('Empresa',sorted({d['cnpj'] for d in a['docs']}),key='base_company')
        period=st.selectbox('Competência',sorted({d['competencia'] for d in a['docs'] if d['cnpj']==company}),key='base_period')
        documents=[d for d in a['docs'] if d['cnpj']==company and d['competencia']==period]
        doc_id=st.selectbox('Folha', [d['hash'] for d in documents],format_func=lambda h:next(d['tipo']+' · '+d['arquivo'].split(' :: ')[-1] for d in documents if d['hash']==h),key='base_doc')
        d=next(d for d in documents if d['hash']==doc_id)
        current=[r for r in rows if r['documento']==doc_id]
        st.subheader('Base informada no PDF')
        c1,c2=st.columns(2)
        c1.metric('Base INSS empresa — mensal',core.brl(d['bases'].get('mensal')))
        c2.metric('Base INSS empresa — 13º',core.brl(d['bases'].get('13')))
        st.dataframe(display([{k:r[k] for k in ['indicador','valor_centavos','situacao','pagina']} for r in core.previdencia_rows(d)]),hide_index=True,width='stretch')
        if d['alertas']: st.warning(' | '.join(d['alertas']))
        st.subheader('Participação indicada pelo relatório de incidência')
        st.caption('Acréscimos são possibilidades indicadas pelo cadastro. Não representam inclusão comprovada nem exclusão aprovada. Selecione somente o que deseja levar ao levantamento.')
        groups=['Possíveis acréscimos','Reduções da base','Fora da base segundo cadastro','Não determinado']
        default=0 if any(r['grupo']==groups[0] for r in current) else 3
        group=st.radio('Mostrar',groups,index=default,horizontal=True,key=f'group_{doc_id}')
        view=[r for r in current if r['grupo']==group]
        st.caption(' · '.join(f'{g}: {sum(r["grupo"]==g for r in current)}' for g in groups))
        if not a.get('catalog'): st.info('Importe o relatório de incidência para obter a triagem automática.')
        if not view: st.info('Nenhuma rubrica neste grupo para a folha selecionada.')
        else:
            table=[]
            for r in view:
                table.append({'id':core.selection_key(r),'Selecionar':bool(r['selecionada']),'Código':r['codigo'],'Rubrica na folha':r['descricao'],'Valor':core.brl(r['valor_centavos']),'Base':r['base'] if r['grupo']!='Não determinado' else 'Não determinada','Código CP':r['codIncCP'],'Descrição no relatório':r['descricao_relatorio'],'Vigência do cadastro':r['vigencia_relatorio'],'Correspondência':r['correspondencia'],'Indicação':r['efeito'],'Observação':r['motivo'],'Página':r['pagina']})
            frame=pd.DataFrame(table)
            signature=core.hashlib.sha256(json.dumps(table,sort_keys=True).encode()).hexdigest()[:12]
            edited=st.data_editor(frame,hide_index=True,width='stretch',key=f'select_{doc_id}_{group}_{signature}',disabled=[c for c in frame.columns if c!='Selecionar'],column_config={'id':None,'Selecionar':st.column_config.CheckboxColumn('Selecionar'),'Descrição no relatório':None,'Vigência do cadastro':None,'Correspondência':None,'Observação':None,'Página':None})
            with st.expander('Ver correspondências, vigências e motivos deste grupo'):
                st.dataframe(frame[['Código','Rubrica na folha','Descrição no relatório','Vigência do cadastro','Correspondência','Observação','Página']],hide_index=True,width='stretch')
            st.caption('Selecionar leva o valor ao relatório; não altera o efeito na base nem exige classificar as outras rubricas.')
            if st.button('Salvar seleção deste grupo',type='primary'):
                a.setdefault('selections',{}).update({r['id']:bool(r['Selecionar']) for r in edited.to_dict('records')})
                core.save(a,'Seleção manual após cruzamento da folha'); st.rerun()
        historical=[r for r in current if r['selecionada'] and r['grupo']!='Possíveis acréscimos']
        if historical: st.info(f'{len(historical)} rubrica(s) selecionada(s) estão em outros grupos. Permanecem identificadas no Excel; não são somadas como acréscimos.')
        with st.expander('Conferência da composição — opcional'):
            st.caption('Comparação aritmética, sem cálculo da contribuição. Pendências não entram na parcela reconstruída; não ajustar regras para forçar fechamento.')
            st.dataframe(display([r for r in core.reconciliation(a) if r['arquivo']==d['arquivo']]),hide_index=True)
            st.dataframe(display(d['checagens']),hide_index=True)
        with st.expander('Ajustar uma correspondência ou rating — opcional'):
            choice=st.selectbox('Rubrica para revisar',range(len(current)),format_func=lambda i:current[i]['codigo']+' · '+current[i]['descricao'])
            r=current[choice]
            with st.form('review_'+doc_id+'_'+str(choice)):
                effects=['Pendente','Acrescenta (sugestão)','Reduz (sugestão)','Não integra (sugestão)','Acrescenta','Reduz','Não integra']
                effect=st.selectbox('Efeito adotado',effects,index=effects.index(r['efeito']))
                scope=st.selectbox('Base', ['Mensal','13º'],index=0 if r['base']=='Mensal' else 1)
                ratings=['Sem classificação','Verde','Amarelo']
                rating=st.selectbox('Rating da equipe',ratings,index=ratings.index(r['rating']))
                why=st.text_input('Justificativa',value=r['justificativa'])
                who=st.text_input('Responsável',value=r.get('responsavel',''))
                if st.form_submit_button('Salvar ajuste'):
                    if not why.strip() or not who.strip(): st.error('Informe justificativa e responsável para alterar o critério.')
                    else:
                        a.setdefault('decisions',{}).setdefault(r['chave'],{}).update(efeito=effect,base=scope,rating=rating,justificativa=why,responsavel=who)
                        core.save(a,'Ajuste de critério por '+who);st.rerun()
        with st.expander('Situação patronal do período — apenas informativa'):
            st.caption('A desoneração não será deduzida de contribuição zerada e não altera os valores extraídos. Não há cálculo dos 20% nesta versão.')
            choices=['Não verificada','Sem substituição confirmada','Com substituição confirmada','Parcial/mista']
            regime_key=company+'|'+period
            regime=st.selectbox('Situação',choices,index=choices.index(a.get('regimes',{}).get(regime_key,'Não verificada')))
            evidence=st.text_input('Documento ou observação de suporte',value=a.get('regime_evidence',{}).get(regime_key,''))
            if st.button('Salvar informação do período'):
                if regime!='Não verificada' and not evidence.strip(): st.error('Informe o suporte da situação registrada.')
                else:
                    a.setdefault('regimes',{})[regime_key]=regime;a.setdefault('regime_evidence',{})[regime_key]=evidence
                    core.save(a,'Situação patronal informativa');st.rerun()
        with st.expander('Consultar documento original'):
            page=st.number_input('Página do PDF',1,d['paginas'],1,key='page_'+doc_id)
            if st.checkbox('Visualizar página',key='preview_'+doc_id):
                import pdfplumber
                with pdfplumber.open(d['path']) as pdf: st.image(pdf.pages[page-1].to_image(resolution=110).original)
            st.download_button('Baixar PDF original',Path(d['path']).read_bytes(),file_name=d['arquivo'].split(' :: ')[-1],mime='application/pdf')

with tabs[2]:
    st.subheader('Relatório de composição e rubricas selecionadas')
    st.caption('Todos os relatórios são Excel. Os valores permanecem numéricos. Sem cálculo de contribuição, crédito ou Selic.')
    if a['docs']:
        companies=st.multiselect('Empresas do relatório',sorted({d['cnpj'] for d in a['docs']}),default=sorted({d['cnpj'] for d in a['docs']}))
        periods=st.multiselect('Competências do relatório',sorted({d['competencia'] for d in a['docs']}),default=sorted({d['competencia'] for d in a['docs']}))
        kinds=st.multiselect('Tipos de folha',sorted({d['tipo'] for d in a['docs']}),default=sorted({d['tipo'] for d in a['docs']}))
        export_a={**a,'docs':[d for d in a['docs'] if d['cnpj'] in companies and d['competencia'] in periods and d['tipo'] in kinds]}
        selected_rows=[r for r in core.details(export_a) if r['selecionada']]
        st.dataframe(display([{k:r[k] for k in ['cnpj','competencia','tipo','codigo','descricao','valor_centavos','grupo','efeito','rating','arquivo','pagina']} for r in selected_rows]),hide_index=True)
        if not selected_rows: st.info('Nenhuma seleção manual neste recorte. O Excel ainda pode ser gerado com o cruzamento completo e seus grupos.')
        if st.button('Preparar relatório Excel',type='primary',disabled=not export_a['docs']):
            st.session_state.excel=core.export_excel(export_a)
            st.session_state.excel_signature=json.dumps(export_a,sort_keys=True)
        if st.session_state.get('excel_signature')==json.dumps(export_a,sort_keys=True):
            st.download_button('Baixar levantamento.xlsx',st.session_state.excel,'levantamento.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
