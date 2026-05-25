from io import BytesIO
import pandas as pd


def _format_workbook(writer, dfs: dict[str, pd.DataFrame]):
    workbook = writer.book
    header_fmt = workbook.add_format({"bold": True, "text_wrap": True, "valign": "top", "border": 1})
    money_fmt = workbook.add_format({"num_format": "R$ #,##0.00"})

    for sheet_name, df in dfs.items():
        worksheet = writer.sheets[sheet_name]
        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, max(len(df), 1), max(len(df.columns) - 1, 0))

        for col_num, col_name in enumerate(df.columns):
            worksheet.write(0, col_num, col_name, header_fmt)
            width = min(max(len(str(col_name)) + 2, 12), 45)
            worksheet.set_column(col_num, col_num, width)
            if any(token in col_name.upper() for token in ["VL_", "VALOR", "ICMS", "CREDITO", "BASE", "BC_", "DIF_"]):
                worksheet.set_column(col_num, col_num, width, money_fmt)


def gerar_excel(
    resumo: pd.DataFrame,
    icms_base: pd.DataFrame,
    cruz_c170: pd.DataFrame | None,
    cruz_c175: pd.DataFrame | None,
    comparativo: pd.DataFrame | None,
    divergencias: pd.DataFrame,
    credito: pd.DataFrame,
    parametros: pd.DataFrame,
) -> bytes:
    output = BytesIO()
    dfs: dict[str, pd.DataFrame] = {
        "01_resumo_geral": resumo,
        "02_icms_fiscal_base": icms_base,
    }
    if cruz_c170 is not None and not cruz_c170.empty:
        dfs["03_cruzamento_c170"] = cruz_c170
    if cruz_c175 is not None and not cruz_c175.empty:
        dfs["04_cruzamento_c175"] = cruz_c175
    if comparativo is not None and not comparativo.empty:
        dfs["05_comparativo_c170_c175"] = comparativo
    dfs["06_divergencias"] = divergencias
    dfs["07_potencial_credito"] = credito
    dfs["08_parametros"] = parametros

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for sheet, df in dfs.items():
            df.to_excel(writer, index=False, sheet_name=sheet[:31])
        _format_workbook(writer, dfs)

    return output.getvalue()
