import re
import unicodedata
import pandas as pd


def normalizar_texto(valor):
    """
    Normaliza texto para facilitar comparação de nomes de colunas:
    - remove acentos
    - deixa maiúsculo
    - troca caracteres especiais por _
    """
    if valor is None:
        return ""

    texto = str(valor).strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9]+", "_", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")

    return texto


def normalizar_colunas(df):
    df = df.copy()
    df.columns = [normalizar_texto(c) for c in df.columns]
    return df


def obter_aliquotas_por_regime(regime):
    """
    Retorna alíquotas padrão de PIS e COFINS.
    """
    if regime == "Lucro Real":
        return 0.0165, 0.076

    if regime == "Lucro Presumido":
        return 0.0065, 0.03

    return 0.0165, 0.076


def converter_numero_serie(valor):
    """
    Converte números que podem vir em formato brasileiro ou americano.
    """
    if pd.isna(valor):
        return 0.0

    texto = str(valor).strip()

    if texto == "":
        return 0.0

    texto = texto.replace("R$", "").replace(" ", "")

    # Formato brasileiro: 1.234,56
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        return float(texto)
    except Exception:
        return 0.0


def preparar_colunas_numericas(df, colunas):
    df = df.copy()

    for coluna in colunas:
        if coluna in df.columns:
            df[coluna] = df[coluna].apply(converter_numero_serie)

    return df


def primeira_coluna_existente(df, possibilidades):
    """
    Retorna a primeira coluna existente dentro de uma lista de possibilidades.
    """
    for coluna in possibilidades:
        coluna_norm = normalizar_texto(coluna)
        if coluna_norm in df.columns:
            return coluna_norm

    return None


def garantir_competencia(df):
    """
    Tenta garantir uma coluna COMPETENCIA.
    Caso não exista, tenta montar a partir de data.
    """
    df = df.copy()

    if "COMPETENCIA" in df.columns:
        return df

    possibilidades_data = [
        "DT_DOC",
        "DATA",
        "DATA_DOC",
        "DT_E_S",
        "DT_INI",
        "PERIODO",
        "MES"
    ]

    col_data = primeira_coluna_existente(df, possibilidades_data)

    if col_data:
        datas = pd.to_datetime(df[col_data], errors="coerce", dayfirst=True)
        df["COMPETENCIA"] = datas.dt.to_period("M").astype(str)
    else:
        df["COMPETENCIA"] = "SEM_COMPETENCIA"

    return df


def filtrar_operacoes_elegiveis_credito(df):
    """
    Critério fiscal definido para potencial crédito:

    CST ICMS = 000
    CST PIS/COFINS = 01
    STATUS = ICMS INCLUÍDO

    A função tenta encontrar variações comuns de nomes de colunas.
    """
    df = df.copy()

    col_cst_icms = primeira_coluna_existente(
        df,
        [
            "CST_ICMS",
            "CST_ICMS_LISTA",
            "CST ICMS",
            "CST"
        ]
    )

    col_cst_pis = primeira_coluna_existente(
        df,
        [
            "CST_PIS",
            "CST_PIS_LISTA",
            "CST PIS",
            "CST_PIS_COFINS",
            "CST PIS/COFINS"
        ]
    )

    col_cst_cofins = primeira_coluna_existente(
        df,
        [
            "CST_COFINS",
            "CST_COFINS_LISTA",
            "CST COFINS"
        ]
    )

    col_status = primeira_coluna_existente(
        df,
        [
            "STATUS",
            "CLASSIFICACAO",
            "SITUACAO",
            "RESULTADO"
        ]
    )

    if not col_cst_icms or not col_status:
        return df.iloc[0:0].copy()

    mask_icms = df[col_cst_icms].astype(str).str.zfill(3).eq("000")
    mask_status = df[col_status].astype(str).str.upper().str.contains("ICMS INCLU", na=False)

    if col_cst_pis:
        mask_pis = df[col_cst_pis].astype(str).str.zfill(2).eq("01")
    else:
        mask_pis = True

    if col_cst_cofins:
        mask_cofins = df[col_cst_cofins].astype(str).str.zfill(2).eq("01")
    else:
        mask_cofins = True

    return df[mask_icms & mask_pis & mask_cofins & mask_status].copy()


