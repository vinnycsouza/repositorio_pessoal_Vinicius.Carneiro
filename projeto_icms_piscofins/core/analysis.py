from __future__ import annotations

import numpy as np
import pandas as pd


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


def ensure_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0.0, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def ensure_text(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype="object")
    return df[col].fillna("").astype(str).str.strip()


def run_analysis(
    icms_df: pd.DataFrame,
    pis_df: pd.DataFrame,
    tolerancia: float = 0.01,
    aliq_pis: float = 1.65,
    aliq_cofins: float = 7.60,
) -> tuple[pd.DataFrame, dict]:
    merged = prepare_join(icms_df, pis_df)

    # Numéricos
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
    merged["bc_icms_final"] = np.where(
        merged["bc_icms_icms_orig"] != 0,
        merged["bc_icms_icms_orig"],
        merged["bc_icms_pis_orig"],
    )

    merged["vl_icms_final"] = np.where(
        merged["vl_icms_icms_orig"] != 0,
        merged["vl_icms_icms_orig"],
        merged["vl_icms_pis_orig"],
    )

    merged["bc_icms_st_final"] = np.where(
        merged["bc_icms_st_icms_orig"] != 0,
        merged["bc_icms_st_icms_orig"],
        merged["bc_icms_st_pis_orig"],
    )

    merged["vl_icms_st_final"] = np.where(
        merged["vl_icms_st_icms_orig"] != 0,
        merged["vl_icms_st_icms_orig"],
        merged["vl_icms_st_pis_orig"],
    )

    # Origem
    merged["origem_icms_base"] = np.where(
        merged["bc_icms_icms_orig"] != 0,
        "ICMS/IPI",
        np.where(merged["bc_icms_pis_orig"] != 0, "PIS/COFINS", "Sem valor"),
    )

    merged["origem_icms_valor"] = np.where(
        merged["vl_icms_icms_orig"] != 0,
        "ICMS/IPI",
        np.where(merged["vl_icms_pis_orig"] != 0, "PIS/COFINS", "Sem valor"),
    )

    # Textuais
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
    merged["ind_oper_pis_txt"] = ensure_text(merged, "ind_oper_pis")
    merged["ind_oper_icms_txt"] = ensure_text(merged, "ind_oper_icms")

    merged["cfop"] = ensure_text(merged, "cfop_pis")
    merged.loc[merged["cfop"] == "", "cfop"] = ensure_text(merged, "cfop_icms")

    # Flags e diferenças
    merged["dif_icms_pis"] = merged["bc_icms_final"] - merged["bc_pis_pis"]
    merged["dif_icms_cofins"] = merged["bc_icms_final"] - merged["bc_cofins_pis"]

    cond_pis_campos = (merged["bc_icms_final"] > 0) & (merged["bc_pis_pis"] > 0) & (merged["vl_icms_final"] > 0)
    cond_cofins_campos = (merged["bc_icms_final"] > 0) & (merged["bc_cofins_pis"] > 0) & (merged["vl_icms_final"] > 0)

    merged["pis_excluido"] = cond_pis_campos & ((merged["dif_icms_pis"] - merged["vl_icms_final"]).abs() <= tolerancia)
    merged["cofins_excluido"] = cond_cofins_campos & ((merged["dif_icms_cofins"] - merged["vl_icms_final"]).abs() <= tolerancia)

    merged["pis_excluido_txt"] = np.where(merged["pis_excluido"], "Sim", "Não")
    merged["cofins_excluido_txt"] = np.where(merged["cofins_excluido"], "Sim", "Não")

    bases_iguais_pis = (merged["bc_icms_final"] > 0) & (merged["bc_pis_pis"] > 0) & ((merged["bc_icms_final"] - merged["bc_pis_pis"]).abs() <= tolerancia)
    bases_iguais_cofins = (merged["bc_icms_final"] > 0) & (merged["bc_cofins_pis"] > 0) & ((merged["bc_icms_final"] - merged["bc_cofins_pis"]).abs() <= tolerancia)

    merged["possui_st"] = np.where(merged["vl_icms_st_final"] > tolerancia, "Sim", "Não")
    merged["join_ok"] = np.where(merged["_merge"] == "both", "Sim", "Não")

    documento_entrada_bool = (
        (merged["ind_oper_pis_txt"] == "0")
        | (merged["ind_oper_icms_txt"] == "0")
        | (merged["ind_oper_desc_pis"].str.lower() == "entrada")
    )
    merged["documento_entrada"] = np.where(documento_entrada_bool, "Sim", "Não")

    situacao_ok = merged["situacao_ok_pis"] if "situacao_ok_pis" in merged.columns else pd.Series(True, index=merged.index)

    sem_dados = (merged["bc_icms_final"] <= 0) | (merged["vl_icms_final"] <= 0) | ((merged["bc_pis_pis"] <= 0) & (merged["bc_cofins_pis"] <= 0))
    exclusao = merged["pis_excluido"] & merged["cofins_excluido"]
    sem_indicio = bases_iguais_pis & bases_iguais_cofins & (~sem_dados) & (~exclusao)

    merged["status_analise"] = np.select(
        [
            sem_dados,
            exclusao,
            sem_indicio,
        ],
        [
            "Sem dados suficientes",
            "Exclusão identificada",
            "Sem indício de exclusão",
        ],
        default="Divergente / Revisar",
    )

    # Motivo
    motivos = []

    for idx in merged.index:
        m = []
        if not bool(situacao_ok.loc[idx]):
            m.append("Situação do documento não é regular")
        if merged.at[idx, "possui_st"] == "Sim":
            m.append("Possui ICMS-ST")
        if merged.at[idx, "documento_entrada"] == "Sim":
            m.append("Documento de entrada")
        if merged.at[idx, "join_ok"] == "Não":
            m.append("Item não localizado no arquivo ICMS/IPI")

        status = merged.at[idx, "status_analise"]
        if status == "Sem dados suficientes" and not m:
            m.append("Campos essenciais ausentes para comparação")
        elif status == "Exclusão identificada" and not m:
            m.append("A diferença entre Base ICMS e Bases PIS/COFINS equivale ao Valor de ICMS")
        elif status == "Sem indício de exclusão" and not m:
            m.append("Bases de ICMS, PIS e COFINS estão equivalentes")
        elif status == "Divergente / Revisar" and not m:
            m.append("Diferenças entre as bases não equivalem ao Valor de ICMS")

        motivos.append(" | ".join(dict.fromkeys([x for x in m if x])))

    merged["motivo"] = motivos

    # Crédito: só quando NÃO houver indício de exclusão
    base_credito_pis = np.where(merged["status_analise"] == "Sem indício de exclusão", np.maximum(merged["dif_icms_pis"], 0), 0)
    base_credito_cofins = np.where(merged["status_analise"] == "Sem indício de exclusão", np.maximum(merged["dif_icms_cofins"], 0), 0)

    merged["credito_pis_estimado"] = base_credito_pis * (aliq_pis / 100.0)
    merged["credito_cofins_estimado"] = base_credito_cofins * (aliq_cofins / 100.0)
    merged["credito_total_estimado"] = merged["credito_pis_estimado"] + merged["credito_cofins_estimado"]

    report = merged[
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