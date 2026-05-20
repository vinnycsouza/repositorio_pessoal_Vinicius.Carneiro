from dataclasses import dataclass
import re
import pandas as pd
from .utils import normalize_column_name


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


def _registro_codigo(texto: str) -> str:
    """Extrai C100/C170/C175/C190 de nomes como 'C190 - Analítico'."""
    m = re.search(r"\b([A-Z]\d{3})\b", str(texto).upper())
    return m.group(1) if m else normalize_column_name(texto)


def _sheet_map(sheet_names: list[str]) -> dict[str, str]:
    mapa = {}
    for nome in sheet_names:
        # Mapa por nome normalizado completo
        mapa[normalize_column_name(nome)] = nome
        # Mapa pelo código do registro
        codigo = _registro_codigo(nome)
        mapa.setdefault(codigo, nome)
    return mapa


def validate_sheet_exists(xls: pd.ExcelFile, required_sheets: list[str], file_label: str) -> ValidationResult:
    existing = _sheet_map(xls.sheet_names)
    errors = []
    warnings = []

    for sheet in required_sheets:
        codigo = _registro_codigo(sheet)
        nome_norm = normalize_column_name(sheet)
        if codigo not in existing and nome_norm not in existing:
            disponiveis = ", ".join(xls.sheet_names[:20])
            errors.append(
                f"{file_label}: aba obrigatória não localizada: {sheet}. "
                f"Exemplo de abas existentes: {disponiveis}"
            )

    return ValidationResult(ok=len(errors) == 0, errors=errors, warnings=warnings)


def get_sheet_name(xls: pd.ExcelFile, sheet: str) -> str:
    existing = _sheet_map(xls.sheet_names)
    codigo = _registro_codigo(sheet)
    nome_norm = normalize_column_name(sheet)

    if codigo in existing:
        return existing[codigo]
    if nome_norm in existing:
        return existing[nome_norm]

    raise KeyError(f"Aba não localizada: {sheet}")
