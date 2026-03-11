from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


def detectar_engine(caminho_arquivo: str) -> str:
    ext = Path(caminho_arquivo).suffix.lower()
    return "pyxlsb" if ext == ".xlsb" else "openpyxl"


def listar_abas(caminho_arquivo: str) -> list[str]:
    engine = detectar_engine(caminho_arquivo)
    xls = pd.ExcelFile(caminho_arquivo, engine=engine)
    return xls.sheet_names


def classificar_abas_icms_ipi(sheet_names: Iterable[str]) -> list[tuple[str, str]]:
    saida: list[tuple[str, str]] = []

    for nome in sheet_names:
        n = nome.strip().lower()

        if n.startswith("c170"):
            saida.append((nome, "c170"))
        elif n.startswith("c175"):
            saida.append((nome, "c175"))
        elif n.startswith("c190"):
            saida.append((nome, "c190"))
        elif n.startswith("c191"):
            saida.append((nome, "c191"))
        elif n.startswith("e316"):
            saida.append((nome, "e316"))

    return saida


def normalizar_texto(valor) -> str:
    if valor is None:
        return ""
    s = str(valor).strip()
    if s.lower() == "nan":
        return ""
    return s


def normalizar_numero(valor) -> float:
    if valor is None:
        return 0.0

    if isinstance(valor, (int, float)):
        return float(valor)

    s = str(valor).strip()
    if not s or s.lower() == "nan":
        return 0.0

    try:
        return float(s.replace(".", "").replace(",", "."))
    except Exception:
        pass

    try:
        return float(s)
    except Exception:
        return 0.0


