from __future__ import annotations

import pandas as pd


ALIQUOTAS_PADRAO = {
    "real": {"pis": 0.0165, "cofins": 0.0760},
    "presumido": {"pis": 0.0065, "cofins": 0.0300},
}


def calcular_por_dentro(base: float, aliquota: float) -> float:
    if base <= 0 or aliquota <= 0:
        return 0.0
    return base * aliquota / (1 + aliquota)


def calcular_linha(
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
        raise ValueError("Regime inválido.")

    base_ajustada = max(base_ajustada, 0.0)

    pis = calcular_por_dentro(base_ajustada, aliquota_pis)
    cofins = calcular_por_dentro(base_ajustada, aliquota_cofins)

    return {
        "base_original": float(base_original),
        "icms_st_excluido": float(icms_st),
        "icms_difal_excluido": float(difal_excluido),
        "base_ajustada": float(base_ajustada),
        "pis_recuperar": float(pis),
        "cofins_recuperar": float(cofins),
        "total_recuperar": float(pis + cofins),
    }


def calcular_oportunidades(
    df_consolidado: pd.DataFrame,
    regime: str,
    aliquota_pis: float,
    aliquota_cofins: float,
) -> tuple[pd.DataFrame, dict]:
    if df_consolidado.empty:
        vazio = pd.DataFrame(columns=list(df_consolidado.columns) + [
            "icms_st_excluido",
            "icms_difal_excluido",
            "base_ajustada",
            "pis_recuperar",
            "cofins_recuperar",
            "total_recuperar",
        ])
        resumo = {
            "base_total": 0.0,
            "icms_st": 0.0,
            "difal": 0.0,
            "base_ajustada": 0.0,
            "pis": 0.0,
            "cofins": 0.0,
            "total": 0.0,
        }
        return vazio, resumo

    df = df_consolidado.copy()

    resultados = df.apply(
        lambda row: pd.Series(
            calcular_linha(
                base_original=float(row.get("base_original", 0.0) or 0.0),
                icms_st=float(row.get("icms_st", 0.0) or 0.0),
                icms_difal=float(row.get("icms_difal", 0.0) or 0.0),
                regime=regime,
                aliquota_pis=aliquota_pis,
                aliquota_cofins=aliquota_cofins,
            )
        ),
        axis=1,
    )

    df["icms_st_excluido"] = resultados["icms_st_excluido"]
    df["icms_difal_excluido"] = resultados["icms_difal_excluido"]
    df["base_ajustada"] = resultados["base_ajustada"]
    df["pis_recuperar"] = resultados["pis_recuperar"]
    df["cofins_recuperar"] = resultados["cofins_recuperar"]
    df["total_recuperar"] = resultados["total_recuperar"]

    resumo = {
        "base_total": float(df["base_original"].sum()),
        "icms_st": float(df["icms_st_excluido"].sum()),
        "difal": float(df["icms_difal_excluido"].sum()),
        "base_ajustada": float(df["base_ajustada"].sum()),
        "pis": float(df["pis_recuperar"].sum()),
        "cofins": float(df["cofins_recuperar"].sum()),
        "total": float(df["total_recuperar"].sum()),
    }

    return df, resumo


def resumo_por_ano(df_resultado: pd.DataFrame) -> pd.DataFrame:
    if df_resultado.empty:
        return pd.DataFrame(columns=[
            "ano", "base_original", "icms_st_excluido", "icms_difal_excluido",
            "base_ajustada", "pis_recuperar", "cofins_recuperar", "total_recuperar"
        ])

    return (
        df_resultado.groupby("ano", dropna=False, as_index=False)[
            ["base_original", "icms_st_excluido", "icms_difal_excluido", "base_ajustada", "pis_recuperar", "cofins_recuperar", "total_recuperar"]
        ]
        .sum()
        .sort_values("ano")
        .reset_index(drop=True)
    )


def resumo_por_empresa(df_resultado: pd.DataFrame) -> pd.DataFrame:
    if df_resultado.empty:
        return pd.DataFrame(columns=[
            "empresa", "base_original", "icms_st_excluido", "icms_difal_excluido",
            "base_ajustada", "pis_recuperar", "cofins_recuperar", "total_recuperar"
        ])

    return (
        df_resultado.groupby("empresa", dropna=False, as_index=False)[
            ["base_original", "icms_st_excluido", "icms_difal_excluido", "base_ajustada", "pis_recuperar", "cofins_recuperar", "total_recuperar"]
        ]
        .sum()
        .sort_values("total_recuperar", ascending=False)
        .reset_index(drop=True)
    )


def resumo_por_cfop(df_resultado: pd.DataFrame) -> pd.DataFrame:
    if df_resultado.empty:
        return pd.DataFrame(columns=[
            "cfop", "base_original", "icms_st_excluido", "icms_difal_excluido",
            "base_ajustada", "pis_recuperar", "cofins_recuperar", "total_recuperar"
        ])

    return (
        df_resultado.groupby("cfop", dropna=False, as_index=False)[
            ["base_original", "icms_st_excluido", "icms_difal_excluido", "base_ajustada", "pis_recuperar", "cofins_recuperar", "total_recuperar"]
        ]
        .sum()
        .sort_values("total_recuperar", ascending=False)
        .reset_index(drop=True)
    )