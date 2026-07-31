# Integração do Levantamento com o Workspace

## Nova origem

O módulo de Levantamento passa a aceitar `Workspace (SQLite existente)` além de
ZIP e Excel. O usuário pode informar a pasta do Workspace ou o arquivo
`processamento.db`.

Se um Workspace concluído já estiver carregado na sessão, ele é usado
automaticamente. No modo ZIP do Levantamento, a existência desse Workspace
impede o reprocessamento acidental dos mesmos XMLs.

## Fonte compartilhada

`modules/data_source.py` introduz `WorkspaceContext` e `SQLiteDataSource` para
centralizar localização, validação e conexão somente leitura. O contexto exige
um Workspace concluído e as tabelas mínimas usadas pelo Levantamento.

## Consultas e memória

`modules/levantamento_sqlite.py` executa diretamente no SQLite:

- opções de filtros;
- competências;
- rubricas agrupadas;
- métricas;
- resumo por rubrica;
- resumo por competência e rubrica;
- prévia limitada de movimentos.

As rubricas selecionadas são colocadas em tabela TEMP da conexão, evitando o
limite de parâmetros do SQLite. Essa tabela não altera `processamento.db`.

Quando o detalhamento é solicitado no Excel, a aba `03_movimentos` é escrita por
cursor e em chunks pelo Excel Builder. O layout das seis abas do Levantamento é
preservado.

## Compatibilidade

Os caminhos ZIP e Excel anteriores permanecem disponíveis. Não foram alterados
parser XML, schema persistente, regras tributárias, classificação CP ou regras
de cálculo do Levantamento.
