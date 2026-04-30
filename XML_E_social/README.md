# XML_e-social — Auditoria CPP v4

Aplicativo em Streamlit para ler um ou mais ZIPs do eSocial e fazer triagem de possível incidência indevida de CPP sobre verbas não incidentes/indenizatórias.

## Novidades da versão 4

- aceita múltiplos ZIPs no mesmo processamento;
- permite enviar pacotes separados, por exemplo: tabelas S-1010, remunerações S-1200 e consolidado S-5001/S-5011;
- extrai o S-5001 em detalhe por trabalhador, matrícula, lotação, categoria, `tpValor` e valor;
- cria aba de composição teórica com base no S-1200 cruzado com o S-1010;
- cria conciliação entre a composição teórica e a base oficial do S-5001;
- mantém identificação de rubricas do S-1200 sem correspondência no S-1010;
- gera Excel final `auditoria_cpp_esocial_v4.xlsx`.

## Eventos principais

- S-1010 — Tabela de Rubricas / incidência CP;
- S-1200 — Remuneração e itens de folha;
- S-5001 — Base oficial por trabalhador;
- S-5011 — Base consolidada patronal, quando existir;
- S-3000 — Exclusões.

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

## Uso recomendado

Envie, no mesmo processamento, todos os pacotes disponíveis para a empresa/período analisado:

1. ZIP com S-1010;
2. ZIP com S-1200;
3. ZIP consolidado com S-5001 e, se existir, S-5011;
4. ZIP com S-3000, caso existam exclusões.

Sem S-1200, o app consegue ler a base oficial do S-5001, mas não consegue explicar a composição por rubrica. Sem S-1010, ele enxerga as rubricas do S-1200, mas não consegue classificar corretamente a incidência CP.
