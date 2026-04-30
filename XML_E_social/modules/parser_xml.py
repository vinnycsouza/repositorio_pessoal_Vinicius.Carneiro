from dataclasses import dataclass
from typing import Dict, List, Tuple
import xml.etree.ElementTree as ET

from utils.helpers import (
    all_elements_by_localname,
    first_text_by_localname,
    localname,
    only_digits,
    safe_float,
)


@dataclass
class RubricaInfo:
    cod_rubr: str
    ide_tab_rubr: str
    dsc_rubr: str
    nat_rubr: str
    cod_inc_cp: str
    cod_inc_fgts: str
    cod_inc_irrf: str
    tp_rubr: str
    origem_bloco: str
    ini_valid: str
    fim_valid: str


@dataclass
class RubricaPagamento:
    arquivo: str
    cpf: str
    matricula: str
    per_apur: str
    cod_categ: str
    tp_insc_estab: str
    nr_insc_estab: str
    cod_lotacao: str
    cod_rubr: str
    ide_tab_rubr: str
    vr_rubr: float
    nat_rubr: str
    cod_inc_cp: str
    dsc_rubr: str
    tp_rubr: str
    nr_recibo_evento: str


@dataclass
class BaseTrabalhador:
    arquivo: str
    cpf: str
    matricula: str
    per_apur: str
    per_ref: str
    cod_categ: str
    tp_insc_estab: str
    nr_insc_estab: str
    cod_lotacao: str
    ind13: str
    tp_valor: str
    valor: float
    origem_valor: str
    nr_recibo_base: str


@dataclass
class BaseContribuicao:
    arquivo: str
    per_apur: str
    tp_insc_estab: str
    nr_insc_estab: str
    cod_lotacao: str
    cod_categ: str
    ind_incid: str
    fpas: str
    cod_tercs: str
    aliq_rat_ajust: float
    vr_bc_cp: float
    vr_bc_cp_00: float
    vr_bc_cp_15: float
    vr_bc_cp_20: float
    vr_bc_cp_25: float
    nr_recibo_base: str


EVENTOS_MAPA = {
    "evtInfoEmpregador": "S-1000",
    "evtTabEstab": "S-1005",
    "evtTabLotacao": "S-1020",
    "evtRubrica": "S-1010",
    "evtTabRubrica": "S-1010",
    "evtAdmPrelim": "S-2190",
    "evtAdmissao": "S-2200",
    "evtAltCadastral": "S-2205",
    "evtAltContratual": "S-2206",
    "evtAfastTemp": "S-2230",
    "evtDeslig": "S-2299",
    "evtTSVInicio": "S-2300",
    "evtRemun": "S-1200",
    "evtPgtos": "S-1210",
    "evtReabreEvPer": "S-1298",
    "evtFechaEvPer": "S-1299",
    "evtExclusao": "S-3000",
    "evtBasesTrab": "S-5001",
    "evtIrrfBenef": "S-5002",
    "evtBasesFGTS": "S-5003",
    "evtCS": "S-5011",
    "evtIrrf": "S-5012",
    "evtFGTS": "S-5013",
}


def children_by_localname(root: ET.Element, name: str) -> List[ET.Element]:
    return [el for el in list(root) if localname(el.tag) == name]


def first_child_by_localname(root: ET.Element, name: str):
    for el in list(root):
        if localname(el.tag) == name:
            return el
    return None


def detectar_tipo_evento(root: ET.Element) -> str:
    for el in root.iter():
        nome = localname(el.tag)
        if nome in EVENTOS_MAPA:
            return EVENTOS_MAPA[nome]
    return "DESCONHECIDO"


def obter_recibo_principal(root: ET.Element) -> str:
    return (
        first_text_by_localname(root, "nrRecibo")
        or first_text_by_localname(root, "nrRecArqBase")
        or first_text_by_localname(root, "nrProtEntr")
        or ""
    )


def parse_s3000(root: ET.Element) -> Dict[str, str]:
    return {
        "nrRecEvt": first_text_by_localname(root, "nrRecEvt") or "",
        "nrRecibo": obter_recibo_principal(root),
    }


