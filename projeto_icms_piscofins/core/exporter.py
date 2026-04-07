from __future__ import annotations

import io
from typing import Any

import pandas as pd
from openpyxl import Workbook


def criar_resumo(report: pd.DataFrame, resumo: dict[str, Any]) -> pd.DataFrame:
    total = int(resumo.get("itens_analisados", len(report)))
    exclusao = int(resumo.get("itens_exclusao_identificada", 0))
    sem_indicio = int(resumo.get("itens_sem_indicio", 0))
    divergente = int(resumo.get("itens_divergente_revisar", 0))
    sem_dados = int(resumo.get("itens_sem_dados", 0))
    sem_match = int(resumo.get("itens_sem_match", 0))
    base_icms = int(resumo.get("itens_com_base_icms_final", 0))
    valor_icms = int(resumo.get("itens_com_valor_icms_final", 0))
    credito_total = float(resumo.get("credito_total_estimado", 0.0))

    join_sim = int((report["Cruzou com ICMS/IPI"].astype(str) == "Sim").sum()) if "Cruzou com ICMS/IPI" in report.columns else 0
    join_nao = int((report["Cruzou com ICMS/IPI"].astype(str) == "Não").sum()) if "Cruzou com ICMS/IPI" in report.columns else 0
    itens_st = int((report["Possui ST"].astype(str) == "Sim").sum()) if "Possui ST" in report.columns else 0

    dados = [
        ["RESULTADO DA ANÁLISE", ""],
        ["Itens analisados", total],
        ["Exclusão identificada", exclusao],
        ["Sem indício de exclusão", sem_indicio],
        ["Divergente / Revisar", divergente],
        ["Sem dados suficientes", sem_dados],
        ["% com exclusão", exclusao / total if total else 0],
        ["% sem exclusão", sem_indicio / total if total else 0],
        ["Crédito total estimado", credito_total],
        ["", ""],
        ["QUALIDADE DOS DADOS", ""],
        ["Linhas com Base de ICMS Final", base_icms],
        ["Linhas com Valor de ICMS Final", valor_icms],
        ["Join Sim", join_sim],
        ["Join Não", join_nao],
        ["Itens com ICMS-ST", itens_st],
        ["Itens sem cruzamento", sem_match],
    ]
    return pd.DataFrame(dados, columns=["Indicador", "Valor"])


def simplificar(df: pd.DataFrame) -> pd.DataFrame:
    colunas = [
        "Empresa", "CNPJ", "Mês", "Ano", "Número da Nota", "Série", "Item", "Código do Produto", "Descrição",
        "CFOP", "Operação", "Base de ICMS Final", "Valor de ICMS Final", "Base de PIS Informada",
        "Base de COFINS Informada", "Diferença ICMS x PIS", "Diferença ICMS x COFINS",
        "Diferença bate com ICMS? PIS", "Diferença bate com ICMS? COFINS", "Status da Análise", "Motivo",
        "Crédito PIS Estimado", "Crédito COFINS Estimado", "Crédito Total Estimado",
    ]
    if df.empty:
        return pd.DataFrame(columns=colunas)
    return df[[c for c in colunas if c in df.columns]].copy()


