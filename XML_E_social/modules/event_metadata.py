from __future__ import annotations

from dataclasses import dataclass
import io
import re
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
    evento_tag: str = ""
    namespace_xml: str = ""
    versao_layout: str = ""
    identificacao_parser: str = "fallback_legado"
    versao_desconhecida: bool = False
    divergencia_identificacao: bool = False


VERSOES_LAYOUT_CONHECIDAS = {
    "S_01_00_00", "S_01_01_00", "S_01_02_00", "S_01_03_00",
}
_RE_VERSAO = re.compile(r"/v_([^/]+?)/?$", re.IGNORECASE)
_RE_TAG = re.compile(rb"<\s*(?:[A-Za-z_][\w.-]*:)?(evt[A-Za-z0-9_]+)\b")
_RE_XMLNS = re.compile(rb"xmlns(?:\s*:\s*[A-Za-z_][\w.-]*)?\s*=\s*['\"]([^'\"]+)['\"]")


@dataclass(frozen=True)
class SniffedEvent:
    """Identificacao preliminar e limitada; nunca substitui a arvore validada."""

    evento_tag: str = ""
    tipo: str = "DESCONHECIDO"
    namespace_xml: str = ""
    versao_layout: str = ""


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") and "}" in tag else ""


def _versao_namespace(namespace: str) -> str:
    achado = _RE_VERSAO.search(namespace or "")
    return achado.group(1) if achado else ""


def identificar_evento_rapido(xml_bytes: bytes, limite: int = 262_144) -> SniffedEvent:
    """Extrai somente pistas estruturais do inicio do XML.

    O resultado e sempre confrontado com ``ElementTree`` por ``inspecionar_evento``.
    Assim um prefixo, comentario ou envelope incomum apenas aciona o fallback seguro.
    """
    trecho = bytes(xml_bytes[:max(0, limite)])
    tag_match = _RE_TAG.search(trecho)
    evento_tag = tag_match.group(1).decode("ascii", "ignore") if tag_match else ""
    namespace_match = _RE_XMLNS.search(trecho)
    namespace = namespace_match.group(1).decode("utf-8", "replace") if namespace_match else ""
    return SniffedEvent(
        evento_tag=evento_tag,
        tipo=EVENTOS_MAPA.get(evento_tag, "DESCONHECIDO"),
        namespace_xml=namespace,
        versao_layout=_versao_namespace(namespace),
    )


def _texto_descendente(bloco: ET.Element | None, nome: str) -> str:
    if bloco is None:
        return ""
    for elemento in bloco.iter():
        if localname(elemento.tag) == nome:
            return str(elemento.text or "").strip()
    return ""


def inspecionar_evento(
    root: ET.Element, identificacao_rapida: SniffedEvent | None = None
) -> EventMetadata:
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
    evento_tag = ""
    namespace_evento = ""

    for elemento in root.iter():
        nome = localname(elemento.tag)
        texto = str(elemento.text or "").strip()
        if tipo == "DESCONHECIDO" and nome in EVENTOS_MAPA:
            tipo = EVENTOS_MAPA[nome]
        if evento is None and nome.startswith("evt"):
            evento = elemento
            evento_tag = nome
            namespace_evento = _namespace(str(elemento.tag))
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

    namespace_xml = namespace_evento or _namespace(str(root.tag))
    versao_layout = _versao_namespace(namespace_xml)
    divergencia = False
    identificacao = "fallback_legado"
    if identificacao_rapida is not None and identificacao_rapida.evento_tag:
        divergencia = (
            identificacao_rapida.tipo != tipo
            or identificacao_rapida.evento_tag != evento_tag
            or bool(identificacao_rapida.namespace_xml)
            and identificacao_rapida.namespace_xml != namespace_xml
        )
        identificacao = "divergencia_fallback" if divergencia else "sniffer_confirmado"

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
        evento_tag=evento_tag,
        namespace_xml=namespace_xml,
        versao_layout=versao_layout,
        identificacao_parser=identificacao,
        versao_desconhecida=bool(
            versao_layout and versao_layout not in VERSOES_LAYOUT_CONHECIDAS
        ),
        divergencia_identificacao=divergencia,
    )


