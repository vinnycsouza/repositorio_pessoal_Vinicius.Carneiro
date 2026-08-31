# Analisador de créditos PER/DCOMP

Aplicação Streamlit para receber múltiplos PDFs ou arquivos ZIP, extrair os
campos de crédito dos demonstrativos PER/DCOMP e organizar a cadeia de
utilização por competência e data de transmissão.

## Execução local

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Os documentos enviados são processados durante a sessão e não devem ser
versionados. O projeto será desenvolvido para ser compatível com o Streamlit
Community Cloud.

