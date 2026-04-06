from __future__ import annotations

import pandas as pd


STATUS_EXCLUSAO_IDENTIFICADA = "Exclusão identificada"
STATUS_SEM_INDICIO = "Sem indício de exclusão"
STATUS_DIVERGENTE = "Divergente / Revisar"
STATUS_SEM_DADOS = "Sem dados suficientes"


def make_item_key(df: pd.DataFrame) -> pd.Series:
    chave = df.get("chave", pd.Series(index=df.index, dtype="object")).fillna("").astype(str).str.strip()
    has_key = chave.str.len() >= 20

    numero_nota = pd.to_numeric(df.get("numero_nota", 0), errors="coerce").fillna(0).astype(int).astype(str)
    item = pd.to_numeric(df.get("item", 0), errors="coerce").fillna(0).astype(int).astype(str)
    ano = pd.to_numeric(df.get("ano", 0), errors="coerce").fillna(0).astype(int).astype(str)
    mes = df.get("mes", pd.Series(index=df.index, dtype="object")).fillna("").astype(str).str.strip()
    serie = df.get("serie", pd.Series(index=df.index, dtype="object")).fillna("").astype(str).str.strip()
    cnpj = df.get("cnpj_matriz", pd.Series(index=df.index, dtype="object")).fillna("").astype(str).str.strip()

    fallback = cnpj + "|" + numero_nota + "|" + serie + "|" + item + "|" + mes + "|" + ano
    return chave.where(has_key, fallback)



def ensure_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0.0, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)



def ensure_text(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype="object")
    return df[col].fillna("").astype(str)



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



def _prefer_origin(row: pd.Series, col_icms: str, col_pis: str) -> tuple[float, str]:
    v_icms = float(row.get(col_icms, 0) or 0)
    v_pis = float(row.get(col_pis, 0) or 0)
    if v_icms != 0:
        return v_icms, "ICMS/IPI"
    if v_pis != 0:
        return v_pis, "PIS/COFINS"
    return 0.0, "Sem valor"



def classify_row(row: pd.Series, tolerancia: float) -> pd.Series:
    base_icms = float(row.get("bc_icms_final", 0) or 0)
    valor_icms = float(row.get("vl_icms_final", 0) or 0)
    base_pis = float(row.get("bc_pis_pis", 0) or 0)
    base_cofins = float(row.get("bc_cofins_pis", 0) or 0)
    valor_item = float(row.get("valor_item_pis", 0) or 0)
    valor_icms_st = float(row.get("vl_icms_st_final", 0) or 0)

    dif_icms_pis = base_icms - base_pis
    dif_icms_cofins = base_icms - base_cofins

    icms_eq_dif_pis = abs(dif_icms_pis - valor_icms) <= tolerancia if base_icms > 0 and base_pis > 0 and valor_icms > 0 else False
    icms_eq_dif_cofins = abs(dif_icms_cofins - valor_icms) <= tolerancia if base_icms > 0 and base_cofins > 0 and valor_icms > 0 else False

    base_icms_eq_pis = abs(base_icms - base_pis) <= tolerancia if base_icms > 0 and base_pis > 0 else False
    base_icms_eq_cofins = abs(base_icms - base_cofins) <= tolerancia if base_icms > 0 and base_cofins > 0 else False

    join_ok = row.get("_merge") == "both"
    documento_entrada = str(row.get("ind_oper_desc_pis", "")).strip().lower() == "entrada"
    possui_st = valor_icms_st > tolerancia
    situacao_ok = bool(row.get("situacao_ok_pis", True))

    motivo = []
    status = STATUS_SEM_DADOS

    dados_suficientes = base_icms > 0 and valor_icms > 0 and (base_pis > 0 or base_cofins > 0)
    if not dados_suficientes:
        motivo.append("Base de ICMS, valor de ICMS ou bases de PIS/COFINS insuficientes")
        status = STATUS_SEM_DADOS
    else:
        if icms_eq_dif_pis and icms_eq_dif_cofins:
            status = STATUS_EXCLUSAO_IDENTIFICADA
            motivo.append("Base de ICMS menos base de PIS/COFINS equivale ao valor do ICMS")
        elif base_icms_eq_pis and base_icms_eq_cofins:
            status = STATUS_SEM_INDICIO
            motivo.append("Base de ICMS coincide com as bases de PIS e COFINS")
        else:
            status = STATUS_DIVERGENTE
            motivo.append("Diferença entre bases não reproduz o valor do ICMS")

    if possui_st:
        motivo.append("Possui ICMS-ST")
    if documento_entrada:
        motivo.append("Documento de entrada")
    if not situacao_ok:
        motivo.append("Situação do documento não regular")
    if not join_ok:
        motivo.append("Sem correspondência no ICMS/IPI")

    return pd.Series(
        {
            "dif_icms_pis": dif_icms_pis,
            "dif_icms_cofins": dif_icms_cofins,
            "icms_equivale_dif_pis": "Verdadeiro" if icms_eq_dif_pis else "Falso",
            "icms_equivale_dif_cofins": "Verdadeiro" if icms_eq_dif_cofins else "Falso",
            "bases_icms_pis_iguais": "Verdadeiro" if base_icms_eq_pis else "Falso",
            "bases_icms_cofins_iguais": "Verdadeiro" if base_icms_eq_cofins else "Falso",
            "status_analise": status,
            "motivo": " | ".join(dict.fromkeys(motivo)),
            "join_ok": "Sim" if join_ok else "Não",
            "documento_entrada": "Sim" if documento_entrada else "Não",
            "possui_st": "Sim" if possui_st else "Não",
            "valor_item": valor_item,
        }
    )



