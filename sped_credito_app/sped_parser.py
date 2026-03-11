from __future__ import annotations

from typing import Dict, List
import pandas as pd


def ler_linhas_sped(arquivo_bytes, encoding="latin1") -> List[str]:
    conteudo = arquivo_bytes.read().decode(encoding, errors="ignore")
    linhas = [linha.strip() for linha in conteudo.splitlines() if linha.strip()]
    return linhas


def separar_registros(linhas: List[str], registros_interesse=None) -> Dict[str, List[List[str]]]:
    if registros_interesse is None:
        registros_interesse = {"C100", "C170", "C175", "E316"}

    dados = {reg: [] for reg in registros_interesse}

    for linha in linhas:
        partes = linha.split("|")
        if len(partes) < 2:
            continue

        reg = partes[1].strip()
        if reg in dados:
            dados[reg].append(partes)

    return dados


def df_registro(registros: List[List[str]]) -> pd.DataFrame:
    if not registros:
        return pd.DataFrame()

    max_cols = max(len(l) for l in registros)
    normalizado = [l + [""] * (max_cols - len(l)) for l in registros]
    colunas = [f"campo_{i}" for i in range(max_cols)]
    return pd.DataFrame(normalizado, columns=colunas)


def to_float_br(valor) -> float:
    if valor is None:
        return 0.0

    s = str(valor).strip()
    if not s:
        return 0.0

    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def preparar_c170(df_raw: pd.DataFrame, mapa_campos: dict) -> pd.DataFrame:
    """
    mapa_campos exemplo:
    {
        "num_item": "campo_2",
        "cod_item": "campo_3",
        "cfop": "campo_11",
        "vl_item": "campo_7",
        "vl_icms_st": "campo_15",
        "ano": None
    }
    """
    if df_raw.empty:
        return pd.DataFrame(columns=[
            "num_item", "cod_item", "cfop", "vl_item", "vl_icms_st", "ano"
        ])

    df = pd.DataFrame()

    for destino, origem in mapa_campos.items():
        if origem is None:
            df[destino] = None
        elif origem in df_raw.columns:
            df[destino] = df_raw[origem]
        else:
            df[destino] = None

    for col in ["vl_item", "vl_icms_st"]:
        if col in df.columns:
            df[col] = df[col].apply(to_float_br)

    if "ano" in df.columns:
        df["ano"] = df["ano"].fillna("N/I")

    return df


def preparar_c175(df_raw: pd.DataFrame, mapa_campos: dict) -> pd.DataFrame:
    if df_raw.empty:
        return pd.DataFrame(columns=[
            "cfop", "vl_operacao", "vl_icms_st", "ano"
        ])

    df = pd.DataFrame()

    for destino, origem in mapa_campos.items():
        if origem is None:
            df[destino] = None
        elif origem in df_raw.columns:
            df[destino] = df_raw[origem]
        else:
            df[destino] = None

    for col in ["vl_operacao", "vl_icms_st"]:
        if col in df.columns:
            df[col] = df[col].apply(to_float_br)

    if "ano" in df.columns:
        df["ano"] = df["ano"].fillna("N/I")

    return df


def preparar_e316(df_raw: pd.DataFrame, mapa_campos: dict) -> pd.DataFrame:
    """
    E316 será usado aqui como base para DIFAL, conforme sua regra do presumido.
    """
    if df_raw.empty:
        return pd.DataFrame(columns=[
            "uf", "vl_or", "vl_difal", "ano"
        ])

    df = pd.DataFrame()

    for destino, origem in mapa_campos.items():
        if origem is None:
            df[destino] = None
        elif origem in df_raw.columns:
            df[destino] = df_raw[origem]
        else:
            df[destino] = None

    for col in ["vl_or", "vl_difal"]:
        if col in df.columns:
            df[col] = df[col].apply(to_float_br)

    if "ano" in df.columns:
        df["ano"] = df["ano"].fillna("N/I")

    return df