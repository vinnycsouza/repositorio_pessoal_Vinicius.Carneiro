# XML_E_social

Aplicativo em Python + Streamlit para auditoria inicial de possível incidência indevida de CPP sobre verbas indenizatórias no eSocial.

## O que o app faz
- abre o ZIP original do eSocial;
- localiza automaticamente XMLs relevantes;
- funciona com subpastas e ZIP dentro de ZIP;
- lê S-1010, S-1200, S-5001 e S-3000;
- desconsidera eventos excluídos por S-3000 na triagem;
- gera painel e Excel de auditoria.

## Estrutura
```text
XML_E_social/
├── app.py
├── requirements.txt
├── README.md
├── modules/
│   ├── __init__.py
│   ├── auditoria.py
│   ├── parser_xml.py
│   └── processador_zip.py
├── utils/
│   ├── __init__.py
│   └── helpers.py
├── data/
└── output/
```

## Como rodar no VS Code
Abra a pasta `XML_E_social` no VS Code e rode no terminal:

```bash
python -m venv .venv
```

### PowerShell
```bash
.venv\Scripts\Activate.ps1
```

### CMD
```bash
.venv\Scripts\activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Rode o Streamlit:

```bash
streamlit run app.py
```

Se precisar aumentar upload:

```bash
streamlit run app.py --server.maxUploadSize=1000
```

## Observação importante
Este projeto é um MVP de triagem. Ele sinaliza indícios de possível tributação indevida quando encontra rubricas com `codIncCP = 00` em contexto de base previdenciária no mesmo CPF, matrícula e período. A validação final pode exigir refinamento adicional da composição da base.
