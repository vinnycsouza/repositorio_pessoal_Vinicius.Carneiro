from __future__ import annotations

import io

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


AZUL = "1F4E78"
AZUL_CLARO = "D9EAF7"


def _ajustar_planilha(ws) -> None:
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False
    for celula in ws[1]:
        celula.fill = PatternFill("solid", fgColor=AZUL)
        celula.font = Font(color="FFFFFF", bold=True)
        celula.alignment = Alignment(horizontal="center", vertical="center")
    for coluna in ws.columns:
        valores = [str(c.value or "") for c in coluna[:200]]
        largura = min(max(max(map(len, valores), default=0) + 2, 12), 48)
        ws.column_dimensions[get_column_letter(coluna[0].column)].width = largura


def gerar_excel_ecac(
    resumo: pd.DataFrame,
    documentos: pd.DataFrame,
    ocorrencias: pd.DataFrame,
) -> bytes:
    memoria = io.BytesIO()
    with pd.ExcelWriter(memoria, engine="openpyxl") as writer:
        resumo.to_excel(writer, sheet_name="Salário Família", index=False)
        documentos.to_excel(writer, sheet_name="Documentos", index=False)
        if not ocorrencias.empty:
            ocorrencias.to_excel(writer, sheet_name="Ocorrências", index=False)
        for ws in writer.book.worksheets:
            _ajustar_planilha(ws)
        principal = writer.book["Salário Família"]
        cabecalhos = {celula.value: celula.column for celula in principal[1]}
        coluna_valor = cabecalhos.get("salario_familia")
        if coluna_valor:
            for celula in principal.iter_cols(
                min_col=coluna_valor,
                max_col=coluna_valor,
                min_row=2,
            ):
                for item in celula:
                    item.number_format = 'R$ #,##0.00'
            principal.column_dimensions[get_column_letter(coluna_valor)].width = 20
    return memoria.getvalue()


def gerar_excel_comparativo(
    comparativo: pd.DataFrame,
    ecac: pd.DataFrame,
    levantamento: pd.DataFrame,
) -> bytes:
    memoria = io.BytesIO()
    with pd.ExcelWriter(memoria, engine="openpyxl") as writer:
        comparativo.to_excel(writer, sheet_name="Comparativo", index=False)
        ecac.to_excel(writer, sheet_name="Dados e-CAC", index=False)
        levantamento.to_excel(writer, sheet_name="Levantamento", index=False)
        for ws in writer.book.worksheets:
            _ajustar_planilha(ws)
            for celula in ws[1]:
                if "valor" in str(celula.value).lower() or "diferença" in str(celula.value).lower():
                    for item in ws.iter_cols(
                        min_col=celula.column,
                        max_col=celula.column,
                        min_row=2,
                    ):
                        for valor in item:
                            valor.number_format = 'R$ #,##0.00'
    return memoria.getvalue()

