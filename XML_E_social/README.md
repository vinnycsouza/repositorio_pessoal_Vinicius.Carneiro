# XML_E_social — v7.6

Aplicativo em Streamlit para ler ZIPs do eSocial e gerar relatório de composição da incidência de CP por rubrica, com módulo separado para levantamento de verbas.

## Principais recursos da v7.6

- Escolha do módulo logo no início:
  - Relatório de Incidência CP;
  - Levantamento de Verbas.
- O upload aparece somente depois da escolha do módulo.
- Mantém entrada por ZIP(s) do eSocial.
- Mantém entrada por Excel consolidado no módulo de levantamento.
- Motor de cruzamento S-1010 em camadas:
  1. S-1010 válido por `codRubr + ideTabRubr + validade`;
  2. S-1010 válido por `codRubr + validade`, quando a tabela diverge ou está ausente;
  3. S-1010 histórico compatível, quando o mesmo código aparece em outra vigência/tabela com incidência CP única;
  4. S-1010 histórico divergente, quando o mesmo código aparece com incidências diferentes;
  5. Sem S-1010.
- Novas colunas de auditoria:
  - `origem_validacao`;
  - `nivel_confianca`;
  - `status_auditoria`;
  - `observacao_validacao`.
- Mantém a exportação inteligente para grandes volumes.
- Mantém o padrão dos Excel gerados.
- Busca múltipla no levantamento de verbas: aceita códigos/descrições separados por `;`, vírgula, tabulação ou quebra de linha, inclusive listas coladas direto do Excel.

## Como rodar

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
streamlit run app.py --server.maxUploadSize=2500
```

## Relatórios gerados

```text
relatorio_incidencia_cp_esocial_v7_4.xlsx
levantamento_verbas_cp_v7_4.xlsx
```

## Conjunto recomendado de arquivos

- S-1010 — tabela de rubricas / `codIncCP`;
- S-1200 — movimentos de remuneração;
- S-5001 — conferência da base por trabalhador;
- S-5011 — apoio consolidado, quando existir;
- S-3000 — exclusões, quando existir.


## Versão 7.5

- Levantamento otimizado: o Excel do levantamento só é preparado após a seleção das rubricas.
- A aba detalhada `03_movimentos` passa a ser opcional na exportação do levantamento, reduzindo tempo e uso de RAM em arquivos grandes.
- Os resumos `02_resumo_rubricas`, `04_resumo_competencia` e `05_competencia_rubrica` continuam sendo gerados no padrão do app.


## Versão 7.6

- Incluído indicador visual durante a geração do Excel de levantamento.
- O app mostra a última geração concluída: data/hora, quantidade de rubricas, movimentos, CPFs e se a aba 03_movimentos foi incluída.
- O objetivo é evitar confusão entre o arquivo antigo em memória e um novo levantamento ainda em processamento.
