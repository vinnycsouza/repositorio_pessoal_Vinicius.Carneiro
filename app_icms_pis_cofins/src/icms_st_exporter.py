from io import BytesIO
import pandas as pd


def _formatar(writer, dfs: dict[str, pd.DataFrame]):
    workbook = writer.book
    header_fmt = workbook.add_format({"bold": True, "text_wrap": True, "valign": "top", "border": 1})
    money_fmt = workbook.add_format({"num_format": "R$ #,##0.00"})
    percent_fmt = workbook.add_format({"num_format": "0.00%"})

    for sheet_name, df in dfs.items():
        worksheet = writer.sheets[sheet_name]
        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, max(len(df), 1), max(len(df.columns) - 1, 0))

        for col_num, col_name in enumerate(df.columns):
            worksheet.write(0, col_num, col_name, header_fmt)
            width = min(max(len(str(col_name)) + 2, 12), 45)
            col_upper = str(col_name).upper()
            if "ALIQUOTA" in col_upper:
                worksheet.set_column(col_num, col_num, width, percent_fmt)
            elif any(token in col_upper for token in ["VL_", "VALOR", "ICMS", "CREDITO", "BASE", "BC_", "DIF_"]):
                worksheet.set_column(col_num, col_num, width, money_fmt)
            else:
                worksheet.set_column(col_num, col_num, width)


def gerar_excel_icms_st(resultado: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for nome, df in resultado.items():
            if not isinstance(df, pd.DataFrame):
                continue
            sheet = nome[:31]
            df.to_excel(writer, index=False, sheet_name=sheet)
        _formatar(writer, {k[:31]: v for k, v in resultado.items() if isinstance(v, pd.DataFrame)})

    return output.getvalue()
