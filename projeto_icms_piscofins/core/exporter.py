from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def _safe_autofit(writer: pd.ExcelWriter, df: pd.DataFrame, sheet_name: str) -> None:
    ws = writer.sheets[sheet_name]
    for idx, col in enumerate(df.columns, start=1):
        max_len = len(str(col))
        if not df.empty:
            series_as_str = df[col].astype(str).fillna("")
            max_len = max(max_len, series_as_str.map(len).max())
        ws.column_dimensions[chr(64 + idx) if idx <= 26 else "A"].width = min(max_len + 2, 40)


def _set_column_widths_openpyxl(writer: pd.ExcelWriter, df: pd.DataFrame, sheet_name: str) -> None:
    ws = writer.sheets[sheet_name]
    from openpyxl.utils import get_column_letter

    for i, col in enumerate(df.columns, start=1):
        max_len = len(str(col))
        if not df.empty:
            values = df[col].astype(str).fillna("")
            max_len = max(max_len, values.map(len).max())
        ws.column_dimensions[get_column_letter(i)].width = min(max_len + 2, 40)


def _build_resumo_df(report: pd.DataFrame, resumo: dict[str, Any]) -> pd.DataFrame:
    linhas = [
        ["Itens analisados", resumo.get("itens_analisados", len(report))],
        ["Potencial alto", resumo.get("itens_potencial_alto", 0)],
        ["Potencial moderado", resumo.get("itens_potencial_moderado", 0)],
        ["Revisão manual", resumo.get("itens_revisao_manual", 0)],
        ["Sem match", resumo.get("itens_sem_match", 0)],
        ["Crédito total estimado", resumo.get("credito_total_estimado", 0.0)],
    ]

    if "Valor de ICMS Final" in report.columns:
        linhas.append(["Linhas com Valor de ICMS Final", int((pd.to_numeric(report["Valor de ICMS Final"], errors="coerce").fillna(0) != 0).sum())])

    if "Base de ICMS Final" in report.columns:
        linhas.append(["Linhas com Base de ICMS Final", int((pd.to_numeric(report["Base de ICMS Final"], errors="coerce").fillna(0) != 0).sum())])

    if "Cruzou com ICMS/IPI" in report.columns:
        linhas.append(["Join Sim", int((report["Cruzou com ICMS/IPI"].astype(str) == "Sim").sum())])
        linhas.append(["Join Não", int((report["Cruzou com ICMS/IPI"].astype(str) == "Não").sum())])

    return pd.DataFrame(linhas, columns=["Indicador", "Valor"])


def _prepare_oportunidades(report: pd.DataFrame) -> pd.DataFrame:
    if "Nível de Oportunidade" not in report.columns:
        return report.copy()

    oportunidades = report[
        report["Nível de Oportunidade"].isin(["Potencial alto", "Potencial moderado"])
    ].copy()

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
        "Base Esperada sem ICMS",
        "Diferença Base PIS",
        "Diferença Base COFINS",
        "Crédito PIS Estimado",
        "Crédito COFINS Estimado",
        "Crédito Total Estimado",
        "Nível de Oportunidade",
        "Motivo",
        "Possui ST",
        "Cruzou com ICMS/IPI",
        "Documento de Entrada",
    ]

    colunas_existentes = [c for c in colunas_prioridade if c in oportunidades.columns]
    outras = [c for c in oportunidades.columns if c not in colunas_existentes]
    return oportunidades[colunas_existentes + outras]


def export_report(report: pd.DataFrame, resumo: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Garante que estamos exportando exatamente o dataframe que está na tela
    report_export = report.copy()

    # Tenta converter colunas numéricas sem destruir texto
    colunas_numericas_preferenciais = [
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
        "Base Esperada sem ICMS",
        "Diferença Base PIS",
        "Diferença Base COFINS",
        "Crédito PIS Estimado",
        "Crédito COFINS Estimado",
        "Crédito Total Estimado",
    ]

    for col in colunas_numericas_preferenciais:
        if col in report_export.columns:
            report_export[col] = pd.to_numeric(report_export[col], errors="coerce")

    resumo_df = _build_resumo_df(report_export, resumo)
    oportunidades_df = _prepare_oportunidades(report_export)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        resumo_df.to_excel(writer, sheet_name="Resumo", index=False)
        report_export.to_excel(writer, sheet_name="Relatorio Completo", index=False)
        oportunidades_df.to_excel(writer, sheet_name="Oportunidades", index=False)

        _set_column_widths_openpyxl(writer, resumo_df, "Resumo")
        _set_column_widths_openpyxl(writer, report_export, "Relatorio Completo")
        _set_column_widths_openpyxl(writer, oportunidades_df, "Oportunidades")

    return output_path