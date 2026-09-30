# Revisão dos consolidados para apresentação

Data: 29/09/2026. Versão do programa: 0.12.2.

## Conclusão

A extração e as operações aritméticas verificadas estão consistentes. A composição previdenciária permanece uma hipótese em diversos blocos: estes relatórios não são apuração de crédito ou confirmação de recolhimento. Não apresentar os saldos como crédito disponível.

## O que foi verificado

- 188 PDFs originais, com verificação de integridade SHA-256 e reextração integral.
- 10.823 ocorrências de rubricas; bases, totais, grupos e identificação confrontados com os dados salvos.
- 564 verificações de totais (proventos, descontos e líquido), todas com diferença zero.
- Sem documentos repetidos para a mesma empresa, competência e tipo no recorte.
- 100 testes automatizados aprovados.
- Classificações, projeções e cenários idênticos à versão 0.12.1. Nenhum valor foi ajustado para fechar uma base.

## Melhorias no Excel

- Resumo inicial de conciliação e conferência da extração.
- Quantidade de fechamentos exatos que ainda têm rubricas pendentes.
- Diferenças de extração por documento na aba de apoio.
- Descrição do cadastro e incidência CP junto às pendências.
- Preservação das três abas e dos cenários independentes.

## AJ Serviços

125 folhas e 6438 ocorrências de rubricas.

Conciliação: {'Inconclusiva': 8, 'Divergente': 150, 'Fechamento exato': 73}. Entre os fechamentos exatos, 53 têm rubricas pendentes ou sem base determinada.

### Referências suspensas no PDF

- 2016-12, base 13º: quantidade da base 62; quantidade da contribuição 61. Base R$ 78665.13; contribuição R$ 15717.79. Arquivo: AJ.zip :: AJ/FOLHA DE PG 2016 AJ.rar :: FOLHA DE PG 2016/FOLHA PG DEZ 2016.pdf.
- 2018-12, base 13º: quantidade da base 1; quantidade da contribuição 2. Base R$ 47.00; contribuição R$ 226.67. Arquivo: AJ.zip :: AJ/FOLHA DE PG 2018 AJ .rar :: FOLHA DE PG 2018/FOLHA DE PG DEZ 2018.pdf.

### Maiores diferenças na projeção principal

| Competência | Folha | Base | Diferença (R$) |
|---|---|---|---:|
| 2015-10 | Mensal | Mensal | 38032.20 |
| 2015-12 | Mensal | Mensal | 18533.20 |
| 2015-11 | Mensal | Mensal | 18152.65 |
| 2015-09 | Mensal | Mensal | 17534.43 |
| 2024-07 | Mensal | Mensal | 17303.67 |
| 2017-11 | Mensal | Mensal | 16932.77 |
| 2017-02 | Mensal | Mensal | 16690.52 |
| 2016-01 | Mensal | Mensal | 16376.41 |

Diferença = base dos 20% menos projeção. Não representa crédito.

## Adserv

63 folhas e 4385 ocorrências de rubricas.

Conciliação: {'Inconclusiva': 8, 'Divergente': 59, 'Fechamento exato': 55}. Entre os fechamentos exatos, 53 têm rubricas pendentes ou sem base determinada.

### Referências suspensas no PDF

- 2016-06, base 13º: quantidade da base 8; quantidade da contribuição 21. Base R$ 4586.85; contribuição R$ 3454.23. Arquivo: Adserv.zip :: Adserv/FOLHAS 01 A 12 2016.rar :: JUNHO 2016.pdf.
- 2016-12, base 13º: quantidade da base 6; quantidade da contribuição 5. Base R$ 6280.97; contribuição R$ 1210.15. Arquivo: Adserv.zip :: Adserv/FOLHAS 01 A 12 2016.rar :: DEZEMBRO 2016.pdf.
- 2018-08, base Mensal: quantidade da base 600; quantidade da contribuição 17. Base R$ 1284012.52; contribuição R$ 7924.53. Arquivo: Adserv.zip :: Adserv/FOLHAS 01 A 12 2019.rar :: AGOSTO COMPLEMENTAR 2019.pdf.
- 2020-12, base Mensal: quantidade da base 2338; quantidade da contribuição 62. Base R$ 2522684.45; contribuição R$ 4580.96. Arquivo: Adserv.zip :: Adserv/FOLHAS 01 A 12 2020.rar :: DEZEMBRO 2� PARC DO 13� 2020.pdf.

### Maiores diferenças na projeção principal

| Competência | Folha | Base | Diferença (R$) |
|---|---|---|---:|
| 2017-05 | Mensal | Mensal | 38204.96 |
| 2017-10 | Mensal | Mensal | 36201.57 |
| 2016-10 | Mensal | Mensal | 34294.74 |
| 2017-04 | Mensal | Mensal | 32588.80 |
| 2017-07 | Mensal | Mensal | 30131.98 |
| 2019-08 | Mensal | Mensal | 29408.23 |
| 2017-06 | Mensal | Mensal | 28040.50 |
| 2017-11 | Mensal | Mensal | 27738.61 |

Diferença = base dos 20% menos projeção. Não representa crédito.

Alerta documental em 2018-08 (Complementar): Ano do nome diverge do período interno.. O período interno foi preservado.
Alerta documental em 2020-12 (Complementar): Nome indica 13º, cabeçalho indica complementar.. O período interno foi preservado.

## O que permanece pendente

- Confirmar a identidade do código 8003 da AJ com o cadastro aplicável à competência. A suspensão da redução não equivale à confirmação de exclusão.
- Validar incidências históricas e participação das rubricas nos blocos divergentes, incluindo maternidade. Os cenários não alteram a projeção principal.
- Esclarecer as seis referências suspensas nas folhas originais; não reconstruir vínculos entre grupos apenas por coincidência de valores.
- Confirmar os dois alertas de nome de arquivo/cabeçalho da Adserv.
- A igualdade dos totais de extração e a reprodutibilidade do parser não substituem a revisão de incidência previdenciária.
- Não houve validação jurídica de elegibilidade, prescrição ou comprovação de pagamentos nesta revisão.
- A interface Streamlit não foi operada interativamente; cálculos e arquivos exportados foram testados.