def localizar_coluna_icms_potencial(df):
    """
    Localiza a coluna que representa a diferença/base recuperável.
    """
    possibilidades = [
        "ICMS_POTENCIAL_INCLUIDO",
        "ICMS_POTENCIAL_INCLUIDO_ANTERIOR",
        "ICMS POTENCIAL INCLUIDO",
        "DIFERENCA_BASE",
        "DIF_BASE",
        "DIFERENCA",
        "VALOR_ICMS",
        "VL_ICMS",
        "SOMA_DE_VALOR_ICMS"
    ]

    return primeira_coluna_existente(df, possibilidades)


def gerar_potencial_credito_por_competencia(
    df_cruzamento,
    aliquota_pis,
    aliquota_cofins,
    regime
):
    """
    Gera a aba 07_potencial_credito a partir da aba de cruzamento,
    considerando apenas operações elegíveis.
    """
    if df_cruzamento is None or df_cruzamento.empty:
        return pd.DataFrame(
            columns=[
                "COMPETENCIA",
                "REGIME",
                "QTD_REGISTROS_ELEGIVEIS",
                "ICMS_POTENCIAL_INCLUIDO",
                "ALIQUOTA_PIS",
                "ALIQUOTA_COFINS",
                "CREDITO_PIS",
                "CREDITO_COFINS",
                "CREDITO_TOTAL",
                "CRITERIO"
            ]
        )

    df = normalizar_colunas(df_cruzamento)
    df = garantir_competencia(df)

    df_elegivel = filtrar_operacoes_elegiveis_credito(df)

    if df_elegivel.empty:
        return pd.DataFrame(
            columns=[
                "COMPETENCIA",
                "REGIME",
                "QTD_REGISTROS_ELEGIVEIS",
                "ICMS_POTENCIAL_INCLUIDO",
                "ALIQUOTA_PIS",
                "ALIQUOTA_COFINS",
                "CREDITO_PIS",
                "CREDITO_COFINS",
                "CREDITO_TOTAL",
                "CRITERIO"
            ]
        )

    col_icms_potencial = localizar_coluna_icms_potencial(df_elegivel)

    if not col_icms_potencial:
        df_elegivel["ICMS_POTENCIAL_INCLUIDO"] = 0.0
        col_icms_potencial = "ICMS_POTENCIAL_INCLUIDO"

    df_elegivel[col_icms_potencial] = df_elegivel[col_icms_potencial].apply(converter_numero_serie)

    resumo = (
        df_elegivel
        .groupby("COMPETENCIA", dropna=False)
        .agg(
            QTD_REGISTROS_ELEGIVEIS=(col_icms_potencial, "size"),
            ICMS_POTENCIAL_INCLUIDO=(col_icms_potencial, "sum")
        )
        .reset_index()
    )

    resumo["REGIME"] = regime
    resumo["ALIQUOTA_PIS"] = aliquota_pis
    resumo["ALIQUOTA_COFINS"] = aliquota_cofins
    resumo["CREDITO_PIS"] = resumo["ICMS_POTENCIAL_INCLUIDO"] * aliquota_pis
    resumo["CREDITO_COFINS"] = resumo["ICMS_POTENCIAL_INCLUIDO"] * aliquota_cofins
    resumo["CREDITO_TOTAL"] = resumo["CREDITO_PIS"] + resumo["CREDITO_COFINS"]
    resumo["CRITERIO"] = "CST ICMS 000 + CST PIS/COFINS 01 + ICMS INCLUÍDO"

    colunas = [
        "COMPETENCIA",
        "REGIME",
        "QTD_REGISTROS_ELEGIVEIS",
        "ICMS_POTENCIAL_INCLUIDO",
        "ALIQUOTA_PIS",
        "ALIQUOTA_COFINS",
        "CREDITO_PIS",
        "CREDITO_COFINS",
        "CREDITO_TOTAL",
        "CRITERIO"
    ]

    return resumo[colunas].sort_values("COMPETENCIA")
def normalize_column_name(texto):
    return normalizar_texto(texto)