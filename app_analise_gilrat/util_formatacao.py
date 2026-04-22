import pandas as pd
import re

# =========================
# Normalizar nomes de colunas
# =========================
def normalizar_colunas(df):
    df.columns = [str(col).strip() for col in df.columns]
    return df


# =========================
# Padronizar competência (DT_COMP)
# =========================
def padronizar_dt_comp(valor):
    if pd.isna(valor):
        return None

    # Caso já seja data
    if isinstance(valor, (pd.Timestamp, )):
        return pd.to_datetime(valor).strftime("%Y-%m")

    valor_str = str(valor).strip()

    if not valor_str:
        return None

    # Tenta converter direto como data
    data = pd.to_datetime(valor_str, errors="coerce", dayfirst=True)
    if pd.notna(data):
        return data.strftime("%Y-%m")

    # Remove tudo que não for número
    digitos = re.sub(r"\D", "", valor_str)

    # Formatos possíveis:
    # 012021 -> 2021-01
    # 12021  -> 2021-01
    # 202101 -> 2021-01

    if len(digitos) == 6:
        mm = digitos[:2]
        yyyy = digitos[2:]
        if 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}"

        yyyy = digitos[:4]
        mm = digitos[4:]
        if 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}"

    if len(digitos) == 5:
        mm = digitos[:1].zfill(2)
        yyyy = digitos[1:]
        if 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}"

    return valor_str


# =========================
# Conversão segura de valores monetários
# =========================
def converter_valor(coluna):
    """
    Converte valores monetários corretamente considerando:
    - números já numéricos (não mexe)
    - formato brasileiro: 206.651,40
    - formato americano: 206651.40
    """

    # Se já for numérico → não mexe
    if pd.api.types.is_numeric_dtype(coluna):
        return coluna.fillna(0)

    serie = coluna.astype(str).str.strip()

    def tratar_valor(x):
        if x in ("", "nan", "None", None):
            return 0.0

        x = str(x).strip()

        # Caso brasileiro completo: 206.651,40
        if "," in x and "." in x:
            x = x.replace(".", "").replace(",", ".")
            return float(x)

        # Caso brasileiro simples: 651,40
        if "," in x:
            x = x.replace(",", ".")
            return float(x)

        # Caso já correto: 206651.40
        return float(x)

    return serie.apply(tratar_valor).fillna(0)