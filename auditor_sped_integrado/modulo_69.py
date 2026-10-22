"""Levantamento independente do Tema 69 a partir de itens C170 escriturados.

O valor calculado é uma oportunidade sujeita a conferência da NF-e, da base
original, do bloco M, do recolhimento e de aproveitamentos anteriores.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
import re

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from auditor_sped_integrado.apresentacao_relatorios import (
    PREENCHIMENTOS, cobertura_do_mes, competencias_esperadas, estilizar_cabecalho, lacunas_competencia,
)
from auditor_sped_integrado.diagnostico_st import CODIGOS_UF, _decimal, _indice, _slug
from auditor_sped_integrado.motor import _cnpj, _competencia
from auditor_sped_integrado.premissas_icms import UFS, buscar_premissa
from auditor_sped_integrado.prazo import classificar_competencia, data_corte


COLUNAS_69 = (
    "competencia", "cnpj_estabelecimento", "chave_nfe", "modelo", "uf",
    "fonte_receita", "fonte_icms",
    "cfop", "itens", "base_pis", "pis_escriturado", "base_cofins",
    "cofins_escriturada", "icms_proprio_escriturado", "pis_potencial",
    "cofins_potencial", "total_potencial", "aliquota_icms_geral_referencia",
    "estado", "motivos", "aba_contribuicoes", "primeira_linha_contribuicoes",
    "aba_icms", "primeira_linha_icms",
)


def _arredondar(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _celula_cabecalho(aba, valor: str, grupo: str = "cabecalho"):
    celula = WriteOnlyCell(aba, value=valor)
    estilizar_cabecalho(celula, grupo)
    return celula


def _fonte(arquivo: str | Path | bytes):
    return BytesIO(arquivo) if isinstance(arquivo, bytes) else Path(arquivo)


def _indices_identidade(h: tuple) -> tuple[int, int, int, int, int]:
    return (
        _indice(h, "Mês"), _indice(h, "Ano"),
        _indice(h, "CNPJ Estabelecimento(C010)", "CNPJ Estabelecimento", "CNPJ"),
        _indice(h, "Chave(C100)", "Chave de Acesso(C100)", "Chave"),
        _indice(h, "Numeração Sequencial", "Item"),
    )


def _identidade(linha: tuple, indices: tuple[int, int, int, int, int]) -> tuple[str, str, str, str]:
    mes_i, ano_i, cnpj_i, chave_i, item_i = indices
    periodo = _competencia(linha[mes_i], linha[ano_i])
    cnpj = _cnpj(linha[cnpj_i])
    chave = re.sub(r"\D", "", str(linha[chave_i] or ""))
    item = str(linha[item_i] or "").strip().removesuffix(".0")
    return periodo, cnpj, chave, item


def levantar_tema_69(
    arquivo_icms: str | Path | bytes, arquivo_contribuicoes: str | Path | bytes,
    data_referencia=None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Cruza C170 por competência, CNPJ, chave e item, sem somar C100/C190."""
    icms_por_item: dict[tuple[str, str, str, str], list[tuple[Decimal, str, int]]] = defaultdict(list)
    def no_recorte(periodo: str) -> bool:
        return data_referencia is None or classificar_competencia(periodo, data_referencia) == "dentro"

    c190_por_grupo = defaultdict(lambda: {"icms": Decimal(0), "aba": "", "linha": None, "duplicado": False})
    vistos_c190 = set()
    livro_icms = load_workbook(_fonte(arquivo_icms), read_only=True, data_only=True)
    try:
        abas_icms = [n for n in livro_icms.sheetnames if _slug(n).startswith("c170")]
        for nome in abas_icms:
            aba = livro_icms[nome]
            aba.reset_dimensions()
            linhas = aba.iter_rows(values_only=True)
            h = next(linhas)
            indices = _indices_identidade(h)
            op_i = _indice(h, "Indicador de Operação(C100)", "Indicador de Operação")
            vl_i = _indice(h, "Valor de Icms", "Valor de ICMS", "VL_ICMS")
            for n, linha in enumerate(linhas, 2):
                if str(linha[op_i] or "").strip().removesuffix(".0") != "1":
                    continue
                identidade = _identidade(linha, indices)
                if not no_recorte(identidade[0]):
                    continue
                if len(identidade[2]) == 44 and identidade[3].isdigit():
                    icms_por_item[identidade].append((_decimal(linha[vl_i]), nome, n))
        for nome in (n for n in livro_icms.sheetnames if _slug(n).startswith("c190")):
            aba = livro_icms[nome]
            aba.reset_dimensions()
            linhas = aba.iter_rows(values_only=True)
            h = next(linhas)
            mes_i, ano_i = _indice(h, "Mês"), _indice(h, "Ano")
            cnpj_i = _indice(h, "CNPJ Estabelecimento(C010)", "CNPJ Estabelecimento", "CNPJ")
            chave_i = _indice(h, "Chave de Acesso(C100)", "Chave(C100)", "Chave")
            cfop_i = _indice(h, "CFOP")
            op_i = _indice(h, "Indicador de Operação(C100)", "Indicador de Operação")
            vl_i = _indice(h, "Valor de Icms", "Valor de ICMS")
            cst_i = _indice(h, "CST de ICMS")
            aliq_i = _indice(h, "Alíquota de Icms", "Aliquota de Icms")
            base_i = _indice(h, "Base de Icms", "Base de ICMS")
            for n, linha in enumerate(linhas, 2):
                if str(linha[op_i] or "").strip().removesuffix(".0") != "1":
                    continue
                periodo = _competencia(linha[mes_i], linha[ano_i])
                if not no_recorte(periodo):
                    continue
                cnpj = _cnpj(linha[cnpj_i])
                chave = re.sub(r"\D", "", str(linha[chave_i] or ""))
                cfop = re.sub(r"\D", "", str(linha[cfop_i] or ""))
                if not periodo or not cnpj or len(chave) != 44 or len(cfop) != 4:
                    continue
                valor = _decimal(linha[vl_i])
                if valor <= 0:
                    continue
                grupo_key = periodo, cnpj, chave, cfop
                assinatura = (grupo_key, str(linha[cst_i]), str(linha[aliq_i]),
                              str(linha[base_i]), str(linha[vl_i]))
                dados = c190_por_grupo[grupo_key]
                if assinatura in vistos_c190:
                    dados["duplicado"] = True
                    continue
                vistos_c190.add(assinatura)
                dados["icms"] += valor
                dados["aba"] = dados["aba"] or nome
                dados["linha"] = dados["linha"] or n
    finally:
        livro_icms.close()

    grupos = defaultdict(lambda: {
        "itens": 0, "bp": Decimal(0), "vp": Decimal(0), "bc": Decimal(0),
        "vc": Decimal(0), "icms": Decimal(0), "pot_pis": Decimal(0),
        "pot_cof": Decimal(0), "motivos": set(), "aba_pis": "", "linha_pis": None,
        "aba_icms": "", "linha_icms": None,
        "fallback_itens": 0, "taxas_pis": set(), "taxas_cofins": set(),
        "fonte_icms": "",
    })
    contagens = Counter()
    vistos_contribuicoes: dict[tuple[str, str, str, str], tuple] = {}
    vistos_c175 = set()
    total_linhas = Counter()
    livro_pis = load_workbook(_fonte(arquivo_contribuicoes), read_only=True, data_only=True)
    try:
        abas_pis = [n for n in livro_pis.sheetnames if _slug(n).startswith("c170")]
        for nome in abas_pis:
            aba = livro_pis[nome]
            aba.reset_dimensions()
            linhas = aba.iter_rows(values_only=True)
            h = next(linhas)
            indices = _indices_identidade(h)
            op_i = _indice(h, "Indicador de Operação(C100)", "Indicador de Operação")
            sit_i = _indice(h, "Situação(C100)", "Situação")
            cfop_i = _indice(h, "CFOP")
            try:
                modelo_i = _indice(h, "Modelo(C100)", "Modelo")
            except ValueError:
                modelo_i = None
            cst_p_i, cst_c_i = _indice(h, "CST de Pis"), _indice(h, "CST de Cofins")
            bp_i, vp_i, ap_i = _indice(h, "Base de Pis"), _indice(h, "Valor de Pis"), _indice(h, "Alíquota de Pis")
            bc_i, vc_i, ac_i = _indice(h, "Base de Cofins"), _indice(h, "Valor de Cofins"), _indice(h, "Alíquota de Cofins")
            for n, linha in enumerate(linhas, 2):
                if str(linha[op_i] or "").strip().removesuffix(".0") != "1":
                    continue
                if str(linha[sit_i] or "").strip().removesuffix(".0").zfill(2) not in {"00", "01"}:
                    continue
                cfop = re.sub(r"\D", "", str(linha[cfop_i] or ""))
                if len(cfop) != 4 or cfop[0] not in {"5", "6"}:
                    continue
                periodo, cnpj, chave, item = _identidade(linha, indices)
                if data_referencia is not None:
                    estado_prazo = classificar_competencia(periodo, data_referencia)
                    contagens[f"prazo_c170_{estado_prazo}"] += 1
                    if estado_prazo != "dentro":
                        continue
                total_linhas[("C170", periodo, cnpj, chave, cfop)] += 1
                if (not any(v > 0 for v, _aba, _linha in icms_por_item.get((periodo, cnpj, chave, item), []))
                        and (periodo, cnpj, chave, cfop) not in c190_por_grupo):
                    contagens["c170_sem_icms_proprio_identificado"] += 1
                    continue
                cst_p = str(linha[cst_p_i] or "").strip().removesuffix(".0").zfill(2)
                cst_c = str(linha[cst_c_i] or "").strip().removesuffix(".0").zfill(2)
                if cst_p not in {"01", "02"} or cst_c not in {"01", "02"}:
                    continue
                modelo = str(linha[modelo_i] or "").strip().removesuffix(".0") if modelo_i is not None else chave[20:22]
                if not periodo or not cnpj:
                    contagens["identificacao_incompleta"] += 1
                    continue
                uf_codigo = chave[:2] if len(chave) == 44 else ""
                chave_ok = (len(chave) == 44 and uf_codigo in CODIGOS_UF
                            and chave[6:20] == cnpj and chave[2:6] == periodo[2:4] + periodo[5:7]
                            and item.isdigit() and int(item) > 0)
                chave_grupo = (periodo, cnpj, chave or f"SEM_CHAVE:{nome}:{n}", modelo, UFS.get(uf_codigo, ""), cfop, "C170")
                grupo = grupos[chave_grupo]
                grupo["itens"] += 1
                grupo["aba_pis"] = grupo["aba_pis"] or nome
                grupo["linha_pis"] = grupo["linha_pis"] or n
                bp, vp, ap = _decimal(linha[bp_i]), _decimal(linha[vp_i]), _decimal(linha[ap_i])
                bc, vc, ac = _decimal(linha[bc_i]), _decimal(linha[vc_i]), _decimal(linha[ac_i])
                grupo["bp"] += bp
                grupo["vp"] += vp
                grupo["bc"] += bc
                grupo["vc"] += vc
                contagens["itens_tributados_c170"] += 1
                identidade = periodo, cnpj, chave, item
                if not chave_ok:
                    grupo["motivos"].add("Chave ou item inválido")
                    contagens["chave_invalida"] += 1
                    continue
                if identidade in vistos_contribuicoes:
                    grupo["motivos"].add("Item duplicado na EFD-Contribuições")
                    grupos[vistos_contribuicoes[identidade]]["motivos"].add("Item duplicado na EFD-Contribuições")
                    contagens["duplicado_contribuicoes"] += 1
                    continue
                vistos_contribuicoes[identidade] = chave_grupo
                correspondencias = icms_por_item.get(identidade, [])
                if len(correspondencias) != 1:
                    if correspondencias:
                        grupo["motivos"].add("Item duplicado no ICMS/IPI")
                        contagens["duplicado_icms_ipi"] += 1
                    else:
                        grupo["fallback_itens"] += 1
                        grupo["taxas_pis"].add(ap)
                        grupo["taxas_cofins"].add(ac)
                        contagens["sem_par_c170_verificar_c190"] += 1
                    continue
                valor_icms, aba_icms, linha_icms = correspondencias[0]
                grupo["aba_icms"] = grupo["aba_icms"] or aba_icms
                grupo["linha_icms"] = grupo["linha_icms"] or linha_icms
                grupo["fonte_icms"] = "C170"
                if valor_icms <= 0:
                    grupo["motivos"].add("Sem ICMS próprio positivo")
                    contagens["sem_icms_proprio"] += 1
                    continue
                grupo["icms"] += valor_icms
                if min(bp, bc, vp, vc, ap, ac) <= 0 or valor_icms > min(bp, bc):
                    grupo["motivos"].add("Base, alíquota ou contribuição incompatível")
                    contagens["base_ou_aliquota_incompativel"] += 1
                    continue
                esperado_pis = _arredondar(bp * ap / Decimal(100))
                esperado_cof = _arredondar(bc * ac / Decimal(100))
                if abs(esperado_pis - vp) > Decimal("0.02") or abs(esperado_cof - vc) > Decimal("0.02"):
                    grupo["motivos"].add("Contribuições divergentes das bases e alíquotas")
                    contagens["contribuicao_divergente"] += 1
                    continue
                grupo["pot_pis"] += min(_arredondar(valor_icms * ap / Decimal(100)), vp)
                grupo["pot_cof"] += min(_arredondar(valor_icms * ac / Decimal(100)), vc)
                contagens["itens_com_calculo_preliminar"] += 1
        for nome in (n for n in livro_pis.sheetnames if _slug(n).startswith("c175")):
            aba = livro_pis[nome]
            aba.reset_dimensions()
            linhas = aba.iter_rows(values_only=True)
            h = next(linhas)
            mes_i, ano_i = _indice(h, "Mês"), _indice(h, "Ano")
            cnpj_i = _indice(h, "CNPJ Estabelecimento(C010)", "CNPJ Estabelecimento", "CNPJ")
            chave_i = _indice(h, "Chave(C100)", "Chave")
            cfop_i = _indice(h, "CFOP")
            sit_i = _indice(h, "Situação(C100)", "Situação")
            try:
                modelo_i = _indice(h, "Modelo(C100)", "Modelo")
            except ValueError:
                modelo_i = None
            cst_p_i, cst_c_i = _indice(h, "CST PIS"), _indice(h, "CST COFINS")
            bp_i, vp_i, ap_i = _indice(h, "Valor BC PIS"), _indice(h, "Valor PIS"), _indice(h, "Aliquota PIS perc.")
            bc_i, vc_i, ac_i = _indice(h, "Valor BC COFINS"), _indice(h, "Valor COFINS"), _indice(h, "Aliquota COFINS perc.")
            for n, linha in enumerate(linhas, 2):
                if str(linha[sit_i] or "").strip().removesuffix(".0").zfill(2) not in {"00", "01"}:
                    continue
                cfop = re.sub(r"\D", "", str(linha[cfop_i] or ""))
                if len(cfop) != 4 or cfop[0] not in {"5", "6"}:
                    continue
                periodo = _competencia(linha[mes_i], linha[ano_i])
                if data_referencia is not None:
                    estado_prazo = classificar_competencia(periodo, data_referencia)
                    contagens[f"prazo_c175_{estado_prazo}"] += 1
                    if estado_prazo != "dentro":
                        continue
                cnpj = _cnpj(linha[cnpj_i])
                chave = re.sub(r"\D", "", str(linha[chave_i] or ""))
                if not periodo or not cnpj:
                    contagens["identificacao_incompleta_c175"] += 1
                    continue
                total_linhas[("C175", periodo, cnpj, chave, cfop)] += 1
                if (periodo, cnpj, chave, cfop) not in c190_por_grupo:
                    contagens["c175_sem_icms_proprio_c190"] += 1
                    continue
                cst_p = str(linha[cst_p_i] or "").strip().removesuffix(".0").zfill(2)
                cst_c = str(linha[cst_c_i] or "").strip().removesuffix(".0").zfill(2)
                if cst_p not in {"01", "02"} or cst_c not in {"01", "02"}:
                    continue
                modelo = str(linha[modelo_i] or "").strip().removesuffix(".0") if modelo_i is not None else chave[20:22]
                uf_codigo = chave[:2] if len(chave) == 44 else ""
                chave_grupo = (periodo, cnpj, chave or f"SEM_CHAVE:{nome}:{n}", modelo,
                               UFS.get(uf_codigo, ""), cfop, "C175")
                grupo = grupos[chave_grupo]
                grupo["itens"] += 1
                grupo["fallback_itens"] += 1
                grupo["aba_pis"] = grupo["aba_pis"] or nome
                grupo["linha_pis"] = grupo["linha_pis"] or n
                bp, vp, ap = _decimal(linha[bp_i]), _decimal(linha[vp_i]), _decimal(linha[ap_i])
                bc, vc, ac = _decimal(linha[bc_i]), _decimal(linha[vc_i]), _decimal(linha[ac_i])
                assinatura = (periodo, cnpj, chave, cfop, cst_p, cst_c, bp, vp, ap, bc, vc, ac)
                if assinatura in vistos_c175:
                    grupo["motivos"].add("Registro C175 duplicado")
                    contagens["duplicado_c175"] += 1
                    continue
                vistos_c175.add(assinatura)
                grupo["bp"] += bp
                grupo["vp"] += vp
                grupo["bc"] += bc
                grupo["vc"] += vc
                grupo["taxas_pis"].add(ap)
                grupo["taxas_cofins"].add(ac)
                contagens["grupos_tributados_c175"] += 1
                if (len(chave) != 44 or uf_codigo not in CODIGOS_UF or chave[6:20] != cnpj
                        or chave[2:6] != periodo[2:4] + periodo[5:7]):
                    grupo["motivos"].add("Chave C175 inválida")
                    contagens["chave_invalida_c175"] += 1
    finally:
        livro_pis.close()

    fontes_por_nota = defaultdict(set)
    for periodo, cnpj, chave, _modelo, _uf, _cfop, fonte_receita in grupos:
        if len(chave) == 44:
            fontes_por_nota[(periodo, cnpj, chave)].add(fonte_receita)
    resultado = []
    for (periodo, cnpj, chave, modelo, uf, cfop, fonte_receita), d in grupos.items():
        if len(fontes_por_nota[(periodo, cnpj, chave)]) > 1:
            d["motivos"].add("Nota presente em C170 e C175; conferir sobreposição")
        if d["itens"] != total_linhas[(fonte_receita, periodo, cnpj, chave, cfop)]:
            d["motivos"].add("CFOP contém linhas com CST não tributado; ICMS exige alocação")
        if d["fallback_itens"]:
            if d["fallback_itens"] != d["itens"] or d["icms"] > 0:
                d["motivos"].add("ICMS dividido entre C170 e C190; conferir")
            elif len(d["taxas_pis"]) != 1 or len(d["taxas_cofins"]) != 1:
                d["motivos"].add("Alíquotas distintas; C190 exige alocação")
            else:
                c190 = c190_por_grupo.get((periodo, cnpj, chave, cfop))
                if not c190:
                    d["motivos"].add("Sem ICMS próprio C170/C190 correspondente")
                elif c190["duplicado"]:
                    d["motivos"].add("C190 duplicado")
                else:
                    valor_icms = c190["icms"]
                    ap, ac = next(iter(d["taxas_pis"])), next(iter(d["taxas_cofins"]))
                    d["icms"] = valor_icms
                    d["aba_icms"], d["linha_icms"], d["fonte_icms"] = c190["aba"], c190["linha"], "C190"
                    if min(d["bp"], d["bc"], d["vp"], d["vc"], ap, ac) <= 0 or valor_icms > min(d["bp"], d["bc"]):
                        d["motivos"].add("Base, alíquota ou contribuição incompatível")
                    elif (abs(_arredondar(d["bp"] * ap / Decimal(100)) - d["vp"]) > Decimal("0.02") * d["itens"]
                          or abs(_arredondar(d["bc"] * ac / Decimal(100)) - d["vc"]) > Decimal("0.02") * d["itens"]):
                        d["motivos"].add("Contribuições divergentes das bases e alíquotas")
                    else:
                        d["pot_pis"] = min(_arredondar(valor_icms * ap / Decimal(100)), d["vp"])
                        d["pot_cof"] = min(_arredondar(valor_icms * ac / Decimal(100)), d["vc"])
                        contagens["grupos_com_calculo_c190"] += 1
        regra_uf = buscar_premissa(chave[:2], periodo) if len(chave) == 44 else None
        motivos = sorted(d["motivos"])
        # Não se publica um total parcial da NF-e quando qualquer item do grupo está pendente.
        apto = not motivos and d["icms"] > 0
        pis = _arredondar(d["pot_pis"]) if apto else None
        cof = _arredondar(d["pot_cof"]) if apto else None
        resultado.append({
            "competencia": periodo, "cnpj_estabelecimento": cnpj, "chave_nfe": chave,
            "modelo": modelo, "uf": uf, "fonte_receita": fonte_receita,
            "fonte_icms": d["fonte_icms"], "cfop": cfop, "itens": d["itens"],
            "base_pis": float(_arredondar(d["bp"])), "pis_escriturado": float(_arredondar(d["vp"])),
            "base_cofins": float(_arredondar(d["bc"])), "cofins_escriturada": float(_arredondar(d["vc"])),
            "icms_proprio_escriturado": float(_arredondar(d["icms"])),
            "pis_potencial": float(pis) if pis is not None else None,
            "cofins_potencial": float(cof) if cof is not None else None,
            "total_potencial": float(pis + cof) if pis is not None else None,
            "aliquota_icms_geral_referencia": float(regra_uf.aliquota_geral) if regra_uf else None,
            "estado": "Possível valor sob conferência" if apto else "Pendente de revisão",
            "motivos": "; ".join(motivos) or "Conferir NF-e, apuração e exclusões anteriores",
            "aba_contribuicoes": d["aba_pis"], "primeira_linha_contribuicoes": d["linha_pis"],
            "aba_icms": d["aba_icms"], "primeira_linha_icms": d["linha_icms"],
        })
    return pd.DataFrame(resultado, columns=COLUNAS_69), dict(contagens)


