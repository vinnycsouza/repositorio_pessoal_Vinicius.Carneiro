from __future__ import annotations

from pathlib import Path

import pandas as pd

from .utils import choose_sheet


class WorkbookReader:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.xls = pd.ExcelFile(self.path)
        self.sheet_names = self.xls.sheet_names

    def read_sheet(self, logical_name: str) -> pd.DataFrame:
        sheet = choose_sheet(self.sheet_names, logical_name)
        if not sheet:
            raise KeyError(
                f"A aba lógica '{logical_name}' não foi localizada em {self.path.name}. "
                f"Abas disponíveis: {', '.join(self.sheet_names)}"
            )
        return pd.read_excel(self.path, sheet_name=sheet)
