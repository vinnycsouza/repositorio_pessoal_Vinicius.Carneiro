# V9.5 - Engine V3

## Arquitetura

- Novo Builder unico em `modules/excel_builder.py`.
- Streamlit nao cria workbooks diretamente.
- Escrita `openpyxl` em modo `write_only`.
- Consultas SQLite percorridas por cursor e `fetchmany`, sem DataFrame integral.
- Divisao por limite do Excel ocorre em abas do mesmo workbook.

## Entrega

- Um unico XLSX consolidado.
- Validacao estrutural e de linhas antes da disponibilizacao.
- Controle de integridade incorporado ao workbook.
- Manifesto CSV opcional.
- Download por arquivo em disco, sem duplicar o XLSX em `session_state`.

## Compatibilidade

Foram preservados parser XML, SQL, calculos, classificacao CP, auditoria,
interface, SQLite, checkpoints e retomada da V9.4.1.

## Preservacao de dados

Workspaces, SQLite, XMLs, logs e checkpoints nao sao apagados automaticamente.
Rotinas de descarte existentes continuam condicionadas a uma acao explicita do
usuario.

## Verificacao

Os testes cobrem:

- workbook pequeno;
- ausencia de S-1010;
- consulta SQLite incremental;
- divisao em varias abas dentro de um unico XLSX;
- manifesto desativado e ativado;
- validacao de estrutura e contagem de linhas.
