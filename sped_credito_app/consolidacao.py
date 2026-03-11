from __future__ import annotations

import pandas as pd


def _chave_documento(df: pd.DataFrame) -> pd.Series:
    chave = (
        df.get("cnpj_estabelecimento", "").astype(str).fillna("")
        + "|"
        + df.get("chave", "").astype(str).fillna("")
        + "|"
        + df.get("numero_nota", "").astype(str).fillna("")
        + "|"
        + df.get("serie", "").astype(str).fillna("")
        + "|"
        + df.get("modelo", "").astype(str).fillna("")
        + "|"
        + df.get("cfop", "").astype(str).fillna("")
        + "|"
        + df.get("ano", "").astype(str).fillna("")
        + "|"
        + df.get("mes", "").astype(str).fillna("")
    )
    return chave


def consolidar_bases(df_pis: pd.DataFrame, df_icms: pd.DataFrame) -> pd.DataFrame:
    if df_pis.empty:
        df_pis = pd.DataFrame(columns=[
            "fonte_sped", "origem_tipo", "origem_aba", "ano", "mes", "cnpj", "empresa",
            "cnpj_estabelecimento", "participante", "numero_nota", "modelo", "serie", "chave",
            "valor_nota", "cfop", "cst_icms", "cst_pis", "cst_cofins", "base_original",
            "base_icms_st", "icms_st", "base_pis", "valor_pis", "base_cofins", "valor_cofins", "icms_difal"
        ])

    if df_icms.empty:
        df_icms = pd.DataFrame(columns=[
            "fonte_sped", "origem_tipo", "origem_aba", "ano", "mes", "cnpj", "empresa",
            "cnpj_estabelecimento", "participante", "numero_nota", "modelo", "serie", "chave",
            "valor_nota", "cfop", "cst_icms", "base_original", "base_icms_st", "icms_st", "icms_difal"
        ])

    pis = df_pis.copy()
    icms = df_icms.copy()

    pis["chave_doc"] = _chave_documento(pis)
    icms["chave_doc"] = _chave_documento(icms)

    grp_pis = pis.groupby("chave_doc", dropna=False, as_index=False).agg({
        "ano": "first",
        "mes": "first",
        "cnpj": "first",
        "empresa": "first",
        "cnpj_estabelecimento": "first",
        "participante": "first",
        "numero_nota": "first",
        "modelo": "first",
        "serie": "first",
        "chave": "first",
        "cfop": "first",
        "cst_pis": "first",
        "cst_cofins": "first",
        "base_original": "sum",
        "base_pis": "sum",
        "valor_pis": "sum",
        "base_cofins": "sum",
        "valor_cofins": "sum",
    })

    grp_icms = icms.groupby("chave_doc", dropna=False, as_index=False).agg({
        "ano": "first",
        "mes": "first",
        "cnpj": "first",
        "empresa": "first",
        "cnpj_estabelecimento": "first",
        "participante": "first",
        "numero_nota": "first",
        "modelo": "first",
        "serie": "first",
        "chave": "first",
        "cfop": "first",
        "cst_icms": "first",
        "base_original": "sum",
        "base_icms_st": "sum",
        "icms_st": "sum",
        "icms_difal": "sum",
    })

    consolidado = grp_pis.merge(
        grp_icms[[
            "chave_doc",
            "base_icms_st",
            "icms_st",
            "icms_difal",
            "cst_icms",
        ]],
        on="chave_doc",
        how="left",
    )

    for col in ["base_icms_st", "icms_st", "icms_difal"]:
        consolidado[col] = consolidado[col].fillna(0.0)

    consolidado["cst_icms"] = consolidado["cst_icms"].fillna("")

    return consolidado