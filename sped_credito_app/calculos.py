from __future__ import annotations

import pandas as pd


ALIQUOTAS_PADRAO = {
    "real": {"pis": 0.0165, "cofins": 0.0760},
    "presumido": {"pis": 0.0065, "cofins": 0.0300},
}


def calcular_por_dentro(base_ajustada: float, aliquota: float) -> float:
    if base_ajustada <= 0 or aliquota <= 0:
        return 0.0
    return base_ajustada * aliquota / (1 + aliquota)


def calcular_creditos_totais(
    base_original: float,
    icms_st: float,
    icms_difal: float,
    regime: str,
    aliquota_pis: float,
    aliquota_cofins: float,
) -> dict:
    regime = regime.lower().strip()

    if regime == "real":
        base_ajustada = base_original - icms_st
        difal_excluido = 0.0
    elif regime == "presumido":
        base_ajustada = base_original - icms_st - icms_difal
        difal_excluido = icms_difal
    else:
        raise ValueError("Regime inválido. Use 'real' ou 'presumido'.")

    base_ajustada = max(base_ajustada, 0.0)

    pis = calcular_por_dentro(base_ajustada, aliquota_pis)
    cofins = calcular_por_dentro(base_ajustada, aliquota_cofins)

    return {
        "regime": regime,
        "base_original": float(base_original),
        "icms_st_excluido": float(icms_st),
        "icms_difal_excluido": float(difal_excluido),
        "base_ajustada": float(base_ajustada),
        "pis_recuperar": float(pis),
        "cofins_recuperar": float(cofins),
        "total_recuperar": float(pis + cofins),
    }


def resumo_por_ano(
    df_bases: pd.DataFrame,
    regime: str,
    aliquota_pis: float,
    aliquota_cofins: float,
) -> pd.DataFrame:
    if df_bases.empty:
        return pd.DataFrame(columns=[
            "ano",
            "base_original",
            "icms_st_total",
            "icms_difal_total",
            "base_ajustada",
            "pis_recuperar",
            "cofins_recuperar",
            "total_recuperar",
        ])

    linhas = []

    for ano, grupo in df_bases.groupby("ano", dropna=False):
        base_original = grupo["base_original"].sum()
        icms_st_total = grupo["icms_st"].sum()
        icms_difal_total = grupo["icms_difal"].sum()

        calc = calcular_creditos_totais(
            base_original=base_original,
            icms_st=icms_st_total,
            icms_difal=icms_difal_total,
            regime=regime,
            aliquota_pis=aliquota_pis,
            aliquota_cofins=aliquota_cofins,
        )

        linhas.append({
            "ano": str(ano) if pd.notna(ano) else "N/I",
            "base_original": base_original,
            "icms_st_total": icms_st_total,
            "icms_difal_total": icms_difal_total,
            "base_ajustada": calc["base_ajustada"],
            "pis_recuperar": calc["pis_recuperar"],
            "cofins_recuperar": calc["cofins_recuperar"],
            "total_recuperar": calc["total_recuperar"],
        })

    return pd.DataFrame(linhas).sort_values("ano").reset_index(drop=True)


def resumo_geral(
    df_bases: pd.DataFrame,
    regime: str,
    aliquota_pis: float,
    aliquota_cofins: float,
) -> dict:
    if df_bases.empty:
        return calcular_creditos_totais(
            base_original=0.0,
            icms_st=0.0,
            icms_difal=0.0,
            regime=regime,
            aliquota_pis=aliquota_pis,
            aliquota_cofins=aliquota_cofins,
        )

    return calcular_creditos_totais(
        base_original=df_bases["base_original"].sum(),
        icms_st=df_bases["icms_st"].sum(),
        icms_difal=df_bases["icms_difal"].sum(),
        regime=regime,
        aliquota_pis=aliquota_pis,
        aliquota_cofins=aliquota_cofins,
    )