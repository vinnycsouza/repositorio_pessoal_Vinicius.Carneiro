from __future__ import annotations

import pandas as pd

from .utils import IND_OPER_MAP, coerce_number, normalize_cnpj, normalize_key


ICMS_ITEM_MAP = {
    "Mês": "mes",
    "Ano": "ano",
    "CNPJ": "cnpj_matriz",
    "Empresa": "empresa",
    "Participante(C100)": "participante",
    "Número da Nota(C100)": "numero_nota",
    "Modelo(C100)": "modelo",
    "Série(C100)": "serie",
    "Chave de Acesso(C100)": "chave",
    "Indicador de Operação(C100)": "ind_oper",
    "C170 - Fixo": "reg_c170",
    "Numeração Sequencial": "item",
    "Código do Produto": "cod_produto",
    "Descrição Complementar": "descricao",
    "Quantidade": "quantidade",
    "Valor Total do Produto": "valor_item",
    "Valor de Desconto": "valor_desconto",
    "CST de ICMS": "cst_icms",
    "CFOP": "cfop",
    "Base de Icms": "bc_icms",
    "Valor de Icms": "vl_icms",
    "Base de Icms ST": "bc_icms_st",
    "Valor de Icms ST": "vl_icms_st",
    "CST de Pis": "cst_pis",
    "Base de Pis": "bc_pis_icms",
    "Valor de Pis": "vl_pis_icms",
    "CST de Cofins": "cst_cofins",
    "Base de Cofins": "bc_cofins_icms",
    "Valor de Cofins": "vl_cofins_icms",
}

PISCOFINS_ITEM_MAP = {
    "Mês": "mes",
    "Ano": "ano",
    "CNPJ": "cnpj_matriz",
    "Empresa": "empresa",
    "CNPJ Estabelecimento(C010)": "cnpj_estabelecimento",
    "Participante(C100)": "participante",
    "Número da Nota(C100)": "numero_nota",
    "Modelo(C100)": "modelo",
    "Série(C100)": "serie",
    "Chave(C100)": "chave",
    "Indicador de Operação(C100)": "ind_oper",
    "Situação(C100)": "situacao",
    "Valor(C100)": "valor_nota",
    "C170 - Fixo": "reg_c170",
    "Numeração Sequencial": "item",
    "Código do Produto": "cod_produto",
    "Descrição Complementar": "descricao",
    "QTD": "quantidade",
    "Valor Total do Produto": "valor_item",
    "Valor de Desconto": "valor_desconto",
    "CST de ICMS": "cst_icms",
    "CFOP": "cfop",
    "Base de Icms": "bc_icms",
    "Valor de Icms": "vl_icms",
    "Base de Icms ST": "bc_icms_st",
    "Valor de Icms ST": "vl_icms_st",
    "CST de Pis": "cst_pis",
    "Base de Pis": "bc_pis",
    "Valor de Pis": "vl_pis",
    "CST de Cofins": "cst_cofins",
    "Base de Cofins": "bc_cofins",
    "Valor de Cofins": "vl_cofins",
}


NUMERIC_COLS = [
    "ano",
    "numero_nota",
    "serie",
    "item",
    "quantidade",
    "valor_item",
    "valor_nota",
    "valor_desconto",
    "bc_icms",
    "vl_icms",
    "bc_icms_st",
    "vl_icms_st",
    "bc_pis",
    "vl_pis",
    "bc_cofins",
    "vl_cofins",
    "bc_pis_icms",
    "vl_pis_icms",
    "bc_cofins_icms",
    "vl_cofins_icms",
]


STATUS_VALIDOS = {"00", "01", "1", "0", 0, 1}



def _rename(df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
    available = {k: v for k, v in col_map.items() if k in df.columns}
    out = df.rename(columns=available).copy()
    for col in set(col_map.values()) - set(out.columns):
        out[col] = None
    return out



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

    for col in ["bc_icms", "vl_icms", "bc_icms_st", "vl_icms_st", "bc_pis", "bc_cofins", "valor_item"]:
        if col not in df.columns:
            df[col] = 0.0

    return df



def normalize_icms_items(df: pd.DataFrame) -> pd.DataFrame:
    out = _rename(df, ICMS_ITEM_MAP)
    out = _post_process(out)
    if "valor_nota" not in out.columns:
        out["valor_nota"] = 0.0
    out["fonte"] = "ICMS/IPI"
    return out



def normalize_piscofins_items(df: pd.DataFrame) -> pd.DataFrame:
    out = _rename(df, PISCOFINS_ITEM_MAP)
    out = _post_process(out)
    out["fonte"] = "PIS/COFINS"
    return out
