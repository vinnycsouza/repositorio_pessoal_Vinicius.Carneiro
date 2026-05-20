from dataclasses import dataclass
import pandas as pd
from .utils import normalize_column_name


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


def validate_sheet_exists(xls: pd.ExcelFile, required_sheets: list[str], file_label: str) -> ValidationResult:
    existing = {normalize_column_name(s): s for s in xls.sheet_names}
    errors = []
    for sheet in required_sheets:
        if normalize_column_name(sheet) not in existing:
            errors.append(f"{file_label}: aba obrigatória não localizada: {sheet}")
    return ValidationResult(ok=len(errors) == 0, errors=errors, warnings=[])


def get_sheet_name(xls: pd.ExcelFile, sheet: str) -> str:
    existing = {normalize_column_name(s): s for s in xls.sheet_names}
    return existing[normalize_column_name(sheet)]
