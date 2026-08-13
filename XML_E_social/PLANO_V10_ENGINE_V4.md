# ENGINE V4 — V10 — Plano Mestre de Evolução

## 1. Estado do documento

- Tipo: especificação de arquitetura, implementação, migração e aceite.
- Situação: planejado; nenhuma mudança da V10 está ativa na Engine atual.
- Base de comparação: V9.5.2/V9.5 com Workspace persistente, carga incremental,
  SQLite, relatório em streaming, Levantamento por Workspace e progresso em duas barras.
- Fontes técnicas analisadas:
  - estrutura e campos dos relatórios LaraTex fornecidos para a empresa ESPOSENDE;
  - esquemas oficiais eSocial S-1.3 publicados em 27/04/2026 e 01/07/2026;
  - código, testes, schema SQLite e planos existentes da Engine V3;
  - gargalos observados em empresas pequenas, médias e de grande porte.

Este documento deve ser atualizado com os resultados de cada benchmark. Hipóteses
de desempenho não são critérios de aceite até serem medidas.

## 2. Visão da V10

A V10 evoluirá a Engine de um processador orientado a arquivos para uma plataforma
orientada a eventos, versões e fontes compartilhadas. O XML será lido uma única vez,
catalogado com rastreabilidade, transformado por parser específico e reutilizado pelo
Relatório de Incidência CP, Levantamento e relatórios futuros.

Objetivos simultâneos:

1. preservar integralmente segurança, auditoria, checkpoints e regras tributárias;
2. reduzir varreduras repetidas das árvores XML;
3. aproveitar melhor SQLite e processamento em streaming;
4. cobrir explicitamente remunerações periódicas e de desligamento;
5. ampliar os controles de reconciliação com bases oficiais do eSocial;
6. manter desempenho previsível em volumes pequenos, médios e grandes;
7. permitir evolução por versão do leiaute sem espalhar condicionais pela aplicação.

## 3. Princípios obrigatórios

- Resultado tributário correto prevalece sobre velocidade.
- Nenhuma regra será inferida apenas a partir dos relatórios LaraTex.
- O LaraTex é referência de cobertura e organização, não fonte normativa.
- O XSD é fonte estrutural; regras tributárias dependem da documentação oficial e das
  regras já homologadas da Engine.
- O modo padrão não validará todo XML contra XSD; validação integral será opcional.
- Um Workspace concluído nunca será substituído silenciosamente.
- Todo parser novo deverá coexistir temporariamente com o parser legado em modo sombra.
- Nenhuma otimização poderá eliminar inventário, hash, recibo, retificação, exclusão,
  origem, versão ou trilha de auditoria.
- O processamento continuará retomável e com um único escritor SQLite.
- DataFrames integrais continuarão proibidos para tabelas de grande volume.
- Toda migração de banco será idempotente e compatível com Workspaces anteriores.

## 4. Aprendizados incorporados

### 4.1 Relatórios LaraTex analisados

| Origem | Papel observado | Uso proposto na V10 |
|---|---|---|
| S-1000 | Empresa, classificação e desoneração | contexto empresarial versionado |
| S-1010 | Rubrica, operação, vigência e incidências | cadastro temporal e trilha de alterações/exclusões |
| S-1020 | Lotação e terceiros/processos | contexto de lotação e reconciliação |
| S-1200 | Remuneração periódica e rubricas | principal fonte dos movimentos de crédito |
| S-2200 | Cadastro e categoria do trabalhador | enriquecimento opcional e controles cadastrais |
| S-2299 | Remuneração de trabalhadores desligados | nova fonte de movimentos, sujeita a homologação tributária |
| S-5011 | Bases oficiais e contribuições sociais | reconciliação por período, estabelecimento, lotação e categoria |

Campos analíticos observados e que inspiram controles futuros:

- período de apuração e referência;
- recibo, trabalhador, matrícula/categoria;
- estabelecimento e lotação;
- rubrica, tabela, natureza e vigência;
- valor da rubrica e classificação de incidência;
- base teórica, base oficial e diferença;
- patronal, RAT ajustado e terceiros;
- indícios de retificação e rastreabilidade da origem;
- FPAS, código de terceiros, FAP, RAT e códigos de receita quando disponíveis;
- segmentação entre valores vindos de S-1200 e S-2299.

