from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import os
from pathlib import Path


XSD_POR_EVENTO = {
    "S-1000": "evtInfoEmpregador.xsd",
    "S-1010": "evtTabRubrica.xsd",
    "S-1020": "evtTabLotacao.xsd",
    "S-1200": "evtRemun.xsd",
    "S-2200": "evtAdmissao.xsd",
    "S-2299": "evtDeslig.xsd",
    "S-3000": "evtExclusao.xsd",
    "S-5001": "evtBasesTrab.xsd",
    "S-5011": "evtCS.xsd",
}


@dataclass(frozen=True)
class ResultadoValidacaoXSD:
    executada: bool
    valida: bool
    status: str
    erro: str = ""


def modo_validacao_xsd() -> str:
    valor = os.environ.get("ESOCIAL_VALIDACAO_XSD", "desligada").strip().lower()
    if valor in {"completa", "full", "1", "true"}:
        return "completa"
    if valor in {"amostral", "sample", "amostra"}:
        return "amostral"
    return "desligada"


def _selecionado_amostra(hash_conteudo: str) -> bool:
    taxa = max(0.0, min(1.0, float(os.environ.get("ESOCIAL_XSD_TAXA_AMOSTRA", "0.01"))))
    numero = int((hash_conteudo or hashlib.sha256(b"").hexdigest())[:8], 16)
    return numero / 0xFFFFFFFF <= taxa


@lru_cache(maxsize=32)
def _schema_compilado(caminho: str):
    from lxml import etree

    documento = etree.parse(caminho)
    return etree.XMLSchema(documento)


def validar_xml_xsd(
    xml_bytes: bytes,
    tipo: str,
    hash_conteudo: str,
) -> ResultadoValidacaoXSD:
    modo = modo_validacao_xsd()
    if modo == "desligada":
        return ResultadoValidacaoXSD(False, True, "desligada")
    if modo == "amostral" and not _selecionado_amostra(hash_conteudo):
        return ResultadoValidacaoXSD(False, True, "fora_da_amostra")
    nome_xsd = XSD_POR_EVENTO.get(tipo)
    if not nome_xsd:
        return ResultadoValidacaoXSD(False, True, "evento_sem_xsd_configurado")
    pasta = os.environ.get("ESOCIAL_XSD_DIR", "").strip()
    if not pasta:
        return ResultadoValidacaoXSD(False, True, "diretorio_xsd_nao_configurado")
    caminho = Path(pasta).expanduser().resolve() / nome_xsd
    if not caminho.is_file():
        return ResultadoValidacaoXSD(False, True, "xsd_nao_localizado", str(caminho))
    try:
        from lxml import etree
    except ImportError:
        return ResultadoValidacaoXSD(False, True, "lxml_indisponivel")
    try:
        documento = etree.fromstring(xml_bytes)
        schema = _schema_compilado(str(caminho))
        schema.assertValid(documento)
        return ResultadoValidacaoXSD(True, True, "valido")
    except Exception as exc:
        return ResultadoValidacaoXSD(True, False, "invalido", str(exc))