def parse_s1010(root: ET.Element) -> List[RubricaInfo]:
    saida: List[RubricaInfo] = []

    blocos_origem = []
    for nome_bloco in ("inclusao", "alteracao", "novaValidade"):
        blocos_origem.extend([(nome_bloco, bloco) for bloco in all_elements_by_localname(root, nome_bloco)])

    if not blocos_origem:
        blocos_origem = [("raiz", root)]

    for origem, bloco in blocos_origem:
        ide_rubrica = None
        dados_rubrica = None
        for child in bloco.iter():
            nome = localname(child.tag)
            if nome == "ideRubrica" and ide_rubrica is None:
                ide_rubrica = child
            elif nome == "dadosRubrica" and dados_rubrica is None:
                dados_rubrica = child

        ide_rubrica = ide_rubrica or bloco
        dados_rubrica = dados_rubrica or bloco

        cod_rubr = first_text_by_localname(ide_rubrica, "codRubr") or first_text_by_localname(bloco, "codRubr") or ""
        ide_tab_rubr = first_text_by_localname(ide_rubrica, "ideTabRubr") or first_text_by_localname(bloco, "ideTabRubr") or ""
        dsc_rubr = first_text_by_localname(dados_rubrica, "dscRubr") or ""
        nat_rubr = first_text_by_localname(dados_rubrica, "natRubr") or ""
        cod_inc_cp = first_text_by_localname(dados_rubrica, "codIncCP") or ""
        cod_inc_fgts = first_text_by_localname(dados_rubrica, "codIncFGTS") or ""
        cod_inc_irrf = first_text_by_localname(dados_rubrica, "codIncIRRF") or ""
        tp_rubr = first_text_by_localname(dados_rubrica, "tpRubr") or ""
        ini_valid = first_text_by_localname(ide_rubrica, "iniValid") or first_text_by_localname(bloco, "iniValid") or ""
        fim_valid = first_text_by_localname(ide_rubrica, "fimValid") or first_text_by_localname(bloco, "fimValid") or ""

        if cod_rubr:
            saida.append(
                RubricaInfo(
                    cod_rubr=cod_rubr,
                    ide_tab_rubr=ide_tab_rubr,
                    dsc_rubr=dsc_rubr,
                    nat_rubr=nat_rubr,
                    cod_inc_cp=cod_inc_cp,
                    cod_inc_fgts=cod_inc_fgts,
                    cod_inc_irrf=cod_inc_irrf,
                    tp_rubr=tp_rubr,
                    origem_bloco=origem,
                    ini_valid=ini_valid,
                    fim_valid=fim_valid,
                )
            )

    dedup: Dict[Tuple[str, str], RubricaInfo] = {}
    for item in saida:
        dedup[(item.cod_rubr, item.ide_tab_rubr)] = item
    return list(dedup.values())