def inspecionar_evento_streaming(
    xml_bytes: bytes,
    identificacao_rapida: SniffedEvent | None = None,
) -> EventMetadata:
    """Coleta metadados sem conservar a árvore de eventos não analíticos."""
    pilha: list[str] = []
    tipo = "DESCONHECIDO"
    evento_tag = ""
    namespace_xml = ""
    id_evento = ""
    raiz_tag = ""
    ind_retif = ""
    recibo_referencia = ""
    recibo_evento = ""
    primeiro_recibo = ""
    primeiro_rec_arq = ""
    primeiro_prot = ""
    periodo = ""
    tp_insc = ""
    nr_insc = ""
    nome_empresa = ""
    encontrou_recibo = False

    for acao, elemento in ET.iterparse(io.BytesIO(xml_bytes), events=("start", "end")):
        nome = localname(elemento.tag)
        if acao == "start":
            pilha.append(nome)
            if not raiz_tag:
                raiz_tag = nome
            if not evento_tag and nome in EVENTOS_MAPA:
                evento_tag = nome
                tipo = EVENTOS_MAPA[nome]
                namespace_xml = _namespace(str(elemento.tag))
                id_evento = str(elemento.attrib.get("Id", ""))
            if nome == "recibo":
                encontrou_recibo = True
            continue

        texto = str(elemento.text or "").strip()
        ancestrais = set(pilha[:-1])
        if texto:
            if nome == "indRetif" and "ideEvento" in ancestrais and not ind_retif:
                ind_retif = texto
            elif nome == "nrRecibo":
                primeiro_recibo = primeiro_recibo or texto
                if "recibo" in ancestrais:
                    recibo_evento = recibo_evento or texto
                elif "ideEvento" in ancestrais:
                    recibo_referencia = recibo_referencia or texto
            elif nome == "nrRecArqBase":
                primeiro_rec_arq = primeiro_rec_arq or texto
            elif nome == "nrProtEntr":
                primeiro_prot = primeiro_prot or texto
            elif nome in {"perApur", "iniValid"} and not periodo:
                periodo = texto
            elif nome == "tpInsc" and "ideEmpregador" in ancestrais and not tp_insc:
                tp_insc = texto
            elif nome == "nrInsc" and "ideEmpregador" in ancestrais and not nr_insc:
                nr_insc = texto
            elif nome in {"nmRazao", "razaoSocial"} and not nome_empresa:
                nome_empresa = texto
        elemento.clear()
        pilha.pop()

    if ind_retif != "2":
        recibo_referencia = ""
        recibo_evento = recibo_evento or primeiro_recibo or primeiro_rec_arq or primeiro_prot
    namespace_xml = namespace_xml or (identificacao_rapida.namespace_xml if identificacao_rapida else "")
    versao_layout = _versao_namespace(namespace_xml)
    divergencia = False
    identificacao = "streaming_seletivo"
    if identificacao_rapida is not None and identificacao_rapida.evento_tag:
        divergencia = (
            identificacao_rapida.tipo != tipo
            or identificacao_rapida.evento_tag != evento_tag
            or bool(identificacao_rapida.namespace_xml)
            and identificacao_rapida.namespace_xml != namespace_xml
        )
        identificacao = (
            "divergencia_fallback_streaming" if divergencia else "sniffer_streaming_confirmado"
        )
    return EventMetadata(
        tipo=tipo,
        envelope_recibo=raiz_tag == "retornoEventoCompleto" or encontrou_recibo,
        id_evento_esocial=id_evento,
        ind_retif=ind_retif,
        recibo_evento=recibo_evento,
        recibo_referencia=recibo_referencia if ind_retif == "2" else "",
        periodo=periodo,
        tp_insc_empregador=tp_insc,
        cnpj_empregador=only_digits(nr_insc),
        nome_empresa=nome_empresa,
        evento_tag=evento_tag,
        namespace_xml=namespace_xml,
        versao_layout=versao_layout,
        identificacao_parser=identificacao,
        versao_desconhecida=bool(
            versao_layout and versao_layout not in VERSOES_LAYOUT_CONHECIDAS
        ),
        divergencia_identificacao=divergencia,
    )
