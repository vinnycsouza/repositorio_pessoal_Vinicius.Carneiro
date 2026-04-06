from __future__ import annotations

import pandas as pd


def make_item_key(df: pd.DataFrame) -> pd.Series:
    has_key = df["chave"].fillna("").astype(str).str.len() >= 20
    key_part = df["chave"].where(has_key, "")
    fallback = (
        df["cnpj_matriz"].fillna("").astype(str)
        + "|"
        + df["numero_nota"].fillna(0).astype(int).astype(str)
        + "|"
        + df["serie"].fillna("").astype(str)
        + "|"
        + df["item"].fillna(0).astype(int).astype(str)
        + "|"
        + df["mes"].fillna("").astype(str)
        + "|"
        + df["ano"].fillna(0).astype(int).astype(str)
    )
    return key_part.where(has_key, fallback)



def prepare_join(icms_df: pd.DataFrame, pis_df: pd.DataFrame) -> pd.DataFrame:
    icms = icms_df.copy()
    pis = pis_df.copy()
    icms["join_key"] = make_item_key(icms)
    pis["join_key"] = make_item_key(pis)

    icms = icms.add_suffix("_icms")
    pis = pis.add_suffix("_pis")

    merged = pis.merge(
        icms,
        left_on="join_key_pis",
        right_on="join_key_icms",
        how="left",
        indicator=True,
    )
    return merged



def classify_row(row: pd.Series, tolerancia: float, aliq_pis_padrao: float, aliq_cofins_padrao: float) -> pd.Series:
    valor_item = float(row.get("valor_item_pis", 0) or 0)
    vl_icms = float(row.get("vl_icms_icms", row.get("vl_icms_pis", 0)) or 0)
    vl_icms_st = float(row.get("vl_icms_st_icms", row.get("vl_icms_st_pis", 0)) or 0)
    bc_pis = float(row.get("bc_pis_pis", 0) or 0)
    bc_cofins = float(row.get("bc_cofins_pis", 0) or 0)
    cst_pis = str(row.get("cst_pis_pis", "") or "").strip()
    cst_cofins = str(row.get("cst_cofins_pis", "") or "").strip()
    cfop = str(row.get("cfop_pis", row.get("cfop_icms", "")) or "").strip()
    ind_oper = str(row.get("ind_oper_pis", row.get("ind_oper_icms", "")) or "").strip()
    situacao_ok = bool(row.get("situacao_ok_pis", True))

    base_esperada = max(valor_item - vl_icms, 0.0)
    diferenca_pis = max(bc_pis - base_esperada, 0.0)
    diferenca_cofins = max(bc_cofins - base_esperada, 0.0)

    has_st = vl_icms_st > tolerancia
    cst_sem_credito = cst_pis in {"04", "05", "06", "07", "08", "09"} or cst_cofins in {"04", "05", "06", "07", "08", "09"}
    documento_entrada = ind_oper == "0"
    join_ok = row.get("_merge") == "both"

    motivo = []
    nivel = "Sem oportunidade"

    if not join_ok:
        motivo.append("Item não localizado no arquivo ICMS/IPI")
        nivel = "Revisão manual"
    if not situacao_ok:
        motivo.append("Situação do documento não é regular")
        nivel = "Revisão manual"
    if has_st:
        motivo.append("Possui ICMS-ST")
        if nivel == "Sem oportunidade":
            nivel = "Revisão manual"
    if cst_sem_credito:
        motivo.append("CST de PIS/COFINS fora do escopo principal")
        if nivel == "Sem oportunidade":
            nivel = "Revisão manual"
    if documento_entrada:
        motivo.append("Operação de entrada: revisar aderência jurídica")
        if nivel == "Sem oportunidade":
            nivel = "Revisão manual"

    if join_ok and situacao_ok and not has_st and not cst_sem_credito and diferenca_pis > tolerancia:
        nivel = "Potencial alto"
        motivo = ["Base de PIS maior que a base esperada sem ICMS"]
    elif join_ok and situacao_ok and not has_st and diferenca_pis > 0:
        if nivel == "Sem oportunidade":
            nivel = "Potencial moderado"
            motivo = ["Diferença positiva com necessidade de revisão"]

    aliq_pis = float(row.get("aliquota_pis_utilizada", aliq_pis_padrao))
    aliq_cofins = float(row.get("aliquota_cofins_utilizada", aliq_cofins_padrao))
    credito_pis = diferenca_pis * aliq_pis / 100
    credito_cofins = diferenca_cofins * aliq_cofins / 100

    return pd.Series(
        {
            "base_esperada_sem_icms": base_esperada,
            "diferenca_base_pis": diferenca_pis,
            "diferenca_base_cofins": diferenca_cofins,
            "credito_pis_estimado": credito_pis,
            "credito_cofins_estimado": credito_cofins,
            "credito_total_estimado": credito_pis + credito_cofins,
            "nivel_oportunidade": nivel,
            "motivo": " | ".join(motivo) if motivo else "Sem indícios materiais",
            "possui_st": "Sim" if has_st else "Não",
            "join_ok": "Sim" if join_ok else "Não",
            "documento_entrada": "Sim" if documento_entrada else "Não",
            "cfop": cfop,
        }
    )



