import io
import zipfile
from dataclasses import asdict
from typing import Dict, List, Tuple
import xml.etree.ElementTree as ET

import pandas as pd

from modules.parser_xml import (
    BaseTrabalhador,
    RubricaInfo,
    RubricaPagamento,
    detectar_tipo_evento,
    parse_s1010,
    parse_s1200,
    parse_s3000,
    parse_s5001,
)



def iterar_arquivos_zip_recursivo(blob: bytes, zip_name: str = "ZIP_PRINCIPAL"):
    """Varre ZIP, subpastas e ZIP dentro de ZIP."""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue

                nome = info.filename
                try:
                    data = zf.read(info)
                except Exception:
                    continue

                if nome.lower().endswith(".zip"):
                    yield from iterar_arquivos_zip_recursivo(data, zip_name=nome)
                else:
                    yield nome, data
    except zipfile.BadZipFile:
        return



def processar_zip_esocial(zip_bytes: bytes) -> Dict[str, object]:
    inventario: List[Dict[str, object]] = []
    erros_xml: List[Dict[str, str]] = []
    xmls_relevantes: List[Tuple[str, str, ET.Element]] = []
    rubricas: List[RubricaInfo] = []
    exclusoes: List[Dict[str, str]] = []

    eventos_relevantes = {"S-1000", "S-1005", "S-1010", "S-1020", "S-1200", "S-3000", "S-5001"}

    for caminho, conteudo in iterar_arquivos_zip_recursivo(zip_bytes):
        nome_lower = caminho.lower()
        if not nome_lower.endswith(".xml"):
            inventario.append({
                "arquivo": caminho,
                "tipo": "NAO_XML",
                "tamanho_bytes": len(conteudo),
            })
            continue

        try:
            root = ET.fromstring(conteudo)
        except Exception as exc:
            erros_xml.append({
                "arquivo": caminho,
                "erro": str(exc),
            })
            inventario.append({
                "arquivo": caminho,
                "tipo": "XML_INVALIDO",
                "tamanho_bytes": len(conteudo),
            })
            continue

        tipo_evento = detectar_tipo_evento(root)
        inventario.append({
            "arquivo": caminho,
            "tipo": tipo_evento,
            "tamanho_bytes": len(conteudo),
        })

        if tipo_evento in eventos_relevantes:
            xmls_relevantes.append((caminho, tipo_evento, root))
            if tipo_evento == "S-1010":
                rubricas.extend(parse_s1010(root))
            elif tipo_evento == "S-3000":
                exclusoes.append(parse_s3000(root))

    rubricas_map: Dict[Tuple[str, str], RubricaInfo] = {}
    for r in rubricas:
        rubricas_map[(r.cod_rubr, r.ide_tab_rubr)] = r
        if (r.cod_rubr, "") not in rubricas_map:
            rubricas_map[(r.cod_rubr, "")] = r

    remuneracoes: List[RubricaPagamento] = []
    bases: List[BaseTrabalhador] = []

    for caminho, tipo_evento, root in xmls_relevantes:
        if tipo_evento == "S-1200":
            remuneracoes.extend(parse_s1200(root, rubricas_map, caminho))
        elif tipo_evento == "S-5001":
            bases.extend(parse_s5001(root, caminho))

    recibos_excluidos = {x.get("nrRecEvt", "") for x in exclusoes if x.get("nrRecEvt")}

    remuneracoes_filtradas = [r for r in remuneracoes if r.nr_recibo_evento not in recibos_excluidos]
    bases_filtradas = [b for b in bases if b.nr_recibo_base not in recibos_excluidos]

    df_inventario = pd.DataFrame(inventario)
    df_rubricas = pd.DataFrame([asdict(x) for x in rubricas])
    df_exclusoes = pd.DataFrame(exclusoes)
    df_remun = pd.DataFrame([asdict(x) for x in remuneracoes_filtradas])
    df_bases = pd.DataFrame([asdict(x) for x in bases_filtradas])
    df_erros = pd.DataFrame(erros_xml)

    return {
        "inventario": df_inventario,
        "rubricas": df_rubricas,
        "exclusoes": df_exclusoes,
        "remuneracoes": df_remun,
        "bases": df_bases,
        "erros_xml": df_erros,
        "recibos_excluidos": recibos_excluidos,
    }
