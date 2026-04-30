# XML_E-social — Relatório de Incidência CP

Aplicativo em Streamlit para ler ZIPs originais do eSocial e gerar um relatório simplificado de composição da incidência de Contribuição Previdenciária (CP) por rubrica.

## Versão 5

Foco do relatório:

- identificar quais rubricas do S-1200 estão com incidência de CP conforme o S-1010;
- separar rubricas com incidência, sem incidência e sem cadastro S-1010;
- classificar visualmente o caráter da verba: remuneratório, rescisório, férias, 13º salário, desconto, informativo/técnico ou revisar;
- confrontar o total com incidência CP com os detalhes do S-5001 quando disponível;
- manter abas de apoio com os dados brutos extraídos.

## Eventos utilizados

- S-1010 — tabela de rubricas e codIncCP;
- S-1200 — movimentos de remuneração por trabalhador;
- S-5001 — base oficial por trabalhador, quando disponível;
- S-5011 — base patronal consolidada, quando disponível;
- S-3000 — exclusões.

## Relatório gerado

O arquivo exportado é:

```text
relatorio_incidencia_cp_esocial_v5.xlsx
```

Principais abas:

- `01_resumo`
- `02_rubricas_cp`
- `03_movimentos_cp`
- `04_base_trabalhador`
- `05_sem_s1010`
- `06_s5001_tpvalor`
- abas de apoio: S-1010, S-1200, S-5001, S-5011, S-3000, inventário e erros.

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
streamlit run app.py
```

Para upload maior:

```bash
streamlit run app.py --server.maxUploadSize=1000
```
