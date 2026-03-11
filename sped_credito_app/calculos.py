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
    elif regime == "presumido":
        base_ajustada = base_original - icms_st - icms_difal
    else:
        raise ValueError("Regime inválido. Use 'real' ou 'presumido'.")

    base_ajustada = max(base_ajustada, 0.0)

    pis = calcular_por_dentro(base_ajustada, aliquota_pis)
    cofins = calcular_por_dentro(base_ajustada, aliquota_cofins)

    return {
        "regime": regime,
        "base_original": base_original,
        "icms_st_excluido": icms_st,
        "icms_difal_excluido": icms_difal if regime == "presumido" else 0.0,
        "base_ajustada": base_ajustada,
        "pis_recuperar": pis,
        "cofins_recuperar": cofins,
        "total_recuperar": pis + cofins,
    }


def resumir_bases(
    df_c170: pd.DataFrame,
    df_c175: pd.DataFrame,
    df_e316: pd.DataFrame,
) -> dict:
    total_base_c170 = df_c170["vl_item"].sum() if "vl_item" in df_c170.columns else 0.0
    total_icms_st_c170 = df_c170["vl_icms_st"].sum() if "vl_icms_st" in df_c170.columns else 0.0

    total_base_c175 = df_c175["vl_operacao"].sum() if "vl_operacao" in df_c175.columns else 0.0
    total_icms_st_c175 = df_c175["vl_icms_st"].sum() if "vl_icms_st" in df_c175.columns else 0.0

    total_difal = df_e316["vl_difal"].sum() if "vl_difal" in df_e316.columns else 0.0

    base_original = total_base_c170 + total_base_c175
    icms_st_total = total_icms_st_c170 + total_icms_st_c175

    return {
        "base_original": base_original,
        "icms_st_total": icms_st_total,
        "icms_difal_total": total_difal,
        "base_c170": total_base_c170,
        "base_c175": total_base_c175,
        "icms_st_c170": total_icms_st_c170,
        "icms_st_c175": total_icms_st_c175,
    }


def resumo_por_ano(
    df_c170: pd.DataFrame,
    df_c175: pd.DataFrame,
    df_e316: pd.DataFrame,
    regime: str,
    aliquota_pis: float,
    aliquota_cofins: float,
) -> pd.DataFrame:
    anos = set()

    if not df_c170.empty and "ano" in df_c170.columns:
        anos.update(df_c170["ano"].dropna().astype(str).unique())
    if not df_c175.empty and "ano" in df_c175.columns:
        anos.update(df_c175["ano"].dropna().astype(str).unique())
    if not df_e316.empty and "ano" in df_e316.columns:
        anos.update(df_e316["ano"].dropna().astype(str).unique())

    if not anos:
        anos = {"N/I"}

    linhas = []

    for ano in sorted(anos):
        c170_ano = df_c170[df_c170["ano"].astype(str) == str(ano)] if not df_c170.empty and "ano" in df_c170.columns else pd.DataFrame()
        c175_ano = df_c175[df_c175["ano"].astype(str) == str(ano)] if not df_c175.empty and "ano" in df_c175.columns else pd.DataFrame()
        e316_ano = df_e316[df_e316["ano"].astype(str) == str(ano)] if not df_e316.empty and "ano" in df_e316.columns else pd.DataFrame()

        bases = resumir_bases(c170_ano, c175_ano, e316_ano)
        calc = calcular_creditos_totais(
            base_original=bases["base_original"],
            icms_st=bases["icms_st_total"],
            icms_difal=bases["icms_difal_total"],
            regime=regime,
            aliquota_pis=aliquota_pis,
            aliquota_cofins=aliquota_cofins,
        )

        linhas.append({
            "ano": ano,
            **bases,
            **calc,
        })

    return pd.DataFrame(linhas)