Observação decisiva: a inclusão do S-2299 altera o universo de movimentos. Ela não será
tratada como otimização mecânica. Exigirá especificação tributária, parser, schema,
reconciliação, relatório e testes próprios antes de ser habilitada por padrão.

### 4.2 Esquemas XSD S-1.3

Os dois pacotes possuem 52 arquivos. Seis tiveram alteração de conteúdo entre as
publicações: `evtAdmissao.xsd`, `evtBasesTrab.xsd`, `evtCdBenefIn.xsd`,
`evtProcTrab.xsd`, `evtRemun.xsd` e `tipos.xsd`.

Para os campos atualmente consumidos de S-1200 e S-5001, as diferenças observadas nos
arquivos específicos foram predominantemente documentais. S-1010, S-3000 e S-5011
não apresentaram alteração de arquivo entre os dois pacotes.

Usos aprovados dos XSDs:

- registro oficial evento + namespace + versão;
- mapa de hierarquia e cardinalidade por evento;
- geração/validação de fixtures de teste;
- detecção de versão desconhecida;
- suporte ao desenvolvimento de parsers especializados;
- validação XSD completa opcional para auditoria.

Uso rejeitado no fluxo padrão: validar cada XML integralmente contra XSD durante a
ingestão, porque acrescentaria CPU e latência sem contribuir para o cálculo normal.

## 5. Arquitetura-alvo

```text
Interface / CLI de benchmark
        |
        v
WorkspaceContext + DataSource compartilhada
        |
        v
Inventário de fontes e ZIPs aninhados
        |
        v
Identificador rápido (namespace, evento, versão, envelope)
        |
        +--> evento não analítico --> inventário + hash + metadados mínimos
        |
        +--> evento analítico --> roteador de parser por evento/versão
                                      |
                                      v
                           lotes de objetos normalizados
                                      |
                                      v
                            escritor SQLite único
                                      |
                    +-----------------+-----------------+
                    v                                   v
          materialização analítica             trilha de auditoria
                    |
                    v
          camada de reconciliação
                    |
          +---------+----------+
          v                    v
 Relatório Incidência CP   Levantamento / módulos futuros
```

### 5.1 Componentes previstos

1. `SchemaRegistry`: evento, namespace, versão, XSD, parser e compatibilidade.
2. `EventSniffer`: identificação mínima segura sem varrer repetidamente a árvore.
3. `ParserRouter`: seleciona parser especializado e mantém fallback legado.
4. `NormalizedEventBatch`: contrato de saída entre parser e escritor.
5. `SQLiteWriter`: único responsável por commits, deduplicação e checkpoints.
6. `ReconciliationService`: compara movimentos teóricos com bases oficiais.
7. `BenchmarkSuite`: mede tempo, memória, disco, contagens, valores e equivalência.
8. `WorkspaceContext/DataSource`: continua sendo o acesso compartilhado dos módulos.

## 6. Pacotes de implementação

### Pacote 0 — Linha de base e observabilidade

Antes de otimizar, registrar por Workspace e por carga:

- tempo de inventário, ingestão, parsing por evento, compressão, escrita SQLite,
  segunda passagem, materialização, consolidação, integridade e exportação;
- quantidade e bytes por tipo de evento;
- tempo de CPU e tempo de espera de disco quando mensurável;
- memória atual e pico do processo;
- número de commits, tamanho médio dos lotes e taxa de duplicidade;
- tamanho do SQLite, WAL e temporários;
- velocidade média e percentis por fonte/tipo;
- versão da Engine, Python, schema SQLite e parser utilizado.

O progresso visual existente permanecerá. Telemetria será local no Workspace, sem
transmissão externa e sem dados pessoais em nomes de métricas.

### Pacote 1 — Registro de schema e identificação rápida

