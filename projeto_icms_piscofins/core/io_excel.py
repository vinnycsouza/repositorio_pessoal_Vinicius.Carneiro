from __future__ import annotations

from pathlib import Path
import pandas as pd


class WorkbookReader:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._xls = None

    def _open(self) -> pd.ExcelFile:
        if self._xls is None:
            try:
                self._xls = pd.ExcelFile(self.path, engine="calamine")
            except Exception:
                self._xls = pd.ExcelFile(self.path, engine="openpyxl")
        return self._xls

    def list_sheets(self) -> list[str]:
        return self._open().sheet_names

    def read_sheet(self, sheet_hint: str) -> pd.DataFrame:
        xls = self._open()
        hint = sheet_hint.strip().lower()

        matches = []
        for sheet in xls.sheet_names:
            s = sheet.strip().lower()
            if hint in s:
                matches.append(sheet)

        target = matches[0] if matches else xls.sheet_names[0]

        try:
            return pd.read_excel(self.path, sheet_name=target, engine="calamine")
        except Exception:
            return pd.read_excel(self.path, sheet_name=target, engine="openpyxl")