def parse_s1200(root: ET.Element, rubricas_map: Dict[Tuple[str, str], RubricaInfo], arquivo: str) -> List[RubricaPagamento]:
    saida: List[RubricaPagamento] = []

    cpf = only_digits(first_text_by_localname(root, "cpfTrab"))
    per_apur = first_text_by_localname(root, "perApur") or ""
    nr_recibo_evento = obter_recibo_principal(root)

    for dm_dev in all_elements_by_localname(root, "dmDev"):
        cod_categ = first_text_by_localname(dm_dev, "codCateg") or ""

        # S-1200 pode trazer período atual (infoPerApur) e/ou períodos anteriores (infoPerAnt).
        blocos_periodo = all_elements_by_localname(dm_dev, "infoPerApur") + all_elements_by_localname(dm_dev, "infoPerAnt")
        if not blocos_periodo:
            blocos_periodo = [dm_dev]

        for bloco_periodo in blocos_periodo:
            for ide_estab in all_elements_by_localname(bloco_periodo, "ideEstabLot"):
                tp_insc_estab = first_text_by_localname(ide_estab, "tpInsc") or ""
                nr_insc_estab = first_text_by_localname(ide_estab, "nrInsc") or ""
                cod_lotacao = first_text_by_localname(ide_estab, "codLotacao") or ""

                blocos_remun = all_elements_by_localname(ide_estab, "remunPerApur") + all_elements_by_localname(ide_estab, "remunPerAnt")
                if not blocos_remun:
                    blocos_remun = [ide_estab]

                for remun in blocos_remun:
                    matricula = first_text_by_localname(remun, "matricula") or first_text_by_localname(dm_dev, "matricula") or ""

                    for item in all_elements_by_localname(remun, "itensRemun"):
                        cod_rubr = first_text_by_localname(item, "codRubr") or ""
                        ide_tab_rubr = first_text_by_localname(item, "ideTabRubr") or ""
                        vr_rubr = safe_float(first_text_by_localname(item, "vrRubr"))

                        rubr = rubricas_map.get((cod_rubr, ide_tab_rubr)) or rubricas_map.get((cod_rubr, ""))
                        nat_rubr = rubr.nat_rubr if rubr else ""
                        cod_inc_cp = rubr.cod_inc_cp if rubr else ""
                        dsc_rubr = rubr.dsc_rubr if rubr else ""
                        tp_rubr = rubr.tp_rubr if rubr else ""

                        if cod_rubr:
                            saida.append(
                                RubricaPagamento(
                                    arquivo=arquivo,
                                    cpf=cpf,
                                    matricula=matricula,
                                    per_apur=per_apur,
                                    cod_categ=cod_categ,
                                    tp_insc_estab=tp_insc_estab,
                                    nr_insc_estab=nr_insc_estab,
                                    cod_lotacao=cod_lotacao,
                                    cod_rubr=cod_rubr,
                                    ide_tab_rubr=ide_tab_rubr,
                                    vr_rubr=vr_rubr,
                                    nat_rubr=nat_rubr,
                                    cod_inc_cp=cod_inc_cp,
                                    dsc_rubr=dsc_rubr,
                                    tp_rubr=tp_rubr,
                                    nr_recibo_evento=nr_recibo_evento,
                                )
                            )

    return saida


def parse_s5001(root: ET.Element, arquivo: str) -> List[BaseTrabalhador]:
    """Extrai o detalhamento do S-5001.

    A versão anterior só guardava CPF/matrícula. Para auditoria da base, o que importa é
    o bloco infoBaseCS, onde aparecem tpValor e valor por trabalhador/categoria/lotação.
    Também capturamos detInfoPerRef quando disponível, para explicar competências de referência.
    """
    saida: List[BaseTrabalhador] = []
    per_apur = first_text_by_localname(root, "perApur") or ""
    nr_recibo_base = first_text_by_localname(root, "nrRecArqBase") or ""

    ide_trab = first_child_by_localname(next((e for e in root.iter() if localname(e.tag) == "evtBasesTrab"), root), "ideTrabalhador")
    cpf = only_digits(first_text_by_localname(ide_trab, "cpfTrab") if ide_trab is not None else first_text_by_localname(root, "cpfTrab"))

    for ide_estab in all_elements_by_localname(root, "ideEstabLot"):
        tp_insc_estab = first_text_by_localname(ide_estab, "tpInsc") or ""
        nr_insc_estab = first_text_by_localname(ide_estab, "nrInsc") or ""
        cod_lotacao = first_text_by_localname(ide_estab, "codLotacao") or ""

        for info_cat in all_elements_by_localname(ide_estab, "infoCategIncid"):
            matricula = first_text_by_localname(info_cat, "matricula") or ""
            cod_categ = first_text_by_localname(info_cat, "codCateg") or ""

            # Base por trabalhador/categoria/lotação.
            for info_base in children_by_localname(info_cat, "infoBaseCS"):
                saida.append(
                    BaseTrabalhador(
                        arquivo=arquivo,
                        cpf=cpf,
                        matricula=matricula,
                        per_apur=per_apur,
                        per_ref=per_apur,
                        cod_categ=cod_categ,
                        tp_insc_estab=tp_insc_estab,
                        nr_insc_estab=nr_insc_estab,
                        cod_lotacao=cod_lotacao,
                        ind13=first_text_by_localname(info_base, "ind13") or "",
                        tp_valor=first_text_by_localname(info_base, "tpValor") or "",
                        valor=safe_float(first_text_by_localname(info_base, "valor")),
                        origem_valor="infoBaseCS",
                        nr_recibo_base=nr_recibo_base,
                    )
                )

            # Detalhe por competência de referência, quando existente.
            for info_per_ref in children_by_localname(info_cat, "infoPerRef"):
                per_ref = first_text_by_localname(info_per_ref, "perRef") or per_apur
                for det in children_by_localname(info_per_ref, "detInfoPerRef"):
                    saida.append(
                        BaseTrabalhador(
                            arquivo=arquivo,
                            cpf=cpf,
                            matricula=matricula,
                            per_apur=per_apur,
                            per_ref=per_ref,
                            cod_categ=cod_categ,
                            tp_insc_estab=tp_insc_estab,
                            nr_insc_estab=nr_insc_estab,
                            cod_lotacao=cod_lotacao,
                            ind13=first_text_by_localname(det, "ind13") or "",
                            tp_valor=first_text_by_localname(det, "tpValor") or "",
                            valor=safe_float(first_text_by_localname(det, "vrPerRef")),
                            origem_valor="detInfoPerRef",
                            nr_recibo_base=nr_recibo_base,
                        )
                    )

    if not saida and cpf:
        saida.append(
            BaseTrabalhador(
                arquivo=arquivo,
                cpf=cpf,
                matricula="",
                per_apur=per_apur,
                per_ref=per_apur,
                cod_categ="",
                tp_insc_estab="",
                nr_insc_estab="",
                cod_lotacao="",
                ind13="",
                tp_valor="",
                valor=0.0,
                origem_valor="sem_infoBaseCS",
                nr_recibo_base=nr_recibo_base,
            )
        )
    return saida


