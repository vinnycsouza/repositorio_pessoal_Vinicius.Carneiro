from __future__ import annotations

import io
import os
import shutil
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Tuple, Union
import xml.etree.ElementTree as ET

import pandas as pd

from modules.parser_xml import (
    BaseContribuicao, BaseTrabalhador, RubricaInfo, RubricaPagamento,
    detectar_tipo_evento, parse_s1010, parse_s1200, parse_s3000,
    parse_s5001, parse_s5011, parse_empresa_info,
)
from utils.helpers import localname

Fonte = Tuple[str, Union[bytes, bytearray, memoryview, str, os.PathLike]]
MAX_NIVEL_ZIP = 8
MAX_XML_INDIVIDUAL = 256 * 1024 * 1024
TAMANHO_BLOCO = 1024 * 1024


def _nome_seguro(nome: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in nome)[-180:] or "arquivo"


def _copiar_stream(origem, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("wb") as out:
        shutil.copyfileobj(origem, out, length=TAMANHO_BLOCO)


def _materializar_fonte(fonte, destino: Path) -> Path:
    if isinstance(fonte, (str, os.PathLike)):
        return Path(fonte)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("wb") as fp:
        view = memoryview(bytes(fonte))
        for ini in range(0, len(view), TAMANHO_BLOCO):
            fp.write(view[ini:ini + TAMANHO_BLOCO])
    return destino


def _extrair_zip_para_spool(zip_path: Path, raiz: Path, prefixo: str, nivel: int = 0) -> Iterator[Tuple[str, Path, int]]:
    """Extrai somente XML/ZIP em streaming para disco temporário.

    Evita `fp.read()` de cada membro e permite duas passagens sem descompactar
    novamente os arquivos grandes.
    """
    if nivel > MAX_NIVEL_ZIP:
        return
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for idx, info in enumerate(zf.infolist()):
                if info.is_dir():
                    continue
                nome = info.filename
                caminho_logico = f"{prefixo}::{nome}" if prefixo else nome
                ext = Path(nome).suffix.lower()
                if ext not in {".xml", ".zip"}:
                    continue
                if ext == ".xml" and info.file_size > MAX_XML_INDIVIDUAL:
                    yield caminho_logico, Path(), info.file_size
                    continue
                alvo = raiz / f"n{nivel}" / f"{idx:08d}_{_nome_seguro(Path(nome).name)}"
                try:
                    with zf.open(info, "r") as src:
                        _copiar_stream(src, alvo)
                except Exception:
                    continue
                if ext == ".zip":
                    yield from _extrair_zip_para_spool(alvo, raiz / f"zip_{idx:08d}", caminho_logico, nivel + 1)
                    try:
                        alvo.unlink(missing_ok=True)
                    except Exception:
                        pass
                else:
                    yield caminho_logico, alvo, info.file_size
    except (zipfile.BadZipFile, FileNotFoundError, PermissionError, OSError):
        return


def _eh_retorno_evento_completo(root: ET.Element) -> bool:
    return localname(root.tag) == "retornoEventoCompleto" or any(localname(el.tag) == "recibo" for el in root.iter())


def _carregar_root(xml_path: Path) -> ET.Element | None:
    try:
        return ET.parse(xml_path).getroot()
    except Exception:
        return None


def _montar_indice_rubricas(rubricas: List[RubricaInfo]):
    mapa = {}
    ordenadas = sorted(rubricas, key=lambda r: (0 if r.fonte_dados == "Download principal" else 1, r.ini_valid, r.fim_valid))
    for r in ordenadas:
        cod, tab = str(r.cod_rubr or "").strip(), str(r.ide_tab_rubr or "").strip()
        mapa.setdefault((cod, tab), []).append(r)
        mapa.setdefault((cod, ""), []).append(r)
    return mapa


def processar_fontes_esocial(fontes: Iterable[Fonte]) -> Dict[str, object]:
    """Engine V2: spool temporário em disco, inventário e duas passagens.

    1) Cada ZIP é materializado uma única vez.
    2) XMLs são extraídos por streaming para uma área temporária.
    3) S-1010/S-3000 são lidos primeiro; movimentos e bases, depois.
    4) Apenas um XML permanece aberto por vez.
    """
    workspace = Path(tempfile.mkdtemp(prefix="esocial_engine_v2_"))
    xmls: List[Tuple[str, Path, int]] = []
    for i, (nome, fonte) in enumerate(list(fontes)):
        origem_path = _materializar_fonte(fonte, workspace / "fontes" / f"{i:04d}_{_nome_seguro(nome)}")
        if Path(str(nome)).suffix.lower() == ".xml":
            tamanho = origem_path.stat().st_size if origem_path.exists() else 0
            if tamanho > MAX_XML_INDIVIDUAL:
                xmls.append((nome, Path(), tamanho))
            else:
                xmls.append((nome, origem_path, tamanho))
        else:
            xmls.extend(_extrair_zip_para_spool(origem_path, workspace / "spool" / f"fonte_{i:04d}", nome))

    inventario, erros_xml, rubricas, exclusoes, empresas = [], [], [], [], []
    eventos_relevantes = {"S-1000", "S-1005", "S-1010", "S-1020", "S-1200", "S-3000", "S-5001", "S-5011"}
    contagem_localizada: Dict[str, int] = {}

    for caminho, xml_path, tamanho in xmls:
        if not xml_path:
            erros_xml.append({"arquivo": caminho, "erro": "XML acima do limite individual de segurança"})
            inventario.append({"arquivo": caminho, "tipo": "XML_INVALIDO", "tamanho_bytes": tamanho, "parseado": False})
            continue
        root = _carregar_root(xml_path)
        if root is None:
            erros_xml.append({"arquivo": caminho, "erro": "XML inválido ou ilegível"})
            inventario.append({"arquivo": caminho, "tipo": "XML_INVALIDO", "tamanho_bytes": tamanho, "parseado": False})
            continue
        tipo = detectar_tipo_evento(root)
        contagem_localizada[tipo] = contagem_localizada.get(tipo, 0) + 1
        recibo = _eh_retorno_evento_completo(root)
        inventario.append({"arquivo": caminho, "tipo": tipo, "tamanho_bytes": tamanho, "parseado": tipo in eventos_relevantes, "envelope_recibo": "Sim" if recibo else "Não"})
        if tipo in eventos_relevantes:
            empresas.append(parse_empresa_info(root, caminho))
        if tipo == "S-1010":
            rubricas.extend(parse_s1010(root, arquivo=caminho, fonte_dados="Recibo S-1010" if recibo else "Download principal"))
        elif tipo == "S-3000":
            item = parse_s3000(root); item["arquivo_origem"] = caminho; exclusoes.append(item)
        root.clear()

    rubricas_map = _montar_indice_rubricas(rubricas)
    remuneracoes: List[RubricaPagamento] = []
    bases_trabalhador: List[BaseTrabalhador] = []
    bases_contribuicao: List[BaseContribuicao] = []
    contagem_parseada = {"S-1010": contagem_localizada.get("S-1010", 0), "S-1200": 0, "S-5001": 0, "S-5011": 0, "S-3000": len(exclusoes)}

    for caminho, xml_path, _ in xmls:
        if not xml_path:
            continue
        root = _carregar_root(xml_path)
        if root is None:
            continue
        tipo = detectar_tipo_evento(root)
        if tipo == "S-1200":
            itens = parse_s1200(root, rubricas_map, caminho); remuneracoes.extend(itens); contagem_parseada["S-1200"] += int(bool(itens))
        elif tipo == "S-5001":
            itens = parse_s5001(root, caminho); bases_trabalhador.extend(itens); contagem_parseada["S-5001"] += int(bool(itens))
        elif tipo == "S-5011":
            itens = parse_s5011(root, caminho); bases_contribuicao.extend(itens); contagem_parseada["S-5011"] += int(bool(itens))
        root.clear()

    recibos_excluidos = {x.get("nrRecEvt", "") for x in exclusoes if x.get("nrRecEvt")}
    remuneracoes = [r for r in remuneracoes if r.nr_recibo_evento not in recibos_excluidos]
    bases_trabalhador = [b for b in bases_trabalhador if b.nr_recibo_base not in recibos_excluidos]
    bases_contribuicao = [b for b in bases_contribuicao if b.nr_recibo_base not in recibos_excluidos]

    def df(items): return pd.DataFrame(items)
    df_empresa = df(empresas)
    if not df_empresa.empty:
        df_empresa = df_empresa.drop_duplicates().copy(); df_empresa["tem_nome"] = df_empresa["nome_empresa"].fillna("").astype(str).str.strip().ne("")
        df_empresa = df_empresa.sort_values(["tem_nome", "cnpj_empregador"], ascending=[False, True]).drop(columns=["tem_nome"])
    resumo = df([{"tipo": t, "xml_localizados": q} for t, q in contagem_localizada.items() if t in eventos_relevantes])
    parsed = df([{"tipo": k, "xml_parseados": v} for k, v in contagem_parseada.items()])
    layout = resumo.merge(parsed, on="tipo", how="outer").fillna(0) if not resumo.empty or not parsed.empty else pd.DataFrame()
    if not layout.empty:
        layout[["xml_localizados", "xml_parseados"]] = layout[["xml_localizados", "xml_parseados"]].astype(int)
        layout["nao_parseados"] = layout["xml_localizados"] - layout["xml_parseados"]

    return {
        "inventario": df(inventario), "rubricas": df([asdict(x) for x in rubricas]), "exclusoes": df(exclusoes),
        "remuneracoes": df([asdict(x) for x in remuneracoes]), "bases_trabalhador": df([asdict(x) for x in bases_trabalhador]),
        "bases_contribuicao": df([asdict(x) for x in bases_contribuicao]), "erros_xml": df(erros_xml),
        "layout_check": layout, "empresa": df_empresa, "recibos_excluidos": recibos_excluidos,
        "workspace_temporario": str(workspace), "quantidade_xml_spool": len(xmls),
    }


def processar_zip_esocial(zip_bytes: bytes) -> Dict[str, object]:
    return processar_fontes_esocial([("upload.zip", zip_bytes)])
