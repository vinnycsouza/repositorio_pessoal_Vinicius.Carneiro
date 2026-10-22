"""Recorte operacional de cinco anos; não determina prescrição jurídica."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from functools import lru_cache


def data_corte(referencia: date) -> date:
    """Mesmo dia, cinco anos antes; 29/02 recua para 28/02 quando necessário."""
    try:
        return referencia.replace(year=referencia.year - 5)
    except ValueError:
        return referencia.replace(year=referencia.year - 5, day=28)


@lru_cache(maxsize=4096)
def classificar_competencia(competencia: str, referencia: date) -> str:
    """Retorna dentro, anterior, limite, futura ou inválida.

    A competência do mês do corte fica pendente: a EFD não prova a data de
    extinção do crédito tributário que inicia o prazo do CTN, art. 168.
    """
    try:
        ano, mes = map(int, competencia.split("-"))
        inicio = date(ano, mes, 1)
        fim = date(ano, mes, monthrange(ano, mes)[1])
    except (ValueError, AttributeError):
        return "invalida"
    corte = data_corte(referencia)
    if inicio > referencia:
        return "futura"
    if fim < corte:
        return "anterior"
    if inicio < corte:
        return "limite"
    return "dentro"
