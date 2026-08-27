from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import os
import sqlite3
from typing import Iterable


ENGINE_VERSION = "10.0.0"
SCHEMA_SQLITE_VERSION = 3
PARSER_VERSION = "v10.0"


@dataclass(frozen=True)
class EventSchema:
    tipo: str
    tag: str
    parser_flag: str
    analitico: bool = False
    segunda_passagem: bool = False


EVENT_SCHEMAS = {
    item.tipo: item
    for item in (
        EventSchema("S-1000", "evtInfoEmpregador", "ESOCIAL_V10_PARSER_CONTEXTO"),
        EventSchema("S-1010", "evtTabRubrica", "ESOCIAL_V10_PARSER_S1010", True),
        EventSchema("S-1020", "evtTabLotacao", "ESOCIAL_V10_PARSER_CONTEXTO"),
        EventSchema("S-1200", "evtRemun", "ESOCIAL_V10_PARSER_S1200", True, True),
        EventSchema("S-2200", "evtAdmissao", "ESOCIAL_V10_PARSER_CONTEXTO"),
        EventSchema("S-2299", "evtDeslig", "ESOCIAL_V10_PARSER_S2299", True, True),
        EventSchema("S-3000", "evtExclusao", "ESOCIAL_V10_PARSER_S3000", True),
        EventSchema("S-5001", "evtBasesTrab", "ESOCIAL_V10_PARSER_BASES", True, True),
        EventSchema("S-5011", "evtCS", "ESOCIAL_V10_PARSER_BASES", True, True),
    )
}


@dataclass(frozen=True)
class NormalizedEventBatch:
    tipo: str
    arquivo: str
    parser_versao: str
    categoria: str
    itens: tuple[object, ...]


def flag_ativa(nome: str, padrao: bool = False) -> bool:
    valor = os.environ.get(nome)
    if valor is None:
        return bool(padrao)
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on", "v10"}


def modo_parser(tipo: str) -> str:
    """Retorna legado, sombra ou v10 sem alternar dentro do mesmo evento."""
    schema = EVENT_SCHEMAS.get(tipo)
    if schema is None:
        return "legado"
    padrao = "v10" if tipo == "S-2299" else "legado"
    valor = os.environ.get(schema.parser_flag, padrao).strip().lower()
    if valor in {"1", "true", "sim", "yes", "on", "v10"}:
        return "v10"
    if valor in {"sombra", "shadow"}:
        return "sombra"
    return "legado"


def assinatura_itens(itens: Iterable[object]) -> str:
    """Assinatura estável para equivalência do modo sombra."""
    normalizados = []
    for item in itens:
        if is_dataclass(item):
            valor = asdict(item)
        elif isinstance(item, dict):
            valor = dict(item)
        else:
            valor = str(item)
        normalizados.append(valor)
    serializado = json.dumps(
        normalizados,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(serializado).hexdigest()


def registrar_versoes_workspace(conn: sqlite3.Connection) -> None:
    valores = {
        "versao_engine": ENGINE_VERSION,
        "versao_schema_sqlite": SCHEMA_SQLITE_VERSION,
        "versao_parser": PARSER_VERSION,
    }
    conn.executemany(
        "INSERT INTO meta(chave,valor) VALUES(?,?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
        valores.items(),
    )
