from io import BytesIO
import pandas as pd


ORDEM_ABAS = [
    "01_resumo_mensal",
    "02_analitico_documental",
    "03_elegiveis_credito",
    "04_divergencias",
    "05_parametros",
    "06_tabela_aliquotas_usada",
    "07_diagnostico",
]


ORDEM_COLUNAS = {
    "01_resumo_mensal": [
        "COMPETENCIA",
        "UF",
        "ALIQUOTA_ICMS_MEDIA",
        "QTD_REGISTROS",
        "QTD_DOCUMENTOS",
        "BASE_OPERACAO_LIQUIDA",
        "ICMS_ST_ESTIMADO",
        "BASE_ESTIMADA_SEM_ICMS_ST",
        "CREDITO_PIS_ESTIMADO",
        "CREDITO_COFINS_ESTIMADO",
        "CREDITO_TOTAL_ESTIMADO",
    ],
    "02_analitico_documental": [
        "COMPETENCIA",
        "COMPETENCIA_ORIGINAL",
        "REGISTRO",
        "DOCUMENTO",
        "CHAVE",
        "NUMERO_NF",
        "CFOP",
        "CST_PIS",
        "CST_COFINS",
        "VL_OPERACAO",
        "VL_DESCONTO",
        "BASE_OPERACAO_LIQUIDA",
        "VL_BC_PIS",
        "VL_BC_COFINS",
        "DIF_BASE_OPERACAO_VS_BC_PIS",
        "BC_PIS_COMPATIVEL",
        "UF",
        "ALIQUOTA_ICMS",
        "ICMS_ST_ESTIMADO",
        "BASE_ESTIMADA_SEM_ICMS_ST",
        "REGIME_PIS_COFINS",
        "ALIQUOTA_PIS_CALCULO",
        "ALIQUOTA_COFINS_CALCULO",
        "ALIQUOTA_TOTAL_PIS_COFINS",
        "PIS_RECALCULADO_SEM_ST",
        "COFINS_RECALCULADO_SEM_ST",
        "PISCOFINS_RECALCULADO_SEM_ST",
        "CREDITO_PIS_ESTIMADO",
        "CREDITO_COFINS_ESTIMADO",
        "CREDITO_TOTAL_ESTIMADO",
        "STATUS_ANALISE",
        "TIPO_APURACAO",
        "CRITERIO",
        "FONTE_ALIQUOTA",
        "OBS_ALIQUOTA",
    ],
    "03_elegiveis_credito": [
        "COMPETENCIA",
        "DOCUMENTO",
        "CFOP",
        "CST_PIS",
        "CST_COFINS",
        "VL_OPERACAO",
        "VL_DESCONTO",
        "BASE_OPERACAO_LIQUIDA",
        "VL_BC_PIS",
        "DIF_BASE_OPERACAO_VS_BC_PIS",
        "ALIQUOTA_ICMS",
        "ICMS_ST_ESTIMADO",
        "BASE_ESTIMADA_SEM_ICMS_ST",
        "CREDITO_PIS_ESTIMADO",
        "CREDITO_COFINS_ESTIMADO",
        "CREDITO_TOTAL_ESTIMADO",
        "STATUS_ANALISE",
    ],
    "04_divergencias": [
        "COMPETENCIA",
        "DOCUMENTO",
        "CFOP",
        "CST_PIS",
        "CST_COFINS",
        "VL_OPERACAO",
        "VL_DESCONTO",
        "BASE_OPERACAO_LIQUIDA",
        "VL_BC_PIS",
        "DIF_BASE_OPERACAO_VS_BC_PIS",
        "BC_PIS_COMPATIVEL",
        "ALIQUOTA_ICMS",
        "STATUS_ANALISE",
        "CRITERIO",
        "ERRO",
    ],
}


