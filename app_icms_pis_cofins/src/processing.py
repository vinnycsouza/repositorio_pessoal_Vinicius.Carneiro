import pandas as pd
import numpy as np
from .utils import normalize_columns, find_col, to_number, normalize_key, competence_from_date


def load_sheet(xls: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(xls, sheet_name=sheet_name, dtype=object)
    return normalize_columns(df)


def prepare_icms_c190(c100: pd.DataFrame, c190: pd.DataFrame) -> pd.DataFrame:
    c100 = normalize_columns(c100)
    c190 = normalize_columns(c190)

    c100_chave = find_col(c100, ["CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF"], required=True)
    c100_dt = find_col(c100, ["DT_DOC", "DATA", "DATA_DOC", "DT_E_S"], required=False)
    c100_sit = find_col(c100, ["COD_SIT", "SITUACAO"], required=False)

    c190_chave = find_col(c190, ["CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF"], required=True)
    c190_cfop = find_col(c190, ["CFOP"], required=False)
    c190_cst = find_col(c190, ["CST_ICMS", "CST"], required=False)
    c190_vl_opr = find_col(c190, ["VL_OPR", "VALOR_OPERACAO", "VL_OPERACAO"], required=True)
    c190_vl_bc_icms = find_col(c190, ["VL_BC_ICMS", "BASE_ICMS", "BC_ICMS"], required=True)
    c190_vl_icms = find_col(c190, ["VL_ICMS", "ICMS"], required=True)

    out = pd.DataFrame()
    out["CHAVE"] = normalize_key(c190[c190_chave])
    out["CFOP"] = c190[c190_cfop].astype(str).str.strip() if c190_cfop else ""
    out["CST_ICMS"] = c190[c190_cst].astype(str).str.strip() if c190_cst else ""
    out["VL_OPR_ICMS"] = to_number(c190[c190_vl_opr])
    out["VL_BC_ICMS"] = to_number(c190[c190_vl_bc_icms])
    out["VL_ICMS"] = to_number(c190[c190_vl_icms])

    c100_aux = pd.DataFrame()
    c100_aux["CHAVE"] = normalize_key(c100[c100_chave])
    c100_aux["COMPETENCIA"] = competence_from_date(c100[c100_dt]) if c100_dt else "SEM_DATA"
    c100_aux["COD_SIT"] = c100[c100_sit].astype(str).str.strip() if c100_sit else ""
    c100_aux = c100_aux.drop_duplicates(subset=["CHAVE"])

    out = out.merge(c100_aux, on="CHAVE", how="left")
    out["COMPETENCIA"] = out["COMPETENCIA"].fillna("SEM_DATA")
    return out


def consolidate_icms_by_key(icms: pd.DataFrame) -> pd.DataFrame:
    grouped = icms.groupby(["CHAVE", "COMPETENCIA"], dropna=False).agg(
        VL_OPR_ICMS=("VL_OPR_ICMS", "sum"),
        VL_BC_ICMS=("VL_BC_ICMS", "sum"),
        VL_ICMS=("VL_ICMS", "sum"),
        CFOP_LISTA=("CFOP", lambda x: ", ".join(sorted(set([str(v) for v in x if str(v) != "nan"])))) ,
        CST_ICMS_LISTA=("CST_ICMS", lambda x: ", ".join(sorted(set([str(v) for v in x if str(v) != "nan"]))))
    ).reset_index()
    grouped["BASE_ESPERADA_SEM_ICMS"] = grouped["VL_OPR_ICMS"] - grouped["VL_ICMS"]
    return grouped


def prepare_pis_cofins(df: pd.DataFrame, registro: str) -> pd.DataFrame:
    df = normalize_columns(df)
    chave = find_col(df, ["CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF"], required=True)
    cfop = find_col(df, ["CFOP"], required=False)
    cst_pis = find_col(df, ["CST_PIS", "CST"], required=False)
    num_item = find_col(df, ["NUM_ITEM", "ITEM", "N_ITEM"], required=False)
    vl_item = find_col(df, ["VL_ITEM", "VL_OPR", "VALOR_OPERACAO", "VL_OPERACAO"], required=True)
    bc_pis = find_col(df, ["VL_BC_PIS", "BC_PIS", "BASE_PIS"], required=True)
    bc_cofins = find_col(df, ["VL_BC_COFINS", "BC_COFINS", "BASE_COFINS"], required=True)

    out = pd.DataFrame()
    out["REGISTRO"] = registro
    out["CHAVE"] = normalize_key(df[chave])
    out["NUM_ITEM"] = df[num_item].astype(str).str.strip() if num_item else ""
    out["CFOP_PISCOFINS"] = df[cfop].astype(str).str.strip() if cfop else ""
    out["CST_PIS"] = df[cst_pis].astype(str).str.strip() if cst_pis else ""
    out["VL_OPERACAO_PISCOFINS"] = to_number(df[vl_item])
    out["VL_BC_PIS"] = to_number(df[bc_pis])
    out["VL_BC_COFINS"] = to_number(df[bc_cofins])
    return out


def consolidate_pis_by_key(pis: pd.DataFrame) -> pd.DataFrame:
    grouped = pis.groupby(["CHAVE", "REGISTRO"], dropna=False).agg(
        VL_OPERACAO_PISCOFINS=("VL_OPERACAO_PISCOFINS", "sum"),
        VL_BC_PIS=("VL_BC_PIS", "sum"),
        VL_BC_COFINS=("VL_BC_COFINS", "sum"),
        CFOP_PISCOFINS_LISTA=("CFOP_PISCOFINS", lambda x: ", ".join(sorted(set([str(v) for v in x if str(v) != "nan"])))) ,
        CST_PIS_LISTA=("CST_PIS", lambda x: ", ".join(sorted(set([str(v) for v in x if str(v) != "nan"]))))
    ).reset_index()
    return grouped


def classify_row(row, tolerancia: float) -> str:
    bc_pis = row.get("VL_BC_PIS", 0.0)
    opr = row.get("VL_OPR_ICMS", 0.0)
    esperada = row.get("BASE_ESPERADA_SEM_ICMS", 0.0)
    icms = row.get("VL_ICMS", 0.0)

    if pd.isna(bc_pis):
        return "SEM PIS/COFINS"
    if pd.isna(opr):
        return "SEM ICMS/IPI"
    if abs(bc_pis - esperada) <= tolerancia:
        return "ICMS EXCLUÍDO"
    if abs(bc_pis - opr) <= tolerancia:
        return "ICMS INCLUÍDO"
    if esperada < bc_pis < opr and icms > 0:
        return "EXCLUSÃO PARCIAL"
    return "DIVERGENTE / REVISAR"


def cruzar_icms_pis(icms_key: pd.DataFrame, pis_key: pd.DataFrame, tolerancia: float) -> pd.DataFrame:
    cruz = icms_key.merge(pis_key, on="CHAVE", how="outer")
    cruz["COMPETENCIA"] = cruz["COMPETENCIA"].fillna("SEM_DATA")
    numeric_cols = [
        "VL_OPR_ICMS", "VL_BC_ICMS", "VL_ICMS", "BASE_ESPERADA_SEM_ICMS",
        "VL_OPERACAO_PISCOFINS", "VL_BC_PIS", "VL_BC_COFINS"
    ]
    for col in numeric_cols:
        if col in cruz.columns:
            cruz[col] = pd.to_numeric(cruz[col], errors="coerce").fillna(0.0)

    cruz["DIF_PIS_VS_BASE_ESPERADA"] = cruz["VL_BC_PIS"] - cruz["BASE_ESPERADA_SEM_ICMS"]
    cruz["DIF_COFINS_VS_BASE_ESPERADA"] = cruz["VL_BC_COFINS"] - cruz["BASE_ESPERADA_SEM_ICMS"]
    cruz["DIF_PIS_VS_OPERACAO"] = cruz["VL_BC_PIS"] - cruz["VL_OPR_ICMS"]
    cruz["DIF_COFINS_VS_OPERACAO"] = cruz["VL_BC_COFINS"] - cruz["VL_OPR_ICMS"]
    cruz["STATUS"] = cruz.apply(lambda r: classify_row(r, tolerancia), axis=1)

    cruz["ICMS_POTENCIAL_INCLUIDO"] = np.where(
        cruz["STATUS"].isin(["ICMS INCLUÍDO", "EXCLUSÃO PARCIAL"]),
        np.minimum(np.maximum(cruz["DIF_PIS_VS_BASE_ESPERADA"], 0), cruz["VL_ICMS"]),
        0.0,
    )
    return cruz


def resumo_geral(cruzamentos: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for nome, df in cruzamentos.items():
        if df.empty:
            continue
        rows.append({
            "ANALISE": nome,
            "QTD_CHAVES": df["CHAVE"].nunique(),
            "ICMS_EXCLUIDO": int((df["STATUS"] == "ICMS EXCLUÍDO").sum()),
            "ICMS_INCLUIDO": int((df["STATUS"] == "ICMS INCLUÍDO").sum()),
            "EXCLUSAO_PARCIAL": int((df["STATUS"] == "EXCLUSÃO PARCIAL").sum()),
            "DIVERGENTE_REVISAR": int((df["STATUS"] == "DIVERGENTE / REVISAR").sum()),
            "SEM_PISCOFINS": int((df["STATUS"] == "SEM PIS/COFINS").sum()),
            "SEM_ICMS_IPI": int((df["STATUS"] == "SEM ICMS/IPI").sum()),
            "VL_ICMS_POTENCIAL_INCLUIDO": df["ICMS_POTENCIAL_INCLUIDO"].sum(),
        })
    return pd.DataFrame(rows)


def potencial_credito(cruzamentos: dict[str, pd.DataFrame], aliquota_pis: float, aliquota_cofins: float) -> pd.DataFrame:
    frames = []
    for nome, df in cruzamentos.items():
        if df.empty:
            continue
        tmp = df.groupby("COMPETENCIA", dropna=False).agg(
            ICMS_POTENCIAL_INCLUIDO=("ICMS_POTENCIAL_INCLUIDO", "sum"),
            QTD_CHAVES=("CHAVE", "nunique"),
        ).reset_index()
        tmp["ANALISE"] = nome
        tmp["CREDITO_PIS_ESTIMADO"] = tmp["ICMS_POTENCIAL_INCLUIDO"] * aliquota_pis
        tmp["CREDITO_COFINS_ESTIMADO"] = tmp["ICMS_POTENCIAL_INCLUIDO"] * aliquota_cofins
        tmp["CREDITO_TOTAL_ESTIMADO"] = tmp["CREDITO_PIS_ESTIMADO"] + tmp["CREDITO_COFINS_ESTIMADO"]
        frames.append(tmp)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def comparativo_c170_c175(df170: pd.DataFrame, df175: pd.DataFrame) -> pd.DataFrame:
    if df170.empty or df175.empty:
        return pd.DataFrame()
    a = df170[["CHAVE", "STATUS", "ICMS_POTENCIAL_INCLUIDO", "VL_BC_PIS", "VL_BC_COFINS"]].rename(columns={
        "STATUS": "STATUS_C170",
        "ICMS_POTENCIAL_INCLUIDO": "ICMS_POTENCIAL_C170",
        "VL_BC_PIS": "BC_PIS_C170",
        "VL_BC_COFINS": "BC_COFINS_C170",
    })
    b = df175[["CHAVE", "STATUS", "ICMS_POTENCIAL_INCLUIDO", "VL_BC_PIS", "VL_BC_COFINS"]].rename(columns={
        "STATUS": "STATUS_C175",
        "ICMS_POTENCIAL_INCLUIDO": "ICMS_POTENCIAL_C175",
        "VL_BC_PIS": "BC_PIS_C175",
        "VL_BC_COFINS": "BC_COFINS_C175",
    })
    comp = a.merge(b, on="CHAVE", how="outer")
    comp["DIF_ICMS_POTENCIAL"] = comp["ICMS_POTENCIAL_C170"].fillna(0) - comp["ICMS_POTENCIAL_C175"].fillna(0)
    return comp
