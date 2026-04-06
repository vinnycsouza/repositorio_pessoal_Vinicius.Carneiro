# Auditor local — ICMS x PIS/COFINS

Aplicação local em Streamlit para cruzar os arquivos Excel convertidos do SPED ICMS/IPI e do SPED PIS/COFINS, identificando itens com indício de não exclusão do ICMS da base de cálculo do PIS/COFINS.

## O que esta versão faz

- lê os arquivos por **caminho local**
- usa a aba **C170 - Itens da Nota** de cada workbook
- cruza os itens por:
  - chave da NF-e, quando existir
  - fallback por CNPJ + número da nota + série + item + competência
- calcula base esperada sem ICMS:
  - `Valor do Item - Valor de ICMS`
- classifica os resultados em:
  - Potencial alto
  - Revisão manual
  - Sem oportunidade
- gera Excel com:
  - Resumo
  - Oportunidades
  - Revisão Manual
  - Sem Cruzamento

## Estrutura

```text
projeto_icms_piscofins_local/
├── app.py
├── requirements.txt
├── README.md
└── core/
    ├── analysis.py
    ├── exporter.py
    ├── io_excel.py
    ├── normalize.py
    └── utils.py
```

## Como instalar

No terminal, dentro da pasta do projeto:

```bash
pip install -r requirements.txt
```

## Como rodar

```bash
streamlit run app.py
```

## Como usar

1. Abra o app.
2. Informe o caminho completo do Excel **ICMS/IPI**.
3. Informe o caminho completo do Excel **PIS/COFINS**.
4. Ajuste tolerância e alíquotas, se necessário.
5. Clique em **Processar arquivos**.
6. Revise a grade e depois clique em **Gerar Excel do relatório**.

## Observações importantes

- O projeto foi mapeado para o padrão de colunas que você me mostrou.
- Se o seu conversor alterar nomes de abas ou colunas, ajuste os dicionários em `core/normalize.py`.
- Itens com ICMS-ST vão para **revisão manual**.
- Operações de entrada também vão sinalizadas para revisão jurídica/técnica.
- O relatório é indiciário e não substitui validação fiscal final.
