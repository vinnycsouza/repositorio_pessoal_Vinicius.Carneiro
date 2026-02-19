from __future__ import annotations

import io
from pathlib import Path
from typing import Optional, Set

import pandas as pd
from openpyxl import Workbook

from .layout import CAB_K300, CAB_K050


def _write_txt_event_to_sheet(ws, path_txt: Path, header: list[str], filter_fn=None):
    ws.append(header)
    with path_txt.open("r", encoding="utf-8", errors="ignore") as f:
        for linha in f:
            linha = linha.rstrip("\n")
            partes = linha.split("|")
            partes = partes[: len(header)]
            if len(partes) < len(header):
                partes += [""] * (len(header) - len(partes))
            if filter_fn and not filter_fn(partes):
                continue
            ws.append(partes)


def gerar_excel_interno(
    path_k300: Path,
    path_k150: Optional[Path],
    path_k050: Optional[Path],
    selected_codigos: Set[str],
    allowed_ind_rubr: Set[str],
    allowed_ind_base_ps: Set[str],
    df_rubricas: pd.DataFrame,
) -> bytes:
    """
    Gera Excel interno:
      - K300_FILTRADO (filtrado por rubricas + IND_RUBR + IND_BASE_PS)
      - K150_SELECIONADAS (rubricas escolhidas)  ✅ ordem por código
      - K050_TRABALHADORES (completo, sem filtro)
    """
    selected_codigos = set(map(str, selected_codigos))
    allowed_ind_rubr = set(map(str, allowed_ind_rubr))
    allowed_ind_base_ps = set(map(str, allowed_ind_base_ps))

    wb = Workbook(write_only=True)

    # Aba K300 filtrado
    ws_k300 = wb.create_sheet(title="K300_FILTRADO")

    def k300_filter(partes):
        # idx: 6=COD_RUBR, 8=IND_RUBR, 10=IND_BASE_PS
        cod = (partes[6] or "").strip()
        ind_r = (partes[8] or "").strip()
        ind_ps = (partes[10] or "").strip()

        if cod not in selected_codigos:
            return False
        if allowed_ind_rubr and ind_r not in allowed_ind_rubr:
            return False
        if allowed_ind_base_ps and ind_ps not in allowed_ind_base_ps:
            return False
        return True

    _write_txt_event_to_sheet(ws_k300, path_k300, CAB_K300, filter_fn=k300_filter)

    # Aba K150 selecionadas (ordem por código)
    ws_k150 = wb.create_sheet(title="K150_SELECIONADAS")
    ws_k150.append(["COD_RUBRICA", "DESC_RUBRICA"])

    if df_rubricas is not None and not df_rubricas.empty and selected_codigos:
        df_sel = df_rubricas.copy()
        df_sel["COD_RUBRICA"] = df_sel["COD_RUBRICA"].astype(str).str.strip()
        df_sel = df_sel[df_sel["COD_RUBRICA"].isin(selected_codigos)].drop_duplicates()

        # ✅ ordena por código (numérico quando possível)
        df_sel["_COD_NUM"] = pd.to_numeric(df_sel["COD_RUBRICA"], errors="coerce")
        df_sel = df_sel.sort_values(by=["_COD_NUM", "COD_RUBRICA"], kind="stable", na_position="last").drop(
            columns=["_COD_NUM"]
        )

        for _, r in df_sel.iterrows():
            ws_k150.append([str(r["COD_RUBRICA"]), str(r.get("DESC_RUBRICA", ""))])

    # Aba K050 (completa)
    if path_k050 and path_k050.exists():
        ws_k050 = wb.create_sheet(title="K050_TRABALHADORES")
        _write_txt_event_to_sheet(ws_k050, path_k050, CAB_K050, filter_fn=None)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()