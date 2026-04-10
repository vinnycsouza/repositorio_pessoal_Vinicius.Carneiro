from dataclasses import dataclass
from typing import Dict, List, Tuple
import xml.etree.ElementTree as ET

from utils.helpers import (
    all_elements_by_localname,
    first_text_by_localname,
    localname,
    only_digits,
    safe_float,
    text_or_none,
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


@dataclass
class RubricaPagamento:
    arquivo: str
    cpf: str
    matricula: str
    per_apur: str
    cod_rubr: str
    ide_tab_rubr: str
    vr_rubr: float
    nat_rubr: str
    cod_inc_cp: str
    dsc_rubr: str
    nr_recibo_evento: str


@dataclass
class BaseTrabalhador:
    arquivo: str
    cpf: str
    matricula: str
    per_apur: str
    cod_categ: str
    base_cp: float
    base_seg: float
    vr_desc_seg: float
    nr_recibo_base: str


EVENTOS_MAPA = {
    "evtInfoEmpregador": "S-1000",
    "evtTabEstab": "S-1005",
    "evtTabLotacao": "S-1020",
    "evtRubrica": "S-1010",
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


def detectar_tipo_evento(root: ET.Element) -> str:
    for el in root.iter():
        nome = localname(el.tag)
        if nome in EVENTOS_MAPA:
            return EVENTOS_MAPA[nome]
    return "DESCONHECIDO"



def obter_recibo_principal(root: ET.Element) -> str:
    return (
        first_text_by_localname(root, "nrRecibo")
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
    ide_tab_rubr = first_text_by_localname(root, "ideTabRubr") or ""

    dados_rubrica = all_elements_by_localname(root, "dadosRubrica")
    if dados_rubrica:
        for bloco in dados_rubrica:
            cod_rubr = first_text_by_localname(bloco, "codRubr") or first_text_by_localname(root, "codRubr") or ""
            if not cod_rubr:
                continue
            saida.append(
                RubricaInfo(
                    cod_rubr=cod_rubr,
                    ide_tab_rubr=ide_tab_rubr,
                    dsc_rubr=first_text_by_localname(bloco, "dscRubr") or "",
                    nat_rubr=first_text_by_localname(bloco, "natRubr") or "",
                    cod_inc_cp=first_text_by_localname(bloco, "codIncCP") or "",
                    cod_inc_fgts=first_text_by_localname(bloco, "codIncFGTS") or "",
                    cod_inc_irrf=first_text_by_localname(bloco, "codIncIRRF") or "",
                )
            )
    else:
        cod_rubr = first_text_by_localname(root, "codRubr") or ""
        if cod_rubr:
            saida.append(
                RubricaInfo(
                    cod_rubr=cod_rubr,
                    ide_tab_rubr=ide_tab_rubr,
                    dsc_rubr=first_text_by_localname(root, "dscRubr") or "",
                    nat_rubr=first_text_by_localname(root, "natRubr") or "",
                    cod_inc_cp=first_text_by_localname(root, "codIncCP") or "",
                    cod_inc_fgts=first_text_by_localname(root, "codIncFGTS") or "",
                    cod_inc_irrf=first_text_by_localname(root, "codIncIRRF") or "",
                )
            )
    return saida



def parse_s1200(root: ET.Element, rubricas_map: Dict[Tuple[str, str], RubricaInfo], arquivo: str) -> List[RubricaPagamento]:
    saida: List[RubricaPagamento] = []

    cpf = only_digits(first_text_by_localname(root, "cpfTrab"))
    matricula = first_text_by_localname(root, "matricula") or ""
    per_apur = first_text_by_localname(root, "perApur") or ""
    nr_recibo_evento = obter_recibo_principal(root)

    for dm_dev in all_elements_by_localname(root, "dmDev"):
        ide_tab_rubr_dm = first_text_by_localname(dm_dev, "ideTabRubr") or ""
        for item in dm_dev.iter():
            if localname(item.tag) != "detRubr":
                continue

            cod_rubr = first_text_by_localname(item, "codRubr") or ""
            ide_tab_rubr = first_text_by_localname(item, "ideTabRubr") or ide_tab_rubr_dm
            vr_rubr = safe_float(first_text_by_localname(item, "vrRubr"))

            rubr = rubricas_map.get((cod_rubr, ide_tab_rubr)) or rubricas_map.get((cod_rubr, ""))
            nat_rubr = rubr.nat_rubr if rubr else ""
            cod_inc_cp = rubr.cod_inc_cp if rubr else ""
            dsc_rubr = rubr.dsc_rubr if rubr else ""

            if cod_rubr:
                saida.append(
                    RubricaPagamento(
                        arquivo=arquivo,
                        cpf=cpf,
                        matricula=matricula,
                        per_apur=per_apur,
                        cod_rubr=cod_rubr,
                        ide_tab_rubr=ide_tab_rubr,
                        vr_rubr=vr_rubr,
                        nat_rubr=nat_rubr,
                        cod_inc_cp=cod_inc_cp,
                        dsc_rubr=dsc_rubr,
                        nr_recibo_evento=nr_recibo_evento,
                    )
                )
    return saida



def parse_s5001(root: ET.Element, arquivo: str) -> List[BaseTrabalhador]:
    saida: List[BaseTrabalhador] = []
    per_apur = first_text_by_localname(root, "perApur") or ""
    nr_recibo_base = first_text_by_localname(root, "nrRecArqBase") or ""

    blocos = all_elements_by_localname(root, "ideTrabalhador")
    if blocos:
        for bloco in blocos:
            cpf = only_digits(first_text_by_localname(bloco, "cpfTrab"))
            matricula = first_text_by_localname(bloco, "matricula") or ""
            cod_categ = first_text_by_localname(bloco, "codCateg") or ""

            base_cp = 0.0
            base_seg = 0.0
            vr_desc_seg = 0.0

            for el in bloco.iter():
                nome = localname(el.tag)
                val = safe_float(text_or_none(el))
                if nome in {"vrBcCp00", "vrBcCp15", "vrBcCp20", "vrBcCp25", "vrBcCp13"}:
                    base_cp += val
                elif nome == "vrBcSeg":
                    base_seg += val
                elif nome == "vrDescSeg":
                    vr_desc_seg += val

            if cpf or matricula or base_cp or base_seg or vr_desc_seg:
                saida.append(
                    BaseTrabalhador(
                        arquivo=arquivo,
                        cpf=cpf,
                        matricula=matricula,
                        per_apur=per_apur,
                        cod_categ=cod_categ,
                        base_cp=base_cp,
                        base_seg=base_seg,
                        vr_desc_seg=vr_desc_seg,
                        nr_recibo_base=nr_recibo_base,
                    )
                )
        return saida

    cpf = only_digits(first_text_by_localname(root, "cpfTrab"))
    matricula = first_text_by_localname(root, "matricula") or ""
    cod_categ = first_text_by_localname(root, "codCateg") or ""
    base_cp = 0.0
    base_seg = 0.0
    vr_desc_seg = 0.0

    for el in root.iter():
        nome = localname(el.tag)
        val = safe_float(text_or_none(el))
        if nome in {"vrBcCp00", "vrBcCp15", "vrBcCp20", "vrBcCp25", "vrBcCp13"}:
            base_cp += val
        elif nome == "vrBcSeg":
            base_seg += val
        elif nome == "vrDescSeg":
            vr_desc_seg += val

    if cpf or matricula or base_cp or base_seg or vr_desc_seg:
        saida.append(
            BaseTrabalhador(
                arquivo=arquivo,
                cpf=cpf,
                matricula=matricula,
                per_apur=per_apur,
                cod_categ=cod_categ,
                base_cp=base_cp,
                base_seg=base_seg,
                vr_desc_seg=vr_desc_seg,
                nr_recibo_base=nr_recibo_base,
            )
        )
    return saida
