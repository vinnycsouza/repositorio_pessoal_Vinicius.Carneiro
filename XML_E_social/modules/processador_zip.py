from __future__ import annotations

import io
import os
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import BinaryIO, Dict, Iterable, Iterator, List, Tuple, Union
import xml.etree.ElementTree as ET

import pandas as pd

from modules.parser_xml import (
    BaseContribuicao,
    BaseTrabalhador,
    RubricaInfo,
    RubricaPagamento,
    detectar_tipo_evento,
    parse_s1010,
    parse_s1200,
    parse_s3000,
    parse_s5001,
    parse_s5011,
    parse_empresa_info,
)
from utils.helpers import localname

Fonte = Tuple[str, Union[bytes, bytearray, memoryview, str, os.PathLike]]

# Proteções básicas contra arquivos ZIP malformados/zip-bomb.
MAX_NIVEL_ZIP = 8
MAX_XML_INDIVIDUAL = 256 * 1024 * 1024  # 256 MB por XML


def _abrir_fonte_zip(fonte: Union[bytes, bytearray, memoryview, str, os.PathLike]):
    if isinstance(fonte, (str, os.PathLike)):
        return zipfile.ZipFile(Path(fonte), "r")
    return zipfile.ZipFile(io.BytesIO(bytes(fonte)), "r")


def _iterar_zip_aberto(zf: zipfile.ZipFile, caminho_base: str = "", nivel: int = 0) -> Iterator[Tuple[str, bytes]]:
    if nivel > MAX_NIVEL_ZIP:
        return
    for info in zf.infolist():
        if info.is_dir():
            continue
        nome = info.filename
        caminho_atual = f"{caminho_base}::{nome}" if caminho_base else nome

        # Evita descompactar XML individual absurdamente grande sem aviso.
        if info.file_size > MAX_XML_INDIVIDUAL and nome.lower().endswith(".xml"):
            yield caminho_atual, b""
            continue

        try:
            with zf.open(info, "r") as fp:
                data = fp.read()
        except Exception:
            continue

        if nome.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data), "r") as interno:
                    yield from _iterar_zip_aberto(interno, caminho_atual, nivel + 1)
            except zipfile.BadZipFile:
                continue
        else:
            yield caminho_atual, data


def iterar_arquivos_zip_recursivo(fonte: Union[bytes, bytearray, memoryview, str, os.PathLike], caminho_base: str = ""):
    """Varre ZIP, subpastas e ZIP dentro de ZIP sem manter árvores XML em memória."""
    try:
        with _abrir_fonte_zip(fonte) as zf:
            yield from _iterar_zip_aberto(zf, caminho_base=caminho_base, nivel=0)
    except (zipfile.BadZipFile, FileNotFoundError, PermissionError):
        return


def _eh_retorno_evento_completo(root: ET.Element) -> bool:
    return localname(root.tag) == "retornoEventoCompleto" or any(
        localname(el.tag) == "recibo" for el in root.iter()
    )


def _iterar_fontes(fontes: Iterable[Fonte]):
    for nome_fonte, fonte in fontes:
        yield nome_fonte, fonte