def gerar_relatorio_69(inventario: list[dict], candidatos: pd.DataFrame, contagens: dict[str, int],
                      data_referencia=None, cobertura_fontes: dict | None = None) -> bytes:
    """Excel independente do Tema 1125, com resumo, memória e conferência."""
    livro = Workbook(write_only=True)
    resumo = livro.create_sheet("Resumo_Tema_69")
    memoria = livro.create_sheet("Memoria_Mensal_69")
    notas = livro.create_sheet("Conferencia_Tema_69")
    resumo.column_dimensions["A"].width = 57
    resumo.column_dimensions["B"].width = 84
    resumo.column_dimensions["C"].width = 28
    resumo.column_dimensions["D"].width = 58
    resumo.column_dimensions["E"].width = 38
    resumo.freeze_panes = "B5"
    resumo.sheet_view.showGridLines = False
    resumo.page_setup.orientation = "landscape"
    resumo.page_setup.fitToWidth = 1

    colunas_memoria = ["Competência", "CNPJ estabelecimento", "Origem receita", "Origem ICMS",
                       "Grupos no filtro", "Grupos com valor", "Grupos pendentes", "Base PIS (R$)",
                       "Base COFINS (R$)", "ICMS próprio (R$)", "Possível PIS (R$)",
                       "Possível COFINS (R$)", "Possível total (R$)", "Saídas Contribuições no mês",
                       "Saídas C190 ICMS/IPI no mês", "Situação da cobertura"]
    for indice, nome in enumerate(colunas_memoria, 1):
        memoria.column_dimensions[get_column_letter(indice)].width = min(max(len(nome) + 3, 17), 48)
    memoria.freeze_panes = "C2"
    memoria.sheet_view.showGridLines = False

    colunas_conferencia = ["competencia", "cnpj_estabelecimento", "chave_nfe", "uf", "cfop",
                           "fonte_receita", "fonte_icms", "estado", "motivos", "base_pis",
                           "pis_escriturado", "base_cofins", "cofins_escriturada",
                           "icms_proprio_escriturado", "pis_potencial", "cofins_potencial",
                           "total_potencial", "conferencia_manual", "conferencia_prazo",
                           "data_extincao_tributo", "medida_que_afete_prazo", "revisor", "observacoes",
                           "modelo", "itens", "aliquota_icms_geral_referencia", "aba_contribuicoes",
                           "primeira_linha_contribuicoes", "aba_icms", "primeira_linha_icms"]
    for indice, nome in enumerate(colunas_conferencia, 1):
        notas.column_dimensions[get_column_letter(indice)].width = min(max(len(nome) + 3, 17), 50)
    notas.column_dimensions["C"].width = 48
    notas.column_dimensions["I"].width = 65
    notas.column_dimensions["U"].width = 45
    notas.freeze_panes = "D2"
    notas.sheet_view.showGridLines = False

    linha_resumo = 0
    def adicionar_resumo(valores, estilo=None, moedas=()):
        nonlocal linha_resumo
        linha_resumo += 1
        if estilo == "titulo":
            resumo.row_dimensions[linha_resumo].height = 34
        elif estilo == "cabecalho":
            resumo.row_dimensions[linha_resumo].height = 34
        elif any(isinstance(v, str) and len(v) > 100 for v in valores):
            resumo.row_dimensions[linha_resumo].height = 58
        celulas = []
        for indice, valor in enumerate(valores, 1):
            celula = WriteOnlyCell(resumo, value=valor)
            if estilo == "titulo":
                celula.font = Font(size=16, bold=True, color="FFFFFF")
                celula.fill = PREENCHIMENTOS["titulo"]
            elif estilo == "cabecalho":
                estilizar_cabecalho(celula)
            elif estilo == "destaque":
                celula.font = Font(bold=True, color="17365D")
                celula.fill = PREENCHIMENTOS["calculo"]
            if isinstance(valor, str) and len(valor) > 65 and estilo != "titulo":
                celula.alignment = Alignment(wrap_text=True, vertical="center")
            if indice in moedas:
                celula.number_format = '#,##0.00'
            celulas.append(celula)
        resumo.append(celulas)

    meses = candidatos["competencia"].astype(str).tolist() if not candidatos.empty else []
    faltantes = lacunas_competencia(data_referencia, meses)
    anos = sorted({mes[:4] for mes in competencias_esperadas(data_referencia, meses)} | {mes[:4] for mes in meses})
    aptos = candidatos["total_potencial"].notna() if not candidatos.empty else pd.Series(dtype=bool)
    adicionar_resumo(["TEMA 69 | ICMS próprio na base de PIS/COFINS"], "titulo")
    adicionar_resumo(["Levantamento preliminar para conferência documental"])
    if data_referencia is not None:
        adicionar_resumo(["Data de referência", data_referencia.strftime("%d/%m/%Y"),
                          "Corte operacional", data_corte(data_referencia).strftime("%d/%m/%Y")])
    adicionar_resumo([])
    adicionar_resumo(["RESULTADO PRELIMINAR", "Quantidade ou valor (R$)"], "cabecalho")
    adicionar_resumo(["Grupos NF-e/CFOP no filtro", len(candidatos)])
    adicionar_resumo(["Grupos com valor preliminar", int(aptos.sum())])
    adicionar_resumo(["Grupos pendentes de revisão", int((~aptos).sum()) if not candidatos.empty else 0])
    adicionar_resumo(["Possível PIS", float(candidatos["pis_potencial"].sum()) if not candidatos.empty else 0], moedas=(2,))
    adicionar_resumo(["Possível COFINS", float(candidatos["cofins_potencial"].sum()) if not candidatos.empty else 0], moedas=(2,))
    adicionar_resumo(["Possível total sob conferência", float(candidatos["total_potencial"].sum()) if not candidatos.empty else 0], "destaque", (2,))
    adicionar_resumo(["Situação", "Os valores dependem de NF-e, apuração, recolhimento e exclusões anteriores. Conferências manual e de prazo ainda devem ser preenchidas."])
    adicionar_resumo(["Competências sem grupo no filtro", ", ".join(faltantes) or "Nenhuma no intervalo de meses completos."])
    adicionar_resumo([])
    adicionar_resumo(["ORIGEM DO ICMS NESTE LEVANTAMENTO", "Grupos", "Com valor", "Possível total (R$)"], "cabecalho")
    if not candidatos.empty:
        for origem, dados in candidatos.groupby("fonte_icms", dropna=False):
            adicionar_resumo([origem or "Não identificada", len(dados), int(dados["total_potencial"].notna().sum()),
                              float(dados["total_potencial"].sum())], moedas=(4,))
    adicionar_resumo([])
    adicionar_resumo(["ANO", "Grupos", "Com valor", "Possível total (R$)", "Cobertura do filtro"], "cabecalho")
    for ano in anos:
        dados = candidatos.loc[candidatos["competencia"].astype(str).str.startswith(ano)] if not candidatos.empty else candidatos
        adicionar_resumo([int(ano), len(dados), int(dados["total_potencial"].notna().sum()) if not dados.empty else 0,
                          float(dados["total_potencial"].sum()) if not dados.empty else None,
                          "Com grupos no filtro" if not dados.empty else "Sem grupo no filtro; verificar fontes"], moedas=(4,))
    adicionar_resumo([])
    adicionar_resumo(["MÉTODO E LIMITES", "DETALHE"], "cabecalho")
    adicionar_resumo(["Cobertura", "Saídas C170/C175 da EFD-Contribuições, CFOP 5xxx/6xxx e CST 01/02 em PIS e COFINS, conciliadas com ICMS/IPI."])
    adicionar_resumo(["Fonte do ICMS", "C170 por item ou C190 por chave e CFOP, conforme a coluna de origem acima. Os registros não são somados entre si."])
    adicionar_resumo(["Alíquota geral da UF", "Apenas referência; o cálculo usa o ICMS próprio escriturado na fonte indicada por grupo."])
    adicionar_resumo(["Prescrição", "O corte de cinco anos é operacional. Conferir pagamento, medidas judiciais, modulação e aproveitamentos anteriores antes de concluir o prazo."])
    adicionar_resumo(["Pendências", "A memória traz valores por competência, estabelecimento e origem; a conferência reúne notas, motivos e campos de revisão."])
    adicionar_resumo(["Cobertura das fontes", "A memória conta saídas mapeadas em C170/C175 de Contribuições e C190 de ICMS/IPI; a ausência de grupo no filtro não prova ausência de escrituração."])
    adicionar_resumo([])
    adicionar_resumo(["CHECAGENS DA TRIAGEM", "Quantidade", "Unidade", "Código interno"], "cabecalho")
    nomes = {
        "c170_sem_icms_proprio_identificado": ("C170 sem ICMS próprio correspondente", "linhas C170"),
        "c175_sem_icms_proprio_c190": ("C175 sem ICMS próprio C190 correspondente", "linhas C175"),
        "grupos_com_calculo_c190": ("C190 com cálculo intermediário, antes dos bloqueios finais", "grupos"),
        "grupos_tributados_c175": ("C175 tributados com par C190", "linhas C175"),
        "itens_tributados_c170": ("C170 tributados com ICMS identificado", "itens C170"),
        "sem_par_c170_verificar_c190": ("C170 encaminhados ao C190", "itens C170"),
    }
    for nome, total in sorted(contagens.items()):
        rotulo, unidade = nomes.get(nome, (nome.replace("_", " ").capitalize(),
                                          "linhas" if nome.startswith("prazo_") else "ocorrências"))
        adicionar_resumo([rotulo, total, unidade, nome])
    adicionar_resumo([])
    adicionar_resumo(["ARQUIVOS-FONTE", "Nome", "SHA-256"], "cabecalho")
    for item in inventario:
        adicionar_resumo([item["tipo"], item["arquivo"], item["sha256"]])

    linha_memoria = []
    if not candidatos.empty:
        trabalho = candidatos.copy()
        trabalho["_com_valor"] = trabalho["total_potencial"].notna().astype(int)
        trabalho["_pendente"] = 1 - trabalho["_com_valor"]
        grupos = trabalho.groupby(["competencia", "cnpj_estabelecimento", "fonte_receita", "fonte_icms"],
                                  dropna=False, sort=True).agg(
            grupos=("chave_nfe", "size"), com_valor=("_com_valor", "sum"),
            pendentes=("_pendente", "sum"), base_pis=("base_pis", "sum"),
            base_cofins=("base_cofins", "sum"), icms=("icms_proprio_escriturado", "sum"),
            pis=("pis_potencial", "sum"), cofins=("cofins_potencial", "sum"),
            total=("total_potencial", "sum"),
        ).reset_index()
        linha_memoria = grupos.to_dict("records")
    linha_memoria.extend({"competencia": mes, "cobertura": "Sem grupo no filtro; verificar fontes"} for mes in faltantes)
    linha_memoria.sort(key=lambda item: (str(item["competencia"]), str(item.get("cnpj_estabelecimento", ""))))
    memoria.row_dimensions[1].height = 52
    memoria.append([_celula_cabecalho(memoria, nome) for nome in colunas_memoria])
    for item in linha_memoria:
        saidas_pis, saidas_icms, cobertura = cobertura_do_mes(
            str(item["competencia"]), "grupos" in item, cobertura_fontes,
        )
        valores = [item.get("competencia"), item.get("cnpj_estabelecimento"), item.get("fonte_receita"),
                   item.get("fonte_icms"), item.get("grupos"), item.get("com_valor"), item.get("pendentes"),
                   item.get("base_pis"), item.get("base_cofins"), item.get("icms"), item.get("pis"),
                   item.get("cofins"), item.get("total"), saidas_pis, saidas_icms, cobertura]
        linha = []
        for indice, valor in enumerate(valores, 1):
            celula = WriteOnlyCell(memoria, value=valor)
            if 8 <= indice <= 13:
                celula.number_format = '#,##0.00'
            linha.append(celula)
        memoria.append(linha)
    memoria.auto_filter.ref = f"A1:P{max(2, len(linha_memoria) + 1)}"

    notas.row_dimensions[1].height = 56
    notas.append([_celula_cabecalho(notas, nome, "entrada" if 18 <= indice <= 23 else
                                    "tecnico" if indice >= 24 else "cabecalho")
                  for indice, nome in enumerate(colunas_conferencia, 1)])
    moedas = {"base_pis", "pis_escriturado", "base_cofins", "cofins_escriturada",
              "icms_proprio_escriturado", "pis_potencial", "cofins_potencial", "total_potencial"}
    for dados in candidatos.to_dict("records"):
        dados = {**dados, "conferencia_manual": "Pendente", "conferencia_prazo": "Pendente"}
        linha = []
        for indice, nome in enumerate(colunas_conferencia, 1):
            valor = dados.get(nome)
            if valor is not None and pd.isna(valor):
                valor = None
            elif isinstance(valor, str) and valor.startswith(("=", "+", "-", "@")):
                valor = "'" + valor
            celula = WriteOnlyCell(notas, value=valor)
            if nome in moedas:
                celula.number_format = '#,##0.00'
            if 18 <= indice <= 23:
                celula.fill = PREENCHIMENTOS["entrada"]
            linha.append(celula)
        notas.append(linha)
    notas.auto_filter.ref = f"A1:AD{max(2, len(candidatos) + 1)}"
    validacao_manual = DataValidation(type="list", formula1='"Pendente,Confirmado,Rejeitado"')
    validacao_manual.add(f"R2:R{max(2, len(candidatos) + 1)}")
    notas.data_validations.append(validacao_manual)
    validacao_prazo = DataValidation(type="list", formula1='"Pendente,Conferido,Rejeitado"')
    validacao_prazo.add(f"S2:S{max(2, len(candidatos) + 1)}")
    notas.data_validations.append(validacao_prazo)
    ultima_linha = max(2, len(candidatos) + 1)
    notas.conditional_formatting.add(
        f"H2:H{ultima_linha}", FormulaRule(formula=['$H2="Possível valor sob conferência"'],
                                            fill=PREENCHIMENTOS["calculo"]),
    )
    notas.conditional_formatting.add(
        f"H2:H{ultima_linha}", FormulaRule(formula=['$H2="Pendente de revisão"'],
                                            fill=PREENCHIMENTOS["pendencia"]),
    )
    notas.conditional_formatting.add(
        f"R2:R{ultima_linha}", FormulaRule(formula=['AND($R2="Confirmado",$S2="Conferido")'],
                                            fill=PREENCHIMENTOS["confirmado"]),
    )
    arquivo = BytesIO()
    livro.save(arquivo)
    return arquivo.getvalue()
