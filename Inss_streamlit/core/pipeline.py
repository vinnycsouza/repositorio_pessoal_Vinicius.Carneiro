# core/pipeline.py
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional

from core.detector import detect_model_from_text
from core.models import ResumoIndexado, SubtipoResumo, Modelo, Confianca, BlocoCandidato
from core.normalize import normalize_text, extract_parenthesis_scope
from core.indexer import index_blocks_from_pdf
from core.competencia_extract import extrair_competencia_texto


def _make_resumo_id(arquivo_id: str, competencia: str, pag_ini: int, pag_fim: int, resumo_nome_norm: str, modelo: Modelo) -> str:
    raw = f"{arquivo_id}|{competencia}|{pag_ini}-{pag_fim}|{modelo.value}|{resumo_nome_norm}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _extract_resumo_nome_e_subtipo(text_norm: str, modelo: Modelo) -> tuple[str, str, SubtipoResumo, list[str]]:
    sinais: list[str] = []

    # 1) TOTALIZACAO DA FOLHA - ...
    m = re.search(r"TOTALIZACAO DA FOLHA\s*-\s*([^\n\r]+)", text_norm)
    if m:
        nome = normalize_text(m.group(1))
        sinais.append("NOME: TOTALIZACAO DA FOLHA - ...")
        return nome, nome, SubtipoResumo.TOTALIZACAO_CCUSTO, sinais

    # 2) DEPARTAMENTO ...
    m = re.search(r"\bDEPARTAMENTO[: ]\s*([^\n\r]+)", text_norm)
    if m:
        nome = normalize_text(m.group(1))
        sinais.append("NOME: DEPARTAMENTO")
        return nome, nome, SubtipoResumo.DEPARTAMENTO, sinais

    # 3) Parênteses no gerencial
    if modelo == Modelo.GERENCIAL_2021_PLUS:
        scope = extract_parenthesis_scope(text_norm)
        if scope:
            sinais.append("NOME: PARENTESES (ESCOPO)")
            return scope, scope, SubtipoResumo.PARENTESES_ESCOPO, sinais

    # 4) Hierarquia
    if modelo == Modelo.SAGE_HIERARQUIA_EMPRESARIAL:
        sinais.append("NOME: HIERARQUIA (DEFAULT)")
        return "HIERARQUIA EMPRESARIAL", "HIERARQUIA EMPRESARIAL", SubtipoResumo.HIERARQUIA, sinais

    sinais.append("NOME: NAO_IDENTIFICADO")
    return "NAO_IDENTIFICADO", "NAO_IDENTIFICADO", SubtipoResumo.NAO_IDENTIFICADO, sinais


@dataclass
class _PageHit:
    arquivo: str
    arquivo_id: str
    page_idx: int  # 0-based
    competencia: str
    modelo: Modelo
    score: int
    confianca: Confianca
    resumo_nome: str
    resumo_nome_norm: str
    subtipo: SubtipoResumo
    sinais: List[str]


def _merge_adjacent_pages(hits: List[_PageHit]) -> List[ResumoIndexado]:
    """
    Mescla páginas adjacentes se tiverem MESMA (competencia + modelo + resumo_nome_norm).
    """
    if not hits:
        return []

    hits = sorted(hits, key=lambda x: x.page_idx)
    out: List[ResumoIndexado] = []

    cur = hits[0]
    pag_ini = cur.page_idx
    pag_fim = cur.page_idx
    sinais = list(cur.sinais)
    score_max = cur.score
    confianca = cur.confianca

    def flush():
        nonlocal pag_ini, pag_fim, sinais, score_max, confianca, cur
        resumo_id = _make_resumo_id(
            arquivo_id=cur.arquivo_id,
            competencia=cur.competencia,
            pag_ini=pag_ini,
            pag_fim=pag_fim,
            resumo_nome_norm=cur.resumo_nome_norm,
            modelo=cur.modelo,
        )
        out.append(
            ResumoIndexado(
                arquivo=cur.arquivo,
                arquivo_id=cur.arquivo_id,
                competencia=cur.competencia,
                resumo_id=resumo_id,
                modelo=cur.modelo,
                subtipo=cur.subtipo,
                resumo_nome=cur.resumo_nome,
                resumo_nome_norm=cur.resumo_nome_norm,
                pag_ini=pag_ini,
                pag_fim=pag_fim,
                sinais_detectados=list(dict.fromkeys(sinais)),
                score_modelo=score_max,
                confianca_modelo=confianca,
            )
        )

    for h in hits[1:]:
        same_key = (
            h.competencia == cur.competencia
            and h.modelo == cur.modelo
            and h.resumo_nome_norm == cur.resumo_nome_norm
            and h.page_idx == pag_fim + 1
        )

        if same_key:
            pag_fim = h.page_idx
            sinais.extend(h.sinais)
            score_max = max(score_max, h.score)
            # se qualquer página for ALTA, marca ALTA
            if h.confianca == Confianca.ALTA:
                confianca = Confianca.ALTA
            elif confianca != Confianca.ALTA and h.confianca == Confianca.MEDIA:
                confianca = Confianca.MEDIA
        else:
            flush()
            cur = h
            pag_ini = h.page_idx
            pag_fim = h.page_idx
            sinais = list(h.sinais)
            score_max = h.score
            confianca = h.confianca

    flush()
    return out


def run_index_only(
    pdf_path: str,
    arquivo_nome: Optional[str] = None,
    max_pages: Optional[int] = None,
) -> List[ResumoIndexado]:
    """
    Agora: indexação por BLOCO (mescla páginas adjacentes).
    - extrai competência por página (robusto)
    - detecta modelo por assinatura
    - extrai nome do resumo (modelo-aware)
    - mescla páginas adjacentes com mesma chave
    """
    blocos: List[BlocoCandidato] = index_blocks_from_pdf(pdf_path, arquivo_nome=arquivo_nome, max_pages=max_pages)

    hits: List[_PageHit] = []

    comp_atual = ""  # fallback dentro do PDF (apenas se a página não tiver competência detectável)
    for b in blocos:
        texto_raw = (b.header_text or "")
        texto_norm = normalize_text(texto_raw) + "\n" + (b.sample_text or "")

        # competência por página (sem emissão)
        comp = extrair_competencia_texto(texto_raw) or comp_atual
        comp = comp or "SEM_COMP"
        comp_atual = comp if comp != "SEM_COMP" else comp_atual

        det = detect_model_from_text(texto_norm)
        resumo_nome, resumo_nome_norm, subtipo, sinais_nome = _extract_resumo_nome_e_subtipo(texto_norm, det.modelo)

        sinais = list(dict.fromkeys(det.sinais + sinais_nome))

        hits.append(
            _PageHit(
                arquivo=b.arquivo,
                arquivo_id=b.arquivo_id,
                page_idx=b.pag_ini,
                competencia=comp,
                modelo=det.modelo,
                score=det.score,
                confianca=det.confianca,
                resumo_nome=resumo_nome,
                resumo_nome_norm=resumo_nome_norm,
                subtipo=subtipo,
                sinais=sinais,
            )
        )

    # mescla por adjacência
    resumos_por_bloco: List[ResumoIndexado] = []
    # mesclar por competência também: faz por arquivo inteiro, mas a chave inclui competência
    resumos_por_bloco = _merge_adjacent_pages(hits)
    return resumos_por_bloco