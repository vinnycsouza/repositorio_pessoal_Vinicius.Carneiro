# core/normalize.py
from __future__ import annotations

import re
import unicodedata


def normalize_text(s: str) -> str:
    """Normaliza texto: remove acentos, upper, colapsa espaços."""
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.upper()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_parenthesis_scope(s: str) -> str:
    """
    Extrai texto entre parênteses mais relevante para escopo (ex.: (GERAL)).
    Retorna vazio se não achar.
    """
    if not s:
        return ""
    m = re.search(r"\(([^)]+)\)", s)
    if not m:
        return ""
    return normalize_text(m.group(1))