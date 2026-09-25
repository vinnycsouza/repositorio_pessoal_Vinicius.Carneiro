import io, json
from pathlib import Path
import pandas as pd
import streamlit as st
import core

st.set_page_config(page_title='Levantamento de folhas',page_icon='📋',layout='wide')
st.title('Levantamento de rubricas')
st.caption('Composição provável da base do INSS empresa, por folha · Sem apuração de crédito')

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

# Enrich saved documents without replacing selections, decisions or original PDFs.
if 'analysis' in st.session_state:
    current=st.session_state.analysis
    changed=False
    pending_documents=[d for d in current['docs'] if 'grupos_empresa' not in d or 'previdencia' not in d]
    if pending_documents:
        with st.spinner('Conferindo os grupos de base nos PDFs preservados…'):
            for document in pending_documents:
                try:
                    content=Path(document['path']).read_bytes()
                    if 'previdencia' not in document:
                        document['previdencia']=core.extract(document['arquivo'],content)['previdencia']
                    document['grupos_empresa']=core.extract_company_groups(content)
                    document['versao']=core.VERSION
                    changed=True
                except Exception as exc:
                    st.warning(f"Não foi possível atualizar {document['arquivo']}: {exc}")
    if changed:
        core.save(current,'Atualização das bases, quantidades e contribuições por grupo do PDF')
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
    catalog_employer=st.text_input('CNPJ da empresa do relatório — se não identificado no arquivo',help='Informe o CNPJ completo ou a raiz de 8 dígitos. Use apenas quando souber a qual empresa pertence este cadastro. O vínculo manual fica registrado.')
    if st.button('Ler cadastro S-1010'):
        try:
            with st.spinner('Lendo o cadastro de incidência…'):
                a['catalog']=core.import_catalog(io.BytesIO(catalog_file.getvalue()) if catalog_file else catalog_path.strip().strip('"'),employer_override=catalog_employer)
            core.save(a,'Importação do relatório de incidência')
            st.success(f"{len(a['catalog']['rubricas'])} registros históricos importados.")
        except Exception as e: st.error(str(e))
    if a.get('catalog'):
        st.caption('CNPJ raiz do relatório: '+a['catalog']['empresa_raiz'])
        st.caption(a['catalog'].get('identificacao_empresa','Identificação importada do relatório.'))

with st.sidebar:
    st.divider()
    previdencia_filter=st.selectbox('Total de previdência empresa',core.PREVIDENCIA_FILTERS,key='previdencia_filter')
    st.caption('Filtro aplicado à consulta das folhas e aos relatórios Excel. Zero não comprova desoneração.')
