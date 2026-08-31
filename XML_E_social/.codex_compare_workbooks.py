from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def cell_value(cell):
    tipo = cell.attrib.get("t", "")
    if tipo == "inlineStr":
        return "".join(t.text or "" for t in cell.findall(".//m:t", NS))
    valor = cell.find("m:v", NS)
    return valor.text if valor is not None else ""


def inspect(path: Path):
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {
            rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("p:Relationship", NS)
        }
        sheets = []
        for sh in wb.findall("m:sheets/m:sheet", NS):
            rid = sh.attrib[f"{{{NS['r']}}}id"]
            target = targets[rid].lstrip("/")
            if not target.startswith("xl/"):
                target = str(PurePosixPath("xl") / target)
            data = z.read(target)
            dim_match = re.search(br'<dimension[^>]+ref="([^"]+)"', data[:5000])
            dimensao = dim_match.group(1).decode() if dim_match else "desconhecida"
            root = ET.fromstring(data)
            primeira = root.find("m:sheetData/m:row", NS)
            cabecalhos = [cell_value(c) for c in primeira.findall("m:c", NS)] if primeira is not None else []
            info = z.getinfo(target)
            sheets.append({
                "nome": sh.attrib["name"],
                "dimensao": dimensao,
                "cabecalhos": cabecalhos,
                "xml_mb": round(info.file_size / 1024 / 1024, 2),
                "compactado_mb": round(info.compress_size / 1024 / 1024, 2),
            })
        return {
            "arquivo": str(path),
            "tamanho_mb": round(path.stat().st_size / 1024 / 1024, 2),
            "abas": sheets,
            "tabelas": len([n for n in z.namelist() if n.startswith("xl/tables/")]),
            "graficos": len([n for n in z.namelist() if n.startswith("xl/charts/")]),
        }


print(json.dumps([inspect(Path(p)) for p in sys.argv[1:]], ensure_ascii=False, indent=2))
