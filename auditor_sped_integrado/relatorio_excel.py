"""Relatório único da auditoria, sem transformar indícios em créditos."""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.formatting.rule import FormulaRule
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from auditor_sped_integrado.apresentacao_relatorios import (
    PREENCHIMENTOS, cobertura_do_mes, competencias_esperadas, estilizar_cabecalho, lacunas_competencia,
)
from auditor_sped_integrado.premissas_icms import PeriodoRegime, UFS
from auditor_sped_integrado.prazo import data_corte


COR_TITULO = "17365D"
COR_CABECALHO = "DCE6F1"
FORMATO_MOEDA = '#,##0.00'
def _valor_celula(valor: object) -> object:
    if pd.isna(valor):
        return None
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@"):
        return "'" + valor
    return valor


def resumir_candidatos(c175: pd.DataFrame, simulacao: pd.DataFrame | None = None) -> pd.DataFrame:
    colunas = [
        "competencia", "cnpj_estabelecimento", "fonte_registro", "registros_c175", "valor_operacao",
        "base_pis", "pis_escriturado", "base_cofins", "cofins_escriturada",
        "registros_base_divergente", "registros_chave_invalida",
        "registros_duplicados_entre_abas",
        "contribuicoes_sob_analise", "simulacao_pis_cofins_uf",
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
    if "fonte_registro" not in candidatos.columns:
        candidatos = candidatos.assign(fonte_registro="C175")
    candidatos = candidatos.copy()
    bloqueados = candidatos["registros_duplicados_entre_abas"].fillna(0).gt(0) if "registros_duplicados_entre_abas" in candidatos.columns else pd.Series(False, index=candidatos.index)
    candidatos.loc[bloqueados, ["valor_operacao", "base_pis", "valor_pis", "base_cofins", "valor_cofins"]] = 0
    grupos = candidatos.groupby(["competencia", "cnpj_estabelecimento", "fonte_registro"], as_index=False).agg(
        registros_c175=("registros_c175", "sum"),
        valor_operacao=("valor_operacao", "sum"),
        base_pis=("base_pis", "sum"),
        pis_escriturado=("valor_pis", "sum"),
        base_cofins=("base_cofins", "sum"),
        cofins_escriturada=("valor_cofins", "sum"),
    )
    for coluna in (
        "registros_base_divergente", "registros_chave_invalida",
        "registros_duplicados_entre_abas",
    ):
        if coluna in candidatos.columns:
            contagens = candidatos.groupby(["competencia", "cnpj_estabelecimento", "fonte_registro"])[coluna].sum()
            grupos[coluna] = [
                int(contagens.loc[(linha["competencia"], linha["cnpj_estabelecimento"], linha["fonte_registro"])])
                for _, linha in grupos.iterrows()
            ]
        else:
            grupos[coluna] = 0
    grupos["contribuicoes_sob_analise"] = (
        grupos["pis_escriturado"] + grupos["cofins_escriturada"]
    ).round(2)
    grupos["simulacao_pis_cofins_uf"] = None
    if simulacao is not None and not simulacao.empty:
        if "fonte_registro" not in simulacao.columns:
            simulacao = simulacao.assign(fonte_registro="C175")
        somas = simulacao.groupby(["competencia", "cnpj_estabelecimento", "fonte_registro"])["total_simulado"].sum(min_count=1)
        for indice, linha in grupos.iterrows():
            chave = (linha["competencia"], linha["cnpj_estabelecimento"], linha["fonte_registro"])
            if chave in somas.index and pd.notna(somas.loc[chave]):
                grupos.at[indice, "simulacao_pis_cofins_uf"] = round(float(somas.loc[chave]), 2)
    for coluna in ("icms_st_vinculado", "exclusao_calculada", "credito_pis_calculado", "credito_cofins_calculado"):
        grupos[coluna] = None
    grupos["estado"] = "Possível recuperação em análise"
    grupos["pendencia"] = "Obter NF de aquisição e vincular ICMS-ST à receita para quantificar a exclusão"
    tem_duplicados = grupos["registros_duplicados_entre_abas"] > 0
    grupos.loc[tem_duplicados, "estado"] = "Conferir duplicação entre abas"
    grupos.loc[tem_duplicados, "pendencia"] = "Revisar linhas repetidas entre abas; simulação afetada bloqueada"
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
    simulacao: pd.DataFrame | None = None,
    historico_regime: tuple[PeriodoRegime, ...] = (),
    uf_selecionada: str | None = None,
    conferencia_nfe=None,
    data_referencia: date | None = None,
    recorte_prazo: dict[str, int] | None = None,
    cobertura_fontes: dict | None = None,
) -> bytes:
    """Gera três abas: apresentação, memória e validação documental por NF-e."""
    livro = Workbook(write_only=True)
    resumo = livro.create_sheet("Resumo_Executivo")
    memoria = livro.create_sheet("Memoria_Mensal")
    conferencia = livro.create_sheet("Conferencia_NF")

    linhas_escritas = {resumo.title: 0, memoria.title: 0, conferencia.title: 0}

    def adicionar(aba, valores, estilo=None, moedas=(), formulas=(), entradas=(), tecnicas=()):
        linhas_escritas[aba.title] += 1
        numero_linha = linhas_escritas[aba.title]
        linha = []
        for indice, valor in enumerate(valores, start=1):
            formula_interna = isinstance(valor, str) and valor.startswith("=") and (
                indice in formulas or (aba is conferencia and indice in (21, 22))
            )
            celula = WriteOnlyCell(aba, value=valor if formula_interna else _valor_celula(valor))
            if estilo == "titulo":
                celula.font = Font(size=16, bold=True, color="FFFFFF")
                celula.fill = PatternFill("solid", fgColor=COR_TITULO)
                celula.alignment = Alignment(vertical="center")
            elif estilo == "cabecalho":
                estilizar_cabecalho(celula, "entrada" if indice in entradas else "tecnico" if indice in tecnicas else "cabecalho")
            elif estilo == "destaque":
                celula.font = Font(bold=True, color=COR_TITULO)
                celula.fill = PatternFill("solid", fgColor=COR_CABECALHO)
            elif indice in entradas:
                celula.fill = PREENCHIMENTOS["entrada"]
            elif indice in tecnicas:
                celula.fill = PREENCHIMENTOS["tecnico"]
            if aba is resumo and isinstance(valor, str) and len(valor) > 60 and estilo != "titulo":
                celula.alignment = Alignment(wrap_text=True, vertical="center")
            if indice in moedas:
                celula.number_format = FORMATO_MOEDA
            linha.append(celula)
        if estilo == "titulo":
            aba.row_dimensions[numero_linha].height = 34
        elif estilo == "cabecalho":
            aba.row_dimensions[numero_linha].height = 36 if aba is resumo else 52
        elif aba is resumo and any(isinstance(v, str) and len(v) > 90 for v in valores):
            aba.row_dimensions[numero_linha].height = 57
        aba.append(linha)

    candidatos = resumir_candidatos(vendas_c175, simulacao)
    sim = simulacao if simulacao is not None else pd.DataFrame()
    sim_validas = sim.loc[sim["total_simulado"].notna()] if not sim.empty else sim
    competencias_candidatas = candidatos["competencia"].astype(str).tolist() if not candidatos.empty else []
    meses_esperados = competencias_esperadas(data_referencia, competencias_candidatas)
    meses_sem_grupo = lacunas_competencia(data_referencia, competencias_candidatas)
    anos = sorted({mes[:4] for mes in meses_esperados} | {mes[:4] for mes in competencias_candidatas})
    resumo.column_dimensions["A"].width = 56
    resumo.column_dimensions["B"].width = 39
    for letra in "CDE":
        resumo.column_dimensions[letra].width = 23
    resumo.column_dimensions["F"].width = 25
    resumo.column_dimensions["G"].width = 37
    resumo.freeze_panes = "B5"
    resumo.sheet_view.showGridLines = False
    resumo.page_setup.orientation = "landscape"
    resumo.page_setup.fitToWidth = 1
    adicionar(resumo, ["TEMA 1125 | ICMS-ST na base de PIS/COFINS"], "titulo")
    adicionar(resumo, ["Levantamento preliminar para conferência documental"])
    if data_referencia is not None:
        adicionar(resumo, ["Data de referência", data_referencia.strftime("%d/%m/%Y"),
                         "Corte operacional", data_corte(data_referencia).strftime("%d/%m/%Y")])
    adicionar(resumo, ["Gerado em", (gerado_em or datetime.now()).strftime("%d/%m/%Y %H:%M"),
                     "UF de referência", uf_selecionada or "Pela chave da NF-e"])
    adicionar(resumo, [])
    adicionar(resumo, ["RESULTADO PRELIMINAR", "PIS escriturado no filtro", "COFINS escriturada no filtro", "Possível PIS", "Possível COFINS", "Possível total"], "cabecalho")
    adicionar(resumo, ["Total", float(candidatos["pis_escriturado"].sum()),
                     float(candidatos["cofins_escriturada"].sum()),
                     float(sim_validas["pis_simulado"].sum()) if not sim_validas.empty else None,
                     float(sim_validas["cofins_simulada"].sum()) if not sim_validas.empty else None,
                     float(sim_validas["total_simulado"].sum()) if not sim_validas.empty else None], "destaque", (2, 3, 4, 5, 6))
    adicionar(resumo, ["Situação", "Possível crédito pela premissa estadual; ICMS-ST da aquisição e aproveitamentos anteriores ainda exigem conferência."])
    adicionar(resumo, ["Competências sem grupo no filtro", ", ".join(meses_sem_grupo) or "Nenhuma no intervalo de meses completos."])
    adicionar(resumo, [])
    adicionar(resumo, ["RECONCILIAÇÃO DO FILTRO", "Base PIS (R$)", "Base COFINS (R$)", "Registros"], "cabecalho")
    adicionar(resumo, ["Vendas escrituradas no filtro", float(candidatos["base_pis"].sum()),
                     float(candidatos["base_cofins"].sum()), int(candidatos["registros_c175"].sum())], moedas=(2, 3))
    adicionar(resumo, ["Base considerada na premissa", float(sim_validas["base_pis_conferida"].sum()) if not sim_validas.empty else 0,
                     float(sim_validas["base_cofins_conferida"].sum()) if not sim_validas.empty else 0,
                     int(sim_validas["registros_base_conferida"].sum()) if not sim_validas.empty else 0], moedas=(2, 3))
    adicionar(resumo, ["Diferença monetária a revisar",
                     max(0, float(candidatos["base_pis"].sum()) - float(sim_validas["base_pis_conferida"].sum())) if not sim_validas.empty else float(candidatos["base_pis"].sum()),
                     max(0, float(candidatos["base_cofins"].sum()) - float(sim_validas["base_cofins_conferida"].sum())) if not sim_validas.empty else float(candidatos["base_cofins"].sum()),
                     None], moedas=(2, 3))
    adicionar(resumo, ["Registros com base divergente", None, None,
                     int(sim["registros_base_divergente"].sum()) if not sim.empty else 0])
    adicionar(resumo, ["Leitura da diferença", "A diferença monetária também pode refletir outros bloqueios ou ausência de premissa. Os registros divergentes são uma contagem separada. Consulte a memória e as NF-e."])
    adicionar(resumo, [])
    adicionar(resumo, ["ANO", "PIS escriturado", "COFINS escriturada", "Possível PIS", "Possível COFINS", "Possível total", "Cobertura do filtro"], "cabecalho")
    for ano in anos:
        cand_ano = candidatos.loc[candidatos["competencia"].astype(str).str.startswith(ano)]
        sim_ano = sim_validas.loc[sim_validas["competencia"].astype(str).str.startswith(ano)] if not sim_validas.empty else sim_validas
        adicionar(resumo, [int(ano), float(cand_ano["pis_escriturado"].sum()),
                         float(cand_ano["cofins_escriturada"].sum()),
                         float(sim_ano["pis_simulado"].sum()) if not sim_ano.empty else None,
                         float(sim_ano["cofins_simulada"].sum()) if not sim_ano.empty else None,
                         float(sim_ano["total_simulado"].sum()) if not sim_ano.empty else None,
                         "Com grupos no filtro" if not cand_ano.empty else "Sem grupo no filtro; verificar fontes"], moedas=(2, 3, 4, 5, 6))
    adicionar(resumo, [])
    adicionar(resumo, ["APÓS CONFERÊNCIA DO ST", "PIS", "COFINS", "TOTAL"], "cabecalho")
    adicionar(resumo, ["Após conferência manual",
        '=IF(COUNT(Conferencia_NF!U:U)=0,"Pendente",SUM(Conferencia_NF!U:U))',
        '=IF(COUNT(Conferencia_NF!V:V)=0,"Pendente",SUM(Conferencia_NF!V:V))',
        '=IF(COUNT(Conferencia_NF!U:V)=0,"Pendente",SUM(Conferencia_NF!U:V))'],
        "destaque", (2, 3, 4), (2, 3, 4))
    adicionar(resumo, ["Natureza", "A conferência por NF-e calcula apenas as linhas com aquisição vinculada, ICMS-ST alocado, prazo conferido e revisão manual confirmada."])
    adicionar(resumo, [])
    adicionar(resumo, ["MÉTODO E LIMITES", "DETALHE"] , "cabecalho")
    adicionar(resumo, ["Filtro", "C170 e C175; CFOP 5405; CST 01 em PIS e COFINS."])
    adicionar(resumo, ["Regime IRPJ/CSLL informado", regime])
    adicionar(resumo, ["Histórico informado", "; ".join(f"{p.inicio} a {p.fim}: {p.regime}" for p in historico_regime) or "Não informado"])
    adicionar(resumo, ["Alíquotas PIS/COFINS", "O registro de origem prevalece; preenchimentos manuais de lacunas são identificados na memória e na conferência."])
    adicionar(resumo, ["Prescrição", "O corte de cinco anos é operacional. Conferir pagamento, medidas judiciais, modulação e aproveitamentos anteriores antes de concluir o prazo."])
    contagem = recorte_prazo or {}
    adicionar(resumo, ["Linhas fora do recorte", f"Anteriores: {contagem.get('anterior', 0)}; mês do corte pendente: {contagem.get('limite', 0)}"])
    adicionar(resumo, ["Leitura", "Memoria_Mensal detalha a premissa por competência e origem; Conferencia_NF reúne a documentação e os campos de revisão por nota."])
    adicionar(resumo, ["Cobertura das fontes", "Na memória, as contagens mensais mostram saídas mapeadas em C170/C175 de Contribuições e C190 de ICMS/IPI. Ausência de grupo no filtro exige verificar os arquivos; não prova ausência de escrituração."])
    adicionar(resumo, [])
    adicionar(resumo, ["ARQUIVOS-FONTE", "Nome", "SHA-256"], "cabecalho")
    for item in inventario:
        adicionar(resumo, [item["tipo"], item["arquivo"], item["sha256"]])

    colunas_memoria = ["Competência", "CNPJ estabelecimento", "UF NF-e", "Regime 0110",
                      "Alíquota PIS %", "Alíquota COFINS %", "Registros de origem", "Base PIS conferida",
                      "Base COFINS conferida", "Alíquota geral UF %", "Parcela ICMS pela premissa",
                      "Possível PIS", "Possível COFINS", "Possível total", "Bases divergentes",
                      "Chaves inválidas", "Duplicados entre abas", "Situação do cálculo", "Fonte da premissa",
                      "Fonte alíquota PIS", "Fonte alíquota COFINS", "Incidência PIS/COFINS", "Registro de origem",
                      "Saídas Contribuições no mês", "Saídas C190 ICMS/IPI no mês", "Cobertura mensal"]
    for indice, nome in enumerate(colunas_memoria, start=1):
        memoria.column_dimensions[get_column_letter(indice)].width = min(max(len(nome) + 3, 16), 55)
    memoria.freeze_panes = "C2"
    adicionar(memoria, colunas_memoria, "cabecalho")
    linhas_memoria = sim.to_dict("records") + [
        {"competencia": mes, "estado_simulacao": "Sem grupo no filtro; verificar fontes"}
        for mes in meses_sem_grupo
    ]
    linhas_memoria.sort(key=lambda item: (str(item.get("competencia", "")), str(item.get("cnpj_estabelecimento", ""))))
    for item in linhas_memoria:
        saidas_pis, saidas_icms, cobertura = cobertura_do_mes(
            str(item.get("competencia", "")), item.get("estado_simulacao") != "Sem grupo no filtro; verificar fontes",
            cobertura_fontes,
        )
        adicionar(memoria, [item.get(chave) for chave in (
            "competencia", "cnpj_estabelecimento", "uf", "regime_0110", "aliquota_pis",
            "aliquota_cofins", "registros_c175", "base_pis_conferida", "base_cofins_conferida",
            "aliquota_icms_referencia", "parcela_icms_simulada", "pis_simulado", "cofins_simulada",
            "total_simulado", "registros_base_divergente", "registros_chave_invalida",
            "registros_duplicados_entre_abas", "estado_simulacao", "fonte_premissa",
            "fonte_aliquota_pis", "fonte_aliquota_cofins", "descricao_regime", "fonte_registro",
        )] + [saidas_pis, saidas_icms, cobertura], moedas=(8, 9, 11, 12, 13, 14))
    memoria.auto_filter.ref = f"A1:Z{max(2, 1 + len(linhas_memoria))}"

    colunas_nfe = ["Competência", "CNPJ estabelecimento", "Chave NF-e de venda", "UF NF-e",
                   "Registro de origem", "Situação automática", "PIS escriturado", "COFINS escriturada",
                   "Valor operação", "Desconto", "Base PIS", "Base COFINS", "Alíquota PIS %",
                   "Alíquota COFINS %", "NF(s) de aquisição vinculada(s)", "ICMS-ST comprovado alocado (R$)",
                   "Data do pagamento PIS/COFINS", "Medida/ato que afete o prazo", "Prazo conferido",
                   "Conferência manual", "PIS potencial com ST", "COFINS potencial com ST", "Revisor",
                   "Observações", "Aba de origem", "Primeira linha de origem", "Incidência PIS/COFINS (0110)",
                   "Itens de origem", "Bases divergentes", "Duplicados entre abas", "Fonte alíquota PIS",
                   "Fonte alíquota COFINS", "Sobreposição C170/C175"]
    for indice, nome in enumerate(colunas_nfe, start=1):
        conferencia.column_dimensions[get_column_letter(indice)].width = min(max(len(nome) + 3, 14), 52)
    conferencia.column_dimensions["C"].width = 48
    conferencia.column_dimensions["O"].width = 45
    conferencia.column_dimensions["X"].width = 55
    conferencia.freeze_panes = "D2"
    adicionar(conferencia, colunas_nfe, "cabecalho", entradas=(15, 16, 17, 18, 19, 20, 23, 24), tecnicas=tuple(range(25, 34)))
    total_nfe = 0
    if conferencia_nfe is not None:
        for total_nfe, linha in enumerate(conferencia_nfe.linhas(), start=1):
            if total_nfe > 1048575:
                raise ValueError("Mais de 1.048.575 NF-e; divida o levantamento por período para caber no Excel.")
            (periodo, cnpj, chave, chave_ok, uf, regime_0110, pis_min, pis_max,
             cof_min, cof_max, itens, oper, desc, base_pis, pis, base_cof, cof,
             divergentes, duplicados, aba, primeira_linha, fonte_registro,
             sobreposicao, fonte_pis, fonte_cofins) = linha
            codigo_regime = regime_0110 or ("1" if (pis_min, cof_min) == (1.65, 7.6) else "2" if (pis_min, cof_min) == (0.65, 3.0) else "")
            pares_aceitos = {
                "1": {(1.65, 7.6)}, "2": {(0.65, 3.0)},
                "3": {(1.65, 7.6), (0.65, 3.0)},
            }
            aliquotas_compativeis = (round(pis_min, 4), round(cof_min, 4)) in pares_aceitos.get(codigo_regime, set())
            situacao = ("Sobreposição C170/C175" if sobreposicao else
                        "Duplicação entre abas/itens" if duplicados else
                        "Chave incompatível" if not chave_ok else
                        "Alíquotas diferentes na NF-e" if pis_min != pis_max or cof_min != cof_max else
                        "Base divergente" if divergentes else
                        "Alíquotas/regime pendentes" if not aliquotas_compativeis else
                        "UF diferente da escolhida" if uf_selecionada and UFS.get(uf) != uf_selecionada else
                        "Apto para conferência")
            excel_linha = total_nfe + 1
            formula_pis = (f'=IF(AND(T{excel_linha}="Confirmado",S{excel_linha}="Conferido",ISNUMBER(P{excel_linha}),'
                           f'P{excel_linha}>0,F{excel_linha}="Apto para conferência",O{excel_linha}<>""),'
                           f'MAX(0,MIN(ROUND(MIN(P{excel_linha},K{excel_linha})*M{excel_linha}/100,2),G{excel_linha})),"")')
            formula_cof = (f'=IF(AND(T{excel_linha}="Confirmado",S{excel_linha}="Conferido",ISNUMBER(P{excel_linha}),'
                           f'P{excel_linha}>0,F{excel_linha}="Apto para conferência",O{excel_linha}<>""),'
                           f'MAX(0,MIN(ROUND(MIN(P{excel_linha},L{excel_linha})*N{excel_linha}/100,2),H{excel_linha})),"")')
            adicionar(conferencia, [periodo, cnpj, chave, UFS.get(uf, ""), fonte_registro, situacao,
                pis / 100, cof / 100, oper / 100, desc / 100, base_pis / 100, base_cof / 100,
                pis_min if pis_min == pis_max else None, cof_min if cof_min == cof_max else None,
                None, None, None, None, "Pendente", "Pendente", formula_pis, formula_cof,
                None, None, aba, primeira_linha, regime_0110, itens, divergentes, duplicados,
                fonte_pis or fonte_registro, fonte_cofins or fonte_registro, sobreposicao],
                moedas=(7, 8, 9, 10, 11, 12, 16, 21, 22), entradas=(15, 16, 17, 18, 19, 20, 23, 24))
    conferencia.auto_filter.ref = f"A1:AG{max(2, total_nfe + 1)}"
    validacao = DataValidation(type="list", formula1='"Pendente,Confirmado,Rejeitado"')
    validacao.add(f"T2:T{max(2, total_nfe + 1)}")
    conferencia.data_validations.append(validacao)
    validacao_prazo = DataValidation(type="list", formula1='"Pendente,Conferido,Rejeitado"')
    validacao_prazo.add(f"S2:S{max(2, total_nfe + 1)}")
    conferencia.data_validations.append(validacao_prazo)
    ultima_linha = max(2, total_nfe + 1)
    conferencia.conditional_formatting.add(
        f"F2:F{ultima_linha}", FormulaRule(formula=['$F2="Apto para conferência"'],
                                            fill=PREENCHIMENTOS["calculo"]),
    )
    conferencia.conditional_formatting.add(
        f"F2:F{ultima_linha}", FormulaRule(formula=['AND($F2<>"",$F2<>"Apto para conferência")'],
                                            fill=PREENCHIMENTOS["pendencia"]),
    )
    conferencia.conditional_formatting.add(
        f"T2:T{ultima_linha}", FormulaRule(formula=['AND($T2="Confirmado",$S2="Conferido")'],
                                            fill=PREENCHIMENTOS["confirmado"]),
    )
    arquivo = BytesIO()
    livro.save(arquivo)
    return arquivo.getvalue()
