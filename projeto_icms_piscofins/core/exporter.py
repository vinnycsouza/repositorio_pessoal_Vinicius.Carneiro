from __future__ import annotations

import io
import pandas as pd
from openpyxl.utils import get_column_letter


def ajustar_largura(writer, df, sheet):
    ws = writer.sheets[sheet]

    for i, col in enumerate(df.columns, 1):
        tamanho = len(str(col))
        if not df.empty:
            tamanho = max(tamanho, df[col].astype(str).map(len).max())
        ws.column_dimensions[get_column_letter(i)].width = min(tamanho + 2, 40)


def criar_resumo(report: pd.DataFrame) -> pd.DataFrame:
    total = len(report)

    exclusao = (report["Status da Análise"] == "Exclusão identificada").sum()
    sem_indicio = (report["Status da Análise"] == "Sem indício de exclusão").sum()
    divergente = (report["Status da Análise"] == "Divergente / Revisar").sum()
    sem_dados = (report["Status da Análise"] == "Sem dados suficientes").sum()

    sem_match = (report["Cruzou com ICMS/IPI"] == "Não").sum()
    st = (report["Possui ST"] == "Sim").sum()

    return pd.DataFrame(
        [
            ["Total de itens analisados", total],
            ["Exclusão identificada", exclusao],
            ["Sem indício de exclusão", sem_indicio],
            ["Divergente / Revisar", divergente],
            ["Sem dados suficientes", sem_dados],
            ["% com exclusão", exclusao / total if total else 0],
            ["% sem exclusão", sem_indicio / total if total else 0],
            ["Itens sem cruzamento", sem_match],
            ["Itens com ICMS-ST", st],
        ],
        columns=["Indicador", "Valor"],
    )


def simplificar(df: pd.DataFrame) -> pd.DataFrame:
    colunas = [
        "Empresa",
        "CNPJ",
        "Mês",
        "Número da Nota",
        "Item",
        "Base de ICMS Final",
        "Valor de ICMS Final",
        "Base de PIS Informada",
        "Base de COFINS Informada",
        "Diferença ICMS x PIS",
        "Diferença ICMS x COFINS",
        "Diferença bate com ICMS? PIS",
        "Diferença bate com ICMS? COFINS",
        "Status da Análise",
        "Motivo",
    ]

    colunas_existentes = [c for c in colunas if c in df.columns]
    return df[colunas_existentes].copy()


def export_report_to_bytes(report: pd.DataFrame, resumo: dict) -> bytes:

    resumo_df = criar_resumo(report)

    exclusao = simplificar(report[report["Status da Análise"] == "Exclusão identificada"])
    sem_indicio = simplificar(report[report["Status da Análise"] == "Sem indício de exclusão"])
    divergente = simplificar(report[report["Status da Análise"] == "Divergente / Revisar"])
    sem_dados = simplificar(report[report["Status da Análise"] == "Sem dados suficientes"])

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:

        resumo_df.to_excel(writer, sheet_name="Resumo Executivo", index=False)
        exclusao.to_excel(writer, sheet_name="Exclusão Identificada", index=False)
        sem_indicio.to_excel(writer, sheet_name="Sem Indício", index=False)
        divergente.to_excel(writer, sheet_name="Divergente", index=False)
        sem_dados.to_excel(writer, sheet_name="Sem Dados", index=False)
        report.to_excel(writer, sheet_name="Relatorio Completo", index=False)

        ajustar_largura(writer, resumo_df, "Resumo Executivo")
        ajustar_largura(writer, exclusao, "Exclusão Identificada")
        ajustar_largura(writer, sem_indicio, "Sem Indício")
        ajustar_largura(writer, divergente, "Divergente")
        ajustar_largura(writer, sem_dados, "Sem Dados")
        ajustar_largura(writer, report, "Relatorio Completo")

    output.seek(0)
    return output.getvalue()