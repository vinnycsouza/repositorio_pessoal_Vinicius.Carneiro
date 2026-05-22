from pathlib import Path
from datetime import date
import pandas as pd

from .utils import normalize_columns, find_col, to_number, normalize_key, competence_from_date


TABELA_ALIQUOTAS = Path(__file__).parent / "tabelas" / "aliquotas_icms_uf_2021_2026.csv"


def carregar_tabela_aliquotas() -> pd.DataFrame:
    df = pd.read_csv(TABELA_ALIQUOTAS, dtype=str, sep=";")
    df["INICIO_VIGENCIA"] = pd.to_datetime(df["INICIO_VIGENCIA"], errors="coerce")
    df["FIM_VIGENCIA"] = pd.to_datetime(df["FIM_VIGENCIA"], errors="coerce")
    df["ALIQUOTA_ICMS"] = to_number(df["ALIQUOTA_ICMS"]) / 100
    df["UF"] = df["UF"].astype(str).str.upper().str.strip()
    return df


def listar_ufs_aliquotas() -> list[str]:
    try:
        df = carregar_tabela_aliquotas()
        return sorted(df["UF"].dropna().unique().tolist())
    except Exception:
        return [
            "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
            "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
            "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
        ]


def _lista_contem_codigo(valor, codigo: str) -> bool:
    if pd.isna(valor):
        return False

    partes = [
        str(p).strip().zfill(len(codigo))
        for p in str(valor).replace(";", ",").split(",")
        if str(p).strip() != ""
    ]
    return codigo in partes


def _coluna_ou_zero(df: pd.DataFrame, coluna: str):
    if coluna and coluna in df.columns:
        return to_number(df[coluna])
    return 0.0


def _coluna_ou_vazio(df: pd.DataFrame, coluna: str):
    if coluna and coluna in df.columns:
        return df[coluna].astype(str).str.strip()
    return ""


def _normalizar_nome_coluna_local(valor) -> str:
    """
    Normalização local para comparar cabeçalhos com acento, hífen e espaços.
    """
    import unicodedata
    import re

    texto = str(valor).strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9]+", "_", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")
    return texto


def _primeira_existente_manual(df: pd.DataFrame, possibilidades: list[str]):
    """
    Fallback para encontrar coluna quando find_col não reconhece alguma variação.

    Agora compara:
    - nome literal
    - nome em maiúsculo
    - nome normalizado sem acento/espaço/hífen
    """
    cols_upper = {str(c).upper().strip(): c for c in df.columns}
    cols_norm = {_normalizar_nome_coluna_local(c): c for c in df.columns}

    for nome in possibilidades:
        nome_upper = str(nome).upper().strip()
        nome_norm = _normalizar_nome_coluna_local(nome)

        if nome_upper in cols_upper:
            return cols_upper[nome_upper]

        if nome_norm in cols_norm:
            return cols_norm[nome_norm]

    for nome in possibilidades:
        nome_upper = str(nome).upper().strip()
        nome_norm = _normalizar_nome_coluna_local(nome)

        for col_upper, col_original in cols_upper.items():
            if nome_upper and (nome_upper in col_upper or col_upper in nome_upper):
                return col_original

        for col_norm, col_original in cols_norm.items():
            if nome_norm and (nome_norm in col_norm or col_norm in nome_norm):
                return col_original

    return None


def _buscar_aliquota_por_uf_competencia(uf: str, competencia: str, tabela: pd.DataFrame) -> tuple[float, str, str]:
    try:
        data_comp = pd.to_datetime(str(competencia) + "-01", errors="coerce")
    except Exception:
        data_comp = pd.NaT

    if pd.isna(data_comp):
        return 0.0, "NÃO LOCALIZADO", "Competência inválida"

    base = tabela[
        (tabela["UF"].astype(str).str.upper() == str(uf).upper())
        & (tabela["INICIO_VIGENCIA"] <= data_comp)
        & (tabela["FIM_VIGENCIA"] >= data_comp)
    ].copy()

    if base.empty:
        return 0.0, "NÃO LOCALIZADO", "Alíquota não localizada para UF/competência"

    linha = base.iloc[0]
    return float(linha["ALIQUOTA_ICMS"]), str(linha.get("FONTE", "")), str(linha.get("OBSERVACAO", ""))


