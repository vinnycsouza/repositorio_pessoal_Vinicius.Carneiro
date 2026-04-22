import pandas as pd

def normalizar_colunas(df):
    df.columns = [str(col).strip() for col in df.columns]
    return df

def padronizar_dt_comp(valor):
    if pd.isna(valor):
        return None

    valor = str(valor).strip()

    if valor.isdigit() and len(valor) == 6:
        mes = valor[:2]
        ano = valor[2:]
        return f"{ano}-{mes}"

    if valor.isdigit() and len(valor) == 5:
        mes = valor[:1].zfill(2)
        ano = valor[1:]
        return f"{ano}-{mes}"

    data = pd.to_datetime(valor, errors="coerce", dayfirst=True)
    if pd.notna(data):
        return data.strftime("%Y-%m")

    return valor

def converter_valor(coluna):
    return pd.to_numeric(
        coluna.astype(str)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False),
        errors="coerce"
    ).fillna(0)