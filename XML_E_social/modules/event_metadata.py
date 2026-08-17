from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET

from modules.parser_xml import EVENTOS_MAPA
from utils.helpers import localname, only_digits


@dataclass(frozen=True)
class EventMetadata:
    """Metadados estruturais coletados em uma unica passagem pela arvore XML."""

    tipo: str = "DESCONHECIDO"
    envelope_recibo: bool = False
    id_evento_esocial: str = ""
    ind_retif: str = ""
    recibo_evento: str = ""
    recibo_referencia: str = ""
    periodo: str = ""
    tp_insc_empregador: str = ""
    cnpj_empregador: str = ""
    nome_empresa: str = ""


def _texto_descendente(bloco: ET.Element | None, nome: str) -> str:
    if bloco is None:
        return ""
    for elemento in bloco.iter():
        if localname(elemento.tag) == nome:
            return str(elemento.text or "").strip()
    return ""


def inspecionar_evento(root: ET.Element) -> EventMetadata:
    """Coleta os campos comuns sem repetir varreduras completas de ``root``.

    Os parsers tributarios continuam independentes. Esta funcao substitui apenas
    as buscas estruturais redundantes feitas durante a catalogacao.
    """

    tipo = "DESCONHECIDO"
    evento = None
    ide_evento = None
    bloco_recibo = None
    ide_empregador = None
    periodo = ""
    primeiro_nr_recibo = ""
    primeiro_nr_rec_arq_base = ""
    primeiro_nr_prot = ""
    nome_razao = ""
    nome_razao_alternativo = ""

    for elemento in root.iter():
        nome = localname(elemento.tag)
        texto = str(elemento.text or "").strip()
        if tipo == "DESCONHECIDO" and nome in EVENTOS_MAPA:
            tipo = EVENTOS_MAPA[nome]
        if evento is None and nome.startswith("evt"):
            evento = elemento
        if ide_evento is None and nome == "ideEvento":
            ide_evento = elemento
        if bloco_recibo is None and nome == "recibo":
            bloco_recibo = elemento
        if ide_empregador is None and nome == "ideEmpregador":
            ide_empregador = elemento
        if not periodo and nome in {"perApur", "iniValid"} and texto:
            periodo = texto
        if not primeiro_nr_recibo and nome == "nrRecibo":
            primeiro_nr_recibo = texto
        if not primeiro_nr_rec_arq_base and nome == "nrRecArqBase":
            primeiro_nr_rec_arq_base = texto
        if not primeiro_nr_prot and nome == "nrProtEntr":
            primeiro_nr_prot = texto
        if not nome_razao and nome == "nmRazao":
            nome_razao = texto
        if not nome_razao_alternativo and nome == "razaoSocial":
            nome_razao_alternativo = texto

    ind_retif = _texto_descendente(ide_evento, "indRetif")
    recibo_referencia = (
        _texto_descendente(ide_evento, "nrRecibo") if ind_retif == "2" else ""
    )
    recibo_evento = _texto_descendente(bloco_recibo, "nrRecibo")
    if not recibo_evento and ind_retif != "2":
        recibo_evento = (
            primeiro_nr_recibo or primeiro_nr_rec_arq_base or primeiro_nr_prot
        )

    return EventMetadata(
        tipo=tipo,
        envelope_recibo=(
            localname(root.tag) == "retornoEventoCompleto" or bloco_recibo is not None
        ),
        id_evento_esocial=str(
            evento.attrib.get("Id", "") if evento is not None else ""
        ),
        ind_retif=ind_retif,
        recibo_evento=recibo_evento,
        recibo_referencia=recibo_referencia,
        periodo=periodo,
        tp_insc_empregador=_texto_descendente(ide_empregador, "tpInsc"),
        cnpj_empregador=only_digits(
            _texto_descendente(ide_empregador, "nrInsc")
        ),
        nome_empresa=nome_razao or nome_razao_alternativo,
    )
