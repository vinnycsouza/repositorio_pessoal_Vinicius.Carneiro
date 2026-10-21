# Evolução da apuração de ICMS-ST e PIS/COFINS

## Princípio

O auditor deve separar três grandezas: imposto destacado/escriturado, diferença teórica de apuração e valor efetivamente passível de recuperação. Nenhuma soma de ICMS-ST em entradas é, por si, crédito de PIS/COFINS ou restituição estadual de ICMS-ST.

## Fontes já disponíveis

- EFD-Contribuições: 0000, C010, 0110, C100 (duas abas), C170, C175 (duas abas), M100/M500, M200/M600 e M210/M610.
- EFD ICMS/IPI fornecido: 0000, C100, C170, C190 e E110; cobre somente a matriz nos dados deste caso.
- ECD e ECF: inventariados, ainda sem conciliação contábil.

## Entregas em sequência

1. **Diagnóstico de ST escriturado.** Procurar o valor positivo de ICMS-ST em entradas C170, notas C100 e agregados C190, por estabelecimento e competência; destacar transferências e guardar a linha de origem. Resumir em separado as vendas C175 com CFOP 5405 por CST e alíquota. Estes relatórios já estão disponíveis no aplicativo e não calculam crédito. Se o destaque da aquisição estiver ausente, buscar a nota emitida pelo substituto ou outra evidência fiscal válida.
2. **Conciliação documental.** Ler C100 e todas as abas de continuação, validar chave da NF-e e item, confrontar o ST de C100 com a soma de C170 e isolar notas canceladas, duplicadas ou retificadas. Preservar o arquivo, a aba, a linha, o CNPJ e a competência.
3. **Exclusão de ICMS próprio (Tema 69).** Vincular a saída do estabelecimento à nota emitida e à base de PIS/COFINS escriturada; usar o ICMS destacado na nota e a alíquota efetiva do registro/período. Confrontar a diferença por competência com M210/M610 e M200/M600.
4. **Exclusão de ICMS-ST do substituído (Tema 1125).** Confirmar a condição de substituído e o ST destacado na nota de aquisição emitida pelo substituto. Relacionar aquisições, estoque e saídas tributadas sem somar transferências internas duas vezes. C175 informa agrupamentos fiscais, não itens; uma vinculação por produto depende de documento ou detalhe adicional.
5. **Validação do valor recuperável.** Confrontar a apuração recalculada com declarações, pagamentos, compensações anteriores e eventuais retificações. Registrar separadamente valor teórico, valor pago a maior e saldo ainda não utilizado.

## Saída esperada

Uma linha por hipótese, estabelecimento e competência, com base e imposto originais, ajuste proposto, cálculo por PIS e COFINS, fonte de cada parcela, situação da conciliação e pendências. Os estados devem distinguir `Dado escriturado`, `Candidato calculável`, `Pendente de documento`, `Pendente de pagamento/compensação` e `Validado externamente`.

## Dependência deste caso

Para as saídas de filiais sem cobertura no ICMS/IPI fornecido, obter o arquivo do estabelecimento correspondente se a regra depender do confronto da mesma saída nos dois SPEDs. Para ST do substituído, obter as notas de aquisição do fornecedor quando o destaque não puder ser confirmado nos Excel.

## Trilha estadual separada

Ressarcimento estadual do próprio ICMS-ST exige regra da UF e vinculação de compra, estoque e venda. Deve ter módulo e relatório próprios, sem misturar valores com a exclusão de ICMS-ST da base de PIS/COFINS.
