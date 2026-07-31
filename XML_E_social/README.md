# XML eSocial V9.5 - Engine V3

Aplicacao Streamlit para leitura, auditoria e levantamento de eventos do
eSocial, com processamento persistente em SQLite e relatorio Excel consolidado.

## Principais recursos

- processamento de ZIPs e ZIPs aninhados;
- parser e regras tributarias preservados da V9.4.1;
- SQLite persistente com checkpoint e retomada;
- carregamento de um `processamento.db` existente;
- exportacao incremental, adequada a milhoes de registros;
- um unico XLSX por relatorio;
- divisao automatica em varias abas do mesmo workbook quando o limite do Excel
  for atingido;
- validacao do ZIP/XLSX, abas e quantidades de linhas antes do download;
- aba `controle_integridade` incluida no relatorio;
- manifesto CSV opcional;
- workspaces, SQLite, XMLs e checkpoints preservados.

## Execucao

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Fluxo V9.5

```text
XML/ZIP -> Parser -> SQLite/checkpoint -> consultas -> Excel Builder -> validacao -> download
```

A interface Streamlit apenas coleta opcoes, acompanha o progresso e oferece o
arquivo concluido. A escrita do workbook fica centralizada em
`modules/excel_builder.py`.

## Saida

O relatorio de incidencia CP e entregue como
`relatorio_incidencia_cp_esocial_v9_5.xlsx`. Bases acima de 1.048.575 linhas sao
divididas em abas numeradas dentro desse mesmo arquivo.

O manifesto externo nao e necessario para validar o relatorio. Quando solicitado
na interface, ele e gerado ao lado do XLSX.

## Preservacao

O processamento nao apaga automaticamente workspaces, bancos SQLite, XMLs,
logs ou checkpoints. A limpeza disponivel na interface depende de acao explicita
do usuario.

Consulte `PLANO_V9_5.md` e `ATUALIZACOES_V9_5_ENGINE_V3.md`.
