"""Presentation of the existing analysis; no payroll classification is changed here."""
from collections import Counter

MAIN_SHEETS = [
    'Base INSS empresa', 'Composicao dos 20', 'Rubricas dos 20',
    'Simulacao proporcional', 'Rubricas estimadas', 'Cruzamento por folha',
    'Pendencias', 'Selecionadas', 'Conferencia bases', 'Memoria composicao',
    'Grupos base empresa', 'Resumo previdenciario', 'Conferencia extracao',
    'Documentos', 'Criterios',
]

LABELS = {
    'cnpj':'CNPJ', 'empresa':'Empresa', 'competencia':'Competência', 'tipo':'Tipo de folha',
    'documento':'ID do documento', 'hash':'ID do documento', 'codigo':'Código',
    'descricao':'Rubrica na folha', 'lado':'Provento ou desconto', 'base':'Base das rubricas',
    'valor':'Valor integral da rubrica', 'parcela':'Parcela com sinal',
    'arquivo':'Arquivo de origem', 'pagina':'Página', 'paginas':'Páginas',
    'grupo':'Grupo', 'papel':'Papel na composição', 'selecionada':'Selecionada',
    'rating':'Rating da equipe', 'codIncCP':'Código de incidência CP',
    'efeito':'Indicação adotada', 'efeito_relatorio':'Indicação do cadastro',
    'referencia':'Referência da incidência', 'motivo':'Motivo da classificação',
    'correspondencia':'Correspondência com o cadastro', 'descricao_relatorio':'Rubrica no cadastro',
    'vigencia_relatorio':'Vigência do cadastro', 'fonte_referencia':'Fonte da incidência',
    'base_candidata':'Base candidata', 'criterio_candidato':'Critério da candidata',
    'natureza':'Natureza', 'situacao_patronal':'Situação patronal informada',
    'base_20':'Base vinculada aos 20%', 'parcela_projetada':'Parcela projetada / hipótese',
    'saldo_nao_identificado':'Saldo não identificado nos 20%',
    'candidatas_conflitantes':'Candidatas fora da projeção',
    'saldo_condicionado':'Saldo se todas as candidatas forem validadas',
    'parcela_candidata':'Candidata fora da projeção', 'evidencia_20':'Evidência para os 20%',
    'base_total_pdf':'Base total do bloco no PDF', 'base_20_pdf':'Base dos 20% no PDF',
    'fator_proporcao':'Proporção monetária dos 20%', 'saldo_estimado':'Saldo estimado',
    'diferenca_para_base_20':'Base dos 20% menos saldo estimado',
    'diferenca_com_candidatas':'Diferença se todas as candidatas forem validadas',
    'estimativa':'Parcela estimada com sinal', 'valor_integral':'Valor integral da rubrica',
    'parcela_integral':'Parcela integral com sinal', 'cenario':'Cenário',
    'informada':'Base total do bloco no PDF', 'reconstruida':'Parcela explicada da base total',
    'saldo_sem_explicacao':'Base total menos parcela explicada',
    'diferenca':'Parcela explicada menos base total',
    'saldo_apos_todas_candidatas':'Saldo da base total após todas as candidatas',
    'referencia_20':'Referência dos 20%', 'referencia_zerada':'Base com contribuição zerada',
    'base_centavos':'Base do grupo (R$)', 'contribuicao':'Contribuição do grupo no PDF',
    'quantidade_base':'Quantidade na linha da base', 'quantidade_contribuicao':'Quantidade na linha da contribuição',
    'aliquota_percentual':'Alíquota informada (%)', 'validacao':'Validação do vínculo',
    'motivo_validacao':'Motivo da validação', 'situacao_grupos':'Situação dos grupos no PDF',
    'base_mensal':'Base mensal total no PDF', 'base_13':'Base de 13º total no PDF',
    'base_20_mensal':'Base dos 20% mensal', 'base_20_13':'Base dos 20% de 13º',
    'base_empresa_total':'Total da base empresa', 'previdencia_empresa_total':'Total de previdência empresa',
    'rat_total':'RAT', 'segurados_total':'Contribuições descontadas dos segurados',
    'situacao_mensal':'Situação dos grupos mensais', 'situacao_13':'Situação dos grupos de 13º',
    'pontos_de_atencao':'O que conferir', 'rubricas':'Quantidade de rubricas',
    'acrescimos_qtd':'Rubricas em possíveis acréscimos', 'reducoes_qtd':'Rubricas em reduções',
    'fora_qtd':'Rubricas fora segundo cadastro', 'pendentes_qtd':'Rubricas não determinadas',
    'selecionadas_qtd':'Rubricas selecionadas', 'criterio':'Critério', 'situacao':'Situação',
    'conclusao_composicao':'Conclusão da composição', 'responsavel':'Responsável',
    'justificativa':'Justificativa da revisão', 'observacao_analista':'Observação do analista',
    'suporte':'Documento ou observação de suporte', 'nota_previdencia':'Leitura dos totais previdenciários',
}

