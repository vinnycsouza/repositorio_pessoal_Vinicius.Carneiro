# App ICMS na Base do PIS/COFINS

Aplicativo Streamlit para cruzar informações do SPED ICMS/IPI e SPED Contribuições já convertidos para Excel.

## Organização esperada dos arquivos

### Excel ICMS/IPI
Abas obrigatórias:
- `C100`
- `C190`

Colunas mínimas esperadas:

#### Aba C100
- `CHV_NFE` ou `CHAVE`
- `DT_DOC` ou `DATA`
- `COD_MOD` opcional
- `COD_SIT` opcional

#### Aba C190
- `CHV_NFE` ou `CHAVE`
- `CFOP`
- `CST_ICMS` ou `CST`
- `VL_OPR`
- `VL_BC_ICMS`
- `VL_ICMS`

### Excel PIS/COFINS
Abas conforme escolha no app:
- `C170`
- `C175`

#### Aba C170
- `CHV_NFE` ou `CHAVE`
- `NUM_ITEM` opcional
- `CFOP` opcional
- `CST_PIS`
- `VL_ITEM`
- `VL_BC_PIS`
- `VL_BC_COFINS`

#### Aba C175
- `CHV_NFE` ou `CHAVE`
- `CFOP` opcional
- `CST_PIS`
- `VL_OPR` ou `VL_ITEM`
- `VL_BC_PIS`
- `VL_BC_COFINS`

## Como rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Saída gerada

O app gera um Excel com abas:
- `01_resumo_geral`
- `02_icms_c190_base`
- `03_cruzamento_c170` quando selecionado
- `04_cruzamento_c175` quando selecionado
- `05_comparativo_c170_c175` quando ambos forem selecionados
- `06_divergencias`
- `07_potencial_credito`
- `08_parametros`
