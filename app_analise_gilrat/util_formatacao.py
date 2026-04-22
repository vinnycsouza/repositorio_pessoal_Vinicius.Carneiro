import pandas as pd
import re


def normalizar_colunas(df):
    df.columns = [str(col).strip() for col in df.columns]
    return df


def padronizar_dt_comp(valor):
    if pd.isna(valor):
        return None

    if isinstance(valor, pd.Timestamp):
        return pd.to_datetime(valor).strftime("%Y-%m")

    valor_str = str(valor).strip()

    if not valor_str:
        return None

    data = pd.to_datetime(valor_str, errors="coerce", dayfirst=True)
    if pd.notna(data):
        return data.strftime("%Y-%m")

    digitos = re.sub(r"\D", "", valor_str)

    if len(digitos) == 6:
        mm = digitos[:2]
        yyyy = digitos[2:]
        if mm.isdigit() and yyyy.isdigit() and 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}"

        yyyy = digitos[:4]
        mm = digitos[4:]
        if mm.isdigit() and yyyy.isdigit() and 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}"

    if len(digitos) == 5:
        mm = digitos[:1].zfill(2)
        yyyy = digitos[1:]
        if mm.isdigit() and yyyy.isdigit() and 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}"

    return valor_str


def converter_valor(coluna):
    if pd.api.types.is_numeric_dtype(coluna):
        return coluna.fillna(0)

    serie = coluna.astype(str).str.strip()

    def tratar_valor(x):
        if x in ("", "nan", "None", None):
            return 0.0

        x = str(x).strip()

        if "," in x and "." in x:
            x = x.replace(".", "").replace(",", ".")
            return float(x)

        if "," in x:
            x = x.replace(",", ".")
            return float(x)

        return float(x)

    return serie.apply(tratar_valor).fillna(0)