def _preparar_contribuicoes_st(df: pd.DataFrame, registro: str) -> pd.DataFrame:
    df = normalize_columns(df)

    chave = _primeira_existente_manual(df, ["CHV_NFE", "CHAVE", "CHAVE_NFE", "CHAVE_NF", "CHAVE_C100", "CHAVE_DE_ACESSO_C100"])
    cfop = _primeira_existente_manual(df, ["CFOP"])
    cst_pis = _primeira_existente_manual(
        df,
        [
            "CST_PIS",
            "CST - PIS",
            "CST PIS",
            "CST",
            "CST_DE_PIS",
            "CST DO PIS",
        ],
    )
    cst_cofins = _primeira_existente_manual(
        df,
        [
            "CST_COFINS",
            "CST COFINS",
            "CST - COFINS",
            "CST_DE_COFINS",
            "CST DO COFINS",
        ],
    )
    dt_doc = _primeira_existente_manual(
        df,
        [
            "DT_DOC",
            "DATA",
            "DATA_DOC",
            "DT_E_S",
            "DATA_DE_EMISSAO",
            "DATA DE EMISSÃO",
            "DATA DE EMISSAO",
        ],
    )
    mes = _primeira_existente_manual(
        df,
        [
            "COMPETENCIA",
            "MÊS",
            "MES",
            "Mês",
            "MES_ANO",
            "MÊS_ANO",
            "PERIODO",
            "PERÍODO",
        ],
    )

    valor_op = _primeira_existente_manual(
        df,
        [
            "VL_OPERACAO",
            "VL_OPR",
            "VALOR_OPERACAO",
            "VALOR_DA_OPERACAO",
            "VALOR_DA_OPERAÇÃO",
            "VALOR DA OPERACAO",
            "VALOR DA OPERAÇÃO",
            "VALOR DE OPERAÇÃO",
            "VALOR DE OPERACAO",
            "VALOR_DA_OPERACAO_C175",
            "VL_ITEM",
            "VALOR_ITEM",
            "SOMA_DE_VALOR_DA_OPERACAO",
            "SOMA_DE_VALOR_OPERACAO",
            "SOMA_DE_VALOR_ITEM",
            "SOMA_DE_VALOR_DO_ITEM",
            "SOMA_DE_VALOR_TOTAL_DO_ITEM",
            "VALOR_TOTAL_DO_PRODUTO",
        ],
    )

    desconto = _primeira_existente_manual(
        df,
        [
            "VL_DESC",
            "DESCONTO",
            "VALOR_DESCONTO",
            "VALOR_DE_DESCONTO",
            "VALOR DE DESCONTO",
            "VALOR DO DESCONTO",
            "VL_DESCONTO",
            "SOMA_DE_VALOR_DO_DESCONTO",
            "SOMA_DE_VALOR_DESCONTO",
        ],
    )

    bc_pis = _primeira_existente_manual(
        df,
        [
            "VL_BC_PIS",
            "BC_PIS",
            "BASE_PIS",
            "BASE_DE_PIS",
            "VALOR_BC_PIS",
            "VALOR BC PIS",
            "VALOR DA BC PIS",
            "BASE DE CÁLCULO PIS",
            "BASE DE CALCULO PIS",
            "SOMA_DE_VALOR_BC_PIS",
            "SOMA_DE_BASE_PIS",
        ],
    )

    bc_cofins = _primeira_existente_manual(
        df,
        [
            "VL_BC_COFINS",
            "BC_COFINS",
            "BASE_COFINS",
            "BASE_DE_COFINS",
            "VALOR_BC_COFINS",
            "VALOR BC COFINS",
            "VALOR DA BC COFINS",
            "BASE DE CÁLCULO COFINS",
            "BASE DE CALCULO COFINS",
            "SOMA_DE_VALOR_BC_COFINS",
            "SOMA_DE_BASE_COFINS",
        ],
    )

    out = pd.DataFrame(index=df.index)
    out["REGISTRO"] = registro
    out["CHAVE"] = normalize_key(df[chave]) if chave else ""
    out["CFOP"] = _coluna_ou_vazio(df, cfop)
    out["CST_PIS"] = _coluna_ou_vazio(df, cst_pis)
    out["CST_COFINS"] = _coluna_ou_vazio(df, cst_cofins) if cst_cofins else out["CST_PIS"]

    if mes:
        comp = df[mes].astype(str).str.strip()
        datas = pd.to_datetime(comp, errors="coerce", dayfirst=True)
        out["COMPETENCIA"] = datas.dt.strftime("%Y-%m")
        out["COMPETENCIA"] = out["COMPETENCIA"].fillna(
            comp.str.extract(r"(\d{4}-\d{2})", expand=False)
        )
        out["COMPETENCIA"] = out["COMPETENCIA"].fillna(
            comp.str.extract(r"(\d{2}/\d{4})", expand=False)
        )

        # Hotfix v9.3:
        # Garante string antes de usar .str, pois a coluna Mês pode vir como número/data.
        out["COMPETENCIA"] = out["COMPETENCIA"].astype("string")
        out["COMPETENCIA"] = out["COMPETENCIA"].str.replace(
            r"^(\d{2})/(\d{4})$",
            r"\2-\1",
            regex=True
        )
        out["COMPETENCIA"] = out["COMPETENCIA"].fillna("SEM_DATA")
    elif dt_doc:
        out["COMPETENCIA"] = competence_from_date(df[dt_doc])
    else:
        out["COMPETENCIA"] = "SEM_DATA"

    out["VL_OPERACAO"] = _coluna_ou_zero(df, valor_op)
    out["VL_DESCONTO"] = _coluna_ou_zero(df, desconto)
    out["VL_BC_PIS"] = _coluna_ou_zero(df, bc_pis)
    out["VL_BC_COFINS"] = _coluna_ou_zero(df, bc_cofins)

    out["COLUNA_ORIGEM_OPERACAO"] = valor_op or "NÃO LOCALIZADA"
    out["COLUNA_ORIGEM_DESCONTO"] = desconto or "NÃO LOCALIZADA"
    out["COLUNA_ORIGEM_BC_PIS"] = bc_pis or "NÃO LOCALIZADA"
    out["COLUNA_ORIGEM_BC_COFINS"] = bc_cofins or "NÃO LOCALIZADA"

    return out.reset_index(drop=True)


