import pandas as pd
import numpy as np
from .utils import normalize_columns, find_col, to_number, normalize_key, competence_from_date, competence_from_month_year


def load_sheet(xls: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(xls, sheet_name=sheet_name, dtype=object)
    return normalize_columns(df)


def prepare_icms_c190(c100: pd.DataFrame, c190: pd.DataFrame) -> pd.DataFrame:
    c100 = normalize_columns(c100)
    c190 = normalize_columns(c190)

    c100_chave = find_col(c100, ["CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF", "CHAVE_C100", "CHAVE_DE_ACESSO", "CHAVE_DE_ACESSO_C100"], required=True)
    c100_dt = find_col(c100, ["DT_DOC", "DATA", "DATA_DOC", "DT_E_S", "DATA_DE_EMISSAO", "DATA_DE_ENTRADA_SAIDA"], required=False)
    c100_mes = find_col(c100, ["MES", "MÊS"], required=False)
    c100_ano = find_col(c100, ["ANO"], required=False)
    c100_sit = find_col(c100, ["COD_SIT", "SITUACAO", "SITUACAO_C100"], required=False)

    c190_chave = find_col(c190, ["CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF", "CHAVE_C100", "CHAVE_DE_ACESSO", "CHAVE_DE_ACESSO_C100"], required=True)
    c190_cfop = find_col(c190, ["CFOP"], required=False)
    c190_cst = find_col(c190, ["CST_ICMS", "CST", "CST_DE_ICMS"], required=False)
    c190_vl_opr = find_col(c190, ["VL_OPR", "VALOR_OPERACAO", "VL_OPERACAO", "VALOR_DA_OPERACAO"], required=True)
    c190_vl_bc_icms = find_col(c190, ["VL_BC_ICMS", "BASE_ICMS", "BC_ICMS", "BASE_DE_ICMS"], required=True)
    c190_vl_icms = find_col(c190, ["VL_ICMS", "ICMS", "VALOR_DE_ICMS"], required=True)

    out = pd.DataFrame()
    out["CHAVE"] = normalize_key(c190[c190_chave])
    out["CFOP"] = c190[c190_cfop].astype(str).str.strip() if c190_cfop else ""
    out["CST_ICMS"] = c190[c190_cst].astype(str).str.strip() if c190_cst else ""
    out["VL_OPR_ICMS"] = to_number(c190[c190_vl_opr])
    out["VL_BC_ICMS"] = to_number(c190[c190_vl_bc_icms])
    out["VL_ICMS"] = to_number(c190[c190_vl_icms])

    c100_aux = pd.DataFrame()
    c100_aux["CHAVE"] = normalize_key(c100[c100_chave])
    c100_aux["COMPETENCIA"] = competence_from_month_year(c100[c100_mes], c100[c100_ano]) if c100_mes and c100_ano else (competence_from_date(c100[c100_dt]) if c100_dt else "SEM_DATA")
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
    chave = find_col(df, ["CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF", "CHAVE_C100", "CHAVE_DE_ACESSO_C100"], required=True)
    cfop = find_col(df, ["CFOP"], required=False)
    cst_pis = find_col(df, ["CST_PIS", "CST", "CST_DE_PIS"], required=False)
    num_item = find_col(df, ["NUM_ITEM", "ITEM", "N_ITEM", "NUMERACAO_SEQUENCIAL"], required=False)
    vl_item = find_col(df, ["VL_ITEM", "VL_OPR", "VALOR_OPERACAO", "VL_OPERACAO", "VALOR_TOTAL_DO_PRODUTO", "VALOR_DA_OPERACAO"], required=True)
    bc_pis = find_col(df, ["VL_BC_PIS", "BC_PIS", "BASE_PIS", "BASE_DE_PIS", "VALOR_BC_PIS"], required=True)
    bc_cofins = find_col(df, ["VL_BC_COFINS", "BC_COFINS", "BASE_COFINS", "BASE_DE_COFINS", "VALOR_BC_COFINS"], required=True)

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


def cruzar_icms_pis(
    icms_key: pd.DataFrame,
    pis_key: pd.DataFrame,
    tolerancia: float,
    aliquota_pis: float = 0.0165,
    aliquota_cofins: float = 0.0760,
) -> pd.DataFrame:
    cruz = icms_key.merge(pis_key, on="CHAVE", how="outer")
    cruz["COMPETENCIA"] = cruz["COMPETENCIA"].fillna("SEM_DATA")
    numeric_cols = [
        "VL_OPR_ICMS", "VL_BC_ICMS", "VL_ICMS", "BASE_ESPERADA_SEM_ICMS",
        "VL_OPERACAO_PISCOFINS", "VL_BC_PIS", "VL_BC_COFINS"
    ]
    for col in numeric_cols:
        if col in cruz.columns:
            cruz[col] = pd.to_numeric(cruz[col], errors="coerce").fillna(0.0)

    aliquota_total = float(aliquota_pis) + float(aliquota_cofins)

    # Nova lógica solicitada:
    # crédito/recalculo apurado diretamente sobre a BASE_ESPERADA_SEM_ICMS.
    # No Excel, esta coluna fica logo depois da BASE_ESPERADA_SEM_ICMS,
    # equivalente ao cálculo manual: H * alíquota PIS/COFINS.
    cruz["CREDITO_PISCOFINS_BASE_ESPERADA"] = cruz["BASE_ESPERADA_SEM_ICMS"] * aliquota_total
    cruz["ALIQUOTA_PIS_COFINS"] = aliquota_total

    cruz["DIF_PIS_VS_BASE_ESPERADA"] = cruz["VL_BC_PIS"] - cruz["BASE_ESPERADA_SEM_ICMS"]
    cruz["DIF_COFINS_VS_BASE_ESPERADA"] = cruz["VL_BC_COFINS"] - cruz["BASE_ESPERADA_SEM_ICMS"]
    cruz["DIF_PIS_VS_OPERACAO"] = cruz["VL_BC_PIS"] - cruz["VL_OPR_ICMS"]
    cruz["DIF_COFINS_VS_OPERACAO"] = cruz["VL_BC_COFINS"] - cruz["VL_OPR_ICMS"]
    cruz["STATUS"] = cruz.apply(lambda r: classify_row(r, tolerancia), axis=1)

    # Mantido apenas como indicador auxiliar da lógica anterior, para comparação.
    cruz["ICMS_POTENCIAL_INCLUIDO_ANTERIOR"] = np.where(
        cruz["STATUS"].isin(["ICMS INCLUÍDO", "EXCLUSÃO PARCIAL"]),
        np.minimum(np.maximum(cruz["DIF_PIS_VS_BASE_ESPERADA"], 0), cruz["VL_ICMS"]),
        0.0,
    )

    ordem = [
        "CHAVE", "COMPETENCIA", "VL_OPR_ICMS", "VL_BC_ICMS", "VL_ICMS",
        "CFOP_LISTA", "CST_ICMS_LISTA", "BASE_ESPERADA_SEM_ICMS",
        "CREDITO_PISCOFINS_BASE_ESPERADA", "ALIQUOTA_PIS_COFINS",
        "REGISTRO", "VL_OPERACAO_PISCOFINS", "VL_BC_PIS", "VL_BC_COFINS",
        "CFOP_PISCOFINS_LISTA", "CST_PIS_LISTA",
        "DIF_PIS_VS_BASE_ESPERADA", "DIF_COFINS_VS_BASE_ESPERADA",
        "DIF_PIS_VS_OPERACAO", "DIF_COFINS_VS_OPERACAO",
        "STATUS", "ICMS_POTENCIAL_INCLUIDO_ANTERIOR"
    ]
    existentes = [c for c in ordem if c in cruz.columns]
    demais = [c for c in cruz.columns if c not in existentes]
    return cruz[existentes + demais]

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
            "BASE_ESPERADA_SEM_ICMS": df["BASE_ESPERADA_SEM_ICMS"].sum(),
            "CREDITO_PISCOFINS_BASE_ESPERADA": df["CREDITO_PISCOFINS_BASE_ESPERADA"].sum(),
            "VL_ICMS_TOTAL": df["VL_ICMS"].sum(),
        })
    return pd.DataFrame(rows)


