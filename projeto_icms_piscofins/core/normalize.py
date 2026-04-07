from __future__ import annotations

import re
import unicodedata
import pandas as pd


def _slug(text: str) -> str:
    text = str(text or "").strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text)
    return text


def _rename_flex(df: pd.DataFrame, aliases: dict[str, list[str]]) -> pd.DataFrame:
    mapping = {}
    original_cols = list(df.columns)
    slug_cols = {_slug(c): c for c in original_cols}

    for target, options in aliases.items():
        for opt in options:
            s = _slug(opt)
            if s in slug_cols:
                mapping[slug_cols[s]] = target
                break

    return df.rename(columns=mapping)


def _to_num_br(series: pd.Series) -> pd.Series:
    if series.dtype.kind in "biufc":
        return pd.to_numeric(series, errors="coerce").fillna(0.0)

    s = series.fillna("").astype(str).str.strip()
    s = s.str.replace(".", "", regex=False)
    s = s.str.replace(",", ".", regex=False)
    s = s.replace({"": None, "nan": None, "None": None})
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


COMMON_ALIASES = {
    "mes": ["Mês", "Mes"],
    "ano": ["Ano"],
    "cnpj_matriz": ["CNPJ", "CNPJ Estabelecimento(C010)", "CNPJ Estabelecimento", "CNPJ/CEI"],
    "empresa": ["Empresa"],
    "participante": ["Participante(C100)", "Participante"],
    "numero_nota": ["Número da Nota(C100)", "Numero da Nota(C100)", "Número da Nota", "Numero da Nota"],
    "modelo": ["Modelo(C100)", "Modelo"],
    "serie": ["Série(C100)", "Serie(C100)", "Série", "Serie"],
    "chave": ["Chave de Acesso(C100)", "Chave(C100)", "Chave de Acesso", "Chave"],
    "ind_oper": ["Indicador de Operação(C100)", "Indicador de Operação", "Indicador Operação"],
    "situacao": ["Situação(C100)", "Situacao(C100)", "Situação", "Situacao"],
    "item": ["Numeração Sequencial", "Item"],
    "cod_produto": ["Código do Produto", "Codigo do Produto", "COD_ITEM", "Cod Item"],
    "descricao": ["Descrição Complementar", "Descricao Complementar", "Descrição", "Descricao"],
    "valor_item": ["Valor Total do Produto", "Valor do Item", "VL_ITEM"],
    "cst_icms": ["CST de ICMS", "CST ICMS"],
    "cfop": ["CFOP"],
    "bc_icms": ["Base de Icms", "Base de ICMS", "BC ICMS", "Base ICMS"],
    "aliq_icms": ["Alíquota de Icms", "Aliquota de Icms", "Alíquota ICMS", "Aliquota ICMS"],
    "vl_icms": ["Valor de Icms", "Valor de ICMS", "VL ICMS"],
    "bc_icms_st": ["Base de Icms ST", "Base de ICMS ST", "BC ICMS ST"],
    "aliq_icms_st": ["Alíquota de Icms ST", "Aliquota de Icms ST"],
    "vl_icms_st": ["Valor de Icms ST", "Valor de ICMS ST"],
    "cst_pis": ["CST de Pis", "CST de PIS", "CST PIS"],
    "bc_pis": ["Base de Pis", "Base de PIS", "BC PIS"],
    "vl_pis": ["Valor de Pis", "Valor de PIS"],
    "cst_cofins": ["CST de Cofins", "CST de COFINS", "CST COFINS"],
    "bc_cofins": ["Base de Cofins", "Base de COFINS", "BC COFINS"],
    "vl_cofins": ["Valor de Cofins", "Valor de COFINS"],
}


def _base_normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = _rename_flex(df.copy(), COMMON_ALIASES)

    if "ind_oper" in df.columns and "ind_oper_desc" not in df.columns:
        s = df["ind_oper"].fillna("").astype(str).str.strip()
        df["ind_oper_desc"] = s.map({"0": "Entrada", "1": "Saída", "1.0": "Saída", "0.0": "Entrada"}).fillna("")

    if "situacao" in df.columns and "situacao_ok" not in df.columns:
        s = df["situacao"].fillna("").astype(str).str.strip()
        df["situacao_ok"] = ~s.isin({"02", "03", "04", "05", "2", "3", "4", "5"})

    numeric_cols = [
        "valor_item", "bc_icms", "aliq_icms", "vl_icms", "bc_icms_st", "aliq_icms_st", "vl_icms_st",
        "bc_pis", "vl_pis", "bc_cofins", "vl_cofins", "numero_nota", "item", "ano",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = _to_num_br(df[col])

    text_cols = [
        "mes", "cnpj_matriz", "empresa", "participante", "modelo", "serie", "chave", "cfop",
        "descricao", "cod_produto", "cst_icms", "cst_pis", "cst_cofins", "ind_oper_desc", "ind_oper",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def normalize_icms_items(df: pd.DataFrame) -> pd.DataFrame:
    df = _base_normalize(df)
    wanted = [
        "mes", "ano", "cnpj_matriz", "empresa", "numero_nota", "serie", "chave",
        "item", "cod_produto", "descricao", "cfop", "ind_oper", "ind_oper_desc",
        "valor_item", "bc_icms", "vl_icms", "bc_icms_st", "vl_icms_st", "situacao_ok",
    ]
    for col in wanted:
        if col not in df.columns:
            if col in {"valor_item", "bc_icms", "vl_icms", "bc_icms_st", "vl_icms_st", "numero_nota", "item", "ano"}:
                df[col] = 0.0
            elif col == "situacao_ok":
                df[col] = True
            else:
                df[col] = ""
    return df[wanted].copy()


def normalize_piscofins_items(df: pd.DataFrame) -> pd.DataFrame:
    df = _base_normalize(df)
    wanted = [
        "mes", "ano", "cnpj_matriz", "empresa", "numero_nota", "serie", "chave",
        "item", "cod_produto", "descricao", "cfop", "ind_oper", "ind_oper_desc",
        "valor_item", "bc_icms", "vl_icms", "bc_icms_st", "vl_icms_st",
        "bc_pis", "bc_cofins", "cst_pis", "cst_cofins", "situacao_ok",
    ]
    for col in wanted:
        if col not in df.columns:
            if col in {"valor_item", "bc_icms", "vl_icms", "bc_icms_st", "vl_icms_st", "bc_pis", "bc_cofins", "numero_nota", "item", "ano"}:
                df[col] = 0.0
            elif col == "situacao_ok":
                df[col] = True
            else:
                df[col] = ""
    return df[wanted].copy()