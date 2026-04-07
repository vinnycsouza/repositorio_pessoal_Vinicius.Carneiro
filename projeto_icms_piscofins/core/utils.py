from __future__ import annotations

from pathlib import Path


def validate_excel_path(path_str: str) -> Path:
    path_str = (path_str or "").strip()
    if not path_str:
        raise ValueError("Informe o caminho do arquivo.")
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    if not path.is_file():
        raise ValueError(f"O caminho informado não é um arquivo: {path}")
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
        raise ValueError("Informe um arquivo Excel válido (.xlsx, .xlsm ou .xls).")
    return path