- Criar registro de namespace por evento e versão.
- Identificar `eSocial`, evento interno, retorno/recibo e versão.
- Manter fallback por `localname` para XML legado ou envelope não reconhecido.
- Registrar namespace e versão no inventário.
- Marcar, sem rejeitar automaticamente, versões desconhecidas.
- Não confiar exclusivamente no nome do arquivo ZIP/XML.

Critério de segurança: identificação nova e legada devem concordar em 100% do corpus
homologado; divergências vão para auditoria e usam o parser legado.

### Pacote 2 — Parser especializado S-1200

- Percorrer a estrutura seguindo a hierarquia oficial, evitando chamadas repetidas a
  `root.iter()`, `first_text_by_localname()` e `all_elements_by_localname()`.
- Tratar `infoPerApur`, `infoPerAnt`, múltiplos `dmDev`, estabelecimentos, lotações,
  remunerações e itens de rubrica.
- Preservar recibo, competência, referência, categoria, matrícula, estabelecimento,
  lotação, rubrica, tabela e valor.
- Preservar o cruzamento temporal com todas as operações S-1010.
- Executar em modo sombra até equivalência integral.

Primeira implementação: sequencial e streaming/dirigida por caminho. Paralelismo não
faz parte deste pacote.

### Pacote 3 — S-1010 temporal completo

- Consolidar inclusão, alteração, nova validade e exclusão como operações temporais.
- Preservar arquivo, fonte, recibo quando disponível, período e ordem de aplicação.
- Resolver a rubrica válida na competência sem perder histórico.
- Expor motivo do casamento e nível de confiança.
- Reaplicar S-1010 complementar sobre movimentos já persistidos sem reler o ZIP.
- Criar testes para exclusões, períodos ativos/excluídos e alterações posteriores.

Não mudar códigos de incidência nem regras CP; apenas tornar explícito e verificável o
estado temporal que já fundamenta o cruzamento.

### Pacote 4 — Parser e integração S-2299

- Mapear remuneração de desligamento conforme XSD e documentação oficial.
- Persistir origem do movimento (`S-1200` ou `S-2299`).
- Evitar dupla contagem quando recibos, demonstrativos ou referências se relacionarem.
- Aplicar S-3000 e retificações.
- Cruzar com S-1010 pela competência/referência apropriada.
- Segregar valores S-1200 e S-2299 na reconciliação S-5011.
- Preservar layout atual por padrão até aprovação explícita de novas colunas/abas.

Gate obrigatório: parecer funcional/tributário e equivalência em empresas que possuam
desligamentos. O pacote poderá permanecer desabilitado por feature flag até homologação.

### Pacote 5 — Parsers especializados S-5001 e S-5011

- S-5001: trabalhador, matrícula, categoria, estabelecimento, lotação, período,
  `infoBaseCS`, períodos anteriores e recibo-base.
- S-5011: estabelecimento, lotação, categoria, incidência, FPAS, terceiros, RAT/FAP e
  bases CP 00/15/20/25 quando presentes.
- Evitar varreduras descendentes repetidas.
- Persistir somente campos necessários e metadados de auditoria.
- Manter XML comprimido quando necessário para reprocessamento derivado.

### Pacote 6 — Contexto complementar S-1000, S-1020 e S-2200

- S-1000: classificação tributária/desoneração e vigência, sem criar cálculo novo não
  homologado.
- S-1020: lotação, FPAS/terceiros/processos conforme disponibilidade e vigência.
- S-2200: cadastro, matrícula, categoria e dados mínimos para enriquecimento.
- Informações pessoais não essenciais não devem ser duplicadas no relatório.
- O enriquecimento será opcional e não bloqueará o Relatório de Incidência CP.

### Pacote 7 — Ingestão seletiva com inventário completo

- Continuar calculando hash e catalogando todos os XMLs.
- Para evento não analítico, evitar árvore completa quando a identificação mínima for
  conclusiva e segura.
- Persistir tipo, versão, tamanho, hash, origem, envelope e status.
- Para eventos analíticos, encaminhar ao parser específico.
- Manter limites contra XML excessivo, profundidade de ZIP e ZIPs aninhados.
- Manter fallback integral para casos ambíguos.

Resultado: menos CPU/memória sem sacrificar o inventário.

