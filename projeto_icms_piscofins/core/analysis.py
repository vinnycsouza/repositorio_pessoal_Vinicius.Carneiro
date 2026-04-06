from __future__ import annotations

import pandas as pd


def make_item_key(df: pd.DataFrame) -> pd.Series:
    """
    Monta uma chave de cruzamento em nível de item.
    Prioriza a chave da NF-e; se não existir, usa fallback com empresa/nota/série/item/período.
    """
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


def prepare_join(icms_df: pd.DataFrame, pis_df: pd.DataFrame) -> pd.DataFrame:
    """
    Faz o cruzamento entre os itens de PIS/COFINS e ICMS/IPI.
    """
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


def classify_row(
    row: pd.Series,
    tolerancia: float,
    aliq_pis_padrao: float,
    aliq_cofins_padrao: float,
) -> pd.Series:
    """
    Classifica cada linha quanto ao potencial de recuperação.
    """
    valor_item = float(row.get("valor_item_pis", 0) or 0)
    vl_icms = float(row.get("vl_icms_final", 0) or 0)
    vl_icms_st = float(row.get("vl_icms_st_final", 0) or 0)
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
    cst_sem_credito = (
        cst_pis in {"04", "05", "06", "07", "08", "09"}
        or cst_cofins in {"04", "05", "06", "07", "08", "09"}
    )
    documento_entrada = ind_oper == "0" or str(row.get("ind_oper_desc_pis", "")).strip().lower() == "entrada"
    join_ok = row.get("_merge") == "both"

    motivo = []
    nivel = "Sem oportunidade"

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

    if not join_ok:
        motivo.append("Item não localizado no arquivo ICMS/IPI")
        if nivel == "Sem oportunidade":
            nivel = "Revisão manual"

    if situacao_ok and not has_st and not cst_sem_credito and diferenca_pis > tolerancia and vl_icms > 0:
        if join_ok:
            nivel = "Potencial alto"
            motivo = ["Base de PIS maior que a base esperada sem ICMS (com match no ICMS/IPI)"]
        else:
            nivel = "Potencial moderado"
            motivo = ["Base de PIS maior que a base esperada sem ICMS (sem match no ICMS/IPI)"]

    credito_pis = diferenca_pis * (aliq_pis_padrao / 100.0)
    credito_cofins = diferenca_cofins * (aliq_cofins_padrao / 100.0)

    return pd.Series(
        {
            "base_esperada_sem_icms": base_esperada,
            "diferenca_base_pis": diferenca_pis,
            "diferenca_base_cofins": diferenca_cofins,
            "credito_pis_estimado": credito_pis,
            "credito_cofins_estimado": credito_cofins,
            "credito_total_estimado": credito_pis + credito_cofins,
            "nivel_oportunidade": nivel,
            "motivo": " | ".join(dict.fromkeys([m for m in motivo if m])) if motivo else "Sem indícios materiais",
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
    """
    Executa a análise principal e devolve:
    - report: dataframe final para tela e exportação
    - resumo: indicadores gerais
    """
    merged = prepare_join(icms_df, pis_df)

    def ensure_numeric(df: pd.DataFrame, col: str) -> pd.Series:
        if col not in df.columns:
            return pd.Series(0.0, index=df.index, dtype="float64")
        return pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Guarda valores originais de cada fonte
    merged["bc_icms_pis_orig"] = ensure_numeric(merged, "bc_icms_pis")
    merged["vl_icms_pis_orig"] = ensure_numeric(merged, "vl_icms_pis")
    merged["bc_icms_st_pis_orig"] = ensure_numeric(merged, "bc_icms_st_pis")
    merged["vl_icms_st_pis_orig"] = ensure_numeric(merged, "vl_icms_st_pis")

    merged["bc_icms_icms_orig"] = ensure_numeric(merged, "bc_icms_icms")
    merged["vl_icms_icms_orig"] = ensure_numeric(merged, "vl_icms_icms")
    merged["bc_icms_st_icms_orig"] = ensure_numeric(merged, "bc_icms_st_icms")
    merged["vl_icms_st_icms_orig"] = ensure_numeric(merged, "vl_icms_st_icms")

    # Fallback inteligente: prioriza ICMS/IPI; se não houver, usa PIS/COFINS
    merged["bc_icms_final"] = merged["bc_icms_icms_orig"].where(
        merged["bc_icms_icms_orig"] != 0,
        merged["bc_icms_pis_orig"],
    )
    merged["vl_icms_final"] = merged["vl_icms_icms_orig"].where(
        merged["vl_icms_icms_orig"] != 0,
        merged["vl_icms_pis_orig"],
    )
    merged["bc_icms_st_final"] = merged["bc_icms_st_icms_orig"].where(
        merged["bc_icms_st_icms_orig"] != 0,
        merged["bc_icms_st_pis_orig"],
    )
    merged["vl_icms_st_final"] = merged["vl_icms_st_icms_orig"].where(
        merged["vl_icms_st_icms_orig"] != 0,
        merged["vl_icms_st_pis_orig"],
    )

    # Origem dos valores consolidados
    merged["origem_icms_base"] = "Sem valor"
    merged.loc[merged["bc_icms_pis_orig"] != 0, "origem_icms_base"] = "PIS/COFINS"
    merged.loc[merged["bc_icms_icms_orig"] != 0, "origem_icms_base"] = "ICMS/IPI"

    merged["origem_icms_valor"] = "Sem valor"
    merged.loc[merged["vl_icms_pis_orig"] != 0, "origem_icms_valor"] = "PIS/COFINS"
    merged.loc[merged["vl_icms_icms_orig"] != 0, "origem_icms_valor"] = "ICMS/IPI"

    # Garante colunas base de PIS/COFINS
    merged["bc_pis_pis"] = ensure_numeric(merged, "bc_pis_pis")
    merged["bc_cofins_pis"] = ensure_numeric(merged, "bc_cofins_pis")
    merged["valor_item_pis"] = ensure_numeric(merged, "valor_item_pis")

    calc = merged.apply(
        classify_row,
        axis=1,
        tolerancia=tolerancia,
        aliq_pis_padrao=aliq_pis_padrao,
        aliq_cofins_padrao=aliq_cofins_padrao,
    )
    result = pd.concat([merged, calc], axis=1)

    # Garante que colunas textuais existam
    def ensure_text(colname: str) -> pd.Series:
        if colname not in result.columns:
            return pd.Series("", index=result.index, dtype="object")
        return result[colname].fillna("").astype(str)

    result["empresa_pis"] = ensure_text("empresa_pis")
    result["cnpj_matriz_pis"] = ensure_text("cnpj_matriz_pis")
    result["mes_pis"] = ensure_text("mes_pis")
    result["ano_pis"] = ensure_text("ano_pis")
    result["chave_pis"] = ensure_text("chave_pis")
    result["numero_nota_pis"] = ensure_text("numero_nota_pis")
    result["serie_pis"] = ensure_text("serie_pis")
    result["item_pis"] = ensure_text("item_pis")
    result["cod_produto_pis"] = ensure_text("cod_produto_pis")
    result["descricao_pis"] = ensure_text("descricao_pis")
    result["ind_oper_desc_pis"] = ensure_text("ind_oper_desc_pis")

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
            "bc_icms_pis_orig",
            "vl_icms_pis_orig",
            "bc_icms_icms_orig",
            "vl_icms_icms_orig",
            "bc_icms_final",
            "vl_icms_final",
            "bc_icms_st_final",
            "vl_icms_st_final",
            "origem_icms_base",
            "origem_icms_valor",
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
        "itens_potencial_moderado": int((report["Nível de Oportunidade"] == "Potencial moderado").sum()),
        "itens_revisao_manual": int((report["Nível de Oportunidade"] == "Revisão manual").sum()),
        "itens_sem_match": int((report["Cruzou com ICMS/IPI"] == "Não").sum()),
        "credito_total_estimado": float(pd.to_numeric(report["Crédito Total Estimado"], errors="coerce").fillna(0).sum()),
        "itens_com_base_icms_final": int((pd.to_numeric(report["Base de ICMS Final"], errors="coerce").fillna(0) != 0).sum()),
        "itens_com_valor_icms_final": int((pd.to_numeric(report["Valor de ICMS Final"], errors="coerce").fillna(0) != 0).sum()),
    }

    return report, resumo