def _reordenar_colunas(nome_aba: str, df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()

    if df.empty:
        ordem = ORDEM_COLUNAS.get(nome_aba)
        if ordem:
            return pd.DataFrame(columns=ordem)
        return df

    ordem = ORDEM_COLUNAS.get(nome_aba, [])
    existentes = [c for c in ordem if c in df.columns]
    demais = [c for c in df.columns if c not in existentes]

    return df[existentes + demais]


def _formatar(writer, dfs: dict[str, pd.DataFrame]):
    workbook = writer.book

    header_fmt = workbook.add_format(
        {
            "bold": True,
            "text_wrap": True,
            "valign": "top",
            "border": 1,
            "bg_color": "#D9EAF7",
        }
    )

    money_fmt = workbook.add_format({"num_format": 'R$ #,##0.00'})
    percent_fmt = workbook.add_format({"num_format": "0.00%"})
    int_fmt = workbook.add_format({"num_format": "#,##0"})
    text_fmt = workbook.add_format({"num_format": "@"})

    eligible_fmt = workbook.add_format({"bg_color": "#E2F0D9"})
    review_fmt = workbook.add_format({"bg_color": "#FFF2CC"})
    error_fmt = workbook.add_format({"bg_color": "#F4CCCC"})

    for sheet_name, df in dfs.items():
        worksheet = writer.sheets[sheet_name]

        max_row = max(len(df), 1)
        max_col = max(len(df.columns) - 1, 0)

        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, max_row, max_col)

        for col_num, col_name in enumerate(df.columns):
            worksheet.write(0, col_num, col_name, header_fmt)

            col_upper = str(col_name).upper()
            width = min(max(len(str(col_name)) + 2, 12), 42)

            if "ALIQUOTA" in col_upper:
                worksheet.set_column(col_num, col_num, width, percent_fmt)
            elif any(token in col_upper for token in ["VALOR", "VL_", "BASE", "BC_", "ICMS", "CREDITO", "PIS", "COFINS", "DIF_"]):
                if "CST" in col_upper or "STATUS" in col_upper or "CRITERIO" in col_upper:
                    worksheet.set_column(col_num, col_num, width, text_fmt)
                else:
                    worksheet.set_column(col_num, col_num, width, money_fmt)
            elif any(token in col_upper for token in ["QTD", "QUANTIDADE"]):
                worksheet.set_column(col_num, col_num, width, int_fmt)
            else:
                worksheet.set_column(col_num, col_num, width, text_fmt)

        # Formatação condicional para STATUS_ANALISE, quando existir.
        if "STATUS_ANALISE" in df.columns and len(df) > 0:
            col_idx = list(df.columns).index("STATUS_ANALISE")
            col_letter = _excel_col(col_idx)
            status_range = f"{col_letter}2:{col_letter}{len(df)+1}"

            worksheet.conditional_format(
                status_range,
                {
                    "type": "text",
                    "criteria": "containing",
                    "value": "ELEGÍVEL",
                    "format": eligible_fmt,
                },
            )
            worksheet.conditional_format(
                status_range,
                {
                    "type": "text",
                    "criteria": "containing",
                    "value": "INCOMPATÍVEL",
                    "format": review_fmt,
                },
            )
            worksheet.conditional_format(
                status_range,
                {
                    "type": "text",
                    "criteria": "containing",
                    "value": "DIFERENTE",
                    "format": review_fmt,
                },
            )
            worksheet.conditional_format(
                status_range,
                {
                    "type": "text",
                    "criteria": "containing",
                    "value": "SEM",
                    "format": error_fmt,
                },
            )


def _excel_col(idx: int) -> str:
    """
    Converte índice 0-based em letra de coluna Excel.
    """
    letters = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def gerar_excel_icms_st(resultado: dict[str, pd.DataFrame]) -> bytes:
    """
    Exporta o Excel do módulo ICMS-ST em formato documental/analítico.

    Abas:
    01_resumo_mensal
    02_analitico_documental
    03_elegiveis_credito
    04_divergencias
    05_parametros
    06_tabela_aliquotas_usada
    07_diagnostico
    """
    output = BytesIO()

    dfs_ordenados = {}

    for nome in ORDEM_ABAS:
        df = resultado.get(nome, pd.DataFrame())
        dfs_ordenados[nome] = _reordenar_colunas(nome, df)

    # Mantém qualquer aba extra que eventualmente venha no resultado
    for nome, df in resultado.items():
        if nome not in dfs_ordenados and isinstance(df, pd.DataFrame):
            dfs_ordenados[nome] = df

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for nome, df in dfs_ordenados.items():
            sheet = nome[:31]
            df.to_excel(writer, index=False, sheet_name=sheet)

        _formatar(
            writer,
            {nome[:31]: df for nome, df in dfs_ordenados.items()}
        )

    return output.getvalue()
