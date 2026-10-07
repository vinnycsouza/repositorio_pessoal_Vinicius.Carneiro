from __future__ import annotations

import io
import re

import pandas as pd

from modules.comparador import _sem_acentos, normalizar_valor, ordenar_competencias, preparar_levantamento


def identificar_modelo(abas: list[str]) -> str | None:
    if {"K300_FILTRADO", "K150_SELECIONADAS"}.issubset(abas):
        return "MANAD"
    if {"00_empresa", "03_movimentos"}.issubset(abas):
        return "XML/eSocial"
    return None


def importar_modelo(conteudo: bytes, modelo: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    avisos: list[str] = []
    with pd.ExcelFile(io.BytesIO(conteudo)) as excel:
        if modelo == "MANAD":
            detalhe = pd.read_excel(excel, sheet_name="K300_FILTRADO", dtype=str)
            cadastro = pd.read_excel(excel, sheet_name="K150_SELECIONADAS", dtype=str)
            codigos = cadastro.loc[
                cadastro["DESC_RUBRICA"].map(_sem_acentos).str.contains(r"salario[\s-]*familia", regex=True),
                "COD_RUBRICA",
            ].dropna().unique()
            selecionado = detalhe.loc[detalhe["COD_RUBR"].isin(codigos)].copy()
            extras = int(selecionado.duplicated().sum())
            if extras:
                avisos.append(f"{extras} linhas repetidas no MANAD foram preservadas para conferência.")
            cnpj, periodo, valor = "CNPJ/CEI", "DT_COMP", "VLR_RUBR"
        elif modelo == "XML/eSocial":
            detalhe = pd.read_excel(excel, sheet_name="03_movimentos", dtype={
                "nr_insc_estab": str, "tp_insc_estab": str, "per_apur": str,
                "cod_rubr": str, "ide_tab_rubr": str,
            })
            selecionado = detalhe.loc[
                detalhe["dsc_rubr"].map(_sem_acentos).str.contains(r"salario[\s-]*familia", regex=True)
            ].copy()
            cnpj, periodo, valor = "nr_insc_estab", "per_apur", "vr_rubr"
            avisos.append("O CNPJ usado é o do estabelecimento. Confira sua correspondência com a DCTFWeb.")
            if not selecionado.empty and not selecionado["tp_insc_estab"].eq("1").all():
                raise ValueError("Há inscrições de estabelecimento que não são CNPJ. Revise o levantamento.")
            if "origem_periodo" in selecionado and selecionado["origem_periodo"].eq("infoPerAnt").any():
                avisos.append("Há valores de períodos anteriores; a consolidação usa per_apur e preserva per_ref no detalhe.")
        else:
            raise ValueError("Modelo não reconhecido.")

    if selecionado.empty:
        avisos.append("Salário-família não encontrado nesta exportação. A ausência não representa valor zero.")
    if not selecionado[cnpj].fillna("").map(lambda v: bool(re.fullmatch(r"\d{14}", re.sub(r"\D", "", str(v))))).all():
        raise ValueError("O levantamento contém CNPJ ausente ou sem 14 dígitos.")
    if not selecionado[periodo].fillna("").map(lambda v: bool(re.fullmatch(r"(0[1-9]|1[0-2])\d{4}", str(v)) if modelo == "MANAD" else re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(v)))).all():
        raise ValueError("Há competências inválidas ou anuais nas linhas de salário-família. Revise antes de comparar.")
    if selecionado[valor].map(normalizar_valor).isna().any():
        raise ValueError("Há valores ausentes ou inválidos no levantamento.")
    preparado = preparar_levantamento(selecionado, cnpj, periodo, valor, modelo)
    return ordenar_competencias(preparado), selecionado, avisos