def label(field):
    if field in LABELS:
        return LABELS[field]
    money=field.endswith('_centavos')
    key=field.removesuffix('_centavos')
    return LABELS.get(key,key.replace('_',' ').capitalize()) + (' (R$)' if money else '')

def overview(a, rows=None):
    import core
    rows=core.details(a) if rows is None else rows
    result=[]
    for d in sorted(a['docs'],key=lambda d:(d['cnpj'],d['competencia'],d['tipo'],d['hash'])):
        items=[r for r in rows if r['documento']==d['hash']]
        counts=Counter(r['grupo'] for r in items)
        refs={r['base']:r for r in core.company_summary(d)}
        twenty,_=core.twenty_composition({**a,'docs':[d]},items)
        checks=[]
        for t in twenty:
            if refs[t['base']]['situacao_grupos']=='Vínculo entre base e contribuição a conferir':
                checks.append(t['base']+': referência dos 20% suspensa')
            elif t['saldo_nao_identificado_centavos'] not in (None,0):
                checks.append(t['base']+': composição dos 20% com diferença')
            if t['quantidade_candidatas']:
                checks.append(t['base']+': candidatas conflitantes')
        if counts['Não determinado']: checks.append('Rubricas sem indicação determinada')
        if d.get('alertas'): checks.append('Alertas de extração no documento')
        row={'cnpj':d['cnpj'],'competencia':d['competencia'],'tipo':d['tipo'],
             'base_mensal_centavos':d.get('bases',{}).get('mensal'),
             'base_13_centavos':d.get('bases',{}).get('13'),
             'base_20_mensal_centavos':refs['Mensal']['base_20_centavos'],
             'base_20_13_centavos':refs['13º']['base_20_centavos']}
        for key in core.PREVIDENCIA:
            row[key+'_centavos']=d.get('previdencia',{}).get(key,{}).get('valor_centavos')
        row.update(situacao_mensal=refs['Mensal']['situacao_grupos'],situacao_13=refs['13º']['situacao_grupos'],
                   rubricas=len(items),acrescimos_qtd=counts['Possíveis acréscimos'],reducoes_qtd=counts['Reduções da base'],
                   fora_qtd=counts['Fora da base segundo cadastro'],pendentes_qtd=counts['Não determinado'],
                   selecionadas_qtd=sum(bool(r['selecionada']) for r in items),
                   pontos_de_atencao='; '.join(checks) or 'Sem alerta nas verificações disponíveis; validar composição',
                   situacao_patronal=a.get('regimes',{}).get(d['cnpj']+'|'+d['competencia'],'Não verificada'),
                   suporte=a.get('regime_evidence',{}).get(d['cnpj']+'|'+d['competencia'],''),
                   nota_previdencia='Totais transcritos do PDF. Previdência empresa não comprova valor pago. Vazios indicam dados não localizados ou referência suspensa.',
                   empresa=d.get('empresa',''),arquivo=d['arquivo'],documento=d['hash'])
        result.append(row)
    return result

GUIDE = {
    'Base INSS empresa':'Uma linha por PDF. Comece pelos totais e pela coluna O que conferir. Os totais do documento não são repetidos por mensal e 13º.',
    'Composicao dos 20':'Uma linha por PDF e base (mensal/13º), com referência, hipótese, saldo e candidatas separadas.',
    'Rubricas dos 20':'Parcelas e indícios que sustentam o bloco dos 20%. Candidatas conflitantes não entram na projeção.',
    'Simulacao proporcional':'Cenário independente para grupos mistos válidos. Não somar à hipótese. Fator monetário não é confiança.',
    'Rubricas estimadas':'Memória por rubrica do rateio. O cenário de conflitos está separado da estimativa pelo cadastro.',
    'Cruzamento por folha':'Todos os quatro grupos da tela. Filtre Grupo, Base das rubricas, Selecionada, empresa, competência e tipo. Possíveis acréscimos não significam atribuição aos 20%.',
    'Pendencias':'Rubricas não determinadas, ordenadas por valor absoluto dentro de cada folha. Valor integral não é parcela dos 20%.',
    'Selecionadas':'Destaques manuais com grupo, base, rating e justificativa preservados. Observação do analista é livre no Excel e não retorna ao aplicativo.',
    'Conferencia bases':'Conferência da base total mensal/13º, distinta da composição dos 20%.',
    'Memoria composicao':'Parcelas com sinal e candidatas da conferência da base total. Use Papel na composição para separar os cenários.',
    'Grupos base empresa':'Linhas originais de base, quantidade e contribuição com validação. Quantidades não são pessoas únicas.',
    'Resumo previdenciario':'Quatro indicadores por documento, com página e distinção entre zero e ausência.',
    'Conferencia extracao':'Checagens aritméticas da extração por documento.',
    'Documentos':'Identificação dos PDFs e alertas de processamento.',
    'Criterios':'Recorte, data, versão e orientações. O Excel é um retrato da análise: alterações de valores não recalculam as classificações. Gere novamente após revisar no aplicativo.',
}
