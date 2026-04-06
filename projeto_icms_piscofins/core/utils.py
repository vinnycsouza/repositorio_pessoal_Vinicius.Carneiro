from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable

import pandas as pd


SHEET_ALIASES = {
    "c100": ["C100 - Nota Fiscal", "C100"],
    "c170": ["C170 - Itens da Nota", "C170"],
    "c190": ["C190 - Analítico", "C190 - Analitico", "C190"],
}


IND_OPER_MAP = {
    0: "Entrada",
    1: "Saída",
    "0": "Entrada",
    "1": "Saída",
    "Entrada": "Entrada",
    "Saída": "Saída",
    "Saida": "Saída",
}


def normalize_text(value: str) -> str:
    value = "" if value is None else str(value)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value



def normalize_cnpj(value) -> str:
    digits = re.sub(r"\D", "", "" if pd.isna(value) else str(value))
    return digits.zfill(14) if digits else ""



def normalize_key(value) -> str:
    digits = re.sub(r"\D", "", "" if pd.isna(value) else str(value))
    return digits if len(digits) >= 20 else ""



def coerce_number(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="float64")
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    cleaned = (
        series.astype(str)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.replace(" ", "", regex=False)
        .replace({"nan": None, "None": None, "": None})
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)



def choose_sheet(sheet_names: Iterable[str], logical_name: str) -> str | None:
    names = list(sheet_names)
    aliases = SHEET_ALIASES.get(logical_name, [])
    alias_norm = [normalize_text(a) for a in aliases]
    for name in names:
        if normalize_text(name) in alias_norm:
            return name
    for name in names:
        norm_name = normalize_text(name)
        if any(alias in norm_name for alias in alias_norm):
            return name
    return None



def validate_excel_path(path_str: str) -> Path:
    path = Path(path_str.strip().strip('"'))
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
        raise ValueError(f"Arquivo inválido para leitura Excel: {path.name}")
    return path
