# Conciliação de Salário-Maternidade

Aplicação Streamlit independente para:

1. extrair salário-maternidade de Declarações Completas da DCTFWeb em PDF/ZIP;
2. gerar um Excel consolidado;
3. comparar principal e apoios com o declarado, validando a origem nos documentos de apoio.

## Execução local

```powershell
python -m pip install -r requirements.txt
streamlit run app.py
```

Os uploads são processados em memória e não são persistidos pela aplicação.

## Entradas e fluxo

- MANAD: levantamento Excel (`K300_FILTRADO` e `K150_SELECIONADAS`), arquivo MANAD completo TXT e DCTFWeb. O cadastro do TXT é associado por CNPJ/código; os lançamentos do levantamento são conferidos individualmente, preservando repetições e apontando excedentes ou divergências.
- eSocial: levantamento Excel (`03_movimentos`, `03_movimentos_cp` ou `apoio_s1200`), relatório de incidência Excel e DCTFWeb. Não são importados XMLs. O relatório completo fornece movimentos, classificação e rastreabilidade. Versões resumidas ou registros sem S-1010 resultam em validação parcial.
- DCTFWeb: PDF, ZIP ou Excel de maternidade gerado pelo módulo 1. Excel antigo contendo apenas salário-família precisa ser regenerado.

O levantamento direciona; o documento de apoio valida. Lançamentos relacionados à maternidade que existem no validador e faltam no levantamento são reportados, mas não adicionados automaticamente aos valores. Bases espelhadas como `apoio_s1200` e `03_movimentos_cp` não são somadas entre si.

## Classificação e períodos

O termo `matern` sugere candidatos sem fixar códigos de empresas. Todos os itens do levantamento permanecem revisáveis, inclusive descrições alternativas. A interface permite classificar cada rubrica como Principal, Apoio ou Excluir. Sugestões não são conclusões jurídicas.

Licença, prorrogação, rescisão, indenização e outros itens ambíguos recebem Revisar. Itens de 13º em competência mensal e valores de períodos anteriores exigem justificativa; uma competência de destino opcional deve permanecer no mesmo ano dos registros. Quando há vários anos, separe o levantamento por ano para reclassificar o destino.

As competências são ordenadas por ano e período dentro de cada CNPJ. `MM/AAAA` representa apuração mensal; `AAAA` representa anual de 13º. `13AAAA` no MANAD é normalizado para `AAAA`. CNPJ de oito dígitos não é completado artificialmente. No eSocial usa-se o estabelecimento; confira sua correspondência com a DCTFWeb.

## Relatório final

A aba Comparativo contém Principal, Apoios considerados, Total identificado, Declarado no e-CAC, Potencial crédito sem apoios e Potencial crédito com apoios. As duas colunas de crédito mostram somente excedentes positivos sobre o declarado e ficam indisponíveis quando falta algum valor necessário. Declarado superior, com e sem apoios, aparece em colunas separadas.

O Excel também contém dados e-CAC com referência ao documento/recibo, consolidação por grupo, composição dos lançamentos, classificação adotada, critérios e ocorrências. Campos ausentes não viram zero; a retificadora mais recente prevalece e as declarações anteriores continuam na aba Documentos do Excel de extração. Os resultados dependem da composição selecionada e da validação jurídica.

## Testes

```powershell
python -m unittest discover -s tests -v
```
