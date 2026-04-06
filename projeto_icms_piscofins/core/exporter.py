from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.utils import get_column_letter


NUMERIC_COLUMNS = {
    "Valor do Item",
    "Base de ICMS no PIS",
    "Valor de ICMS no PIS",
    "Base de ICMS no ICMS/IPI",
    "Valor de ICMS no ICMS/IPI",
    "Base de ICMS Final",
    "Valor de ICMS Final",
    "Base de ICMS ST",
    "Valor de ICMS ST",
    "Base de PIS",
    "Base de COFINS",
    "Diferença Base ICMS x PIS",
    "Diferença Base ICMS x COFINS",
}


def _set_widths(writer: pd.ExcelWriter, df: pd.DataFrame, sheet_name: str) -> None:
    ws = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns, start=1):
        max_len = len(str(col))
        if not df.empty:
            max_len = max(max_len, df[col].astype(str).map(len).max())
        ws.column_dimensions[get_column_letter(i)].width = min(max_len + 2, 40)


def _format_numeric(writer: pd.ExcelWriter, df: pd.DataFrame, sheet_name: str) -> None:
    ws = writer.sheets[sheet_name]
    header_idx = {name: idx for idx, name in enumerate(df.columns, start=1)}
    for col_name, idx in header_idx.items():
        if col_name in NUMERIC_COLUMNS:
            for row in range(2, ws.max_row + 1):
                ws.cell(row, idx).number_format = '#,##0.00'


def _build_resumo_df(report: pd.DataFrame, resumo: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["Itens analisados", resumo.get("itens_analisados", len(report))],
            ["Exclusão identificada", resumo.get("exclusao_identificada", 0)],
            ["Sem indício de exclusão", resumo.get("sem_indicio", 0)],
            ["Divergente / Revisar", resumo.get("divergente", 0)],
            ["Sem dados suficientes", resumo.get("sem_dados", 0)],
            ["Sem cruzamento com ICMS/IPI", resumo.get("sem_match", 0)],
            ["Linhas com Base de ICMS Final", resumo.get("com_base_icms_final", 0)],
            ["Linhas com Valor de ICMS Final", resumo.get("com_valor_icms_final", 0)],
        ],
        columns=["Indicador", "Valor"],
    )



def export_report(report: pd.DataFrame, resumo: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report_export = report.copy()
    for col in NUMERIC_COLUMNS:
        if col in report_export.columns:
            report_export[col] = pd.to_numeric(report_export[col], errors="coerce")

    resumo_df = _build_resumo_df(report_export, resumo)
    destaques = report_export[report_export["Status da Análise"] == "Exclusão identificada"].copy() if "Status da Análise" in report_export.columns else report_export.copy()
    divergentes = report_export[report_export["Status da Análise"] == "Divergente / Revisar"].copy() if "Status da Análise" in report_export.columns else report_export.iloc[0:0].copy()

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        resumo_df.to_excel(writer, sheet_name="Resumo", index=False)
        report_export.to_excel(writer, sheet_name="Relatorio Completo", index=False)
        destaques.to_excel(writer, sheet_name="Exclusao Identificada", index=False)
        divergentes.to_excel(writer, sheet_name="Divergentes", index=False)

        for sheet_name, df in {
            "Resumo": resumo_df,
            "Relatorio Completo": report_export,
            "Exclusao Identificada": destaques,
            "Divergentes": divergentes,
        }.items():
            _set_widths(writer, df, sheet_name)
            _format_numeric(writer, df, sheet_name)

    return output_path
