from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


def _nome_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def extrair_dados_s1010(caminho: Path) -> tuple[str | None, str | None, str | None]:
    try:
        raiz = ET.parse(caminho).getroot()
    except (ET.ParseError, OSError):
        return None, None, None

    codigo = tabela = vigencia = None
    for elem in raiz.iter():
        nome = _nome_local(elem.tag)
        texto = (elem.text or "").strip()
        if nome == "codRubr" and texto and codigo is None:
            codigo = texto
        elif nome == "ideTabRubr" and texto and tabela is None:
            tabela = texto
        elif nome == "iniValid" and texto and vigencia is None:
            vigencia = texto

    return codigo, tabela, vigencia


def varrer_pasta_xml(pasta: str | Path) -> dict[str, set[str]]:
    resultado: dict[str, set[str]] = {}
    for caminho in Path(pasta).rglob("*.xml"):
        codigo, _, vigencia = extrair_dados_s1010(caminho)
        if not codigo:
            continue
        resultado.setdefault(codigo.upper(), set())
        if vigencia:
            resultado[codigo.upper()].add(vigencia)
    return resultado