filtered_docs=core.filter_previdencia(a['docs'],previdencia_filter)
rows=core.details({**a,'docs':filtered_docs})
with tabs[1]:
    if not filtered_docs:
        st.info('Nenhuma folha corresponde ao filtro. Altere o filtro na barra lateral ou importe documentos.')
    else:
        st.caption(f'{len(filtered_docs)} de {len(a["docs"])} folhas · Total de previdência empresa: {previdencia_filter}')
        with st.expander('Folhas encontradas pelo filtro',expanded=previdencia_filter!='Todas'):
            overview=[]
            for document in filtered_docs:
                values=document.get('previdencia',{})
                overview.append({'empresa':document['empresa'],'cnpj':document['cnpj'],'competencia':document['competencia'],'tipo':document['tipo'],
                                 'base_empresa_centavos':values.get('base_empresa_total',{}).get('valor_centavos'),
                                 'previdencia_empresa_centavos':values.get('previdencia_empresa_total',{}).get('valor_centavos'),
                                 'situacao':core.previdencia_status(document),'arquivo':document['arquivo']})
            st.dataframe(display(overview),hide_index=True,width='stretch')
            st.caption('Panorama por base. Mudanças comparam folhas do mesmo tipo dentro do recorte atual. Zero não identifica o regime tributário.')
            panorama=core.global_overview(filtered_docs)
            st.dataframe(display([{k:r[k] for k in ['competencia','cnpj','tipo','base','total_informado_centavos','base_20_centavos','base_zerada_centavos','situacao_grupos','mudanca_no_recorte']} for r in panorama]),hide_index=True,width='stretch')
        company=st.selectbox('Empresa',sorted({d['cnpj'] for d in filtered_docs}),key='base_company')
        period=st.selectbox('Competência',sorted({d['competencia'] for d in filtered_docs if d['cnpj']==company}),key='base_period')
        documents=[d for d in filtered_docs if d['cnpj']==company and d['competencia']==period]
        doc_id=st.selectbox('Folha', [d['hash'] for d in documents],format_func=lambda h:next(d['tipo']+' · '+d['arquivo'].split(' :: ')[-1] for d in documents if d['hash']==h),key='base_doc')
        d=next(d for d in documents if d['hash']==doc_id)
        current=[r for r in rows if r['documento']==doc_id]
        st.subheader('Base informada no PDF')
        c1,c2=st.columns(2)
        c1.metric('Base INSS empresa — mensal',core.brl(d['bases'].get('mensal')))
        c2.metric('Base INSS empresa — 13º',core.brl(d['bases'].get('13')))
        st.dataframe(display([{k:r[k] for k in ['indicador','valor_centavos','situacao','pagina']} for r in core.previdencia_rows(d)]),hide_index=True,width='stretch')
        st.caption('Os totais acima podem incluir bases com contribuição zerada. As referências abaixo vêm das linhas do PDF, separadas por mensal e 13º.')
        summary=core.company_summary(d)
        st.dataframe(display([{k:v for k,v in r.items() if k not in ('observacao','diferenca_extracao_centavos')} for r in summary]),hide_index=True,width='stretch')
        with st.expander('Bases, quantidades e contribuições por grupo do PDF'):
            groups=core.company_group_rows(d)
            if groups:
                st.dataframe(display([{k:r[k] for k in ['base','grupo','quantidade_base','quantidade_contribuicao','aliquota_percentual','base_centavos','contribuicao_centavos','validacao','motivo_validacao','diferenca_aritmetica_centavos','pagina']} for r in groups]),hide_index=True,width='stretch')
            else: st.info('Grupos não localizados no PDF.')
            st.caption('Quantidade transcrita da coluna Qtd. da base: não representa pessoas únicas. Mensal e 13º podem incluir os mesmos vínculos. Contribuição zerada não comprova desoneração; não há associação automática entre rubricas e grupos.')
            if any(r['diferenca_extracao_centavos'] not in (None,0) for r in summary):
                st.warning('A soma dos grupos difere da base extraída. Confira o documento original.')
        if any(r['situacao_grupos']=='Vínculo entre base e contribuição a conferir' for r in summary):
            st.warning('Há inconsistência entre base e contribuição. A referência dos 20% afetada está suspensa; consulte o detalhamento dos grupos. Nenhuma linha foi reordenada.')
        if d['alertas']: st.warning(' | '.join(d['alertas']))
        st.subheader('Participação indicada pelo relatório de incidência')
        st.caption('Triagem automática: indicações do período e projeções por cadastro de outra época aparecem nos mesmos grupos, identificadas na coluna Referência. Não comprovam inclusão na base. A seleção serve apenas para destacar valores no Excel.')
        with st.container(border=True):
            st.markdown('**Composição provável da base vinculada aos 20%**')
            twenty_summary,twenty_evidence=core.twenty_composition({**a,'docs':[d]},current)
            twenty_scope=st.radio('Base dos 20% a analisar',['Mensal','13º'],index=1 if d['tipo']=='13º final' else 0,horizontal=True,key=f'twenty_scope_{doc_id}')
            t=next(r for r in twenty_summary if r['base']==twenty_scope)
            m1,m2,m3=st.columns(3)
            m1.metric('Base vinculada aos 20%',core.brl(t['base_20_centavos']))
            m2.metric('Parcela projetada / hipótese',core.brl(t['parcela_projetada_centavos']))
            m3.metric('Saldo não identificado',core.brl(t['saldo_nao_identificado_centavos']))
            st.write(t['situacao'])
            st.caption(t['criterio'])
            if t['quantidade_candidatas']:
                st.warning('Há evidência de composição, mas a incidência das candidatas permanece conflitante. Elas estão fora da parcela projetada acima.')
                c1,c2=st.columns(2)
                c1.metric('Candidatas com conflito',core.brl(t['candidatas_conflitantes_centavos']))
                c2.metric('Saldo se todas forem validadas',core.brl(t['saldo_condicionado_centavos']))
            if t['saldo_nao_identificado_centavos'] is not None and t['saldo_nao_identificado_centavos']<0:
                st.warning('A projeção excede a base dos 20%. O saldo negativo indica divergência, não crédito ou exclusão.')
            shown=[r for r in twenty_evidence if r['base']==twenty_scope]
            if shown:
                st.dataframe(display([{'Código':r['codigo'],'Rubrica':r['descricao'],'Papel':r['papel'],
                                      'Valor da rubrica_centavos':r['valor_centavos'],'Parcela na hipótese_centavos':r['parcela_centavos'],
                                      'Candidata fora da projeção_centavos':r['parcela_candidata_centavos'],'Referência':r['referencia'],'Evidência':r['evidencia_20'],'Página':r['pagina']} for r in shown]),hide_index=True,width='stretch')
            else:
                st.info(t['criterio'] if t['base_20_centavos'] in (None,0) or t['situacao'].startswith('Grupos mistos') else 'Existe base dos 20%, mas o cadastro ainda não sustenta parcelas neste bloco. Consulte as correspondências pendentes abaixo.')
            st.caption('Mensal e 13º são analisados separadamente. Fechamento aritmético ou coincidência de quantidade não confirma a participação individual.')
            simulation,estimated_rows=core.proportional_twenty({**a,'docs':[d]},current)
            sim=next((r for r in simulation if r['base']==twenty_scope),None)
            if sim:
                with st.expander('Estimativa proporcional dos 20% — a confirmar na folha',expanded=True):
                    st.warning(sim['premissa'])
                    percentage=f"{sim['fator_proporcao']*100:.2f}".replace('.',',')+'%'
                    st.caption(f"Proporção: {core.brl(sim['base_20_pdf_centavos'])} ÷ {core.brl(sim['base_total_pdf_centavos'])} = {percentage}. O cálculo usa a proporção completa, sem arredondar o fator. Cada parcela é arredondada a centavos.")
                    p1,p2,p3=st.columns(3)
                    p1.metric('Acréscimos estimados',core.brl(sim['acrescimos_estimados_centavos']))
                    p2.metric('Reduções estimadas',core.brl(sim['reducoes_estimadas_centavos']))
                    p3.metric('Saldo estimado',core.brl(sim['saldo_estimado_centavos']))
                    st.metric('Base dos 20% menos saldo estimado',core.brl(sim['diferenca_para_base_20_centavos']))
                    st.caption('A diferença permanece visível: não ajustamos as rubricas para fechar o total. Valor negativo indica que a estimativa excede a base. Rubricas sem correspondência suficiente não recebem valor estimado.')
                    estimated=[r for r in estimated_rows if r['base']==twenty_scope]
                    fields={'codigo':'Código','descricao':'Rubrica','papel':'Papel','valor_integral_centavos':'Valor integral_centavos','estimativa_centavos':'Valor estimado com sinal_centavos','referencia':'Referência'}
                    st.dataframe(display([{v:r[k] for k,v in fields.items()} for r in estimated if r['cenario']=='Estimativa pelo cadastro']),hide_index=True,width='stretch')
                    if sim['quantidade_candidatas']:
                        st.caption('Cenário adicional: candidatas com incidência conflitante, fora do saldo estimado acima.')
                        st.dataframe(display([{v:r[k] for k,v in fields.items()} for r in estimated if r['cenario']=='Adicional condicionado a conflito']),hide_index=True,width='stretch')
                        st.metric('Diferença se todas as candidatas forem validadas',core.brl(sim['diferenca_com_candidatas_centavos']))

        groups=['Possíveis acréscimos','Reduções da base','Fora da base segundo cadastro','Não determinado']
        default=0 if any(r['grupo']==groups[0] for r in current) else 3
        group=st.radio('Mostrar',groups,index=default,horizontal=True,key=f'group_{doc_id}')
        scopes=['Todas','Mensal','13º','Não determinada','Não se aplica']
        scope_view=st.selectbox('Base das rubricas',scopes,key=f'scope_view_{doc_id}')
        view=[r for r in current if r['grupo']==group and (scope_view=='Todas' or r['base']==scope_view)]
        if group=='Não determinado':view=sorted(view,key=lambda r:abs(r['valor_centavos']),reverse=True)
        st.caption(' · '.join(f'{g}: {sum(r["grupo"]==g for r in current)}' for g in groups))
        if not a.get('catalog'): st.info('Importe o relatório de incidência para obter a triagem automática.')
        if not view: st.info('Nenhuma rubrica neste grupo para a folha selecionada.')
        else:
            table=[]
            for r in view:
                table.append({'id':core.selection_key(r),'Selecionar':bool(r['selecionada']),'Código':r['codigo'],'Rubrica na folha':r['descricao'],'Valor':core.brl(r['valor_centavos']),'Base':r['base'],'Natureza':r['natureza'],'Código CP':r['codIncCP'],'Referência':r['referencia'],'Descrição no relatório':r['descricao_relatorio'],'Vigência do cadastro':r['vigencia_relatorio'],'Correspondência':r['correspondencia'],'Indicação':r['efeito'],'Observação':r['motivo'],'Página':r['pagina']})
            frame=pd.DataFrame(table)
            signature=core.hashlib.sha256(json.dumps(table,sort_keys=True).encode()).hexdigest()[:12]
            edited=st.data_editor(frame,hide_index=True,width='stretch',key=f'select_{doc_id}_{group}_{signature}',disabled=[c for c in frame.columns if c!='Selecionar'],column_config={'id':None,'Selecionar':st.column_config.CheckboxColumn('Selecionar'),'Descrição no relatório':None,'Vigência do cadastro':None,'Correspondência':None,'Observação':None,'Página':None})
            with st.expander('Ver correspondências, vigências e motivos deste grupo'):
                st.dataframe(frame[['Código','Rubrica na folha','Referência','Descrição no relatório','Vigência do cadastro','Correspondência','Observação','Página']],hide_index=True,width='stretch')
            st.caption('Selecionar leva o valor ao relatório; não altera o efeito na base nem exige classificar as outras rubricas.')
            if st.button('Salvar seleção deste grupo',type='primary'):
                a.setdefault('selections',{}).update({r['id']:bool(r['Selecionar']) for r in edited.to_dict('records')})
                core.save(a,'Seleção manual após cruzamento da folha'); st.rerun()
        historical=[r for r in current if r['selecionada'] and r['grupo']!='Possíveis acréscimos']
        if historical: st.info(f'{len(historical)} rubrica(s) selecionada(s) estão em outros grupos. Permanecem identificadas no Excel; não são somadas como acréscimos.')
        with st.expander('Conferência da composição provável'):
            st.caption('Acréscimos menos reduções explicam uma parcela da base total, separados por mensal e 13º. O fechamento aritmético não confirma a participação nas linhas de 20%.')
            local_a={**a,'docs':[d]}
            composition=core.reconciliation(local_a)
            st.dataframe(display([{'Base':r['base'],'Total PDF_centavos':r['informada_centavos'],
                                  'Acréscimos_centavos':r['acrescimos_centavos'],'Reduções_centavos':r['reducoes_centavos'],
                                  'Parcela explicada_centavos':r['reconstruida_centavos'],'Saldo sem explicação_centavos':r['saldo_sem_explicacao_centavos'],
                                  'Referência 20%_centavos':r['referencia_20_centavos'],'Conclusão':r['conclusao_composicao']} for r in composition]),hide_index=True,width='stretch')
            parts=core.composition_trace(local_a,current)
            included=[r for r in parts if r['papel'] in ('Acréscimo indicado','Redução indicada')]
            st.caption('Memória das parcelas incluídas na projeção')
            st.dataframe(display([{k:r[k] for k in ['base','codigo','descricao','papel','parcela_centavos','referencia','pagina']} for r in included]),hide_index=True,width='stretch')
            candidates=[r for r in parts if r['papel']=='Candidata condicionada']
            if candidates:
                st.caption('Candidatas com incidência conflitante — fora da parcela explicada. O cenário usa todas as candidatas de cada base; não busca combinações para fechar a conta.')
                st.dataframe(display([{k:r[k] for k in ['base','codigo','descricao','parcela_centavos','codIncCP','criterio','pagina']} for r in candidates]),hide_index=True,width='stretch')
                st.dataframe(display([{'Base':r['base'],'Todas candidatas_centavos':r['candidatas_centavos'],
                                      'Saldo após candidatas_centavos':r['saldo_apos_todas_candidatas_centavos']} for r in composition if r['candidatas']]),hide_index=True,width='stretch')
            for hint in core.relationship_hints(d,current):
                st.info(f"Indício: {hint['codigo']} · {hint['descricao']} tem {core.brl(hint['valor_centavos'])} e quantidade {hint['quantidade']}, iguais a uma linha de {hint['base']} com 20%. A ligação individual não está comprovada.")
            pending=[r for r in current if r['efeito']=='Pendente']
            if pending:
                st.caption(f'{len(pending)} pendências na folha. Rubricas sem base determinada não são atribuídas automaticamente ao mensal ou ao 13º. Veja o grupo Não determinado, ordenado por valor.')
            st.dataframe(display(d['checagens']),hide_index=True)
        with st.expander('Ajustar uma correspondência ou rating — opcional'):
            choice=st.selectbox('Rubrica para revisar',range(len(current)),format_func=lambda i:current[i]['codigo']+' · '+current[i]['descricao'])
            r=current[choice]
            with st.form('review_'+doc_id+'_'+str(choice)):
                effects=['Pendente','Acrescenta (sugestão)','Reduz (sugestão)','Não integra (sugestão)','Acrescenta','Reduz','Não integra']
                effect=st.selectbox('Efeito adotado',effects,index=effects.index(r['efeito']))
                scope_options=['Não determinada','Mensal','13º','Não se aplica']
                scope=st.selectbox('Base',scope_options,index=scope_options.index(r['base']))
                ratings=['Sem classificação','Verde','Amarelo']
                rating=st.selectbox('Rating da equipe',ratings,index=ratings.index(r['rating']))
                why=st.text_input('Justificativa',value=r['justificativa'])
                who=st.text_input('Responsável',value=r.get('responsavel',''))
                if st.form_submit_button('Salvar ajuste'):
                    if effect.startswith(('Acrescenta','Reduz')) and scope not in ('Mensal','13º'): st.error('Informe mensal ou 13º para um efeito que compõe a base.')
                    elif not why.strip() or not who.strip(): st.error('Informe justificativa e responsável para alterar o critério.')
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
    import report_state
    report_state.context(st.session_state,a)
    st.subheader('Relatório por competência')
    st.caption('Três abas: Composição dos 20%, Composição da base total e Simulação proporcional. O consolidado e o relatório de um mês usam o mesmo padrão, com hipóteses e estimativas separadas.')
    if filtered_docs:
        import simple_report
        mode=st.radio('Modelo do relatório',['Consolidado','Por competência'],horizontal=True,key='report_mode')
        company_options=sorted({d['cnpj'] for d in filtered_docs})
        report_state.multiselect(st.session_state,'report_companies',company_options)
        companies=st.multiselect('Empresas do relatório',company_options,key='report_companies')
        available=sorted({d['competencia'] for d in filtered_docs if d['cnpj'] in companies})
        if mode=='Consolidado':
            report_state.multiselect(st.session_state,'report_periods',available)
            periods=st.multiselect('Competências do relatório',available,key='report_periods')
        else:
            report_state.single(st.session_state,'report_single_period',available)
            period=st.selectbox('Competência do relatório',available,key='report_single_period')
            periods=[period] if period else []
        kind_options=sorted({d['tipo'] for d in filtered_docs if d['cnpj'] in companies and d['competencia'] in periods})
        report_state.multiselect(st.session_state,'report_kinds',kind_options)
        kinds=st.multiselect('Tipos de folha',kind_options,key='report_kinds')
        docs=simple_report.select_documents(filtered_docs,companies,periods,kinds)
        export_a={**a,'versao_relatorio':core.VERSION,'modelo_relatorio':mode,'filtro_previdencia':previdencia_filter,'docs':docs}
        st.caption(f"Recorte: {len(docs)} folha(s), {len({d['competencia'] for d in docs})} competência(s). Filtro de previdência empresa: {previdencia_filter}. Os filtros do relatório são independentes do mês aberto na aba Base INSS empresa.")
        st.dataframe(display([{'Competência':d['competencia'],'CNPJ':d['cnpj'],'Tipo de folha':d['tipo'],
            'Base mensal_centavos':d.get('bases',{}).get('mensal'),'Base de 13º_centavos':d.get('bases',{}).get('13'),
            'Arquivo':d['arquivo'].split(' :: ')[-1]} for d in docs]),hide_index=True,width='stretch')
        with st.expander('Como ler o relatório'):
            st.write('Cada competência é apresentada em blocos por folha, com mensal e 13º separados. A primeira aba reúne a base dos 20%, as rubricas da hipótese e a diferença. Reduções e candidatas têm seções próprias. A segunda mostra a composição da base total. A terceira reúne exclusivamente as simulações proporcionais para grupos mistos, com acréscimos, reduções e candidatas separados.')
            st.caption('Não some hipóteses com estimativas. O Excel é um retrato da análise: alterações não recalculam as classificações nem retornam ao aplicativo.')
        if not docs:
            if not companies:st.info('Selecione uma empresa em Empresas do relatório.')
            elif not periods:st.info('Selecione pelo menos uma competência para o relatório.')
            elif not kinds:st.info('Selecione pelo menos um tipo de folha para o relatório.')
            else:st.info('Nenhuma folha corresponde aos filtros do relatório. Revise empresa, competência, tipo de folha e o filtro previdenciário.')
        if st.button('Preparar relatório Excel',type='primary',disabled=not docs):
            with st.spinner('Organizando competências e rubricas no Excel…'):
                st.session_state.excel=core.export_excel(export_a)
                st.session_state.excel_signature=json.dumps(export_a,sort_keys=True)
        if docs and st.session_state.get('excel_signature')==json.dumps(export_a,sort_keys=True):
            filename='composicao_inss_'+('consolidado' if mode=='Consolidado' else periods[0])+'.xlsx'
            st.download_button('Baixar '+filename,st.session_state.excel,filename,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        st.info('Nenhuma folha no filtro atual. Altere o filtro para gerar o Excel.')