### Pacote 8 — Escrita SQLite e lotes adaptativos

- Um único escritor SQLite.
- Tamanho de lote limitado simultaneamente por itens e bytes.
- Perfil conservador para 16 GB de RAM.
- Cache SQLite moderado e configurável após benchmark.
- WAL, timeout e transações preservando retomada e bloqueio exclusivo do Workspace.
- Não manter transação aberta por horas.
- Não usar `temp_store=MEMORY` indiscriminadamente.
- Ajustar lote a memória disponível, tamanho médio dos XMLs e pressão do sistema.
- Separar atualização visual de commits, como já ocorre na V9.5.2.

Paralelismo ficará atrás de feature flag experimental. Se adotado, começará com dois
workers de parsing e um escritor; somente aumentará após prova de ganho e memória.

### Pacote 9 — Materialização e reconciliação analítica

- Materializar por cursor/lote, sem DataFrames gigantes.
- Criar métricas teóricas por período, trabalhador, estabelecimento, lotação e categoria.
- Comparar com S-5001/S-5011 nas chaves compatíveis.
- Evidenciar diferença, cobertura e motivo de não reconciliação.
- Segregar origem S-1200/S-2299.
- Avaliar patronal, RAT e terceiros somente com regras formalmente especificadas.
- Usar S-1000/S-1020 como contexto, não como atalho para inferência tributária.
- Preservar valores brutos e permitir rastrear cada agregado às fontes.

### Pacote 10 — Relatórios e UX

- Preservar Relatório de Incidência CP e Levantamento atuais.
- Acrescentar controles da V10 apenas de forma compatível/versionada.
- Exibir versão de schema/parser e cobertura dos eventos.
- Informar S-2299 habilitado/desabilitado e sua quantidade.
- Mostrar reconciliação S-1200 + S-2299 versus base oficial.
- Manter duas barras: etapa atual e progresso geral.
- Exibir ETA como estimativa, nunca como prazo garantido.
- Não carregar tabelas completas apenas para prévia.
- Exportar por cursor e `write_only`, com validação rápida padrão.

### Pacote 11 — Validação XSD opcional

- Modos: desligada (padrão), amostral e completa.
- Selecionar XSD pelo namespace/versão.
- Guardar erros com arquivo, evento, versão e localização quando disponível.
- Não impedir relatório por advertência documental não estrutural.
- Nunca ativar validação completa automaticamente em grandes volumes.

### Pacote 12 — Workspace, migração e compatibilidade

- Migração idempotente do schema.
- Novas colunas/tabelas terão valores padrão seguros.
- Workspace V9 continuará legível.
- Upgrade V10 deverá criar backup lógico de metadados/schema antes de migrar.
- Workspaces concluídos não serão reprocessados automaticamente.
- Opção explícita de reprocessar derivados com o parser V10 a partir de `xml_zlib` quando
  o conteúdo necessário existir.
- Se o XML bruto legado não estiver disponível, preservar resultado V9 e informar limite.
- Carga incremental, complementos, S-3000, retificação e deduplicação SHA-256 continuam.

## 7. Alterações de dados previstas

Nomes finais dependem da revisão de schema, mas o plano prevê:

- `eventos.namespace_esocial`;
- `eventos.versao_layout`;
- `eventos.parser_versao`;
- `eventos.status_schema`;
- `eventos.origem_movimento`;
- tabela de versões de schema/Engine;
- tabela de métricas por etapa/carga;
- tabela normalizada de operações temporais S-1010 ou extensão equivalente;
- tabelas analíticas de S-2299;
- tabelas de contexto S-1000/S-1020/S-2200;
- tabelas de reconciliação com chaves, cobertura e diferenças;
- índices definidos somente após consulta ao plano de execução e benchmark.

Dados atuais não serão removidos na migração. Projeções derivadas poderão ser
reconstruídas; eventos, hashes e histórico de cargas serão preservados.

## 8. Estratégia de benchmark

### 8.1 Empresa de referência atual

O processamento grande em andamento será a linha de base V9. Não deve ser interrompido,
alterado nem reutilizado como Workspace de desenvolvimento.

