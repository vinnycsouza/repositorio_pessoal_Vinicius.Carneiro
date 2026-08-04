# XML eSocial V9.5.2 - Engine V3

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
- gerenciamento do Workspace atual, com abertura no Explorador e envio seguro
  para a Lixeira.
- reutilização do Workspace no módulo de Levantamento, sem reprocessar XML;
- consultas filtradas e exportação detalhada diretamente pelo SQLite.

## Execucao

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Fluxo V9.5

```text
XML/ZIP -> Parser -> SQLite/checkpoint -> consultas -> Excel Builder -> validacao -> download
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
`relatorio_incidencia_cp_esocial_v9_5.xlsx`. Bases acima de 1.048.575 linhas sao
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

Consulte `PLANO_V9_5.md`, `ATUALIZACOES_V9_5_ENGINE_V3.md` e
`ATUALIZACOES_V9_5_2_ENGINE_V3.md`. Consulte também
`ATUALIZACOES_INTEGRACAO_WORKSPACE_LEVANTAMENTO.md`.
O desenho técnico da carga incremental está em `PLANO_CARGA_INCREMENTAL.md`.
