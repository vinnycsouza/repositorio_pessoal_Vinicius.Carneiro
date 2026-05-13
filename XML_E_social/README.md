# XML_E_social

Aplicativo em Streamlit para ler ZIPs do eSocial e gerar relatório de composição da incidência de CP por rubrica, com apoio para levantamento interativo de verbas.

## Versão 6

Principais recursos:

- leitura automática de um ou mais ZIPs do eSocial, inclusive ZIP dentro de ZIP;
- cruzamento entre S-1010, S-1200, S-5001, S-5011 e S-3000;
- relatório de rubricas com e sem incidência de CP;
- classificação visual da verba: remuneratória, rescisória, férias, 13º salário, desconto, informativa/técnica ou revisar;
- área de **Levantamento de verbas**, com filtros, busca por rubrica, seleção múltipla e cálculo estimado de CPP;
- base por trabalhador para conferência entre movimentos do S-1200 e detalhes do S-5001;
- exportação em Excel com aba específica `07_levantamento`;
- identificação da empresa em aba `00_empresa` nos relatórios gerados.

## Como rodar

Crie o ambiente virtual:

```bash
python -m venv .venv
```

No PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Execute:

```bash
streamlit run app.py
```

Para upload maior:

```bash
streamlit run app.py --server.maxUploadSize=1000
```

## Relatório gerado

```text
relatorio_incidencia_cp_esocial_v6.xlsx
```

## Conjunto recomendado de arquivos

- S-1010 — tabela de rubricas / `codIncCP`;
- S-1200 — movimentos de remuneração;
- S-5001 — conferência da base por trabalhador;
- S-5011 — apoio consolidado, quando existir;
- S-3000 — exclusões, quando existir.


## Atualizacao v6.5
- levantamento de verbas mantido no padrao do app;
- inclusao de resumo por competencia no Excel do levantamento;
- inclusao de resumo por competencia/rubrica para apoio ao recalculo.


## Atualização v6.5
- seleção de rubricas no levantamento por checklist com busca;
- a seleção fica armazenada em sessão e não se perde a cada clique;
- botão separado para aplicar seleção antes de recalcular o levantamento.