def _lista_contem_codigo(valor, codigo: str) -> bool:
    """
    Verifica se uma lista de CSTs contém determinado código.
    Exemplo: '000, 020' contém '000'.
    """
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
    Aba 07_potencial_credito — versão final.

    Regra:
    A aba 07 deve ser o resumo mensal da aba 04 após os filtros:

    - CST ICMS = 000
    - CST PIS/COFINS = 01
    - STATUS = ICMS INCLUÍDO

    O valor consolidado deve vir da coluna:
    CREDITO_PISCOFINS_BASE_ESPERADA

    Assim, o total da aba 07 deve bater com a soma da aba 04
    quando os mesmos filtros forem aplicados.
    """

    frames = []

    for nome, df in cruzamentos.items():
        if df is None or df.empty:
            continue

        base = df.copy()

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

        colunas_numericas = [
            "VL_OPR_ICMS",
            "VL_ICMS",
            "BASE_ESPERADA_SEM_ICMS",
            "VL_BC_PIS",
            "VL_BC_COFINS",
            "ICMS_POTENCIAL_INCLUIDO_ANTERIOR",
            "CREDITO_PISCOFINS_BASE_ESPERADA",
        ]

        for coluna in colunas_numericas:
            if coluna in elegivel.columns:
                elegivel[coluna] = pd.to_numeric(elegivel[coluna], errors="coerce").fillna(0.0)

        agg_dict = {
            "QTD_CHAVES_ELEGIVEIS": ("CHAVE", "nunique"),
            "QTD_REGISTROS_ELEGIVEIS": ("CHAVE", "size"),
            "CREDITO_PISCOFINS_BASE_ESPERADA": ("CREDITO_PISCOFINS_BASE_ESPERADA", "sum"),
        }

        for coluna in [
            "VL_OPR_ICMS",
            "VL_ICMS",
            "BASE_ESPERADA_SEM_ICMS",
            "VL_BC_PIS",
            "VL_BC_COFINS",
            "ICMS_POTENCIAL_INCLUIDO_ANTERIOR",
        ]:
            if coluna in elegivel.columns:
                agg_dict[coluna] = (coluna, "sum")

        tmp = elegivel.groupby("COMPETENCIA", dropna=False).agg(**agg_dict).reset_index()

        tmp.insert(1, "ANALISE", nome)
        tmp["REGIME"] = regime if regime else "Não informado"
        tmp["ALIQUOTA_PIS"] = float(aliquota_pis)
        tmp["ALIQUOTA_COFINS"] = float(aliquota_cofins)
        tmp["ALIQUOTA_TOTAL_PIS_COFINS"] = float(aliquota_pis) + float(aliquota_cofins)

        # Mantém nomes também como crédito total para facilitar leitura no Excel.
        tmp["CREDITO_TOTAL"] = tmp["CREDITO_PISCOFINS_BASE_ESPERADA"]

        if "ICMS_POTENCIAL_INCLUIDO_ANTERIOR" in tmp.columns:
            tmp = tmp.rename(
                columns={
                    "ICMS_POTENCIAL_INCLUIDO_ANTERIOR": "ICMS_POTENCIAL_INCLUIDO"
                }
            )

        tmp["CRITERIO"] = (
            "Resumo da aba 04 filtrado por CFOP 5102 + CST ICMS 000 + "
            "CST PIS/COFINS 01 + STATUS ICMS INCLUÍDO; "
            "valor = soma de CREDITO_PISCOFINS_BASE_ESPERADA"
        )

        frames.append(tmp)

    if not frames:
        return pd.DataFrame(
            columns=[
                "COMPETENCIA",
                "ANALISE",
                "REGIME",
                "QTD_CHAVES_ELEGIVEIS",
                "QTD_REGISTROS_ELEGIVEIS",
                "CREDITO_PISCOFINS_BASE_ESPERADA",
                "CREDITO_TOTAL",
                "ALIQUOTA_PIS",
                "ALIQUOTA_COFINS",
                "ALIQUOTA_TOTAL_PIS_COFINS",
                "CRITERIO",
            ]
        )

    final = pd.concat(frames, ignore_index=True)
    final = final.sort_values(["ANALISE", "COMPETENCIA"]).reset_index(drop=True)

    ordem = [
        "COMPETENCIA",
        "ANALISE",
        "REGIME",
        "QTD_CHAVES_ELEGIVEIS",
        "QTD_REGISTROS_ELEGIVEIS",
        "VL_OPR_ICMS",
        "VL_ICMS",
        "BASE_ESPERADA_SEM_ICMS",
        "VL_BC_PIS",
        "VL_BC_COFINS",
        "ICMS_POTENCIAL_INCLUIDO",
        "CREDITO_PISCOFINS_BASE_ESPERADA",
        "CREDITO_TOTAL",
        "ALIQUOTA_PIS",
        "ALIQUOTA_COFINS",
        "ALIQUOTA_TOTAL_PIS_COFINS",
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