def processar_fontes_esocial(fontes: Iterable[Fonte]) -> Dict[str, object]:
    """Processa múltiplos ZIPs em duas passagens.

    Passagem 1: inventário, empresa, S-1010 e S-3000.
    Passagem 2: S-1200, S-5001 e S-5011 usando o catálogo completo de rubricas.

    A mudança evita manter milhares de ``ElementTree`` simultaneamente na RAM e
    permite que recibos ``retornoEventoCompleto`` com ``evtTabRubrica`` sejam
    usados automaticamente como fonte complementar de S-1010.
    """
    fontes = list(fontes)
    inventario: List[Dict[str, object]] = []
    erros_xml: List[Dict[str, str]] = []
    rubricas: List[RubricaInfo] = []
    exclusoes: List[Dict[str, str]] = []
    empresas: List[Dict[str, str]] = []

    eventos_relevantes = {"S-1000", "S-1005", "S-1010", "S-1020", "S-1200", "S-3000", "S-5001", "S-5011"}
    contagem_localizada: Dict[str, int] = {}

    # PASSAGEM 1 — metadados e catálogo S-1010 completo.
    for nome_fonte, fonte in _iterar_fontes(fontes):
        for caminho, conteudo in iterar_arquivos_zip_recursivo(fonte, caminho_base=nome_fonte):
            if not caminho.lower().endswith(".xml"):
                inventario.append({"arquivo": caminho, "tipo": "NAO_XML", "tamanho_bytes": len(conteudo), "parseado": False})
                continue
            if not conteudo:
                erros_xml.append({"arquivo": caminho, "erro": "XML vazio ou acima do limite individual de segurança"})
                inventario.append({"arquivo": caminho, "tipo": "XML_INVALIDO", "tamanho_bytes": 0, "parseado": False})
                continue
            try:
                root = ET.fromstring(conteudo)
            except Exception as exc:
                erros_xml.append({"arquivo": caminho, "erro": str(exc)})
                inventario.append({"arquivo": caminho, "tipo": "XML_INVALIDO", "tamanho_bytes": len(conteudo), "parseado": False})
                continue

            tipo_evento = detectar_tipo_evento(root)
            contagem_localizada[tipo_evento] = contagem_localizada.get(tipo_evento, 0) + 1
            inventario.append({
                "arquivo": caminho,
                "tipo": tipo_evento,
                "tamanho_bytes": len(conteudo),
                "parseado": tipo_evento in eventos_relevantes,
                "envelope_recibo": "Sim" if _eh_retorno_evento_completo(root) else "Não",
            })

            if tipo_evento in eventos_relevantes:
                empresas.append(parse_empresa_info(root, caminho))
            if tipo_evento == "S-1010":
                fonte_dados = "Recibo S-1010" if _eh_retorno_evento_completo(root) else "Download principal"
                rubricas.extend(parse_s1010(root, arquivo=caminho, fonte_dados=fonte_dados))
            elif tipo_evento == "S-3000":
                item = parse_s3000(root)
                item["arquivo_origem"] = caminho
                exclusoes.append(item)
            root.clear()

    # Índice preservando todas as vigências e dando prioridade ao download principal.
    rubricas_map: Dict[Tuple[str, str], List[RubricaInfo]] = {}
    rubricas_ordenadas = sorted(
        rubricas,
        key=lambda r: (0 if r.fonte_dados == "Download principal" else 1, r.ini_valid, r.fim_valid),
    )
    for r in rubricas_ordenadas:
        cod = str(r.cod_rubr or "").strip()
        tab = str(r.ide_tab_rubr or "").strip()
        rubricas_map.setdefault((cod, tab), []).append(r)
        rubricas_map.setdefault((cod, ""), []).append(r)

    remuneracoes: List[RubricaPagamento] = []
    bases_trabalhador: List[BaseTrabalhador] = []
    bases_contribuicao: List[BaseContribuicao] = []
    contagem_parseada = {"S-1010": contagem_localizada.get("S-1010", 0), "S-1200": 0, "S-5001": 0, "S-5011": 0, "S-3000": len(exclusoes)}

    # PASSAGEM 2 — eventos volumosos, um XML por vez.
    for nome_fonte, fonte in _iterar_fontes(fontes):
        for caminho, conteudo in iterar_arquivos_zip_recursivo(fonte, caminho_base=nome_fonte):
            if not caminho.lower().endswith(".xml") or not conteudo:
                continue
            try:
                root = ET.fromstring(conteudo)
            except Exception:
                continue
            tipo_evento = detectar_tipo_evento(root)
            if tipo_evento == "S-1200":
                itens = parse_s1200(root, rubricas_map, caminho)
                remuneracoes.extend(itens)
                if itens:
                    contagem_parseada["S-1200"] += 1
            elif tipo_evento == "S-5001":
                itens = parse_s5001(root, caminho)
                bases_trabalhador.extend(itens)
                if itens:
                    contagem_parseada["S-5001"] += 1
            elif tipo_evento == "S-5011":
                itens = parse_s5011(root, caminho)
                bases_contribuicao.extend(itens)
                if itens:
                    contagem_parseada["S-5011"] += 1
            root.clear()

    recibos_excluidos = {x.get("nrRecEvt", "") for x in exclusoes if x.get("nrRecEvt")}
    remuneracoes = [r for r in remuneracoes if r.nr_recibo_evento not in recibos_excluidos]
    bases_trabalhador = [b for b in bases_trabalhador if b.nr_recibo_base not in recibos_excluidos]
    bases_contribuicao = [b for b in bases_contribuicao if b.nr_recibo_base not in recibos_excluidos]

    df_inventario = pd.DataFrame(inventario)
    df_rubricas = pd.DataFrame([asdict(x) for x in rubricas])
    df_exclusoes = pd.DataFrame(exclusoes)
    df_remun = pd.DataFrame([asdict(x) for x in remuneracoes])
    df_bases_trab = pd.DataFrame([asdict(x) for x in bases_trabalhador])
    df_bases_contrib = pd.DataFrame([asdict(x) for x in bases_contribuicao])
    df_erros = pd.DataFrame(erros_xml)
    df_empresa = pd.DataFrame(empresas)
    if not df_empresa.empty:
        df_empresa = df_empresa.drop_duplicates().copy()
        df_empresa["tem_nome"] = df_empresa["nome_empresa"].fillna("").astype(str).str.strip().ne("")
        df_empresa = df_empresa.sort_values(["tem_nome", "cnpj_empregador"], ascending=[False, True]).drop(columns=["tem_nome"])

    resumo_eventos = pd.DataFrame([
        {"tipo": tipo, "xml_localizados": qtd}
        for tipo, qtd in contagem_localizada.items() if tipo in eventos_relevantes
    ])
    df_parseado = pd.DataFrame([{"tipo": k, "xml_parseados": v} for k, v in contagem_parseada.items()])
    df_layout = resumo_eventos.merge(df_parseado, on="tipo", how="outer").fillna(0)
    if not df_layout.empty:
        df_layout["xml_localizados"] = df_layout["xml_localizados"].astype(int)
        df_layout["xml_parseados"] = df_layout["xml_parseados"].astype(int)
        df_layout["nao_parseados"] = df_layout["xml_localizados"] - df_layout["xml_parseados"]

    return {
        "inventario": df_inventario,
        "rubricas": df_rubricas,
        "exclusoes": df_exclusoes,
        "remuneracoes": df_remun,
        "bases_trabalhador": df_bases_trab,
        "bases_contribuicao": df_bases_contrib,
        "erros_xml": df_erros,
        "layout_check": df_layout,
        "empresa": df_empresa,
        "recibos_excluidos": recibos_excluidos,
    }


def processar_zip_esocial(zip_bytes: bytes) -> Dict[str, object]:
    """Compatibilidade com versões anteriores que enviam um único ZIP em bytes."""
    return processar_fontes_esocial([("pacote_esocial.zip", zip_bytes)])
