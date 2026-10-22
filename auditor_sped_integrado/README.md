# Auditor SPED integrado — versão inicial

> **Atualização de 22/10/2026:** o fluxo atual separa os Temas 1125 e 69 e
> lê saídas C170/C175, com mapa de C190. Consulte
> [ARQUITETURA_1125_69.md](ARQUITETURA_1125_69.md) para o comportamento e os
> limites atuais. As descrições abaixo registram a evolução da versão inicial.

Projeto local para organizar análises de possíveis recuperações tributárias com trilha de evidências. Reaproveita o formato dos Excel C170 usado em `projeto_icms_piscofins`. A triagem usa **chave da NF-e + item + estabelecimento + competência + saída**, com bloqueio de pares ambíguos.

## Entradas

- Excel `.xlsx` ou `.xlsm` do Sysconv para EFD ICMS/IPI, EFD-Contribuições, ECD e ECF: hash SHA-256 e contagem de linhas por aba;
- Abas C170 dos Excel de EFD ICMS/IPI e EFD-Contribuições: triagem fiscal em nível de item;
- Aba 0000 do ICMS/IPI: cobertura por CNPJ e competência.

Cada Excel pode ser selecionado pelo navegador ou informado por caminho local completo. Os arquivos selecionados são processados em memória; os arquivos indicados por caminho são lidos diretamente do disco. A triagem usa as abas C170 dos dois primeiros. ECD e ECF ainda não têm interpretação contábil automática nesta versão. O inventário conta as linhas registradas no XML de cada aba, ignorando a dimensão declarada pelo Excel, e desconta a primeira linha como cabeçalho. Linhas vazias que tenham um elemento de linha no arquivo também entram nessa contagem.

## Saídas e segurança jurídica

- Indício de possível ICMS próprio não excluído da base de PIS/COFINS (Tema 69);
- Item com ICMS-ST sinalizado para verificar a situação do substituído e o Tema 1125;
- Conciliação ambígua quando há mais de uma saída para a mesma NF-e, item, estabelecimento e competência;
- Diagnóstico de estabelecimento/competência sem cobertura no ICMS/IPI fornecido, operação diferente ou contexto diferente;
- Diagnóstico do ICMS-ST positivo escriturado em entradas C170, notas C100 e agregados C190 do ICMS/IPI, além de resumo das vendas C175 com CFOP 5405 por CST e alíquota;
- Hashes, linhas, CNPJs, competências e CFOPs das planilhas de origem; decisão e justificativa do analista exportáveis em CSV;
- Catálogo de hipóteses futuras com fontes oficiais e tratamento ainda pendente.

Nenhuma linha é declarada crédito validado pelo motor. Base de ICMS igual à base de PIS/COFINS é apenas um **sinal de revisão**: a base de ICMS não é necessariamente a receita tributável. É obrigatório confrontar documentos, apuração e valores pagos, além de verificar período, condição do contribuinte e uso prévio do crédito. O catálogo foi pesquisado em 21/10/2026 e deve ser versionado quando as regras mudarem.

O auditor não retifica arquivos SPED. O [PDF de estudo sobre ICMS-ST](referencias/padrao_analise_icms_st_sped.pdf) e sua [leitura crítica](referencias/LEITURA_CRITICA_PADRAO_ICMS_ST.md) documentam a triagem manual C175/CFOP 5405/CST 01 e os requisitos de evidência antes de qualquer cálculo de exclusão.

A tela usa um único comando, **Executar todas as análises e preparar Excel**, para inventário, triagem C170 e diagnósticos C100/C170/C175/C190. Ao fim, oferece um relatório `.xlsx` com resumo de receitas C175/CFOP 5405/CST 01 por estabelecimento e competência, contribuições escrituradas sob análise, diagnósticos e origem dos arquivos. O estado `Possível recuperação em análise` é preliminar. Os campos de exclusão e crédito calculado ficam vazios quando não há ICMS-ST documental vinculado à receita; o total de PIS/COFINS sob análise não é o valor a recuperar.

**Piloto de simulação histórica:** a aba `Simulacao_UF` usa o regime do registro 0110 em cada competência, quando presente, e as alíquotas de PIS/COFINS informadas no C175, sem impor um regime global. `Premissas_UF` registra a alíquota interna geral de Pernambuco (18% até 2023; 20,5% desde 2024) e de Mato Grosso (17% no período cadastrado), com vigência e fontes oficiais. O simulador só preenche o cenário quando a chave da NF-e identifica uma dessas UFs e o estabelecimento/período, a base confere com operação menos desconto, há 0110 ou histórico informado sem conflito e não há duplicação detectada entre abas. Linhas divergentes seguem no relatório para revisão. A alíquota geral é uma aproximação exploratória: a mercadoria pode estar sujeita a outra alíquota ou regra específica; ela não é o ICMS-ST destacado, que exige nota de aquisição e vínculo com a venda. Outras UFs permanecem sem simulação automática enquanto suas regras históricas não forem cadastradas e testadas.