def run_analysis(
    icms_df: pd.DataFrame,
    pis_df: pd.DataFrame,
    tolerancia: float = 0.01,
    aliq_pis_padrao: float = 1.65,
    aliq_cofins_padrao: float = 7.60,
) -> tuple[pd.DataFrame, dict]:
    merged = prepare_join(icms_df, pis_df)
    merged["aliquota_pis_utilizada"] = aliq_pis_padrao
    merged["aliquota_cofins_utilizada"] = aliq_cofins_padrao
    calc = merged.apply(
        classify_row,
        axis=1,
        tolerancia=tolerancia,
        aliq_pis_padrao=aliq_pis_padrao,
        aliq_cofins_padrao=aliq_cofins_padrao,
    )
    result = pd.concat([merged, calc], axis=1)

    report = result[
        [
            "empresa_pis",
            "cnpj_matriz_pis",
            "mes_pis",
            "ano_pis",
            "chave_pis",
            "numero_nota_pis",
            "serie_pis",
            "item_pis",
            "cod_produto_pis",
            "descricao_pis",
            "cfop",
            "ind_oper_desc_pis",
            "valor_item_pis",
            "vl_icms_icms",
            "vl_icms_st_icms",
            "bc_pis_pis",
            "bc_cofins_pis",
            "base_esperada_sem_icms",
            "diferenca_base_pis",
            "diferenca_base_cofins",
            "credito_pis_estimado",
            "credito_cofins_estimado",
            "credito_total_estimado",
            "nivel_oportunidade",
            "motivo",
            "possui_st",
            "join_ok",
            "documento_entrada",
        ]
    ].copy()

    report.columns = [
        "Empresa",
        "CNPJ",
        "Mês",
        "Ano",
        "Chave",
        "Número da Nota",
        "Série",
        "Item",
        "Código do Produto",
        "Descrição",
        "CFOP",
        "Operação",
        "Valor do Item",
        "Valor de ICMS",
        "Valor de ICMS ST",
        "Base de PIS Informada",
        "Base de COFINS Informada",
        "Base Esperada sem ICMS",
        "Diferença Base PIS",
        "Diferença Base COFINS",
        "Crédito PIS Estimado",
        "Crédito COFINS Estimado",
        "Crédito Total Estimado",
        "Nível de Oportunidade",
        "Motivo",
        "Possui ST",
        "Cruzou com ICMS/IPI",
        "Documento de Entrada",
    ]

    resumo = {
        "itens_analisados": int(len(report)),
        "itens_potencial_alto": int((report["Nível de Oportunidade"] == "Potencial alto").sum()),
        "itens_revisao_manual": int((report["Nível de Oportunidade"] == "Revisão manual").sum()),
        "itens_sem_match": int((report["Cruzou com ICMS/IPI"] == "Não").sum()),
        "credito_total_estimado": float(report["Crédito Total Estimado"].sum()),
    }
    return report, resumo

