from __future__ import annotations

import pandas as pd

from .utils import IND_OPER_MAP, coerce_number, normalize_cnpj, normalize_key, normalize_text

COMMON_ALIASES = {
    "mes": ["mes"],
    "ano": ["ano"],
    "cnpj_matriz": ["cnpj"],
    "empresa": ["empresa"],
    "cnpj_estabelecimento": ["cnpj estabelecimento(c010)", "cnpj estabelecimento", "cnpj estabelecimento c010"],
    "participante": ["participante(c100)", "participante"],
    "numero_nota": ["numero da nota(c100)", "número da nota(c100)", "numero da nota", "número da nota"],
    "modelo": ["modelo(c100)", "modelo"],
    "serie": ["serie(c100)", "série(c100)", "serie", "série"],
    "chave": ["chave(c100)", "chave de acesso(c100)", "chave de acesso", "chave"],
    "ind_oper": ["indicador de operacao(c100)", "indicador de operação(c100)", "indicador de operacao", "indicador de operação"],
    "ind_emissao": ["indicador de emissao(c100)", "indicador de emissão(c100)"],
    "situacao": ["situacao(c100)", "situação(c100)", "situacao", "situação"],
    "valor_nota": ["valor(c100)", "valor da nota(c100)", "valor da nota", "valor"],
    "reg_c170": ["c170 - fixo", "c170"],
    "item": ["numeracao sequencial", "numeração sequencial", "item"],
    "cod_produto": ["codigo do produto", "código do produto"],
    "descricao": ["descricao complementar", "descrição complementar", "descricao", "descrição"],
    "quantidade": ["quantidade", "qtd"],
    "unidade": ["unidade de medida", "unidade"],
    "valor_item": ["valor total do produto", "valor do item", "vl item"],
    "valor_desconto": ["valor de desconto", "desconto"],
    "mov_fisica": ["movimentacao fisica", "movimentação física"],
    "cst_icms": ["cst de icms", "cst icms"],
    "cfop": ["cfop"],
    "natureza_operacao": ["natureza de operacao", "natureza de operação"],
    "bc_icms": ["base de icms", "base de icms ", "bc icms"],
    "aliq_icms": ["aliquota de icms", "alíquota de icms"],
    "vl_icms": ["valor de icms", "vl icms"],
    "bc_icms_st": ["base de icms st", "bc icms st"],
    "aliq_icms_st": ["aliquota de icms st", "alíquota de icms st"],
    "vl_icms_st": ["valor de icms st", "vl icms st"],
    "ind_apur_ipi": ["indicador de apuracao de ipi", "indicador de apuração de ipi"],
    "cst_ipi": ["cst de ipi", "cst ipi"],
    "cod_enq_ipi": ["codigo enquadramento ipi", "código enquadramento ipi"],
    "bc_ipi": ["base de ipi", "bc ipi"],
    "aliq_ipi": ["aliquota de ipi", "alíquota de ipi"],
    "vl_ipi": ["valor de ipi", "vl ipi"],
    "cst_pis": ["cst de pis", "cst pis"],
    "bc_pis": ["base de pis", "bc pis"],
    "aliq_pis": ["aliquota de pis", "alíquota de pis"],
    "bc_pis_qtd": ["base de pis - qtde", "base de pis qtde"],
    "aliq_pis_qtd": ["aliquota de pis qtde", "alíquota de pis qtde"],
    "vl_pis": ["valor de pis", "vl pis"],
    "cst_cofins": ["cst de cofins", "cst cofins"],
    "bc_cofins": ["base de cofins", "bc cofins"],
    "aliq_cofins": ["aliquota de cofins", "alíquota de cofins"],
    "bc_cofins_qtd": ["base de cofins - qtde", "base de cofins qtde"],
    "aliq_cofins_qtd": ["aliquota de cofins qtde", "alíquota de cofins qtde"],
    "vl_cofins": ["valor de cofins", "vl cofins"],
    "conta_contabil": ["conta contabil", "conta contábil"],
}

NUMERIC_COLS = [
    "ano",
    "numero_nota",
    "item",
    "quantidade",
    "valor_item",
    "valor_nota",
    "valor_desconto",
    "bc_icms",
    "aliq_icms",
    "vl_icms",
    "bc_icms_st",
    "aliq_icms_st",
    "vl_icms_st",
    "bc_pis",
    "aliq_pis",
    "vl_pis",
    "bc_cofins",
    "aliq_cofins",
    "vl_cofins",
]

STATUS_VALIDOS = {"00", "01", "1", "0", 0, 1}


def _build_rename_map(df: pd.DataFrame) -> dict[str, str]:
    rename_map: dict[str, str] = {}
    normalized_lookup = {normalize_text(col): col for col in df.columns}
    for canonical, aliases in COMMON_ALIASES.items():
        for alias in aliases:
            alias_norm = normalize_text(alias)
            if alias_norm in normalized_lookup:
                rename_map[normalized_lookup[alias_norm]] = canonical
                break
    return rename_map


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df


def _post_process(df: pd.DataFrame) -> pd.DataFrame:
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = coerce_number(df[col])

    if "cnpj_matriz" in df.columns:
        df["cnpj_matriz"] = df["cnpj_matriz"].apply(normalize_cnpj)
    if "cnpj_estabelecimento" in df.columns:
        df["cnpj_estabelecimento"] = df["cnpj_estabelecimento"].apply(normalize_cnpj)
    if "chave" in df.columns:
        df["chave"] = df["chave"].apply(normalize_key)
    if "serie" in df.columns:
        df["serie"] = df["serie"].astype(str).str.strip().replace({"nan": "", "None": ""})
    if "numero_nota" in df.columns:
        df["numero_nota"] = pd.to_numeric(df["numero_nota"], errors="coerce").fillna(0).astype(int)
    if "item" in df.columns:
        df["item"] = pd.to_numeric(df["item"], errors="coerce").fillna(0).astype(int)
    if "ind_oper" in df.columns:
        df["ind_oper_desc"] = df["ind_oper"].map(IND_OPER_MAP).fillna(df["ind_oper"].astype(str))
    else:
        df["ind_oper_desc"] = ""

    if "situacao" in df.columns:
        df["situacao_ok"] = df["situacao"].astype(str).str.strip().isin({str(v) for v in STATUS_VALIDOS})
    else:
        df["situacao_ok"] = True
    return df


def _normalize_generic_items(df: pd.DataFrame, fonte: str) -> pd.DataFrame:
    rename_map = _build_rename_map(df)
    out = df.rename(columns=rename_map).copy()
    out = _ensure_columns(out, list(COMMON_ALIASES.keys()))
    out = _post_process(out)
    out["fonte"] = fonte
    return out


def normalize_icms_items(df: pd.DataFrame) -> pd.DataFrame:
    return _normalize_generic_items(df, "ICMS/IPI")


def normalize_piscofins_items(df: pd.DataFrame) -> pd.DataFrame:
    return _normalize_generic_items(df, "PIS/COFINS")