Se o Excel não trouxer 0110, o analista pode informar intervalos `AAAA-MM` de lucro presumido, real ou misto na barra lateral. Essa declaração fica registrada em `Historico_Regime`; havendo conflito com o 0110, a simulação é bloqueada. O aplicativo aceita apenas a EFD-Contribuições com C175 para esse teste preliminar, deixando vazios os diagnósticos que exigem ICMS/IPI. Registros C175 idênticos repetidos entre abas são contados, retirados da soma e bloqueiam a simulação do grupo afetado.

A barra lateral permite selecionar uma UF ou usar a UF extraída da chave da NF-e. Uma divergência entre a UF escolhida e a chave bloqueia a simulação daquele grupo. O relatório inclui `Panorama_UF`, com as alíquotas modais anuais das 27 UFs publicadas pelo [Comsefaz para 2022–2025](https://comsefaz.org.br/novo/wp-content/uploads/2025/06/boletim_fiscal_dos_estados_2_edicao_v2.pdf) e lacunas explícitas para 2018–2021 e 2026. Como essa tabela anual não informa todas as datas de vigência, ela é somente referência de pesquisa e não alimenta o cálculo. Apenas `Premissas_UF`, com intervalos documentados, alimenta `Simulacao_UF`.

A triagem ainda é limitada aos itens C170 que possuem chave de NF-e e número de item presentes nas duas bases. A ausência da chave ou do item no ICMS/IPI não gera, nesta etapa, um diagnóstico de documento ausente. C100, C175, abas divididas e versões retificadoras ainda precisam de fluxo próprio. A falta da aba 0000 ou de identificadores suficientes bloqueia a comparação de valores e aparece como cobertura indeterminada.

O diagnóstico de ICMS-ST localiza valores informados sem aplicar alíquotas de PIS/COFINS ou declarar crédito. A coluna `regime_0110` preserva o código do período (1: não cumulativo; 2: cumulativo; 3: ambos). O resumo C175 mostra valores de vendas CFOP 5405, bases e contribuições escrituradas, mas não contém o ICMS-ST retido na aquisição. As grandezas de C100, C170 e C190 representam níveis diferentes e não devem ser somadas entre si. Elas ainda precisam de conciliação com notas fiscais do substituto, saídas tributadas, bloco M e possíveis retificações. Transferências são exibidas à parte e não entram automaticamente em hipótese de exclusão.

O modelo de `sped_credito_app/calculos.py` não foi incorporado como cálculo de crédito porque subtrai ICMS-ST/DIFAL e estima PIS/COFINS por dentro sem verificar, por operação, o direito, a apuração nem o pagamento. Ele permanece referência para futuros cenários, sujeitos a validação jurídica.

## Executar

```powershell
python -m pip install -r auditor_sped_integrado/requirements.txt
streamlit run auditor_sped_integrado/app.py
```

Não coloque planilhas de clientes ou relatórios com dados fiscais sob controle de versão. A aplicação recebe arquivos pelo navegador ou lê caminhos locais, não os envia para serviços externos e só exporta resultados quando o usuário aciona o botão de download.

## Próximas integrações

1. Mapeamento versionado por ano das abas e colunas geradas pelo Sysconv para as quatro escriturações.
2. Conciliação EFD-Contribuições × EFD ICMS/IPI × ECD × ECF e apurações declaradas.
3. Pacotes de regras separados para União e cada UF, com vigência, precedentes, exceções e testes de regressão.
4. Cálculo condicionado à evidência de recolhimento e à inexistência de aproveitamento anterior.

Fontes: [jurisprudência vinculante RFB](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/legislacao/jurisprudencia-vinculante/pis-cofins), [LC 87/1996](https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp87.htm), [orientações RFB sobre créditos de PIS/COFINS](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/conformidade-tributaria/Creditos-Indevidos-de-PIS-Pasep-Cofins-Setor-Supermercadista), [IPI](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/creditos/ipi/conceito%20e%20prazos) e [IRPJ/CSLL](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/creditos/sneg).

