from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN = Side(style="thin", color="D9E1F2")
BORDER = Border(bottom=THIN)
ALERT_FILL = PatternFill("solid", fgColor="FCE4D6")
REVIEW_FILL = PatternFill("solid", fgColor="FFF2CC")
OK_FILL = PatternFill("solid", fgColor="E2F0D9")



def autosize(ws):
    widths = {}
    for row in ws.iter_rows():
        for cell in row:
            val = "" if cell.value is None else str(cell.value)
            widths[cell.column] = min(max(widths.get(cell.column, 0), len(val) + 2), 40)
    for col_idx, width in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width



def write_df(ws, df: pd.DataFrame, start_row: int = 1):
    for col_idx, name in enumerate(df.columns, start=1):
        cell = ws.cell(row=start_row, column=col_idx, value=name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER
    for row_idx, row in enumerate(df.itertuples(index=False), start=start_row + 1):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)



def export_report(report: pd.DataFrame, resumo: dict, output_path: Path) -> Path:
    wb = Workbook()
    ws_resumo = wb.active
    ws_resumo.title = "Resumo"

    ws_resumo["A1"] = "Levantamento de possível exclusão indevida do ICMS da base de PIS/COFINS"
    ws_resumo["A1"].font = Font(bold=True, size=12)
    ws_resumo["A3"] = "Itens analisados"
    ws_resumo["B3"] = resumo["itens_analisados"]
    ws_resumo["A4"] = "Potencial alto"
    ws_resumo["B4"] = resumo["itens_potencial_alto"]
    ws_resumo["A5"] = "Revisão manual"
    ws_resumo["B5"] = resumo["itens_revisao_manual"]
    ws_resumo["A6"] = "Sem cruzamento com ICMS/IPI"
    ws_resumo["B6"] = resumo["itens_sem_match"]
    ws_resumo["A7"] = "Crédito total estimado"
    ws_resumo["B7"] = resumo["credito_total_estimado"]
    ws_resumo["B7"].number_format = 'R$ #,##0.00'

    ws_resumo["A9"] = "Observação"
    ws_resumo["B9"] = (
        "O relatório é indiciário e deve ser validado com a tese aplicada ao caso, natureza das operações, "
        "CSTs, CFOPs, documentos de entrada/saída e tratamento de ICMS-ST."
    )
    ws_resumo["B9"].alignment = Alignment(wrap_text=True)
    ws_resumo.column_dimensions["A"].width = 28
    ws_resumo.column_dimensions["B"].width = 95

    ws_main = wb.create_sheet("Oportunidades")
    write_df(ws_main, report)

    currency_cols = {
        "Valor do Item",
        "Valor de ICMS",
        "Valor de ICMS ST",
        "Base de PIS Informada",
        "Base de COFINS Informada",
        "Base Esperada sem ICMS",
        "Diferença Base PIS",
        "Diferença Base COFINS",
        "Crédito PIS Estimado",
        "Crédito COFINS Estimado",
        "Crédito Total Estimado",
    }
    header_positions = {cell.value: cell.column for cell in ws_main[1]}
    for name, idx in header_positions.items():
        if name in currency_cols:
            for r in range(2, ws_main.max_row + 1):
                ws_main.cell(r, idx).number_format = 'R$ #,##0.00'

    if "Nível de Oportunidade" in header_positions:
        idx = header_positions["Nível de Oportunidade"]
        for r in range(2, ws_main.max_row + 1):
            value = ws_main.cell(r, idx).value
            row_fill = OK_FILL if value == "Sem oportunidade" else REVIEW_FILL
            if value == "Potencial alto":
                row_fill = ALERT_FILL
            for c in range(1, ws_main.max_column + 1):
                ws_main.cell(r, c).fill = row_fill

    autosize(ws_main)

    ws_revisao = wb.create_sheet("Revisão Manual")
    revisao = report[report["Nível de Oportunidade"] == "Revisão manual"].copy()
    write_df(ws_revisao, revisao if not revisao.empty else pd.DataFrame({"Mensagem": ["Nenhum item em revisão manual."]}))
    autosize(ws_revisao)

    ws_div = wb.create_sheet("Sem Cruzamento")
    sem_cruzamento = report[report["Cruzou com ICMS/IPI"] == "Não"].copy()
    write_df(ws_div, sem_cruzamento if not sem_cruzamento.empty else pd.DataFrame({"Mensagem": ["Todos os itens localizaram correspondência."]}))
    autosize(ws_div)

    wb.save(output_path)
    return output_path