def preparar_relatorio_completo(df: pd.DataFrame) -> pd.DataFrame:
    prioridade = [
        "Empresa", "CNPJ", "Mês", "Ano", "Chave", "Número da Nota", "Série", "Item", "Código do Produto", "Descrição",
        "CFOP", "Operação", "Valor do Item", "Base de ICMS Final", "Valor de ICMS Final", "Base de PIS Informada",
        "Base de COFINS Informada", "Diferença ICMS x PIS", "Diferença ICMS x COFINS",
        "Diferença bate com ICMS? PIS", "Diferença bate com ICMS? COFINS", "Status da Análise", "Motivo",
        "Crédito PIS Estimado", "Crédito COFINS Estimado", "Crédito Total Estimado", "Base de ICMS no PIS",
        "Valor de ICMS no PIS", "Base de ICMS no ICMS/IPI", "Valor de ICMS no ICMS/IPI", "Base de ICMS ST",
        "Valor de ICMS ST", "Origem da Base de ICMS", "Origem do Valor de ICMS", "Possui ST",
        "Cruzou com ICMS/IPI", "Documento de Entrada",
    ]
    cols1 = [c for c in prioridade if c in df.columns]
    cols2 = [c for c in df.columns if c not in cols1]
    out = df[cols1 + cols2].copy()

    if "Status da Análise" in out.columns:
        ordem = {
            "Sem indício de exclusão": 0,
            "Divergente / Revisar": 1,
            "Sem dados suficientes": 2,
            "Exclusão identificada": 3,
        }
        out["_ordem_status"] = out["Status da Análise"].map(ordem).fillna(9)
        sort_cols = ["_ordem_status"]
        for c in ["Ano", "Mês", "Número da Nota", "Item"]:
            if c in out.columns:
                sort_cols.append(c)
        out = out.sort_values(sort_cols, kind="stable").drop(columns="_ordem_status")

    return out


def _append_dataframe(ws, df: pd.DataFrame) -> None:
    if df is None or (df.empty and len(df.columns) == 0):
        ws.append(["Mensagem"])
        ws.append(["Nenhum registro encontrado para esta aba."])
        return

    ws.append(list(df.columns))
    for row in df.itertuples(index=False, name=None):
        ws.append(list(row))


def export_report_to_bytes(report: pd.DataFrame, resumo: dict[str, Any]) -> bytes:
    report_export = report.copy()

    colunas_numericas = [
        "Valor do Item", "Base de ICMS no PIS", "Valor de ICMS no PIS", "Base de ICMS no ICMS/IPI",
        "Valor de ICMS no ICMS/IPI", "Base de ICMS Final", "Valor de ICMS Final", "Base de ICMS ST",
        "Valor de ICMS ST", "Base de PIS Informada", "Base de COFINS Informada", "Diferença ICMS x PIS",
        "Diferença ICMS x COFINS", "Crédito PIS Estimado", "Crédito COFINS Estimado", "Crédito Total Estimado",
    ]
    for col in colunas_numericas:
        if col in report_export.columns:
            report_export[col] = pd.to_numeric(report_export[col], errors="coerce")

    resumo_df = criar_resumo(report_export, resumo)

    if "Status da Análise" in report_export.columns:
        exclusao_df = simplificar(report_export[report_export["Status da Análise"] == "Exclusão identificada"].copy())
        sem_indicio_df = simplificar(report_export[report_export["Status da Análise"] == "Sem indício de exclusão"].copy())
        divergente_df = simplificar(report_export[report_export["Status da Análise"] == "Divergente / Revisar"].copy())
        sem_dados_df = simplificar(report_export[report_export["Status da Análise"] == "Sem dados suficientes"].copy())
    else:
        exclusao_df = simplificar(pd.DataFrame())
        sem_indicio_df = simplificar(pd.DataFrame())
        divergente_df = simplificar(pd.DataFrame())
        sem_dados_df = simplificar(pd.DataFrame())

    sem_match_df = simplificar(
        report_export[report_export["Cruzou com ICMS/IPI"] == "Não"].copy()
    ) if "Cruzou com ICMS/IPI" in report_export.columns else simplificar(pd.DataFrame())

    st_df = simplificar(
        report_export[report_export["Possui ST"] == "Sim"].copy()
    ) if "Possui ST" in report_export.columns else simplificar(pd.DataFrame())

    completo_df = preparar_relatorio_completo(report_export)

    wb = Workbook(write_only=True)
    if wb.worksheets:
        wb.remove(wb.worksheets[0])

    sheets = [
        ("Resumo Executivo", resumo_df),
        ("Exclusao Identificada", exclusao_df),
        ("Sem Indicio", sem_indicio_df),
        ("Divergente Revisar", divergente_df),
        ("Sem Dados", sem_dados_df),
        ("Sem Cruzamento", sem_match_df),
        ("Itens com ST", st_df),
        ("Relatorio Completo", completo_df),
    ]

    for nome, df in sheets:
        ws = wb.create_sheet(title=nome[:31])
        _append_dataframe(ws, df)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()