# XML eSocial V10.0 - Engine V4

Aplicacao Streamlit para leitura, auditoria e levantamento de eventos do
eSocial, com processamento persistente em SQLite e relatorio Excel consolidado.

## Principais recursos

- processamento de ZIPs e ZIPs aninhados;
- regras tributarias preservadas e parsers versionados com fallback legado;
- SQLite persistente com checkpoint e retomada;
- carregamento de um `processamento.db` existente;
- exportacao incremental, adequada a milhoes de registros;
- um unico XLSX por relatorio;
- divisao automatica em varias abas do mesmo workbook quando o limite do Excel
  for atingido;
- validacao rápida do ZIP/XLSX e das abas antes do download;
- aba `controle_integridade` incluida no relatorio;
- manifesto CSV opcional;
- workspaces, SQLite, XMLs e checkpoints preservados.
- gerenciamento do Workspace atual, com abertura no Explorador e envio seguro
  para a Lixeira.
- reutilização do Workspace no módulo de Levantamento, sem reprocessar XML;
- consultas filtradas e exportação detalhada diretamente pelo SQLite.
- recibos atuais e referenciados tratados separadamente em retificações;
- S-2299 persistido e reconciliado de forma segregada, sem entrar no cálculo CP padrão;
- reconciliação S-1200/S-2299 com S-5011;
- validação XSD opcional (desligada por padrão);
- migração idempotente de Workspaces anteriores com backup lógico de metadados/schema.

## Execucao

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Fluxo V10

```text
XML/ZIP -> inventário/hash -> parser versionado -> SQLite/checkpoint -> reconciliação -> Excel -> validação rápida -> download
```

No módulo de Levantamento, as origens disponíveis são ZIP, Excel e Workspace.
Quando existe um Workspace válido na sessão, ele é reutilizado automaticamente.
Também é possível informar a pasta do Workspace ou seu `processamento.db`.

Para bases SQLite, somente opções, rubricas agrupadas, métricas e prévias são
carregadas em DataFrames. Os movimentos detalhados são exportados por cursor,
sem materializar a tabela integral em memória.

A interface Streamlit apenas coleta opcoes, acompanha o progresso e oferece o
arquivo concluido. A escrita do workbook fica centralizada em
`modules/excel_builder.py`.

## Saida

O relatorio de incidencia CP e entregue como
`relatorio_incidencia_cp_esocial_v10.xlsx`. Bases acima de 1.048.575 linhas sao
divididas em abas numeradas dentro desse mesmo arquivo.

O manifesto externo nao e necessario para validar o relatorio. Quando solicitado
na interface, ele e gerado ao lado do XLSX.

## Preservacao

O processamento nao apaga automaticamente workspaces, bancos SQLite, XMLs,
logs ou checkpoints. A remoção do Workspace atual depende de confirmação
explícita do usuário e utiliza a Lixeira do sistema operacional.

Na V9.5.2, o antigo botão de limpeza foi substituido por **Gerenciar Workspace
Atual**. O painel mostra empresa, CNPJ, status e tamanhos e permite abrir a pasta
ou enviar todo o Workspace para a Lixeira, sempre com confirmação. Não existe
exclusão definitiva nessa ação.

## Atualização incremental

No painel **Gerenciar Workspace Atual**, a ação **Adicionar complementos ao
Workspace** incorpora novos ZIP/XML ao mesmo `processamento.db`, por upload ou
caminho local. Não é criado um segundo Workspace.

- cada XML novo recebe SHA-256 do conteúdo bruto;
- duplicados são ignorados mesmo quando possuem outro nome;
- ZIPs aninhados continuam suportados;
- cada carga possui histórico e checkpoint para retomada;
- S-3000 e consolidações são reaplicados sobre a base acumulada;
- um novo S-1010 reclassifica os S-1200 preservados no SQLite, sem reler os
  arquivos XML originais;
- Relatório de Incidência CP e Levantamento usam os dados atualizados no mesmo
  Workspace.

Em caso de interrupção, informe novamente as mesmas fontes para retomar a carga
incremental registrada no SQLite.

## Controles opcionais da V10

O funcionamento padrão permanece conservador. Os recursos experimentais ou de
auditoria são habilitados somente por variáveis de ambiente:

- `ESOCIAL_V10_PARSER_S1200=legacy|shadow|v10`: compara ou ativa o parser dirigido
  por hierarquia; qualquer divergência usa o legado e fica registrada;
- `ESOCIAL_V10_INGESTAO_SELETIVA=1`: usa inspeção streaming em eventos não
  analíticos, mantendo hash e inventário completos;
- `ESOCIAL_VALIDACAO_XSD=desligada|amostral|completa`: escolhe o nível de validação;
- `ESOCIAL_XSD_DIR`: pasta dos XSDs oficiais usada nos modos amostral/completo;
- `ESOCIAL_XSD_TAXA_AMOSTRA`: proporção determinística do modo amostral;
- `ESOCIAL_MAX_ITENS_LOTE_SQLITE` e `ESOCIAL_MAX_BYTES_LOTE_SQLITE`: limites do
  escritor analítico; os padrões já reduzem automaticamente sob pressão de memória;
- `ESOCIAL_SQLITE_CACHE_MB`: cache moderado do SQLite (32 a 512 MB).

O S-2299 é armazenado em tabela própria e exibido na reconciliação, mas não é somado
ao Relatório de Incidência CP padrão sem homologação tributária explícita. A validação
XSD nunca bloqueia automaticamente o relatório quando está indisponível ou não
configurada.

Ao abrir um Workspace antigo, a Engine preserva eventos, objetos, hashes e dados
brutos, cria um backup lógico de schema/metadados e reconstrói somente as projeções
derivadas necessárias. Relatórios XLSX já entregues não são sobrescritos.

Consulte `PLANO_V9_5.md`, `ATUALIZACOES_V9_5_ENGINE_V3.md` e
`ATUALIZACOES_V9_5_2_ENGINE_V3.md`. Consulte também
`ATUALIZACOES_INTEGRACAO_WORKSPACE_LEVANTAMENTO.md`.
O desenho técnico da carga incremental está em `PLANO_CARGA_INCREMENTAL.md`.
O plano, rollout e critérios de aceite da V10 estão em `PLANO_V10_ENGINE_V4.md`.