def encontrar_coluna(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    mapa = {str(col).strip().lower(): col for col in df.columns}
    for candidato in candidatos:
        chave = candidato.strip().lower()
        if chave in mapa:
            return mapa[chave]
    return None


def encontrar_coluna_por_fragmento(df: pd.DataFrame, fragmentos: list[str]) -> str | None:
    cols = [str(c).strip() for c in df.columns]
    for frag in fragmentos:
        frag_low = frag.strip().lower()
        for col in cols:
            if frag_low in col.lower():
                return col
    return None


def ler_aba(caminho_arquivo: str, sheet_name: str, skiprows: int = 0) -> pd.DataFrame:
    engine = detectar_engine(caminho_arquivo)

    df = pd.read_excel(
        caminho_arquivo,
        sheet_name=sheet_name,
        engine=engine,
        dtype=str,
        skiprows=skiprows,
        header=0,
    )

    df.columns = [str(c).strip() for c in df.columns]
    return df


def processar_aba_icms(df: pd.DataFrame, tipo: str, nome_aba: str) -> pd.DataFrame:
    col_ano = encontrar_coluna(df, ["Ano"])
    col_mes = encontrar_coluna(df, ["Mês", "Mes"])
    col_cnpj = encontrar_coluna(df, ["CNPJ"])
    col_empresa = encontrar_coluna(df, ["Empresa"])
    col_estab = encontrar_coluna(df, ["CNPJ Estabelecimento(C010)"])
    col_participante = encontrar_coluna(df, ["Participante(C100)"])
    col_nota = encontrar_coluna(df, ["Número da Nota(C100)"])
    col_modelo = encontrar_coluna(df, ["Modelo(C100)"])
    col_serie = encontrar_coluna(df, ["Série(C100)", "Serie(C100)"])
    col_chave = encontrar_coluna(df, ["Chave(C100)"])
    col_valor_nota = encontrar_coluna(df, ["Valor(C100)", "Valor"])

    col_cfop = encontrar_coluna(df, ["CFOP"])
    col_cst_icms = encontrar_coluna(df, ["CST de ICMS", "CST", "CST_ICMS"])
    col_base_original = encontrar_coluna(df, ["Valor Total do Produto", "Valor da Operação", "Valor"])
    col_base_icms_st = encontrar_coluna(df, ["Base de ICMS ST", "Base de Icms ST"])
    col_valor_icms_st = encontrar_coluna(df, ["Valor de ICMS ST", "Valor de Icms ST"])

    col_difal = encontrar_coluna(df, ["Valor de Difal", "Valor de ICMS DIFAL", "Difal"])
    if not col_difal:
        col_difal = encontrar_coluna_por_fragmento(df, ["difal"])

    resultado = pd.DataFrame()
    resultado["fonte_sped"] = "icms_ipi"
    resultado["origem_tipo"] = tipo
    resultado["origem_aba"] = nome_aba
    resultado["ano"] = df[col_ano].apply(normalizar_texto) if col_ano else "N/I"
    resultado["mes"] = df[col_mes].apply(normalizar_texto) if col_mes else ""
    resultado["cnpj"] = df[col_cnpj].apply(normalizar_texto) if col_cnpj else ""
    resultado["empresa"] = df[col_empresa].apply(normalizar_texto) if col_empresa else ""
    resultado["cnpj_estabelecimento"] = df[col_estab].apply(normalizar_texto) if col_estab else ""
    resultado["participante"] = df[col_participante].apply(normalizar_texto) if col_participante else ""
    resultado["numero_nota"] = df[col_nota].apply(normalizar_texto) if col_nota else ""
    resultado["modelo"] = df[col_modelo].apply(normalizar_texto) if col_modelo else ""
    resultado["serie"] = df[col_serie].apply(normalizar_texto) if col_serie else ""
    resultado["chave"] = df[col_chave].apply(normalizar_texto) if col_chave else ""
    resultado["valor_nota"] = df[col_valor_nota].apply(normalizar_numero) if col_valor_nota else 0.0
    resultado["cfop"] = df[col_cfop].apply(normalizar_texto) if col_cfop else ""
    resultado["cst_icms"] = df[col_cst_icms].apply(normalizar_texto) if col_cst_icms else ""
    resultado["base_original"] = df[col_base_original].apply(normalizar_numero) if col_base_original else 0.0
    resultado["base_icms_st"] = df[col_base_icms_st].apply(normalizar_numero) if col_base_icms_st else 0.0
    resultado["icms_st"] = df[col_valor_icms_st].apply(normalizar_numero) if col_valor_icms_st else 0.0
    resultado["icms_difal"] = df[col_difal].apply(normalizar_numero) if col_difal else 0.0

    return resultado


def processar_sped_icms(caminho_arquivo: str, skiprows: int = 0, progress_callback=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    abas = listar_abas(caminho_arquivo)
    classificadas = classificar_abas_icms_ipi(abas)

    colunas_base = [
        "fonte_sped",
        "origem_tipo",
        "origem_aba",
        "ano",
        "mes",
        "cnpj",
        "empresa",
        "cnpj_estabelecimento",
        "participante",
        "numero_nota",
        "modelo",
        "serie",
        "chave",
        "valor_nota",
        "cfop",
        "cst_icms",
        "base_original",
        "base_icms_st",
        "icms_st",
        "icms_difal",
    ]

    if not classificadas:
        return (
            pd.DataFrame(columns=colunas_base),
            pd.DataFrame(columns=["tipo", "aba", "linhas", "base_original", "icms_st", "icms_difal"]),
        )

    partes = []
    resumo_abas = []
    total = len(classificadas)

    for i, (nome_aba, tipo) in enumerate(classificadas, start=1):
        df = ler_aba(caminho_arquivo, nome_aba, skiprows=skiprows)
        base = processar_aba_icms(df, tipo, nome_aba)
        partes.append(base)

        resumo_abas.append({
            "tipo": tipo,
            "aba": nome_aba,
            "linhas": int(len(base)),
            "base_original": float(base["base_original"].sum()) if not base.empty else 0.0,
            "icms_st": float(base["icms_st"].sum()) if not base.empty else 0.0,
            "icms_difal": float(base["icms_difal"].sum()) if not base.empty else 0.0,
        })

        if progress_callback:
            progress_callback(i / total, f"ICMS/IPI: processando aba {i}/{total} - {nome_aba}")

    df_bases = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=colunas_base)
    df_resumo_abas = pd.DataFrame(resumo_abas)

    return df_bases, df_resumo_abas