def parse_s5011(root: ET.Element, arquivo: str) -> List[BaseContribuicao]:
    saida: List[BaseContribuicao] = []
    per_apur = first_text_by_localname(root, "perApur") or ""
    nr_recibo_base = first_text_by_localname(root, "nrRecArqBase") or ""

    for ide_estab in all_elements_by_localname(root, "ideEstab"):
        tp_insc_estab = first_text_by_localname(ide_estab, "tpInsc") or ""
        nr_insc_estab = first_text_by_localname(ide_estab, "nrInsc") or ""
        info_estab = next((x for x in ide_estab if localname(x.tag) == "infoEstab"), ide_estab)
        aliq_rat_ajust = safe_float(first_text_by_localname(info_estab, "aliqRatAjust"))

        for ide_lot in [x for x in ide_estab if localname(x.tag) == "ideLotacao"]:
            cod_lotacao = first_text_by_localname(ide_lot, "codLotacao") or ""
            fpas = first_text_by_localname(ide_lot, "fpas") or ""
            cod_tercs = first_text_by_localname(ide_lot, "codTercs") or ""

            for bases_remun in all_elements_by_localname(ide_lot, "basesRemun"):
                ind_incid = first_text_by_localname(bases_remun, "indIncid") or ""
                cod_categ = first_text_by_localname(bases_remun, "codCateg") or ""
                bases_cp = next((x for x in bases_remun if localname(x.tag) == "basesCp"), bases_remun)

                vr_bc_cp_00 = safe_float(first_text_by_localname(bases_cp, "vrBcCp00"))
                vr_bc_cp_15 = safe_float(first_text_by_localname(bases_cp, "vrBcCp15"))
                vr_bc_cp_20 = safe_float(first_text_by_localname(bases_cp, "vrBcCp20"))
                vr_bc_cp_25 = safe_float(first_text_by_localname(bases_cp, "vrBcCp25"))
                vr_bc_cp = vr_bc_cp_00 + vr_bc_cp_15 + vr_bc_cp_20 + vr_bc_cp_25

                saida.append(
                    BaseContribuicao(
                        arquivo=arquivo,
                        per_apur=per_apur,
                        tp_insc_estab=tp_insc_estab,
                        nr_insc_estab=nr_insc_estab,
                        cod_lotacao=cod_lotacao,
                        cod_categ=cod_categ,
                        ind_incid=ind_incid,
                        fpas=fpas,
                        cod_tercs=cod_tercs,
                        aliq_rat_ajust=aliq_rat_ajust,
                        vr_bc_cp=vr_bc_cp,
                        vr_bc_cp_00=vr_bc_cp_00,
                        vr_bc_cp_15=vr_bc_cp_15,
                        vr_bc_cp_20=vr_bc_cp_20,
                        vr_bc_cp_25=vr_bc_cp_25,
                        nr_recibo_base=nr_recibo_base,
                    )
                )

    return saida