Preservar ao término:

- ZIP original e localização;
- Workspace completo;
- `processamento.db`, WAL/SHM se ainda existirem com o app aberto, logs e metadados;
- relatório final e manifesto, quando aplicável;
- tempos por etapa;
- contagens por evento;
- tamanho e quantidade de fontes/XMLs;
- métricas de integridade e totais tributários.

O teste V10 usará cópia da fonte e diretório de Workspaces isolado. Nunca apontará para
o Workspace de referência.

### 8.2 Matriz de portes

| Porte | Finalidade |
|---|---|
| Pequeno | medir overhead e assegurar resposta rápida |
| Médio | validar ganho normal e diversidade de eventos |
| Grande | medir RAM, disco, retomada e escalabilidade |
| S-2299 | validar desligamentos e ausência de dupla contagem |
| Complementar | S-1010/S-3000/retificação e carga incremental |
| Eventos irrelevantes | medir ingestão seletiva mantendo inventário |

### 8.3 Execução comparável

- mesma máquina e plano de energia;
- fonte no mesmo dispositivo;
- OneDrive sem download/sincronização ativa da fonte durante a medição;
- ao menos uma execução de aquecimento identificada e três medições válidas quando
  praticável;
- registrar temperatura/throttling quando disponível;
- não comparar execução interrompida com execução contínua;
- comparar mediana e dispersão, não somente o melhor tempo.

### 8.4 Métricas de sucesso

- tempo total e por etapa;
- XML/s e MB/s;
- CPU média/pico;
- RAM média/pico;
- bytes escritos, tamanho de WAL e SQLite;
- tempo até primeiro feedback visual;
- custo adicional em empresa pequena;
- desempenho de retomada;
- igualdade de contagens, chaves, valores e relatórios.

Meta inicial, não garantia: reduzir o tempo total em 10% a 25% no corpus de referência,
com ganho maior no parsing, sem exceder uso seguro de memória em computador com 16 GB.

## 9. Protocolo de equivalência

Comparar V9 versus V10 em três níveis:

### Nível A — Inventário

- fontes e membros ZIP;
- total de XMLs, bytes e hashes;
- contagem por tipo, versão e envelope;
- duplicados, inválidos e erros;
- retificações e exclusões.

### Nível B — Dados normalizados

- S-1010 por chave/operação/vigência;
- movimentos S-1200 linha a linha;
- S-5001 e S-5011 linha a linha;
- empresa, trabalhador, estabelecimento e lotação quando aplicáveis;
- recibos, períodos, valores e origem.

### Nível C — Resultado

- total de movimentos;
- rubricas e classificação CP;
- valores por rubrica, competência, trabalhador, estabelecimento e lotação;
- sem S-1010;
- excluídos e retificados;
- bases teóricas e oficiais;
- controles de integridade;
- todas as abas e totais dos relatórios atuais.

Comparações monetárias usarão decimal/centavos e tolerância somente onde já houver regra
formal. Diferença não explicada bloqueia a ativação do parser novo.

## 10. Testes obrigatórios

- unitários por parser/caminho/cardinalidade;
- fixtures válidas derivadas dos XSDs;
- namespaces S-1.3 e versão desconhecida;
- envelopes de retorno/recibo;
- XML inválido, excessivo e ZIP aninhado;
- S-1010 inclusão, alteração, nova validade e exclusão;
- S-1200 período atual/anterior, múltiplos demonstrativos e lotações;
- S-2299 com e sem remuneração, retificação e exclusão;
- S-5001/S-5011 com múltiplas bases;
- deduplicação por SHA-256 com nomes diferentes;
- interrupção em cada etapa e retomada;
- carga incremental com reclassificação histórica;
- concorrência/bloqueio de Workspace;
- migração repetida de Workspace V9;
- exportação grande, abas particionadas e validação rápida;
- Levantamento por Workspace sem XML/DataFrame gigante;
- benchmark pequeno/médio/grande;
- comparação sombra entre parser legado e V10.

## 11. Feature flags e rollout

Flags propostas:

- `ESOCIAL_V10_SNIFFER`;
- `ESOCIAL_V10_PARSER_S1200`;
- `ESOCIAL_V10_PARSER_S2299`;
- `ESOCIAL_V10_PARSER_BASES`;
- `ESOCIAL_V10_INGESTAO_SELETIVA`;
- `ESOCIAL_V10_WORKERS`;
- `ESOCIAL_VALIDACAO_XSD`.

Etapas de ativação:

1. observabilidade sem mudar resultados;
2. identificação rápida em modo sombra;
3. parser S-1200 em modo sombra;
4. parser S-1200 habilitado somente no benchmark;
5. expansão gradual dos parsers;
6. S-2299 após homologação funcional;
7. ingestão seletiva após prova de inventário idêntico;
8. V10 padrão somente após aceite completo.

Fallback: qualquer divergência usa o parser legado, registra a ocorrência e preserva o
Workspace. Não alternar parser no meio de um mesmo evento.

## 12. Critérios de aceite da V10

A V10 será considerada pronta somente quando:

1. todos os testes V9 e novos testes V10 passarem;
2. Workspaces V9 forem abertos/migrados de forma idempotente;
3. inventário e rastreabilidade forem iguais ou superiores;
4. resultados atuais forem integralmente equivalentes no corpus homologado;
5. diferenças introduzidas pelo S-2299 forem justificadas e aprovadas;
6. a empresa grande de referência concluir em Workspace isolado;
7. RAM permanecer em faixa segura para 16 GB, sem paginação excessiva;
8. retomada funcionar em ingestão, parsing, materialização e carga incremental;
9. relatório e Levantamento continuarem usando SQLite/cursor/streaming;
10. desempenho não regredir materialmente em empresa pequena;
11. o ganho medido for documentado por etapa;
12. validação XSD permanecer opcional;
13. feature flags e fallback forem testados;
14. documentação de operação, migração e reversão estiver concluída.

## 13. Itens explicitamente fora do escopo inicial

- copiar fórmulas, teses, fundamentações ou regras proprietárias do LaraTex;
- substituir a classificação tributária vigente sem especificação própria;
- validação XSD obrigatória em toda carga;
- usar todos os núcleos/threads indiscriminadamente;
- carregar XML/SQLite gigante em DataFrame;
- gerenciar múltiplos Workspaces dentro do escopo desta otimização;
- apagar automaticamente fontes, temporários ou Workspaces;
- alterar layout de entrega sem compatibilidade/versionamento;
- transformar estimativa de ETA em promessa de conclusão.

## 14. Ordem recomendada

1. Pacote 0 — observabilidade e baseline;
2. Pacote 1 — schema/identificação rápida;
3. Pacote 2 — S-1200 especializado;
4. Pacote 3 — S-1010 temporal;
5. benchmark e equivalência intermediários;
6. Pacote 5 — S-5001/S-5011;
7. Pacote 4 — S-2299 homologado;
8. Pacote 6 — contexto complementar;
9. Pacote 7 — ingestão seletiva;
10. Pacote 8 — lotes adaptativos/paralelismo experimental;
11. Pacotes 9 e 10 — reconciliação e UX;
12. Pacotes 11 e 12 — XSD opcional, migração e rollout final.

Cada pacote deve gerar commit isolado, testes, benchmark e registro de decisão. Não
implementar vários pacotes tributariamente sensíveis em um único commit.

## 15. Registro de decisões pendentes

- Definir regra funcional exata de inclusão do S-2299 no Relatório de Incidência CP.
- Definir chaves oficiais de reconciliação S-1200/S-2299 versus S-5011.
- Determinar quais campos S-1000/S-1020 influenciam controles e quais são apenas contexto.
- Selecionar biblioteca/estratégia de parsing streaming após microbenchmark.
- Definir política de retenção de `xml_zlib` por evento e Workspace legado.
- Definir limites adaptativos para 8/16/32+ GB após medição.
- Decidir quais novos controles entram no workbook atual e quais exigem relatório V10.
- Aprovar corpus anonimizado mínimo para regressão permanente.

Até essas decisões serem resolvidas, a V9 permanece a versão operacional confiável.
