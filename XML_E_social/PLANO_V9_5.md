# ENGINE V3 - PLANO DE IMPLEMENTACAO V9.5

## 1. Escopo e regras preservadas

A V9.5 sera uma refatoracao de arquitetura, exportacao, organizacao e validacao.
Nao serao alterados:

- `modules/parser_xml.py`;
- SQL de materializacao, consultas e classificacao;
- calculos, regras tributarias e classificacao CP;
- estrutura do SQLite, checkpoints e retomada;
- fluxo funcional e modulos visuais da interface.

## 2. Diagnostico do projeto atual

### Fluxo principal

1. `app.py` recebe ZIPs/caminhos ou um SQLite existente.
2. `modules/processador_zip.py` cataloga XMLs, grava payloads e checkpoints no
   SQLite e materializa as tabelas analiticas.
3. `modules/sqlite_relatorio.py` cria as tabelas relacionais e de relatorio.
4. A interface carrega apenas previas em DataFrames no modo SQLite seguro.
5. Na exportacao, a V9.4.1 chama `gerar_pacote_excel_saida_sqlite`, que consulta
   o SQLite em blocos, mas entrega varios XLSX separados e CSVs auxiliares.
6. Para bases menores, `app.py` chama `gerar_excel_saida` de
   `modules/auditoria.py`, que monta o XLSX em memoria.
7. O levantamento possui uma terceira geracao de Excel diretamente em `app.py`.

### Duplicacoes e codigo obsoleto

- Escrita de DataFrame e divisao de abas repetidas em `app.py`,
  `modules/auditoria.py` e `modules/sqlite_relatorio.py`.
- Exportador consolidado SQLite e exportador segmentado coexistem.
- A interface decide como construir workbooks, contrariando a separacao
  Interface/Builder.
- O pacote segmentado, manifesto obrigatorio e CSV de controle sao produtos
  intermediarios expostos ao usuario.
- A limpeza automatica de workspaces antigos pode remover SQLite, XMLs,
  checkpoints e logs sem uma acao explicita do usuario.

### Gargalos

- `BytesIO` e `DataFrame.to_excel` mantem o arquivo/recorte integral em memoria.
- `LIMIT/OFFSET` em grandes consultas repete trabalho e degrada com muitos
  registros.
- A ausencia de validacao pos-gravacao permite entregar um XLSX truncado ou
  inconsistente.
- Armazenar bytes do XLSX na sessao Streamlit duplica consumo de memoria.

## 3. Arquitetura V9.5

O componente `modules/excel_builder.py` sera o unico responsavel por:

- criar workbooks `openpyxl` em modo `write_only`;
- escrever DataFrames e cursores SQLite incrementalmente;
- dividir somente abas que excedam o limite do Excel, dentro do mesmo workbook;
- gerar um unico XLSX consolidado;
- incluir o controle de integridade no proprio workbook;
- validar arquivo, workbook, nomes de abas e quantidades de linhas antes da
  entrega;
- gerar manifesto apenas quando solicitado;
- reportar progresso por callback, sem dependencia de Streamlit.

`modules/sqlite_relatorio.py` continuara responsavel pelo SQLite e pelas mesmas
consultas existentes. A API de exportacao sera delegada ao Builder, sem alterar
SQL. O exportador segmentado V9.4.1 sera removido por obsolescencia.

`app.py` apenas coletara opcoes, chamara o Builder, exibira progresso e entregara
o caminho do unico XLSX. Nao criara planilhas nem guardara o XLSX inteiro em RAM.

## 4. Arquivos a modificar

### Novo

- `modules/excel_builder.py`
  - Centralizar toda a escrita incremental, consolidacao e validacao.
- `tests/test_excel_builder.py`
  - Cobrir bases pequena/media simulada, divisao de abas, integridade,
    manifesto opcional e cenarios com/sem S-1010.
- `ATUALIZACOES_V9_5_ENGINE_V3.md`
  - Documentar arquitetura, compatibilidade, saida e preservacao.

### Alterados

- `modules/sqlite_relatorio.py`
  - Manter consultas e SQLite intactos; substituir implementacoes duplicadas
    por delegacao ao Builder e remover a entrega segmentada obsoleta.
- `modules/auditoria.py`
  - Preservar auditoria e classificacoes; delegar a exportacao DataFrame ao
    Builder, eliminando escrita Excel duplicada.
- `app.py`
  - Remover geracao direta de Excel, usar somente o Builder, entregar um unico
    arquivo por caminho e tornar o manifesto opcional.
  - Remover a limpeza automatica de workspaces; qualquer descarte continuara
    apenas por acao explicita.
- `modules/processador_zip.py`
  - Remover somente a rotina de limpeza automatica e sua exposicao publica,
    preservando processamento, SQLite, XMLs e checkpoints.
- `README.md`
  - Atualizar execucao, arquitetura V9.5, saida consolidada e politica de
    preservacao.
- `requirements.txt`
  - Registrar dependencias necessarias para execucao e testes.

## 5. Validacoes e testes

1. Compilacao de todos os modulos Python.
2. Testes unitarios do Builder com SQLite temporario e DataFrames.
3. Validacao de:
   - assinatura ZIP;
   - workbook reabrivel;
   - nomes e unicidade das abas;
   - limite de linhas por aba;
   - total exportado versus total esperado;
   - presenca e status do controle de integridade.
4. Casos:
   - empresa pequena com S-1010;
   - empresa sem S-1010;
   - volume medio em multiplos chunks;
   - volume grande simulado com divisao de aba, sem carregar tudo na RAM.
5. Busca final por imports obsoletos, referencias quebradas, geracao Excel em
   `app.py` e entrega segmentada.

## 6. Criterios de aceite

- Um unico relatorio XLSX consolidado por exportacao.
- Interface e regras funcionais preservadas.
- SQLite, workspace, XML, logs e checkpoints nunca apagados automaticamente.
- Escrita incremental com memoria praticamente constante no caminho SQLite.
- Workbook validado antes de ser disponibilizado.
- Manifesto opcional.
- Projeto executavel sem patches ou copias de backup.
