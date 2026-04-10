# XML_E_social

Aplicativo em Streamlit para ler o ZIP original do eSocial e fazer uma triagem de possivel incidencia indevida de CPP sobre verbas indenizatorias.

## Novidades da versao 3
- leitura automatica do ZIP original, inclusive com ZIP dentro de ZIP;
- cruzamento entre S-1010, S-1200, S-5001, S-5011 e S-3000;
- aba de rubricas do S-1200 sem correspondencia no S-1010;
- resumo por competencia;
- ranking por CPF / matricula;
- estimativa inicial de CPP potencialmente recolhida a maior.

## Como rodar
```bash
python -m venv .venv
```

No PowerShell:
```bash
.venv\Scripts\Activate.ps1
```

Instale as dependencias:
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
