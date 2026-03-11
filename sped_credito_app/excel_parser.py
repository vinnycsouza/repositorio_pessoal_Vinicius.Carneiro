from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


@dataclass
class SheetConfig:
    nome: str
    tipo: str  # c170, c175, e316
    usecols: list[str]
    col_considerar: str | None
    col_base: str | None
    col_icms_st: str | None
    col_icms_difal: str | None
    col_ano: str | None


def detectar_engine(caminho_arquivo: str) -> str:
    ext = Path(caminho_arquivo).suffix.lower()
    if ext == ".xlsb":
        return "pyxlsb"
    return "openpyxl"


def listar_abas(caminho_arquivo: str) -> list[str]:
    engine = detectar_engine(caminho_arquivo)
    xls = pd.ExcelFile(caminho_arquivo, engine=engine)
    return xls.sheet_names


def classificar_abas(sheet_names: Iterable[str]) -> list[SheetConfig]:
    configs: list[SheetConfig] = []

    for nome in sheet_names:
        n = nome.strip().lower()

        if n.startswith("c170"):
            configs.append(
                SheetConfig(
                    nome=nome,
                    tipo="c170",
                    usecols=["A", "D", "I"],
                    col_considerar="A",
                    col_base="D",
                    col_icms_st="D",
                    col_icms_difal=None,
                    col_ano="I",
                )
            )

        elif n.startswith("c175"):
            configs.append(
                SheetConfig(
                    nome=nome,
                    tipo="c175",
                    usecols=["A", "D", "I"],
                    col_considerar="A",
                    col_base="D",
                    col_icms_st="D",
                    col_icms_difal=None,
                    col_ano="I",
                )
            )

        elif n.startswith("e316"):
            configs.append(
                SheetConfig(
                    nome=nome,
                    tipo="e316",
                    usecols=["A", "D", "I"],
                    col_considerar="A",
                    col_base=None,
                    col_icms_st=None,
                    col_icms_difal="D",
                    col_ano="I",
                )
            )

    return configs


def normalizar_numero(valor) -> float:
    if valor is None:
        return 0.0

    s = str(valor).strip()
    if not s or s.lower() == "nan":
        return 0.0

    # tenta formato BR: 1.234,56
    s1 = s.replace(".", "").replace(",", ".")
    try:
        return float(s1)
    except Exception:
        pass

    # tenta formato EN: 1234.56
    try:
        return float(s)
    except Exception:
        return 0.0


def normalizar_ano(valor) -> str:
    if valor is None:
        return "N/I"

    s = str(valor).strip()
    if not s or s.lower() == "nan":
        return "N/I"

    return s


def considerar_sim(valor) -> bool:
    if valor is None:
        return False

    s = str(valor).strip().upper()
    return s in {"SIM", "S", "TRUE", "1", "X"}


def ler_aba_resumida(
    caminho_arquivo: str,
    config: SheetConfig,
    skiprows: int = 0,
) -> pd.DataFrame:
    engine = detectar_engine(caminho_arquivo)

    df = pd.read_excel(
        caminho_arquivo,
        sheet_name=config.nome,
        engine=engine,
        usecols=config.usecols,
        dtype=str,
        skiprows=skiprows,
    )

    if df.empty:
        return pd.DataFrame(columns=[
            "origem_tipo",
            "origem_aba",
            "ano",
            "base_original",
            "icms_st",
            "icms_difal",
        ])

    # padroniza nomes pelas letras das colunas lidas
    # quando usecols é ["A", "D", "I"], pandas devolve pelo cabeçalho real,
    # então renomeamos por posição.
    letras = config.usecols
    mapa_posicional = {df.columns[i]: letras[i] for i in range(min(len(df.columns), len(letras)))}
    df = df.rename(columns=mapa_posicional)

    if config.col_considerar and config.col_considerar in df.columns:
        df = df[df[config.col_considerar].apply(considerar_sim)]

    resultado = pd.DataFrame()
    resultado["origem_tipo"] = config.tipo
    resultado["origem_aba"] = config.nome
    resultado["ano"] = df[config.col_ano].apply(normalizar_ano) if config.col_ano in df.columns else "N/I"

    if config.col_base and config.col_base in df.columns:
        resultado["base_original"] = df[config.col_base].apply(normalizar_numero)
    else:
        resultado["base_original"] = 0.0

    if config.col_icms_st and config.col_icms_st in df.columns:
        resultado["icms_st"] = df[config.col_icms_st].apply(normalizar_numero)
    else:
        resultado["icms_st"] = 0.0

    if config.col_icms_difal and config.col_icms_difal in df.columns:
        resultado["icms_difal"] = df[config.col_icms_difal].apply(normalizar_numero)
    else:
        resultado["icms_difal"] = 0.0

    return resultado


def processar_planilha_grande(
    caminho_arquivo: str,
    skiprows: int = 0,
    progress_callback=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    abas = listar_abas(caminho_arquivo)
    configs = classificar_abas(abas)

    if not configs:
        vazio = pd.DataFrame(columns=[
            "origem_tipo",
            "origem_aba",
            "ano",
            "base_original",
            "icms_st",
            "icms_difal",
        ])
        return vazio, pd.DataFrame(columns=["tipo", "aba", "linhas", "base_original", "icms_st", "icms_difal"])

    partes: list[pd.DataFrame] = []
    resumo_abas: list[dict] = []

    total = len(configs)

    for i, config in enumerate(configs, start=1):
        df_aba = ler_aba_resumida(
            caminho_arquivo=caminho_arquivo,
            config=config,
            skiprows=skiprows,
        )

        partes.append(df_aba)

        resumo_abas.append({
            "tipo": config.tipo,
            "aba": config.nome,
            "linhas": int(len(df_aba)),
            "base_original": float(df_aba["base_original"].sum()) if not df_aba.empty else 0.0,
            "icms_st": float(df_aba["icms_st"].sum()) if not df_aba.empty else 0.0,
            "icms_difal": float(df_aba["icms_difal"].sum()) if not df_aba.empty else 0.0,
        })

        if progress_callback:
            progress_callback(i / total, f"Processando aba {i}/{total}: {config.nome}")

        del df_aba

    df_bases = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=[
        "origem_tipo",
        "origem_aba",
        "ano",
        "base_original",
        "icms_st",
        "icms_difal",
    ])

    df_resumo_abas = pd.DataFrame(resumo_abas)

    return df_bases, df_resumo_abas