# Auditor SPED: módulos dos Temas 1125 e 69

Estado da implementação em 22/10/2026. Este documento distingue o que o
aplicativo já calcula do que ainda depende de fonte ou conferência adicional.

## Fluxo único de entrada

1. O usuário informa os Excel do Sysconv por upload ou caminho local.
2. A pré-análise inventaria abas e mostra CFOP/CST das saídas C170 e C175 da
   EFD-Contribuições e CFOP das saídas C190 do ICMS/IPI. C190 não contém CST
   de PIS/COFINS e não entra sozinho no filtro do Tema 1125.
3. O usuário confere regime, alíquotas ausentes e UF de referência do Tema 1125.
4. Após a pré-análise única, cada regra do catálogo aparece como bloco de
   investigação. Os Temas 1125 e 69 têm execução e Excel independentes; os
   outros quatro blocos mostram "Em preparação" e não oferecem cálculo.
5. Executar um tema não apaga o resultado do outro. Os resultados detalhados
   permanecem em duas abas dentro de Análise. Mudar de aba não recalcula.
6. A barra de progresso mostra etapas concluídas na leitura e em cada módulo.
   Ela não estima tempo restante: arquivos grandes podem demorar mais em uma
   única etapa. O botão "Nova análise · limpar tudo" reinicia entradas,
   contexto, pré-análise e resultados da sessão para outro levantamento.

Cada bloco representa uma possível linha de investigação, não um crédito
automaticamente devido. Para ativar outro bloco no futuro, será preciso
implementar critérios, validações, cálculo, relatório e testes próprios.

## Recorte quinquenal e prescrição

- A data de referência é escolhida no aplicativo (por padrão, o dia da
  análise). O corte é o mesmo dia, cinco anos antes. Ambos os módulos só
  somam competências inteiramente dentro desse intervalo.
- O mês que cruza o corte fica fora do cálculo automático e é contado como
  pendência. Competências anteriores e futuras também ficam fora. O mapa de
  escrituração e os diagnósticos exibidos seguem o mesmo recorte.
- O Excel registra a data de referência, o corte e os registros excluídos.
  A conferência manual tem campos para data de extinção/recolhimento, medida
  que afete o prazo e conclusão do revisor. No Tema 1125, as fórmulas de
  crédito com ST comprovado só produzem valor após marcar prazo conferido.
- Este é um recorte operacional conservador, não uma declaração de
  prescrição: o art. 168 do CTN conta o prazo da extinção do crédito
  tributário, que os C170/C175 não demonstram. A equipe deve verificar
  pagamentos, eventuais medidas judiciais/administrativas e modulação dos
  Temas 69 e 1125 antes de validar o levantamento.

## Tema 1125: ICMS-ST

- Fontes das vendas: C170 e C175 da EFD-Contribuições, inclusive abas divididas.
  O filtro inicial é CFOP 5405 e CST 01 em PIS e COFINS. A origem acompanha
  cada grupo e cada NF-e do relatório.
- Alíquotas de PIS/COFINS escrituradas têm prioridade. Apenas lacunas pedem
  escolha manual, identificada no relatório.
- O método existente usa a base conferida e a alíquota interna geral com
  vigência cadastrada para a UF, limitado às contribuições escrituradas. É
  apresentado como **possível crédito pela premissa estadual**. A alíquota
  geral não representa o ST efetivamente suportado na aquisição.
- C100/C170 das entradas e C190 do ICMS/IPI continuam como diagnósticos de ST.
  Esses níveis não são somados às vendas nem entre si.
- A conferência por NF-e pede notas de aquisição e ST comprovado alocado. O
  mesmo valor de aquisição não deve ser alocado mais de uma vez; esse controle
  ainda depende da revisão da memória e dos documentos.
- Duplicidade de item C170, repetição C175 entre abas, chave incompatível,
  base divergente e sobreposição de uma NF-e entre C170/C175 aparecem como
  pendência. Grupos afetados ficam fora do total automático.

## Tema 69: ICMS próprio

- Módulo e Excel próprios. As receitas são saídas C170/C175 da
  EFD-Contribuições, com CFOP 5xxx/6xxx e CST 01/02 em PIS e COFINS.
- ICMS próprio vem do C170 do ICMS/IPI por chave e item, quando o par é único;
  quando não há item de saída, vem do C190 por chave e CFOP. C170 e C190 não
  são somados como se fossem impostos distintos.
- O cálculo preliminar multiplica o ICMS próprio escriturado pela alíquota
  efetiva escriturada de PIS/COFINS, com limite no valor da contribuição da
  operação. A alíquota geral da UF aparece só como referência de conferência.
- Chave ou item inválido, duplicidade, CST misto, alíquotas distintas sem
  alocação, base/contribuição incompatível e sobreposição C170/C175 bloqueiam
  o cálculo do grupo. O relatório registra a aba, a primeira linha e o motivo.
- O número é **possível valor sob conferência**, não valor fiscal validado.
  A inclusão original do ICMS na base, a NF-e, a apuração, o recolhimento e
  exclusões anteriores precisam ser conferidos externamente.

## Próximas verificações fiscais

- Confrontar M210/M610 e ajustes para identificar exclusões já realizadas e
  evitar duplicidade de recuperação entre períodos.
- Conferir status e data exata da nota no C100, retificações e abrangência da
  escrituração por estabelecimento; a premissa histórica do Tema 1125 ainda
  é aplicada por competência no cálculo automático.
- Definir vínculo entre produtos comprados, estoque, vendas e ICMS-ST da nota
  de aquisição; controlar consumo do ST alocado entre todas as vendas.
- Investigar CFOPs de ST fora do 5405 apontados pelo mapa e casos em que só
  exista C190/C100, sem CST de PIS/COFINS conciliável.
- Expandir e verificar as alíquotas estaduais com datas de vigência. O
  panorama anual de 27 UFs não autoriza cálculo automático para todas elas.

O programa não altera nem retifica a escrituração. A interpretação jurídica
final e a decisão de aproveitamento continuam com a equipe fiscal.
