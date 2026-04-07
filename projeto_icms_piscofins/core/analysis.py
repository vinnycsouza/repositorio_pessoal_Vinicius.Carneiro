from __future__ import annotations

import pandas as pd


def make_item_key(df: pd.DataFrame) -> pd.Series:
    """
    Monta chave de cruzamento em nível de item.
    Prioriza a chave da NF-e; se não houver, usa fallback.
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
    Cruza itens do SPED ICMS/IPI com itens do SPED PIS/COFINS.
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


def ensure_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0.0, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def ensure_text(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype="object")
    return df[col].fillna("").astype(str).str.strip()


def classify_row(row: pd.Series, tolerancia: float) -> pd.Series:
    """
    Classificação principal:
    - Exclusão identificada
    - Sem indício de exclusão
    - Divergente / Revisar
    - Sem dados suficientes
    """
    base_icms = float(row.get("bc_icms_final", 0) or 0)
    valor_icms = float(row.get("vl_icms_final", 0) or 0)
    base_pis = float(row.get("bc_pis_pis", 0) or 0)
    base_cofins = float(row.get("bc_cofins_pis", 0) or 0)
    valor_icms_st = float(row.get("vl_icms_st_final", 0) or 0)

    ind_oper = str(row.get("ind_oper_pis", row.get("ind_oper_icms", "")) or "").strip()
    ind_oper_desc = str(row.get("ind_oper_desc_pis", "") or "").strip().lower()
    situacao_ok = bool(row.get("situacao_ok_pis", True))
    join_ok_bool = row.get("_merge") == "both"

    dif_icms_pis = base_icms - base_pis
    dif_icms_cofins = base_icms - base_cofins

    pis_excluido = (
        abs(dif_icms_pis - valor_icms) <= tolerancia
        if base_icms > 0 and base_pis > 0 and valor_icms > 0
        else False
    )
    cofins_excluido = (
        abs(dif_icms_cofins - valor_icms) <= tolerancia
        if base_icms > 0 and base_cofins > 0 and valor_icms > 0
        else False
    )

    bases_iguais_pis = abs(base_icms - base_pis) <= tolerancia if base_icms > 0 and base_pis > 0 else False
    bases_iguais_cofins = abs(base_icms - base_cofins) <= tolerancia if base_icms > 0 and base_cofins > 0 else False

    possui_st = valor_icms_st > tolerancia
    documento_entrada = ind_oper == "0" or ind_oper_desc == "entrada"

    motivos = []

    if not situacao_ok:
        motivos.append("Situação do documento não é regular")

    if possui_st:
        motivos.append("Possui ICMS-ST")

    if documento_entrada:
        motivos.append("Documento de entrada")

    if not join_ok_bool:
        motivos.append("Item não localizado no arquivo ICMS/IPI")

    if base_icms <= 0 or valor_icms <= 0 or (base_pis <= 0 and base_cofins <= 0):
        status = "Sem dados suficientes"
        if not motivos:
            motivos.append("Campos essenciais ausentes para comparação")
    elif pis_excluido and cofins_excluido:
        status = "Exclusão identificada"
        if not motivos:
            motivos.append("A diferença entre Base ICMS e Bases PIS/COFINS equivale ao Valor de ICMS")
    elif bases_iguais_pis and bases_iguais_cofins:
        status = "Sem indício de exclusão"
        if not motivos:
            motivos.append("Bases de ICMS, PIS e COFINS estão equivalentes")
    else:
        status = "Divergente / Revisar"
        if not motivos:
            motivos.append("Diferenças entre as bases não equivalem ao Valor de ICMS")

    return pd.Series(
        {
            "dif_icms_pis": dif_icms_pis,
            "dif_icms_cofins": dif_icms_cofins,
            "pis_excluido": pis_excluido,
            "cofins_excluido": cofins_excluido,
            "pis_excluido_txt": "Sim" if pis_excluido else "Não",
            "cofins_excluido_txt": "Sim" if cofins_excluido else "Não",
            "status_analise": status,
            "motivo": " | ".join(dict.fromkeys([m for m in motivos if m])),
            "possui_st": "Sim" if possui_st else "Não",
            "join_ok": "Sim" if join_ok_bool else "Não",
            "documento_entrada": "Sim" if documento_entrada else "Não",
        }
    )


def calculate_credit_row(row: pd.Series, aliq_pis: float, aliq_cofins: float) -> pd.Series:
    """
    Crédito só é calculado quando NÃO houver indício de exclusão.
    """
    status = str(row.get("status_analise", "") or "").strip()

    if status != "Sem indício de exclusão":
        return pd.Series(
            {
                "credito_pis_estimado": 0.0,
                "credito_cofins_estimado": 0.0,
                "credito_total_estimado": 0.0,
            }
        )

    dif_pis = max(float(row.get("dif_icms_pis", 0) or 0), 0.0)
    dif_cofins = max(float(row.get("dif_icms_cofins", 0) or 0), 0.0)

    credito_pis = dif_pis * (aliq_pis / 100.0)
    credito_cofins = dif_cofins * (aliq_cofins / 100.0)

    return pd.Series(
        {
            "credito_pis_estimado": credito_pis,
            "credito_cofins_estimado": credito_cofins,
            "credito_total_estimado": credito_pis + credito_cofins,
        }
    )


def run_analysis(
    icms_df: pd.DataFrame,
    pis_df: pd.DataFrame,
    tolerancia: float = 0.01,
    aliq_pis: float = 1.65,
    aliq_cofins: float = 7.60,
) -> tuple[pd.DataFrame, dict]:
    """
    Executa a análise principal e devolve:
    - report: dataframe final para tela/exportação
    - resumo: indicadores gerais
    """
    merged = prepare_join(icms_df, pis_df)

    # Campos numéricos
    merged["valor_item_pis"] = ensure_numeric(merged, "valor_item_pis")

    merged["bc_icms_pis_orig"] = ensure_numeric(merged, "bc_icms_pis")
    merged["vl_icms_pis_orig"] = ensure_numeric(merged, "vl_icms_pis")
    merged["bc_icms_st_pis_orig"] = ensure_numeric(merged, "bc_icms_st_pis")
    merged["vl_icms_st_pis_orig"] = ensure_numeric(merged, "vl_icms_st_pis")

    merged["bc_icms_icms_orig"] = ensure_numeric(merged, "bc_icms_icms")
    merged["vl_icms_icms_orig"] = ensure_numeric(merged, "vl_icms_icms")
    merged["bc_icms_st_icms_orig"] = ensure_numeric(merged, "bc_icms_st_icms")
    merged["vl_icms_st_icms_orig"] = ensure_numeric(merged, "vl_icms_st_icms")

    merged["bc_pis_pis"] = ensure_numeric(merged, "bc_pis_pis")
    merged["bc_cofins_pis"] = ensure_numeric(merged, "bc_cofins_pis")

    # Fallback: prioriza ICMS/IPI
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

    # Origem dos valores finais
    merged["origem_icms_base"] = "Sem valor"
    merged.loc[merged["bc_icms_pis_orig"] != 0, "origem_icms_base"] = "PIS/COFINS"
    merged.loc[merged["bc_icms_icms_orig"] != 0, "origem_icms_base"] = "ICMS/IPI"

    merged["origem_icms_valor"] = "Sem valor"
    merged.loc[merged["vl_icms_pis_orig"] != 0, "origem_icms_valor"] = "PIS/COFINS"
    merged.loc[merged["vl_icms_icms_orig"] != 0, "origem_icms_valor"] = "ICMS/IPI"

    # Campos textuais
    merged["empresa_pis"] = ensure_text(merged, "empresa_pis")
    merged["cnpj_matriz_pis"] = ensure_text(merged, "cnpj_matriz_pis")
    merged["mes_pis"] = ensure_text(merged, "mes_pis")
    merged["ano_pis"] = ensure_text(merged, "ano_pis")
    merged["chave_pis"] = ensure_text(merged, "chave_pis")
    merged["numero_nota_pis"] = ensure_text(merged, "numero_nota_pis")
    merged["serie_pis"] = ensure_text(merged, "serie_pis")
    merged["item_pis"] = ensure_text(merged, "item_pis")
    merged["cod_produto_pis"] = ensure_text(merged, "cod_produto_pis")
    merged["descricao_pis"] = ensure_text(merged, "descricao_pis")
    merged["ind_oper_desc_pis"] = ensure_text(merged, "ind_oper_desc_pis")
    merged["cfop"] = ensure_text(merged, "cfop_pis")
    merged.loc[merged["cfop"] == "", "cfop"] = ensure_text(merged, "cfop_icms")

    # Classificação
    calc = merged.apply(classify_row, axis=1, tolerancia=tolerancia)
    result = pd.concat([merged, calc], axis=1)

    # Crédito condicionado ao status
    creditos = result.apply(calculate_credit_row, axis=1, aliq_pis=aliq_pis, aliq_cofins=aliq_cofins)
    result = pd.concat([result, creditos], axis=1)

    # Relatório final
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
            "dif_icms_pis",
            "dif_icms_cofins",
            "pis_excluido_txt",
            "cofins_excluido_txt",
            "status_analise",
            "motivo",
            "possui_st",
            "join_ok",
            "documento_entrada",
            "credito_pis_estimado",
            "credito_cofins_estimado",
            "credito_total_estimado",
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
        "Diferença ICMS x PIS",
        "Diferença ICMS x COFINS",
        "Diferença bate com ICMS? PIS",
        "Diferença bate com ICMS? COFINS",
        "Status da Análise",
        "Motivo",
        "Possui ST",
        "Cruzou com ICMS/IPI",
        "Documento de Entrada",
        "Crédito PIS Estimado",
        "Crédito COFINS Estimado",
        "Crédito Total Estimado",
    ]

    resumo = {
        "itens_analisados": int(len(report)),
        "itens_exclusao_identificada": int((report["Status da Análise"] == "Exclusão identificada").sum()),
        "itens_sem_indicio": int((report["Status da Análise"] == "Sem indício de exclusão").sum()),
        "itens_divergente_revisar": int((report["Status da Análise"] == "Divergente / Revisar").sum()),
        "itens_sem_dados": int((report["Status da Análise"] == "Sem dados suficientes").sum()),
        "itens_com_base_icms_final": int((pd.to_numeric(report["Base de ICMS Final"], errors="coerce").fillna(0) != 0).sum()),
        "itens_com_valor_icms_final": int((pd.to_numeric(report["Valor de ICMS Final"], errors="coerce").fillna(0) != 0).sum()),
        "itens_com_base_pis": int((pd.to_numeric(report["Base de PIS Informada"], errors="coerce").fillna(0) != 0).sum()),
        "itens_com_base_cofins": int((pd.to_numeric(report["Base de COFINS Informada"], errors="coerce").fillna(0) != 0).sum()),
        "itens_sem_match": int((report["Cruzou com ICMS/IPI"] == "Não").sum()),
        "credito_total_estimado": float(pd.to_numeric(report["Crédito Total Estimado"], errors="coerce").fillna(0).sum()),
    }

    return report, resumo