# Leitura crítica do padrão de análise de ICMS-ST

Material de estudo: [padrao_analise_icms_st_sped.pdf](padrao_analise_icms_st_sped.pdf), recebido em 21/10/2026. O PDF foi produzido a partir de pesquisa na internet; suas sugestões não são regras automáticas do auditor nem substituem fontes oficiais.

## Objetivo do trabalho

O auditor identifica receitas e contribuições **escrituradas** que podem conter ICMS-ST na base de PIS/COFINS, preserva as evidências e estima eventual exclusão somente quando houver base documental suficiente. O software não altera nem retifica EFD, declarações ou documentos fiscais. A decisão e execução de eventual retificação cabem à contabilidade da empresa.

## Triagem manual a preservar

Nas saídas, filtrar o registro C175 da EFD-Contribuições por CFOP 5405 e CST de PIS/COFINS 01. Registrar estabelecimento, competência, CFOP, CST, alíquotas, valor da operação, bases e contribuições escrituradas. Esse filtro prioriza operações com tributação informada que merecem revisão; ele não demonstra, sozinho, ICMS-ST excluível nem valor de crédito recuperável. Examinar separadamente CST 02 e outras situações tributadas, conforme a escrituração e a regra aplicável, sem misturar CST 05 (substituição tributária das próprias contribuições) com ICMS-ST. CST 04 e 06 não devem gerar estimativa de PIS/COFINS pago a maior sem evidência de débito.

## Pontos aproveitáveis do PDF

- Procurar ICMS-ST documentado nas aquisições e preservar chave, item, fornecedor, estabelecimento e período.
- Relacionar o valor de ST das aquisições com as receitas do contribuinte substituído, evitando dupla contagem de estoque, transferências e devoluções.
- Conferir o resultado com a apuração da EFD-Contribuições e identificar valores já aproveitados antes de apresentar eventual crédito.

## Limites do PDF e dos arquivos atuais

- C175 agrupa valores por critérios fiscais; não traz, por si só, código de produto e quantidade para ligar uma venda específica a uma aquisição. Não atribuir produto ao C175 por inferência.
- A fórmula `ST por unidade adquirida × quantidade vendida` é uma hipótese de alocação que exige método verificável de estoque, unidades, saldos, transferências e devoluções; não deve ser tratada como regra jurídica geral ou cálculo validado apenas por H010/K200.
- Os Excel atualmente fornecidos não mostram ST positivo nas entradas C100/C170 analisadas. O H010 disponível é fotografia de inventário; não há K200 nem C176 nos arquivos analisados. O EFD ICMS/IPI recebido cobre a matriz, enquanto as saídas tributadas relevantes também aparecem em filiais.
- O PDF sugere retificações; essa etapa está fora do escopo operacional do auditor. O C190 existente nos arquivos analisados pertence à EFD ICMS/IPI e não resolve a apuração de PIS/COFINS no C175.

## Estados de evidência para relatórios futuros

1. **Receita escriturada sob revisão:** filtro C175, com base e contribuições informadas, sem declarar crédito.
2. **ICMS-ST documental localizado:** valor e documento de aquisição do substituto identificados.
3. **Exclusão calculável:** vínculo e critério de alocação entre ST e receita tributada demonstrados, com reconciliação por competência.
4. **Valor recuperável validado externamente:** pagamento, declarações e aproveitamentos anteriores conferidos pelo responsável tributário.

## Fontes oficiais para confrontar a metodologia

- [Receita Federal: jurisprudência vinculante PIS/Cofins, incluindo Tema 1125](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/legislacao/jurisprudencia-vinculante/pis-cofins).
- [Solução de Consulta Cosit nº 100/2025](https://normas.receita.fazenda.gov.br/sijut2consulta/consulta.action?ano_ato=2025&numero_ato=100&orgaosSelecionados=Cosit&tiposAtosSelecionados=72).
- [Tabela oficial de CST da EFD-Contribuições](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/tabelas-de-codigos/tabelas-utilizadas-na-apuracao-das-contribuicoes-para-o-pis-pasep-e-da-cofins/tabela-4-3-12).