def _adicionar_calculos(
    df: pd.DataFrame,
    uf: str,
    origem_aliquota: str,
    aliquota_icms_manual: float | None,
    tabela_aliquotas: pd.DataFrame,
    aliquota_pis: float,
    aliquota_cofins: float,
    regime: str,
    tolerancia_bc: float,
) -> pd.DataFrame:
    out = df.copy()

    # Hotfix: garante colunas mínimas mesmo quando a base filtrada vem vazia.
    for coluna in ["VL_OPERACAO", "VL_DESCONTO", "VL_BC_PIS", "VL_BC_COFINS"]:
        if coluna not in out.columns:
            out[coluna] = 0.0

    if "COMPETENCIA" not in out.columns:
        out["COMPETENCIA"] = "SEM_DATA"

    if "CHAVE" not in out.columns:
        out["CHAVE"] = ""

    out["UF"] = uf
    out["BASE_OPERACAO"] = out["VL_OPERACAO"] - out["VL_DESCONTO"]
    out["DIF_BC_PIS_VS_OPERACAO"] = out["VL_BC_PIS"] - out["BASE_OPERACAO"]
    out["BC_PIS_COMPATIVEL"] = out["DIF_BC_PIS_VS_OPERACAO"].abs() <= float(tolerancia_bc)

    if origem_aliquota == "Alíquota manual":
        out["ALIQUOTA_ICMS"] = float(aliquota_icms_manual or 0.0)
        out["FONTE_ALIQUOTA"] = "MANUAL"
        out["OBS_ALIQUOTA"] = "Alíquota informada pelo usuário"
    else:
        aliquotas = out["COMPETENCIA"].apply(
            lambda comp: _buscar_aliquota_por_uf_competencia(uf, comp, tabela_aliquotas)
        )
        out["ALIQUOTA_ICMS"] = aliquotas.apply(lambda x: x[0])
        out["FONTE_ALIQUOTA"] = aliquotas.apply(lambda x: x[1])
        out["OBS_ALIQUOTA"] = aliquotas.apply(lambda x: x[2])

    out["ICMS_ST_ESTIMADO"] = out["BASE_OPERACAO"] * out["ALIQUOTA_ICMS"]
    out["BASE_ESTIMADA_SEM_ST"] = out["BASE_OPERACAO"] - out["ICMS_ST_ESTIMADO"]

    out["ALIQUOTA_PIS"] = float(aliquota_pis)
    out["ALIQUOTA_COFINS"] = float(aliquota_cofins)
    out["ALIQUOTA_TOTAL_PIS_COFINS"] = float(aliquota_pis) + float(aliquota_cofins)

    out["CREDITO_PIS_ESTIMADO"] = out["ICMS_ST_ESTIMADO"] * out["ALIQUOTA_PIS"]
    out["CREDITO_COFINS_ESTIMADO"] = out["ICMS_ST_ESTIMADO"] * out["ALIQUOTA_COFINS"]
    out["CREDITO_TOTAL_ESTIMADO"] = out["CREDITO_PIS_ESTIMADO"] + out["CREDITO_COFINS_ESTIMADO"]

    out["REGIME_PIS_COFINS"] = regime
    out["TIPO_APURACAO"] = "ESTIMADO"
    out["CRITERIO"] = "CFOP 5405 + CST PIS/COFINS 01 + BC PIS compatível com operação líquida"
    return out


