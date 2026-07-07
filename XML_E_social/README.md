# XML_E_social — v7.3

Aplicativo em Streamlit para ler ZIPs do eSocial e gerar relatório de composição da incidência de CP por rubrica, com módulo separado para levantamento de verbas.

## Principais recursos da v7.3

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
relatorio_incidencia_cp_esocial_v7_3.xlsx
levantamento_verbas_cp_v7_3.xlsx
```

## Conjunto recomendado de arquivos

- S-1010 — tabela de rubricas / `codIncCP`;
- S-1200 — movimentos de remuneração;
- S-5001 — conferência da base por trabalhador;
- S-5011 — apoio consolidado, quando existir;
- S-3000 — exclusões, quando existir.
