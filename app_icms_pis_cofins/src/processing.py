import pandas as pd

from src.utils import (
    normalizar_colunas,
    preparar_colunas_numericas,
    gerar_potencial_credito_por_competencia
)


def ler_excel_normalizado(arquivo, aba):
    df = pd.read_excel(
        arquivo,
        sheet_name=aba,
        dtype=str,
        engine="openpyxl"
    )
    return normalizar_colunas(df)


def localizar_aba(nome_base, abas):
    """
    Localiza abas com nomes como:
    C190
    C190 - Analítico
    C170 - Itens da Nota
    C175 - Analítico
    """
    nome_base = nome_base.upper()

    for aba in abas:
        if str(aba).upper().startswith(nome_base):
            return aba

    return None


def preparar_c190(df):
    df = normalizar_colunas(df)

    colunas_numericas = [
        "VL_OPR",
        "VL_BC_ICMS",
        "VL_ICMS",
        "VALOR_OPERACAO",
        "BASE_ICMS",
        "VALOR_ICMS",
        "SOMA_DE_VALOR_ICMS"
    ]

    return preparar_colunas_numericas(df, colunas_numericas)


def preparar_pis_cofins(df):
    df = normalizar_colunas(df)

    colunas_numericas = [
        "VL_ITEM",
        "VL_OPR",
        "VL_BC_PIS",
        "VL_BC_COFINS",
        "BASE_ESPERADA_SEM_ICMS",
        "ICMS_POTENCIAL_INCLUIDO",
        "ICMS_POTENCIAL_INCLUIDO_ANTERIOR",
        "DIFERENCA_BASE",
        "CREDITO_PIS",
        "CREDITO_COFINS",
        "CREDITO_TOTAL"
    ]

    return preparar_colunas_numericas(df, colunas_numericas)


def processar_arquivos(
    arquivo_icms,
    arquivo_pis,
    modo,
    regime,
    aliquota_pis,
    aliquota_cofins
):
    """
    Processa os arquivos e monta o dicionário de abas para exportação.

    Observação:
    Esta versão preserva a estrutura já existente e corrige principalmente:
    - UX do regime tributário
    - geração da aba 07_potencial_credito
    - filtro de elegibilidade
    """

    xls_icms = pd.ExcelFile(arquivo_icms)
    xls_pis = pd.ExcelFile(arquivo_pis)

    aba_c190 = localizar_aba("C190", xls_icms.sheet_names)
    aba_c170 = localizar_aba("C170", xls_pis.sheet_names)
    aba_c175 = localizar_aba("C175", xls_pis.sheet_names)

    resultado = {}

    if aba_c190:
        df_c190 = preparar_c190(
            pd.read_excel(
                arquivo_icms,
                sheet_name=aba_c190,
                dtype=str,
                engine="openpyxl"
            )
        )
        resultado["02_icms_c190_base"] = df_c190

    df_cruzamento_c175 = pd.DataFrame()
    df_cruzamento_c170 = pd.DataFrame()

    if modo in ["C170", "AMBOS"] and aba_c170:
        df_c170 = preparar_pis_cofins(
            pd.read_excel(
                arquivo_pis,
                sheet_name=aba_c170,
                dtype=str,
                engine="openpyxl"
            )
        )
        resultado["03_pis_cofins_c170"] = df_c170

        # Caso o seu projeto já tenha uma função de cruzamento C170,
        # ela pode ser chamada aqui. Por enquanto, preservamos a base carregada.
        df_cruzamento_c170 = df_c170.copy()
        resultado["04_cruzamento_c170"] = df_cruzamento_c170

    if modo in ["C175", "AMBOS"] and aba_c175:
        df_c175 = preparar_pis_cofins(
            pd.read_excel(
                arquivo_pis,
                sheet_name=aba_c175,
                dtype=str,
                engine="openpyxl"
            )
        )
        resultado["03_pis_cofins_c175"] = df_c175

        # Caso o seu projeto já tenha uma função de cruzamento C175,
        # ela pode ser chamada aqui. Por enquanto, preservamos a base carregada.
        df_cruzamento_c175 = df_c175.copy()
        resultado["04_cruzamento_c175"] = df_cruzamento_c175

    # Define a base para potencial crédito.
    # Prioriza C175 porque foi a aba mencionada na sua validação atual.
    if not df_cruzamento_c175.empty:
        base_credito = df_cruzamento_c175
    elif not df_cruzamento_c170.empty:
        base_credito = df_cruzamento_c170
    else:
        base_credito = pd.DataFrame()

    resultado["07_potencial_credito"] = gerar_potencial_credito_por_competencia(
        df_cruzamento=base_credito,
        aliquota_pis=aliquota_pis,
        aliquota_cofins=aliquota_cofins,
        regime=regime
    )

    resultado["08_parametros"] = pd.DataFrame(
        [
            {
                "PARAMETRO": "Regime tributário",
                "VALOR": regime
            },
            {
                "PARAMETRO": "Alíquota PIS",
                "VALOR": aliquota_pis
            },
            {
                "PARAMETRO": "Alíquota COFINS",
                "VALOR": aliquota_cofins
            },
            {
                "PARAMETRO": "Critério potencial crédito",
                "VALOR": "CST ICMS 000 + CST PIS/COFINS 01 + STATUS ICMS INCLUÍDO"
            },
            {
                "PARAMETRO": "Modo de análise",
                "VALOR": modo
            }
        ]
    )

    return resultado
