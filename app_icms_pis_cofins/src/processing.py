import pandas as pd
import numpy as np

from .utils import (
    normalize_columns,
    find_col,
    to_number,
    normalize_key,
    competence_from_date,
    competence_from_month_year,
)


# ---------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------

def load_sheet(xls: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(xls, sheet_name=sheet_name, dtype=object)
    return normalize_columns(df)


def _safe_find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    try:
        return find_col(df, candidates, required=False)
    except Exception:
        return None


def _serie_texto(df: pd.DataFrame, col: str | None, default: str = "") -> pd.Series:
    if col and col in df.columns:
        return df[col].fillna(default).astype(str).str.strip()
    return pd.Series([default] * len(df), index=df.index, dtype="object")


def _serie_numero(df: pd.DataFrame, col: str | None) -> pd.Series:
    if col and col in df.columns:
        return to_number(df[col])
    return pd.Series([0.0] * len(df), index=df.index, dtype="float64")


def _limpar_item(valor) -> str:
    if pd.isna(valor):
        return ""
    txt = str(valor).strip()
    if txt.endswith(".0") and txt.replace(".0", "").isdigit():
        txt = txt[:-2]
    return txt.zfill(3) if txt.isdigit() else txt


def _lista_unica(series: pd.Series) -> str:
    vals = []
    for v in series:
        s = str(v).strip()
        if s and s.lower() != "nan":
            vals.append(s)
    return ", ".join(sorted(set(vals)))


# ---------------------------------------------------------------------
# C100 — âncora documental
# ---------------------------------------------------------------------

def preparar_c100_anchor(c100: pd.DataFrame, origem: str) -> pd.DataFrame:
    """
    C100 é a âncora documental.

    Ele controla:
    - CHAVE
    - COMPETENCIA
    - COD_SIT
    - IND_OPER
    - VL_DOC

    A auditoria analítica usa somente documentos regulares COD_SIT = 00
    quando o campo existir.
    """
    c100 = normalize_columns(c100)

    chave = find_col(
        c100,
        [
            "CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF", "CHAVE_C100",
            "CHAVE_DE_ACESSO", "CHAVE_DE_ACESSO_C100", "Chave(C100)",
        ],
        required=True,
    )

    dt = _safe_find_col(c100, ["DT_DOC", "DATA", "DATA_DOC", "DT_E_S", "DATA_DE_EMISSAO", "DATA_DE_ENTRADA_SAIDA"])
    mes = _safe_find_col(c100, ["MES", "MÊS"])
    ano = _safe_find_col(c100, ["ANO"])
    cod_sit = _safe_find_col(c100, ["COD_SIT", "SITUACAO", "SITUACAO_C100"])
    ind_oper = _safe_find_col(c100, ["IND_OPER", "ENTRADA_SAIDA", "TIPO_OPERACAO"])
    vl_doc = _safe_find_col(c100, ["VL_DOC", "VALOR_DOC", "VALOR_DOCUMENTO", "VALOR_DA_NOTA"])
    num_doc = _safe_find_col(c100, ["NUM_DOC", "NUMERO", "NUMERO_DA_NOTA", "NÚMERO_DA_NOTA", "Número da Nota(C100)"])

    out = pd.DataFrame()
    out["CHAVE"] = normalize_key(c100[chave])
    out["ORIGEM_C100"] = origem

    if mes and ano:
        out["COMPETENCIA"] = competence_from_month_year(c100[mes], c100[ano])
    elif dt:
        out["COMPETENCIA"] = competence_from_date(c100[dt])
    else:
        out["COMPETENCIA"] = "SEM_DATA"

    out["COD_SIT"] = _serie_texto(c100, cod_sit, "")
    out["IND_OPER"] = _serie_texto(c100, ind_oper, "")
    out["VL_DOC"] = _serie_numero(c100, vl_doc)
    out["NUM_DOC"] = _serie_texto(c100, num_doc, "")

    out["DOCUMENTO_REGULAR"] = (
        out["COD_SIT"].eq("")
        | out["COD_SIT"].str.zfill(2).eq("00")
        | out["COD_SIT"].str.upper().isin(["REGULAR", "00"])
    )

    out = out.drop_duplicates(subset=["CHAVE"], keep="first")
    return out


# ---------------------------------------------------------------------
# SPED ICMS/IPI — C170 item e C190 fallback/consolidado
# ---------------------------------------------------------------------

def preparar_icms_c170(c100: pd.DataFrame, c170: pd.DataFrame) -> pd.DataFrame:
    """
    Origem preferencial do ICMS: C170 item a item.

    Chave analítica:
    CHAVE + NUM_ITEM
    """
    c100_anchor = preparar_c100_anchor(c100, "ICMS/IPI")
    c170 = normalize_columns(c170)

    chave = find_col(c170, ["CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF", "CHAVE_C100", "CHAVE_DE_ACESSO_C100", "Chave(C100)"], required=True)
    num_item = find_col(c170, ["NUM_ITEM", "ITEM", "N_ITEM", "NUMERACAO_SEQUENCIAL", "Número Item"], required=True)

    cfop = _safe_find_col(c170, ["CFOP"])
    cst = _safe_find_col(c170, ["CST_ICMS", "CST", "CST_DE_ICMS", "CST ICMS"])
    vl_item = _safe_find_col(c170, ["VL_ITEM", "VALOR_ITEM", "VALOR_DO_ITEM", "VL_OPR", "VALOR_OPERACAO"])
    vl_desc = _safe_find_col(c170, ["VL_DESC", "VALOR_DESCONTO", "VALOR_DO_DESCONTO", "DESCONTO"])
    vl_icms = find_col(c170, ["VL_ICMS", "ICMS", "VALOR_ICMS", "VALOR_DE_ICMS"], required=True)
    vl_bc_icms = _safe_find_col(c170, ["VL_BC_ICMS", "BC_ICMS", "BASE_ICMS", "BASE_DE_ICMS"])

    out = pd.DataFrame()
    out["CHAVE"] = normalize_key(c170[chave])
    out["NUM_ITEM"] = c170[num_item].apply(_limpar_item)
    out["NIVEL_ICMS"] = "ITEM_C170"
    out["CFOP"] = _serie_texto(c170, cfop)
    out["CST_ICMS"] = _serie_texto(c170, cst)
    out["VL_OPR_ICMS"] = _serie_numero(c170, vl_item)
    out["VL_DESC_ICMS"] = _serie_numero(c170, vl_desc)
    out["VL_BC_ICMS"] = _serie_numero(c170, vl_bc_icms)
    out["VL_ICMS"] = _serie_numero(c170, vl_icms)

    out = out.merge(
        c100_anchor[["CHAVE", "COMPETENCIA", "COD_SIT", "IND_OPER", "VL_DOC", "DOCUMENTO_REGULAR"]],
        on="CHAVE",
        how="left",
    )
    out["COMPETENCIA"] = out["COMPETENCIA"].fillna("SEM_DATA")
    out["DOCUMENTO_REGULAR"] = out["DOCUMENTO_REGULAR"].fillna(False)
    out["CHAVE_ITEM"] = out["CHAVE"] + "|" + out["NUM_ITEM"]
    return out


def preparar_icms_c190(c100: pd.DataFrame, c190: pd.DataFrame, c170: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Interface preservada para o app.

    Nova lógica:
    - Se existir C170 ICMS/IPI com dados úteis, usa C170 item a item.
    - Sempre processa C190 também como base consolidada/fallback.
    - Depois concatena as bases. A consolidação posterior prioriza item quando houver.
    """
    frames = []

    if c170 is not None and isinstance(c170, pd.DataFrame) and not c170.empty:
        try:
            icms_item = preparar_icms_c170(c100, c170)
            if not icms_item.empty:
                frames.append(icms_item)
        except Exception:
            # Não quebra o fluxo antigo. Se C170 vier com estrutura inesperada,
            # o sistema ainda cai para C190.
            pass

    c100_anchor = preparar_c100_anchor(c100, "ICMS/IPI")
    c190 = normalize_columns(c190)

    chave = find_col(c190, ["CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF", "CHAVE_C100", "CHAVE_DE_ACESSO", "CHAVE_DE_ACESSO_C100", "Chave(C100)"], required=True)
    cfop = _safe_find_col(c190, ["CFOP"])
    cst = _safe_find_col(c190, ["CST_ICMS", "CST", "CST_DE_ICMS", "CST ICMS"])
    vl_opr = find_col(c190, ["VL_OPR", "VALOR_OPERACAO", "VL_OPERACAO", "VALOR_DA_OPERACAO", "Valor da Operação"], required=True)
    vl_bc_icms = _safe_find_col(c190, ["VL_BC_ICMS", "BASE_ICMS", "BC_ICMS", "BASE_DE_ICMS"])
    vl_icms = find_col(c190, ["VL_ICMS", "ICMS", "VALOR_DE_ICMS", "Valor ICMS"], required=True)

    out = pd.DataFrame()
    out["CHAVE"] = normalize_key(c190[chave])
    out["NUM_ITEM"] = ""
    out["NIVEL_ICMS"] = "CONSOLIDADO_C190"
    out["CFOP"] = _serie_texto(c190, cfop)
    out["CST_ICMS"] = _serie_texto(c190, cst)
    out["VL_OPR_ICMS"] = _serie_numero(c190, vl_opr)
    out["VL_DESC_ICMS"] = 0.0
    out["VL_BC_ICMS"] = _serie_numero(c190, vl_bc_icms)
    out["VL_ICMS"] = _serie_numero(c190, vl_icms)

    out = out.merge(
        c100_anchor[["CHAVE", "COMPETENCIA", "COD_SIT", "IND_OPER", "VL_DOC", "DOCUMENTO_REGULAR"]],
        on="CHAVE",
        how="left",
    )
    out["COMPETENCIA"] = out["COMPETENCIA"].fillna("SEM_DATA")
    out["DOCUMENTO_REGULAR"] = out["DOCUMENTO_REGULAR"].fillna(False)
    out["CHAVE_ITEM"] = out["CHAVE"] + "|"

    frames.append(out)

    final = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return final


def consolidate_icms_by_key(icms: pd.DataFrame) -> pd.DataFrame:
    """
    Consolidação por CHAVE para preservar compatibilidade com o fluxo atual.

    Observação:
    A análise item a item é feita em cruzar_icms_pis quando o PIS/COFINS
    também possuir NUM_ITEM.
    """
    if icms is None or icms.empty:
        return pd.DataFrame()

    # Para o consolidado por nota, usar todos os níveis disponíveis. Se houver C170 e C190,
    # evita duplicar ICMS preferindo C170 no resumo por chave.
    base = icms.copy()
    tem_item_por_chave = (
        base[base["NIVEL_ICMS"].eq("ITEM_C170")]
        .groupby("CHAVE")["VL_ICMS"]
        .sum()
        .rename("ICMS_ITEM_EXISTE")
    )
    base = base.merge(tem_item_por_chave, on="CHAVE", how="left")
    base["USAR_NO_CONSOLIDADO"] = np.where(
        base["ICMS_ITEM_EXISTE"].fillna(0) > 0,
        base["NIVEL_ICMS"].eq("ITEM_C170"),
        True,
    )
    base = base[base["USAR_NO_CONSOLIDADO"]].copy()

    grouped = base.groupby(["CHAVE", "COMPETENCIA"], dropna=False).agg(
        VL_OPR_ICMS=("VL_OPR_ICMS", "sum"),
        VL_DESC_ICMS=("VL_DESC_ICMS", "sum"),
        VL_BC_ICMS=("VL_BC_ICMS", "sum"),
        VL_ICMS=("VL_ICMS", "sum"),
        CFOP_LISTA=("CFOP", _lista_unica),
        CST_ICMS_LISTA=("CST_ICMS", _lista_unica),
        COD_SIT=("COD_SIT", lambda x: next((str(v) for v in x if str(v).strip()), "")),
        IND_OPER=("IND_OPER", lambda x: next((str(v) for v in x if str(v).strip()), "")),
        DOCUMENTO_REGULAR=("DOCUMENTO_REGULAR", "max"),
        NIVEL_ICMS=("NIVEL_ICMS", _lista_unica),
    ).reset_index()

    grouped["BASE_ESPERADA_SEM_ICMS"] = grouped["VL_OPR_ICMS"] - grouped["VL_DESC_ICMS"] - grouped["VL_ICMS"]
    return grouped


# ---------------------------------------------------------------------
# EFD-Contribuições — C170 item e C175 consolidado
# ---------------------------------------------------------------------

def prepare_pis_cofins(df: pd.DataFrame, registro: str) -> pd.DataFrame:
    df = normalize_columns(df)

    chave = find_col(df, ["CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF", "CHAVE_C100", "CHAVE_DE_ACESSO_C100", "Chave(C100)"], required=True)
    cfop = _safe_find_col(df, ["CFOP"])
    cst_pis = _safe_find_col(df, ["CST_PIS", "CST - PIS", "CST", "CST_DE_PIS", "CST PIS"])
    cst_cofins = _safe_find_col(df, ["CST_COFINS", "CST COFINS", "CST - COFINS", "CST_DE_COFINS"])
    num_item = _safe_find_col(df, ["NUM_ITEM", "ITEM", "N_ITEM", "NUMERACAO_SEQUENCIAL", "Número Item"])
    vl_item = find_col(df, ["VL_ITEM", "VL_OPR", "VALOR_OPERACAO", "VL_OPERACAO", "VALOR_TOTAL_DO_PRODUTO", "VALOR_DA_OPERACAO", "Valor da Operação"], required=True)
    vl_desc = _safe_find_col(df, ["VL_DESC", "VALOR_DESCONTO", "VALOR_DO_DESCONTO", "Valor de Desconto", "Valor do Desconto", "DESCONTO"])
    bc_pis = find_col(df, ["VL_BC_PIS", "BC_PIS", "BASE_PIS", "BASE_DE_PIS", "VALOR_BC_PIS", "Valor BC PIS"], required=True)
    bc_cofins = find_col(df, ["VL_BC_COFINS", "BC_COFINS", "BASE_COFINS", "BASE_DE_COFINS", "VALOR_BC_COFINS", "Valor BC COFINS"], required=True)

    out = pd.DataFrame()
    out["REGISTRO"] = registro
    out["CHAVE"] = normalize_key(df[chave])
    out["NUM_ITEM"] = df[num_item].apply(_limpar_item) if num_item else ""
    out["CHAVE_ITEM"] = out["CHAVE"] + "|" + out["NUM_ITEM"]
    out["CFOP_PISCOFINS"] = _serie_texto(df, cfop)
    out["CST_PIS"] = _serie_texto(df, cst_pis)
    out["CST_COFINS"] = _serie_texto(df, cst_cofins) if cst_cofins else out["CST_PIS"]
    out["VL_OPERACAO_PISCOFINS"] = _serie_numero(df, vl_item)
    out["VL_DESC_PISCOFINS"] = _serie_numero(df, vl_desc)
    out["VL_BC_PIS"] = _serie_numero(df, bc_pis)
    out["VL_BC_COFINS"] = _serie_numero(df, bc_cofins)
    out["BASE_OPERACAO_LIQUIDA_PISCOFINS"] = out["VL_OPERACAO_PISCOFINS"] - out["VL_DESC_PISCOFINS"]
    return out


def consolidate_pis_by_key(pis: pd.DataFrame) -> pd.DataFrame:
    """
    Mantém compatibilidade com o app atual.

    Para C170, mantém também uma marcação de que existe itemização,
    para cruzar_icms_pis tentar CHAVE + NUM_ITEM.
    """
    if pis is None or pis.empty:
        return pd.DataFrame()

    # Não consolidar C170 por item aqui; vamos passar as linhas com NUM_ITEM
    # e deixar cruzar_icms_pis decidir o método.
    if "NUM_ITEM" in pis.columns and pis["NUM_ITEM"].astype(str).str.strip().ne("").any():
        return pis.copy()

    grouped = pis.groupby(["CHAVE", "REGISTRO"], dropna=False).agg(
        VL_OPERACAO_PISCOFINS=("VL_OPERACAO_PISCOFINS", "sum"),
        VL_DESC_PISCOFINS=("VL_DESC_PISCOFINS", "sum"),
        BASE_OPERACAO_LIQUIDA_PISCOFINS=("BASE_OPERACAO_LIQUIDA_PISCOFINS", "sum"),
        VL_BC_PIS=("VL_BC_PIS", "sum"),
        VL_BC_COFINS=("VL_BC_COFINS", "sum"),
        CFOP_PISCOFINS_LISTA=("CFOP_PISCOFINS", _lista_unica),
        CST_PIS_LISTA=("CST_PIS", _lista_unica),
        CST_COFINS_LISTA=("CST_COFINS", _lista_unica),
    ).reset_index()
    grouped["NUM_ITEM"] = ""
    grouped["CHAVE_ITEM"] = grouped["CHAVE"] + "|"
    return grouped


# ---------------------------------------------------------------------
# Classificação
# ---------------------------------------------------------------------

def _status_documental(row) -> str:
    if not bool(row.get("DOCUMENTO_REGULAR", True)):
        return "DOCUMENTO NÃO REGULAR"
    return ""


def classify_row(row, tolerancia: float) -> str:
    doc_status = _status_documental(row)
    if doc_status:
        return doc_status

    bc_pis = row.get("VL_BC_PIS", 0.0)
    opr_liq = row.get("BASE_OPERACAO_LIQUIDA_COMPARACAO", row.get("VL_OPR_ICMS", 0.0))
    esperada = row.get("BASE_ESPERADA_SEM_ICMS", 0.0)
    icms = row.get("VL_ICMS", 0.0)

    if row.get("SEM_PISCOFINS", False):
        return "SEM PIS/COFINS"
    if row.get("SEM_ICMS_IPI", False):
        return "SEM ICMS/IPI"
    if abs(bc_pis - esperada) <= tolerancia:
        return "ICMS EXCLUÍDO"
    if abs(bc_pis - opr_liq) <= tolerancia:
        return "ICMS INCLUÍDO"
    if esperada < bc_pis < opr_liq and icms > 0:
        return "EXCLUSÃO PARCIAL"
    if bc_pis < opr_liq and abs((opr_liq - bc_pis) - icms) > tolerancia:
        return "ANOMALIA / OUTRAS DEDUÇÕES"
    return "DIVERGENTE / REVISAR"


def _filtrar_cst_tributado(df: pd.DataFrame) -> pd.DataFrame:
    """
    PDF: CST PIS/COFINS tributados 01, 02, 05.
    Não elimina linhas; apenas marca elegibilidade.
    """
    if "CST_PIS" in df.columns:
        cst = df["CST_PIS"].astype(str).str.zfill(2)
        df["CST_PISCOFINS_TRIBUTADO"] = cst.isin(["01", "02", "05"])
    elif "CST_PIS_LISTA" in df.columns:
        df["CST_PISCOFINS_TRIBUTADO"] = df["CST_PIS_LISTA"].astype(str).apply(
            lambda x: any(c in [p.strip().zfill(2) for p in x.replace(";", ",").split(",")] for c in ["01", "02", "05"])
        )
    else:
        df["CST_PISCOFINS_TRIBUTADO"] = True
    return df


def cruzar_icms_pis(
    icms_key: pd.DataFrame,
    pis_key: pd.DataFrame,
    tolerancia: float,
    aliquota_pis: float = 0.0165,
    aliquota_cofins: float = 0.0760,
) -> pd.DataFrame:
    """
    Cruzamento melhorado.

    1. Se existir NUM_ITEM em PIS e ICMS item, cruza CHAVE + NUM_ITEM.
    2. Caso contrário, cai para CHAVE consolidada.
    3. C100 entra como âncora documental: COD_SIT/documento regular.
    4. CST PIS/COFINS 01, 02, 05 são marcados como tributados.
    """
    if icms_key is None or icms_key.empty:
        icms_key = pd.DataFrame(columns=["CHAVE"])
    if pis_key is None or pis_key.empty:
        pis_key = pd.DataFrame(columns=["CHAVE"])

    # Caso analítico: PIS possui itens e icms_key ainda está consolidado por chave.
    # O app passa icms_base consolidado para esta função; por compatibilidade,
    # o item a item real é preservado quando consolidate_pis_by_key retorna itens,
    # mas o ICMS detalhado precisa estar dentro de icms_key. Se não estiver, cai
    # para nota.
    analitico_pis = "NUM_ITEM" in pis_key.columns and pis_key["NUM_ITEM"].astype(str).str.strip().ne("").any()
    analitico_icms = "NUM_ITEM" in icms_key.columns and icms_key["NUM_ITEM"].astype(str).str.strip().ne("").any()

    if analitico_pis and analitico_icms:
        cruz = icms_key.merge(pis_key, on=["CHAVE", "NUM_ITEM"], how="outer", suffixes=("", "_PIS"))
        cruz["METODO_CRUZAMENTO"] = "CHAVE + NUM_ITEM"
    else:
        # Consolidar PIS por chave se veio itemizado.
        if "NUM_ITEM" in pis_key.columns and pis_key["NUM_ITEM"].astype(str).str.strip().ne("").any():
            pis_key2 = pis_key.groupby(["CHAVE", "REGISTRO"], dropna=False).agg(
                VL_OPERACAO_PISCOFINS=("VL_OPERACAO_PISCOFINS", "sum"),
                VL_DESC_PISCOFINS=("VL_DESC_PISCOFINS", "sum"),
                BASE_OPERACAO_LIQUIDA_PISCOFINS=("BASE_OPERACAO_LIQUIDA_PISCOFINS", "sum"),
                VL_BC_PIS=("VL_BC_PIS", "sum"),
                VL_BC_COFINS=("VL_BC_COFINS", "sum"),
                CFOP_PISCOFINS_LISTA=("CFOP_PISCOFINS", _lista_unica),
                CST_PIS_LISTA=("CST_PIS", _lista_unica),
                CST_COFINS_LISTA=("CST_COFINS", _lista_unica),
            ).reset_index()
        else:
            pis_key2 = pis_key.copy()

        cruz = icms_key.merge(pis_key2, on="CHAVE", how="outer", suffixes=("", "_PIS"))
        cruz["METODO_CRUZAMENTO"] = "CHAVE CONSOLIDADA"

    # Padronizações
    for col in [
        "VL_OPR_ICMS", "VL_DESC_ICMS", "VL_BC_ICMS", "VL_ICMS", "BASE_ESPERADA_SEM_ICMS",
        "VL_OPERACAO_PISCOFINS", "VL_DESC_PISCOFINS", "BASE_OPERACAO_LIQUIDA_PISCOFINS",
        "VL_BC_PIS", "VL_BC_COFINS",
    ]:
        if col in cruz.columns:
            cruz[col] = pd.to_numeric(cruz[col], errors="coerce").fillna(0.0)

    for col in ["COMPETENCIA", "CFOP_LISTA", "CST_ICMS_LISTA", "COD_SIT", "IND_OPER", "NIVEL_ICMS"]:
        if col in cruz.columns:
            cruz[col] = cruz[col].fillna("")

    cruz["SEM_PISCOFINS"] = ~cruz["VL_BC_PIS"].notna() if "VL_BC_PIS" in cruz.columns else True
    cruz["SEM_ICMS_IPI"] = ~cruz["VL_ICMS"].notna() if "VL_ICMS" in cruz.columns else True

    if "BASE_OPERACAO_LIQUIDA_PISCOFINS" in cruz.columns:
        cruz["BASE_OPERACAO_LIQUIDA_COMPARACAO"] = np.where(
            cruz["BASE_OPERACAO_LIQUIDA_PISCOFINS"] > 0,
            cruz["BASE_OPERACAO_LIQUIDA_PISCOFINS"],
            cruz.get("VL_OPR_ICMS", 0.0) - cruz.get("VL_DESC_ICMS", 0.0),
        )
    else:
        cruz["BASE_OPERACAO_LIQUIDA_COMPARACAO"] = cruz.get("VL_OPR_ICMS", 0.0) - cruz.get("VL_DESC_ICMS", 0.0)

    # Se a base esperada ainda não existir, calcula.
    if "BASE_ESPERADA_SEM_ICMS" not in cruz.columns:
        cruz["BASE_ESPERADA_SEM_ICMS"] = cruz["BASE_OPERACAO_LIQUIDA_COMPARACAO"] - cruz.get("VL_ICMS", 0.0)

    aliquota_total = float(aliquota_pis) + float(aliquota_cofins)
    cruz["ALIQUOTA_PIS_COFINS"] = aliquota_total

    cruz["DIF_PIS_VS_BASE_ESPERADA"] = cruz["VL_BC_PIS"] - cruz["BASE_ESPERADA_SEM_ICMS"]
    cruz["DIF_COFINS_VS_BASE_ESPERADA"] = cruz["VL_BC_COFINS"] - cruz["BASE_ESPERADA_SEM_ICMS"]
    cruz["DIF_PIS_VS_OPERACAO_LIQUIDA"] = cruz["VL_BC_PIS"] - cruz["BASE_OPERACAO_LIQUIDA_COMPARACAO"]
    cruz["DIF_COFINS_VS_OPERACAO_LIQUIDA"] = cruz["VL_BC_COFINS"] - cruz["BASE_OPERACAO_LIQUIDA_COMPARACAO"]

    cruz = _filtrar_cst_tributado(cruz)

    # Status só faz sentido para CST tributado; outros vão para revisão/fora escopo.
    cruz["STATUS"] = cruz.apply(lambda r: classify_row(r, tolerancia), axis=1)
    cruz.loc[~cruz["CST_PISCOFINS_TRIBUTADO"], "STATUS"] = "FORA CST TRIBUTADO"

    cruz["BASE_EXCEDENTE_RECUPERAVEL"] = np.where(
        cruz["STATUS"].isin(["ICMS INCLUÍDO", "EXCLUSÃO PARCIAL"]),
        np.minimum(np.maximum(cruz["DIF_PIS_VS_BASE_ESPERADA"], 0), cruz["VL_ICMS"]),
        0.0,
    )

    # Preserva coluna antiga validada no projeto:
    # para o resumo da aba 07, o usuário validou a soma desta coluna após filtros.
    cruz["CREDITO_PISCOFINS_BASE_ESPERADA"] = cruz["BASE_ESPERADA_SEM_ICMS"] * aliquota_total

    cruz["CREDITO_PIS_BASE_EXCEDENTE"] = cruz["BASE_EXCEDENTE_RECUPERAVEL"] * float(aliquota_pis)
    cruz["CREDITO_COFINS_BASE_EXCEDENTE"] = cruz["BASE_EXCEDENTE_RECUPERAVEL"] * float(aliquota_cofins)
    cruz["CREDITO_TOTAL_BASE_EXCEDENTE"] = cruz["CREDITO_PIS_BASE_EXCEDENTE"] + cruz["CREDITO_COFINS_BASE_EXCEDENTE"]

    cruz["ICMS_POTENCIAL_INCLUIDO_ANTERIOR"] = cruz["BASE_EXCEDENTE_RECUPERAVEL"]

    ordem = [
        "CHAVE", "NUM_ITEM", "METODO_CRUZAMENTO", "NIVEL_ICMS", "COMPETENCIA",
        "COD_SIT", "IND_OPER", "DOCUMENTO_REGULAR",
        "CFOP_LISTA", "CST_ICMS_LISTA", "CFOP_PISCOFINS_LISTA", "CST_PIS_LISTA", "CST_COFINS_LISTA",
        "CST_PIS", "CST_COFINS", "CST_PISCOFINS_TRIBUTADO",
        "VL_OPR_ICMS", "VL_DESC_ICMS", "VL_BC_ICMS", "VL_ICMS",
        "VL_OPERACAO_PISCOFINS", "VL_DESC_PISCOFINS", "BASE_OPERACAO_LIQUIDA_COMPARACAO",
        "BASE_ESPERADA_SEM_ICMS",
        "VL_BC_PIS", "VL_BC_COFINS",
        "DIF_PIS_VS_BASE_ESPERADA", "DIF_COFINS_VS_BASE_ESPERADA",
        "DIF_PIS_VS_OPERACAO_LIQUIDA", "DIF_COFINS_VS_OPERACAO_LIQUIDA",
        "STATUS", "BASE_EXCEDENTE_RECUPERAVEL",
        "CREDITO_PIS_BASE_EXCEDENTE", "CREDITO_COFINS_BASE_EXCEDENTE", "CREDITO_TOTAL_BASE_EXCEDENTE",
        "CREDITO_PISCOFINS_BASE_ESPERADA", "ALIQUOTA_PIS_COFINS",
        "REGISTRO", "ICMS_POTENCIAL_INCLUIDO_ANTERIOR",
    ]

    existentes = [c for c in ordem if c in cruz.columns]
    demais = [c for c in cruz.columns if c not in existentes]
    return cruz[existentes + demais]


# ---------------------------------------------------------------------
# Resumos e créditos — preservando pontos fortes do projeto
# ---------------------------------------------------------------------

def resumo_geral(cruzamentos: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for nome, df in cruzamentos.items():
        if df.empty:
            continue
        rows.append({
            "ANALISE": nome,
            "QTD_CHAVES": df["CHAVE"].nunique() if "CHAVE" in df.columns else 0,
            "QTD_REGISTROS": len(df),
            "METODO_ITEM_A_ITEM": int((df.get("METODO_CRUZAMENTO", pd.Series(dtype=str)) == "CHAVE + NUM_ITEM").sum()),
            "ICMS_EXCLUIDO": int((df["STATUS"] == "ICMS EXCLUÍDO").sum()),
            "ICMS_INCLUIDO": int((df["STATUS"] == "ICMS INCLUÍDO").sum()),
            "EXCLUSAO_PARCIAL": int((df["STATUS"] == "EXCLUSÃO PARCIAL").sum()),
            "ANOMALIA_OUTRAS_DEDUCOES": int((df["STATUS"] == "ANOMALIA / OUTRAS DEDUÇÕES").sum()),
            "FORA_CST_TRIBUTADO": int((df["STATUS"] == "FORA CST TRIBUTADO").sum()),
            "DOCUMENTO_NAO_REGULAR": int((df["STATUS"] == "DOCUMENTO NÃO REGULAR").sum()),
            "DIVERGENTE_REVISAR": int((df["STATUS"] == "DIVERGENTE / REVISAR").sum()),
            "SEM_PISCOFINS": int((df["STATUS"] == "SEM PIS/COFINS").sum()),
            "SEM_ICMS_IPI": int((df["STATUS"] == "SEM ICMS/IPI").sum()),
            "BASE_ESPERADA_SEM_ICMS": df.get("BASE_ESPERADA_SEM_ICMS", pd.Series(dtype=float)).sum(),
            "BASE_EXCEDENTE_RECUPERAVEL": df.get("BASE_EXCEDENTE_RECUPERAVEL", pd.Series(dtype=float)).sum(),
            "CREDITO_TOTAL_BASE_EXCEDENTE": df.get("CREDITO_TOTAL_BASE_EXCEDENTE", pd.Series(dtype=float)).sum(),
            "CREDITO_PISCOFINS_BASE_ESPERADA": df.get("CREDITO_PISCOFINS_BASE_ESPERADA", pd.Series(dtype=float)).sum(),
            "VL_ICMS_TOTAL": df.get("VL_ICMS", pd.Series(dtype=float)).sum(),
        })
    return pd.DataFrame(rows)


def _lista_contem_codigo(valor, codigo: str) -> bool:
    if pd.isna(valor):
        return False
    partes = [
        str(p).strip().zfill(len(codigo))
        for p in str(valor).replace(";", ",").split(",")
        if str(p).strip() != ""
    ]
    return codigo in partes


def potencial_credito(
    cruzamentos: dict[str, pd.DataFrame],
    aliquota_pis: float,
    aliquota_cofins: float,
    regime: str = ""
) -> pd.DataFrame:
    """
    Mantém a lógica validada no projeto:
    Aba 07 = resumo mensal da aba de cruzamento, filtrando:
    CFOP 5102 + CST ICMS 000 + CST PIS/COFINS 01 + STATUS ICMS INCLUÍDO.
    Valor = soma de CREDITO_PISCOFINS_BASE_ESPERADA.
    """

    frames = []

    for nome, df in cruzamentos.items():
        if df is None or df.empty:
            continue

        base = df.copy()

        # Compatibiliza C170 item a item e C175 consolidado.
        if "CFOP_LISTA" not in base.columns and "CFOP" in base.columns:
            base["CFOP_LISTA"] = base["CFOP"]
        if "CST_PIS_LISTA" not in base.columns and "CST_PIS" in base.columns:
            base["CST_PIS_LISTA"] = base["CST_PIS"]
        if "CST_ICMS_LISTA" not in base.columns and "CST_ICMS" in base.columns:
            base["CST_ICMS_LISTA"] = base["CST_ICMS"]

        colunas_necessarias = [
            "COMPETENCIA",
            "CHAVE",
            "CFOP_LISTA",
            "CST_ICMS_LISTA",
            "CST_PIS_LISTA",
            "STATUS",
            "CREDITO_PISCOFINS_BASE_ESPERADA",
        ]

        faltantes = [c for c in colunas_necessarias if c not in base.columns]
        if faltantes:
            continue

        elegivel = base[
            base["CFOP_LISTA"].apply(lambda x: _lista_contem_codigo(x, "5102"))
            & base["CST_ICMS_LISTA"].apply(lambda x: _lista_contem_codigo(x, "000"))
            & base["CST_PIS_LISTA"].apply(lambda x: _lista_contem_codigo(x, "01"))
            & (base["STATUS"].astype(str).str.upper().str.strip() == "ICMS INCLUÍDO")
        ].copy()

        if elegivel.empty:
            continue

        for coluna in [
            "VL_OPR_ICMS", "VL_ICMS", "BASE_ESPERADA_SEM_ICMS", "VL_BC_PIS",
            "VL_BC_COFINS", "BASE_EXCEDENTE_RECUPERAVEL",
            "CREDITO_TOTAL_BASE_EXCEDENTE", "CREDITO_PISCOFINS_BASE_ESPERADA",
        ]:
            if coluna in elegivel.columns:
                elegivel[coluna] = pd.to_numeric(elegivel[coluna], errors="coerce").fillna(0.0)

        agg_dict = {
            "QTD_CHAVES_ELEGIVEIS": ("CHAVE", "nunique"),
            "QTD_REGISTROS_ELEGIVEIS": ("CHAVE", "size"),
            "CREDITO_PISCOFINS_BASE_ESPERADA": ("CREDITO_PISCOFINS_BASE_ESPERADA", "sum"),
        }

        for coluna in [
            "VL_OPR_ICMS", "VL_ICMS", "BASE_ESPERADA_SEM_ICMS", "VL_BC_PIS",
            "VL_BC_COFINS", "BASE_EXCEDENTE_RECUPERAVEL", "CREDITO_TOTAL_BASE_EXCEDENTE",
        ]:
            if coluna in elegivel.columns:
                agg_dict[coluna] = (coluna, "sum")

        tmp = elegivel.groupby("COMPETENCIA", dropna=False).agg(**agg_dict).reset_index()

        tmp.insert(1, "ANALISE", nome)
        tmp["REGIME"] = regime if regime else "Não informado"
        tmp["ALIQUOTA_PIS"] = float(aliquota_pis)
        tmp["ALIQUOTA_COFINS"] = float(aliquota_cofins)
        tmp["ALIQUOTA_TOTAL_PIS_COFINS"] = float(aliquota_pis) + float(aliquota_cofins)
        tmp["CREDITO_TOTAL"] = tmp["CREDITO_PISCOFINS_BASE_ESPERADA"]
        tmp["CRITERIO"] = (
            "Resumo da aba de cruzamento filtrado por CFOP 5102 + CST ICMS 000 + "
            "CST PIS/COFINS 01 + STATUS ICMS INCLUÍDO; "
            "valor = soma de CREDITO_PISCOFINS_BASE_ESPERADA"
        )

        frames.append(tmp)

    if not frames:
        return pd.DataFrame(
            columns=[
                "COMPETENCIA", "ANALISE", "REGIME", "QTD_CHAVES_ELEGIVEIS",
                "QTD_REGISTROS_ELEGIVEIS", "CREDITO_PISCOFINS_BASE_ESPERADA",
                "CREDITO_TOTAL", "ALIQUOTA_PIS", "ALIQUOTA_COFINS",
                "ALIQUOTA_TOTAL_PIS_COFINS", "CRITERIO",
            ]
        )

    final = pd.concat(frames, ignore_index=True)
    final = final.sort_values(["ANALISE", "COMPETENCIA"]).reset_index(drop=True)

    ordem = [
        "COMPETENCIA", "ANALISE", "REGIME", "QTD_CHAVES_ELEGIVEIS",
        "QTD_REGISTROS_ELEGIVEIS", "VL_OPR_ICMS", "VL_ICMS",
        "BASE_ESPERADA_SEM_ICMS", "VL_BC_PIS", "VL_BC_COFINS",
        "BASE_EXCEDENTE_RECUPERAVEL", "CREDITO_TOTAL_BASE_EXCEDENTE",
        "CREDITO_PISCOFINS_BASE_ESPERADA", "CREDITO_TOTAL",
        "ALIQUOTA_PIS", "ALIQUOTA_COFINS", "ALIQUOTA_TOTAL_PIS_COFINS",
        "CRITERIO",
    ]
    existentes = [c for c in ordem if c in final.columns]
    demais = [c for c in final.columns if c not in existentes]
    return final[existentes + demais]


def comparativo_c170_c175(df170: pd.DataFrame, df175: pd.DataFrame) -> pd.DataFrame:
    if df170.empty or df175.empty:
        return pd.DataFrame()

    a = df170[["CHAVE", "STATUS", "CREDITO_PISCOFINS_BASE_ESPERADA", "VL_BC_PIS", "VL_BC_COFINS"]].rename(columns={
        "STATUS": "STATUS_C170",
        "CREDITO_PISCOFINS_BASE_ESPERADA": "CREDITO_BASE_ESPERADA_C170",
        "VL_BC_PIS": "BC_PIS_C170",
        "VL_BC_COFINS": "BC_COFINS_C170",
    })
    b = df175[["CHAVE", "STATUS", "CREDITO_PISCOFINS_BASE_ESPERADA", "VL_BC_PIS", "VL_BC_COFINS"]].rename(columns={
        "STATUS": "STATUS_C175",
        "CREDITO_PISCOFINS_BASE_ESPERADA": "CREDITO_BASE_ESPERADA_C175",
        "VL_BC_PIS": "BC_PIS_C175",
        "VL_BC_COFINS": "BC_COFINS_C175",
    })
    comp = a.merge(b, on="CHAVE", how="outer")
    comp["DIF_CREDITO_BASE_ESPERADA"] = comp["CREDITO_BASE_ESPERADA_C170"].fillna(0) - comp["CREDITO_BASE_ESPERADA_C175"].fillna(0)
    return comp
