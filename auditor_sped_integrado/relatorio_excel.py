"""Relatório único da auditoria, sem transformar indícios em créditos."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


COR_TITULO = "17365D"
COR_CABECALHO = "DCE6F1"
FORMATO_MOEDA = '#,##0.00'
COLUNAS_VALOR = {
    "valor_operacao", "base_pis", "valor_pis", "base_cofins", "valor_cofins",
    "pis_escriturado", "cofins_escriturada", "contribuicoes_sob_analise", "icms_st_vinculado",
    "exclusao_calculada", "credito_pis_calculado", "credito_cofins_calculado",
    "valor_icms_st_destacado", "base_icms", "valor_icms", "valor_icms_st",
    "diferenca_pis", "diferenca_cofins",
}


def _valor_celula(valor: object) -> object:
    if pd.isna(valor):
        return None
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@"):
        return "'" + valor
    return valor


def _aba_quadro(livro: Workbook, nome: str, quadro: pd.DataFrame) -> None:
    aba = livro.create_sheet(nome)
    aba.append(list(quadro.columns))
    for celula in aba[1]:
        celula.fill = PatternFill("solid", fgColor=COR_CABECALHO)
        celula.font = Font(bold=True)
    for linha in quadro.itertuples(index=False, name=None):
        aba.append([_valor_celula(valor) for valor in linha])
    aba.freeze_panes = "A2"
    aba.auto_filter.ref = aba.dimensions
    for indice, coluna in enumerate(quadro.columns, start=1):
        aba.column_dimensions[get_column_letter(indice)].width = min(max(len(str(coluna)) + 3, 14), 34)
        if coluna in COLUNAS_VALOR:
            for celulas in aba.iter_cols(min_col=indice, max_col=indice, min_row=2):
                for celula in celulas:
                    celula.number_format = FORMATO_MOEDA


def resumir_candidatos(c175: pd.DataFrame) -> pd.DataFrame:
    colunas = [
        "competencia", "cnpj_estabelecimento", "registros_c175", "valor_operacao",
        "base_pis", "pis_escriturado", "base_cofins", "cofins_escriturada",
        "contribuicoes_sob_analise",
        "icms_st_vinculado", "exclusao_calculada", "credito_pis_calculado",
        "credito_cofins_calculado", "estado", "pendencia",
    ]
    if c175.empty:
        return pd.DataFrame(columns=colunas)
    candidatos = c175.loc[
        (c175["cfop"].astype(str) == "5405")
        & (c175["cst_pis"].astype(str).str.zfill(2) == "01")
        & (c175["cst_cofins"].astype(str).str.zfill(2) == "01")
    ]
    if candidatos.empty:
        return pd.DataFrame(columns=colunas)
    grupos = candidatos.groupby(["competencia", "cnpj_estabelecimento"], as_index=False).agg(
        registros_c175=("registros_c175", "sum"),
        valor_operacao=("valor_operacao", "sum"),
        base_pis=("base_pis", "sum"),
        pis_escriturado=("valor_pis", "sum"),
        base_cofins=("base_cofins", "sum"),
        cofins_escriturada=("valor_cofins", "sum"),
    )
    grupos["contribuicoes_sob_analise"] = (
        grupos["pis_escriturado"] + grupos["cofins_escriturada"]
    ).round(2)
    for coluna in ("icms_st_vinculado", "exclusao_calculada", "credito_pis_calculado", "credito_cofins_calculado"):
        grupos[coluna] = None
    grupos["estado"] = "Possível recuperação em análise"
    grupos["pendencia"] = "Obter NF de aquisição e vincular ICMS-ST à receita para quantificar a exclusão"
    return grupos[colunas]


def gerar_relatorio_excel(
    inventario: list[dict],
    achados: pd.DataFrame,
    st_c170: pd.DataFrame,
    st_c100: pd.DataFrame,
    vendas_c175: pd.DataFrame,
    st_c190: pd.DataFrame,
    regime: str,
    gerado_em: datetime | None = None,
) -> bytes:
    """Gera livro com resumo de candidatos e abas de evidência rastreável."""
    livro = Workbook()
    resumo = livro.active
    resumo.title = "Resumo"
    resumo["A1"] = "Auditoria SPED — análise preliminar de possível recuperação"
    resumo["A1"].font = Font(size=16, bold=True, color="FFFFFF")
    resumo["A1"].fill = PatternFill("solid", fgColor=COR_TITULO)
    resumo.merge_cells("A1:O1")
    resumo["A2"] = "Gerado em"
    resumo["B2"] = (gerado_em or datetime.now()).strftime("%d/%m/%Y %H:%M")
    resumo["D2"] = "Regime informado"
    resumo["E2"] = regime
    resumo["A3"] = "Filtro principal: C175, CFOP 5405, CST PIS 01 e CST COFINS 01."
    resumo.merge_cells("A3:O3")
    resumo["A4"] = "PIS/COFINS sob análise são valores escriturados nas receitas selecionadas; a possível recuperação ainda depende da medida de ICMS-ST excluível."
    resumo.merge_cells("A4:O4")
    resumo["A4"].alignment = Alignment(wrap_text=True, vertical="center")
    resumo.row_dimensions[4].height = 32
    candidatos = resumir_candidatos(vendas_c175)
    for coluna, titulo in enumerate(candidatos.columns, start=1):
        celula = resumo.cell(6, coluna, titulo)
        celula.fill = PatternFill("solid", fgColor=COR_CABECALHO)
        celula.font = Font(bold=True)
    for linha_excel, valores in enumerate(candidatos.itertuples(index=False, name=None), start=7):
        for coluna, valor in enumerate(valores, start=1):
            celula = resumo.cell(linha_excel, coluna, _valor_celula(valor))
            if candidatos.columns[coluna - 1] in COLUNAS_VALOR:
                celula.number_format = FORMATO_MOEDA
    if candidatos.empty:
        resumo["A7"] = "Nenhuma receita no filtro principal foi encontrada."
    resumo.freeze_panes = "C7"
    resumo.auto_filter.ref = f"A6:O{max(7, 6 + len(candidatos))}"
    for indice, nome in enumerate(candidatos.columns, start=1):
        resumo.column_dimensions[get_column_letter(indice)].width = min(max(len(nome) + 3, 16), 35)
    resumo.column_dimensions["O"].width = 70

    _aba_quadro(livro, "C175_5405", vendas_c175)
    _aba_quadro(livro, "ST_C170", st_c170)
    _aba_quadro(livro, "ST_C100", st_c100)
    _aba_quadro(livro, "ST_C190", st_c190)
    _aba_quadro(livro, "Triagem_C170", achados)
    inventario_linhas = [
        {"tipo": item["tipo"], "nome_arquivo": item["arquivo"], "sha256": item["sha256"],
         "aba": aba, "linhas_dados": total}
        for item in inventario for aba, total in item["abas"].items()
    ]
    _aba_quadro(livro, "Inventario", pd.DataFrame(
        inventario_linhas, columns=["tipo", "nome_arquivo", "sha256", "aba", "linhas_dados"]
    ))
    metodo = pd.DataFrame([
        ("Escopo", "Triagem e documentação de possível exclusão de ICMS-ST da base de PIS/COFINS."),
        ("Filtro principal", "C175, CFOP 5405, CST 01 de PIS e de COFINS."),
        ("Resultado preliminar", "PIS/COFINS sob análise soma os valores escriturados nas receitas selecionadas; não é o valor a recuperar."),
        ("C175", "Registro analítico; não comprova por si só item, quantidade nem ICMS-ST da aquisição."),
        ("C100/C170/C190", "Níveis distintos; não somar os valores entre si."),
        ("Responsabilidade", "O auditor não altera nem retifica SPED ou declarações."),
        ("Tema 1125", "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/legislacao/jurisprudencia-vinculante/pis-cofins"),
        ("CST oficial", "https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/tabelas-de-codigos/tabelas-utilizadas-na-apuracao-das-contribuicoes-para-o-pis-pasep-e-da-cofins/tabela-4-3-12"),
    ], columns=["tema", "observacao"])
    _aba_quadro(livro, "Metodo", metodo)
    arquivo = BytesIO()
    livro.save(arquivo)
    return arquivo.getvalue()
