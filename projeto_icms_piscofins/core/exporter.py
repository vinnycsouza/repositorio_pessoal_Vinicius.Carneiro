from __future__ import annotations

import io
from typing import Any

import pandas as pd
from openpyxl.utils import get_column_letter


def _set_column_widths_openpyxl(writer: pd.ExcelWriter, df: pd.DataFrame, sheet_name: str) -> None:
    ws = writer.sheets[sheet_name]

    for i, col in enumerate(df.columns, start=1):
        max_len = len(str(col))
        if not df.empty:
            values = df[col].astype(str).fillna("")
            max_len = max(max_len, values.map(len).max())
        ws.column_dimensions[get_column_letter(i)].width = min(max_len + 2, 40)


def _build_resumo_df(report: pd.DataFrame, resumo: dict[str, Any]) -> pd.DataFrame:
    linhas = [
        ["Itens analisados", resumo.get("itens_analisados", len(report))],
        ["Exclusão identificada", resumo.get("itens_exclusao_identificada", 0)],
        ["Sem indício de exclusão", resumo.get("itens_sem_indicio", 0)],
        ["Divergente / Revisar", resumo.get("itens_divergente_revisar", 0)],
        ["Sem dados suficientes", resumo.get("itens_sem_dados", 0)],
        ["Linhas com Base de ICMS Final", int((pd.to_numeric(report.get("Base de ICMS Final", 0), errors="coerce").fillna(0) != 0).sum()) if "Base de ICMS Final" in report.columns else 0],
        ["Linhas com Valor de ICMS Final", int((pd.to_numeric(report.get("Valor de ICMS Final", 0), errors="coerce").fillna(0) != 0).sum()) if "Valor de ICMS Final" in report.columns else 0],
    ]

    if "Cruzou com ICMS/IPI" in report.columns:
        linhas.append(["Join Sim", int((report["Cruzou com ICMS/IPI"].astype(str) == "Sim").sum())])
        linhas.append(["Join Não", int((report["Cruzou com ICMS/IPI"].astype(str) == "Não").sum())])

    return pd.DataFrame(linhas, columns=["Indicador", "Valor"])


def _prepare_destaque_df(report: pd.DataFrame) -> pd.DataFrame:
    if "Status da Análise" not in report.columns:
        return report.copy()

    destaque = report[report["Status da Análise"] == "Exclusão identificada"].copy()

    colunas_prioridade = [
        "Empresa",
        "CNPJ",
        "Mês",
        "Ano",
        "Chave",
        "Número da Nota",
        "Série",
        "Item",
        "Código do Produto",
        "Descrição",
        "CFOP",
        "Operação",
        "Valor do Item",
        "Base de ICMS no PIS",
        "Valor de ICMS no PIS",
        "Base de ICMS no ICMS/IPI",
        "Valor de ICMS no ICMS/IPI",
        "Base de ICMS Final",
        "Valor de ICMS Final",
        "Base de ICMS ST",
        "Valor de ICMS ST",
        "Origem da Base de ICMS",
        "Origem do Valor de ICMS",
        "Base de PIS Informada",
        "Base de COFINS Informada",
        "Diferença ICMS x PIS",
        "Diferença ICMS x COFINS",
        "Diferença bate com ICMS? PIS",
        "Diferença bate com ICMS? COFINS",
        "Status da Análise",
        "Motivo",
        "Possui ST",
        "Cruzou com ICMS/IPI",
        "Documento de Entrada",
    ]

    colunas_existentes = [c for c in colunas_prioridade if c in destaque.columns]
    outras = [c for c in destaque.columns if c not in colunas_existentes]
    return destaque[colunas_existentes + outras]


def export_report_to_bytes(report: pd.DataFrame, resumo: dict[str, Any]) -> bytes:
    report_export = report.copy()

    colunas_numericas = [
        "Valor do Item",
        "Base de ICMS no PIS",
        "Valor de ICMS no PIS",
        "Base de ICMS no ICMS/IPI",
        "Valor de ICMS no ICMS/IPI",
        "Base de ICMS Final",
        "Valor de ICMS Final",
        "Base de ICMS ST",
        "Valor de ICMS ST",
        "Base de PIS Informada",
        "Base de COFINS Informada",
        "Diferença ICMS x PIS",
        "Diferença ICMS x COFINS",
    ]

    for col in colunas_numericas:
        if col in report_export.columns:
            report_export[col] = pd.to_numeric(report_export[col], errors="coerce")

    resumo_df = _build_resumo_df(report_export, resumo)
    destaque_df = _prepare_destaque_df(report_export)

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        resumo_df.to_excel(writer, sheet_name="Resumo", index=False)
        report_export.to_excel(writer, sheet_name="Relatorio Completo", index=False)
        destaque_df.to_excel(writer, sheet_name="Exclusao Identificada", index=False)

        _set_column_widths_openpyxl(writer, resumo_df, "Resumo")
        _set_column_widths_openpyxl(writer, report_export, "Relatorio Completo")
        _set_column_widths_openpyxl(writer, destaque_df, "Exclusao Identificada")

    output.seek(0)
    return output.getvalue()