def run_analysis(icms_df: pd.DataFrame, pis_df: pd.DataFrame, tolerancia: float = 0.01) -> tuple[pd.DataFrame, dict]:
    merged = prepare_join(icms_df, pis_df)

    for col in [
        "bc_icms_pis", "vl_icms_pis", "bc_icms_st_pis", "vl_icms_st_pis",
        "bc_icms_icms", "vl_icms_icms", "bc_icms_st_icms", "vl_icms_st_icms",
        "bc_pis_pis", "bc_cofins_pis", "valor_item_pis",
    ]:
        merged[col] = ensure_numeric(merged, col)

    merged["bc_icms_final"] = 0.0
    merged["origem_base_icms"] = "Sem valor"
    merged["vl_icms_final"] = 0.0
    merged["origem_valor_icms"] = "Sem valor"
    merged["bc_icms_st_final"] = 0.0
    merged["origem_base_icms_st"] = "Sem valor"
    merged["vl_icms_st_final"] = 0.0
    merged["origem_valor_icms_st"] = "Sem valor"

    for idx, row in merged.iterrows():
        merged.at[idx, "bc_icms_final"], merged.at[idx, "origem_base_icms"] = _prefer_origin(row, "bc_icms_icms", "bc_icms_pis")
        merged.at[idx, "vl_icms_final"], merged.at[idx, "origem_valor_icms"] = _prefer_origin(row, "vl_icms_icms", "vl_icms_pis")
        merged.at[idx, "bc_icms_st_final"], merged.at[idx, "origem_base_icms_st"] = _prefer_origin(row, "bc_icms_st_icms", "bc_icms_st_pis")
        merged.at[idx, "vl_icms_st_final"], merged.at[idx, "origem_valor_icms_st"] = _prefer_origin(row, "vl_icms_st_icms", "vl_icms_st_pis")

    calc = merged.apply(classify_row, axis=1, tolerancia=tolerancia)
    result = pd.concat([merged, calc], axis=1)

    for col in [
        "empresa_pis", "cnpj_matriz_pis", "mes_pis", "ano_pis", "chave_pis", "numero_nota_pis",
        "serie_pis", "item_pis", "cod_produto_pis", "descricao_pis", "cfop_pis", "ind_oper_desc_pis",
    ]:
        result[col] = ensure_text(result, col)

    result["cfop_final"] = result["cfop_pis"].where(result["cfop_pis"].ne(""), ensure_text(result, "cfop_icms"))

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
            "cfop_final",
            "ind_oper_desc_pis",
            "valor_item",
            "bc_icms_pis",
            "vl_icms_pis",
            "bc_icms_icms",
            "vl_icms_icms",
            "bc_icms_final",
            "vl_icms_final",
            "bc_icms_st_final",
            "vl_icms_st_final",
            "origem_base_icms",
            "origem_valor_icms",
            "bc_pis_pis",
            "bc_cofins_pis",
            "dif_icms_pis",
            "dif_icms_cofins",
            "icms_equivale_dif_pis",
            "icms_equivale_dif_cofins",
            "bases_icms_pis_iguais",
            "bases_icms_cofins_iguais",
            "status_analise",
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
        "Base de ICMS no PIS",
        "Valor de ICMS no PIS",
        "Base de ICMS no ICMS/IPI",
        "Valor de ICMS no ICMS/IPI",
        "Base de ICMS Final",
        "Valor de ICMS Final",
        "Base de ICMS ST",
        "Valor de ICMS ST",
        "Origem da Base de ICMS",
        "Origem do Valor de ICMS",
        "Base de PIS",
        "Base de COFINS",
        "Diferença Base ICMS x PIS",
        "Diferença Base ICMS x COFINS",
        "ICMS equivale à diferença PIS?",
        "ICMS equivale à diferença COFINS?",
        "Base ICMS = Base PIS?",
        "Base ICMS = Base COFINS?",
        "Status da Análise",
        "Motivo",
        "Possui ST",
        "Cruzou com ICMS/IPI",
        "Documento de Entrada",
    ]

    resumo = {
        "itens_analisados": int(len(report)),
        "exclusao_identificada": int((report["Status da Análise"] == STATUS_EXCLUSAO_IDENTIFICADA).sum()),
        "sem_indicio": int((report["Status da Análise"] == STATUS_SEM_INDICIO).sum()),
        "divergente": int((report["Status da Análise"] == STATUS_DIVERGENTE).sum()),
        "sem_dados": int((report["Status da Análise"] == STATUS_SEM_DADOS).sum()),
        "sem_match": int((report["Cruzou com ICMS/IPI"] == "Não").sum()),
        "com_base_icms_final": int((pd.to_numeric(report["Base de ICMS Final"], errors="coerce").fillna(0) != 0).sum()),
        "com_valor_icms_final": int((pd.to_numeric(report["Valor de ICMS Final"], errors="coerce").fillna(0) != 0).sum()),
    }
    return report, resumo
