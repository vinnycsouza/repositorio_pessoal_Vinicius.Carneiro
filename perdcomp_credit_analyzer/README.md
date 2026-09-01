# Analisador de créditos PER/DCOMP

Aplicação Streamlit para receber múltiplos PDFs ou arquivos ZIP, extrair os
campos de crédito dos demonstrativos PER/DCOMP e organizar a cadeia de
utilização por competência e data de transmissão.

## Execução local

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Os documentos enviados são processados em memória e não devem ser versionados.

## Fluxo

1. Envie os demonstrativos individuais em PDF ou um arquivo ZIP.
2. Confira o resumo de saldo por competência.
3. Consulte a sequência cronológica dos PER/DCOMPs de cada competência.
4. Exporte o resumo e o histórico completo para Excel.

O relatório consolidado é produzido pela própria aplicação. Não é necessário
enviar outro modelo de documento. O projeto é compatível com o Streamlit
Community Cloud.
