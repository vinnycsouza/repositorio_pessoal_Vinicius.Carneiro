from pathlib import Path
import pandas as pd


def _formatar_planilha(writer, sheet_name, df):
    workbook = writer.book
    worksheet = writer.sheets[sheet_name]

    header_format = workbook.add_format(
        {
            "bold": True,
            "bg_color": "#D9EAF7",
            "border": 1,
            "text_wrap": True
        }
    )

    money_format = workbook.add_format({"num_format": "#,##0.00"})
    percent_format = workbook.add_format({"num_format": "0.00%"})

    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, header_format)

    worksheet.freeze_panes(1, 0)
    worksheet.autofilter(0, 0, max(len(df), 1), max(len(df.columns) - 1, 0))

    for idx, col in enumerate(df.columns):
        col_upper = str(col).upper()

        largura = min(max(len(str(col)) + 2, 12), 35)
        worksheet.set_column(idx, idx, largura)

        if any(x in col_upper for x in ["VALOR", "BASE", "ICMS", "CREDITO", "VL_"]):
            worksheet.set_column(idx, idx, largura, money_format)

        if "ALIQUOTA" in col_upper:
            worksheet.set_column(idx, idx, largura, percent_format)


def exportar_excel(resultado):
    exports = Path("exports")
    exports.mkdir(exist_ok=True)

    caminho = exports / "investigacao_icms_pis_cofins.xlsx"

    with pd.ExcelWriter(
        caminho,
        engine="xlsxwriter",
        engine_kwargs={"options": {"constant_memory": True}}
    ) as writer:

        for nome_aba, df in resultado.items():
            if not isinstance(df, pd.DataFrame):
                continue

            sheet_name = str(nome_aba)[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            _formatar_planilha(writer, sheet_name, df)

    return caminho
