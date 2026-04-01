# PER/DCOMP — Extrator e Cruzamento

Projeto em Python/Streamlit para:

## Fase 1
- Ler múltiplos PDFs de PER/DCOMP
- Extrair:
  - Tipo do crédito (PIS ou COFINS)
  - Tipo de período do crédito
  - Trimestre
  - Ano
  - Valor original do crédito
  - Saldo do crédito original
  - Crédito utilizado no documento
  - Crédito atualizado
  - Data de criação
  - Data de transmissão
- Exportar um Excel único em ordem cronológica

## Fase 2
- Ler um Excel de levantamento mensal
- Espera colunas compatíveis com:
  - Ano
  - Mês
  - Crédito PIS
  - Crédito COFINS
- Converte mês para trimestre
- Soma PIS e COFINS separadamente
- Cruza com os dados dos PER/DCOMP
- Exporta um Excel único com abas de apoio e aba final de cruzamento

## Como rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Layout esperado do Excel de levantamento

O programa tenta reconhecer nomes equivalentes, mas o formato mais seguro é:

| Ano | Mês | Crédito PIS | Crédito COFINS |
|-----|-----|-------------|----------------|
| 2024 | Janeiro | 1000 | 4000 |
| 2024 | Fevereiro | 1200 | 4200 |

Também aceita mês como número (1 a 12).
