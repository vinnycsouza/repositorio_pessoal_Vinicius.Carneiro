# Conciliação de Salário-Família

Aplicação Streamlit independente para:

1. extrair salário-família de Declarações Completas da DCTFWeb em PDF/ZIP;
2. gerar um Excel consolidado;
3. comparar os valores com levantamentos MANAD, XML/eSocial ou planilhas padronizadas.

## Execução local

```powershell
python -m pip install -r requirements.txt
streamlit run app.py
```

Os uploads são processados em memória e não são persistidos pela aplicação.
