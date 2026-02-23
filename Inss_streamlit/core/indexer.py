# core/indexer.py
from __future__ import annotations

import hashlib
from typing import List

import pdfplumber

from core.models import BlocoCandidato
from core.normalize import normalize_text


def file_id_from_name(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8", errors="ignore")).hexdigest()[:16]


def index_blocks_from_pdf(pdf_path: str, arquivo_nome: str | None = None, max_pages: int | None = None) -> List[BlocoCandidato]:
    """
    MVP: cria um BlocoCandidato por página (pag_ini=pag_fim=p).
    Depois o pipeline pode mesclar páginas adjacentes com mesmo resumo_nome.
    """
    arquivo = arquivo_nome or pdf_path.split("/")[-1]
    arquivo_id = file_id_from_name(arquivo)

    blocos: List[BlocoCandidato] = []

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        lim = min(total_pages, max_pages) if max_pages else total_pages

        for p in range(lim):
            page = pdf.pages[p]
            text = page.extract_text() or ""
            norm = normalize_text(text)

            # Header: primeiras ~12 linhas (ajuste se necessário)
            lines = (text.splitlines() if text else [])[:12]
            header_text = "\n".join(lines)

            blocos.append(
                BlocoCandidato(
                    arquivo=arquivo,
                    arquivo_id=arquivo_id,
                    pag_ini=p,
                    pag_fim=p,
                    header_text=header_text,
                    sample_text=norm[:3000],  # amostra normalizada
                )
            )

    return blocos
