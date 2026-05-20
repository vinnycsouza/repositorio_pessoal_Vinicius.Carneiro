import re
import unicodedata
import pandas as pd


def normalize_column_name(col: str) -> str:
    """Padroniza nomes de colunas para facilitar o mapeamento."""
    col = str(col).strip().upper()
    col = unicodedata.normalize("NFKD", col).encode("ASCII", "ignore").decode("ASCII")
    col = re.sub(r"[^A-Z0-9_]+", "_", col)
    col = re.sub(r"_+", "_", col).strip("_")
    return col


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalize_column_name(c) for c in df.columns]
    return df


def find_col(df: pd.DataFrame, candidates: list[str], required: bool = True) -> str | None:
    cols = set(df.columns)
    for c in candidates:
        c_norm = normalize_column_name(c)
        if c_norm in cols:
            return c_norm
    if required:
        raise ValueError(f"Coluna obrigatória não localizada. Aceitas: {', '.join(candidates)}")
    return None


def to_number(series: pd.Series) -> pd.Series:
    """Converte números nos padrões 1.234,56, 1234,56 e 1234.56."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").fillna(0.0)
    s = series.astype(str).str.strip()
    s = s.str.replace("R$", "", regex=False).str.replace(" ", "", regex=False)
    # Se tem ponto e vírgula, assume padrão BR: 1.234,56
    br_mask = s.str.contains(",", regex=False)
    s_br = s[br_mask].str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    s_us = s[~br_mask].str.replace(",", "", regex=False)
    out = pd.Series(index=series.index, dtype="float64")
    out.loc[br_mask] = pd.to_numeric(s_br, errors="coerce")
    out.loc[~br_mask] = pd.to_numeric(s_us, errors="coerce")
    return out.fillna(0.0)


def normalize_key(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\D", "", regex=True).str.strip()


def competence_from_date(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return dt.dt.strftime("%Y-%m").fillna("SEM_DATA")