def processar_icms_st(
    xls_pis: pd.ExcelFile,
    get_sheet_name,
    modo: str,
    uf: str,
    data_inicio: date,
    data_fim: date,
    origem_aliquota: str,
    aliquota_icms_manual: float | None,
    aliquota_pis: float,
    aliquota_cofins: float,
    regime: str,
    tolerancia_bc: float,
) -> dict[str, pd.DataFrame]:
    registros = []
    if modo in ["C170", "C170 + C175"]:
        registros.append("C170")
    if modo in ["C175", "C170 + C175"]:
        registros.append("C175")

    frames = []
    for registro in registros:
        aba = get_sheet_name(xls_pis, registro)
        df = pd.read_excel(xls_pis, sheet_name=aba, dtype=object)
        frames.append(_preparar_contribuicoes_st(df, registro))

    if frames:
        base = pd.concat(frames, ignore_index=True)
    else:
        base = pd.DataFrame(
            columns=[
                "REGISTRO", "CHAVE", "CFOP", "CST_PIS", "CST_COFINS",
                "COMPETENCIA", "VL_OPERACAO", "VL_DESCONTO", "VL_BC_PIS", "VL_BC_COFINS"
            ]
        )

    tabela_aliquotas = carregar_tabela_aliquotas()

    if base.empty:
        return {
            "01_resumo_mensal": pd.DataFrame(),
            "02_analitico_5405": pd.DataFrame(),
            "03_elegiveis_credito": pd.DataFrame(),
            "04_divergencias": pd.DataFrame(),
            "05_parametros": pd.DataFrame(),
            "06_tabela_aliquotas_usada": tabela_aliquotas,
        }

    base["DATA_COMP"] = pd.to_datetime(base["COMPETENCIA"].astype(str) + "-01", errors="coerce")
    inicio = pd.to_datetime(data_inicio)
    fim = pd.to_datetime(data_fim)

    base = base[(base["DATA_COMP"] >= inicio) & (base["DATA_COMP"] <= fim)].copy()

    analitico_5405 = base[base["CFOP"].apply(lambda x: _lista_contem_codigo(x, "5405"))].copy()

    analitico_5405 = _adicionar_calculos(
        analitico_5405,
        uf=uf,
        origem_aliquota=origem_aliquota,
        aliquota_icms_manual=aliquota_icms_manual,
        tabela_aliquotas=tabela_aliquotas,
        aliquota_pis=aliquota_pis,
        aliquota_cofins=aliquota_cofins,
        regime=regime,
        tolerancia_bc=tolerancia_bc,
    )

    elegiveis = analitico_5405[
        analitico_5405["CST_PIS"].apply(lambda x: _lista_contem_codigo(x, "01"))
        & analitico_5405["CST_COFINS"].apply(lambda x: _lista_contem_codigo(x, "01"))
        & (analitico_5405["BC_PIS_COMPATIVEL"])
        & (analitico_5405["ALIQUOTA_ICMS"] > 0)
    ].copy()

    divergencias = analitico_5405[
        ~(
            analitico_5405["CST_PIS"].apply(lambda x: _lista_contem_codigo(x, "01"))
            & analitico_5405["CST_COFINS"].apply(lambda x: _lista_contem_codigo(x, "01"))
            & (analitico_5405["BC_PIS_COMPATIVEL"])
            & (analitico_5405["ALIQUOTA_ICMS"] > 0)
        )
    ].copy()

    if elegiveis.empty:
        resumo = pd.DataFrame(
            columns=[
                "COMPETENCIA", "UF", "ALIQUOTA_ICMS_MEDIA", "QTD_REGISTROS",
                "QTD_CHAVES", "BASE_OPERACAO", "ICMS_ST_ESTIMADO",
                "CREDITO_PIS_ESTIMADO", "CREDITO_COFINS_ESTIMADO",
                "CREDITO_TOTAL_ESTIMADO",
            ]
        )
    else:
        resumo = (
            elegiveis.groupby(["COMPETENCIA", "UF"], dropna=False)
            .agg(
                ALIQUOTA_ICMS_MEDIA=("ALIQUOTA_ICMS", "mean"),
                QTD_REGISTROS=("CHAVE", "size"),
                QTD_CHAVES=("CHAVE", "nunique"),
                BASE_OPERACAO=("BASE_OPERACAO", "sum"),
                ICMS_ST_ESTIMADO=("ICMS_ST_ESTIMADO", "sum"),
                CREDITO_PIS_ESTIMADO=("CREDITO_PIS_ESTIMADO", "sum"),
                CREDITO_COFINS_ESTIMADO=("CREDITO_COFINS_ESTIMADO", "sum"),
                CREDITO_TOTAL_ESTIMADO=("CREDITO_TOTAL_ESTIMADO", "sum"),
            )
            .reset_index()
            .sort_values(["COMPETENCIA", "UF"])
        )

    parametros = pd.DataFrame(
        [
            {"PARAMETRO": "Data da análise", "VALOR": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M:%S")},
            {"PARAMETRO": "Módulo", "VALOR": "ICMS-ST - análise preliminar"},
            {"PARAMETRO": "Modo", "VALOR": modo},
            {"PARAMETRO": "UF", "VALOR": uf},
            {"PARAMETRO": "Período inicial", "VALOR": str(data_inicio)},
            {"PARAMETRO": "Período final", "VALOR": str(data_fim)},
            {"PARAMETRO": "Origem da alíquota ICMS", "VALOR": origem_aliquota},
            {"PARAMETRO": "Regime PIS/COFINS", "VALOR": regime},
            {"PARAMETRO": "Alíquota PIS", "VALOR": aliquota_pis},
            {"PARAMETRO": "Alíquota COFINS", "VALOR": aliquota_cofins},
            {"PARAMETRO": "Tolerância BC PIS", "VALOR": tolerancia_bc},
            {"PARAMETRO": "Critério", "VALOR": "CFOP 5405 + CST PIS/COFINS 01 + BC PIS compatível com valor operação menos desconto"},
            {"PARAMETRO": "Aviso", "VALOR": "Cálculo estimativo; validar NCM/CEST/produto/FECOP/legislação estadual antes de usar como valor definitivo."},
        ]
    )

    tabela_usada = tabela_aliquotas[tabela_aliquotas["UF"].astype(str).str.upper() == str(uf).upper()].copy()

    for df in [analitico_5405, elegiveis, divergencias]:
        if "DATA_COMP" in df.columns:
            df.drop(columns=["DATA_COMP"], inplace=True)

    return {
        "01_resumo_mensal": resumo,
        "02_analitico_5405": analitico_5405,
        "03_elegiveis_credito": elegiveis,
        "04_divergencias": divergencias,
        "05_parametros": parametros,
        "06_tabela_aliquotas_usada": tabela_usada,
    }
