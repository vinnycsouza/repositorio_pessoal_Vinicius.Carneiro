# exports/excel_export.py
from __future__ import annotations

import io
from typing import List

import pandas as pd

from core.models import ResumoIndexado


def export_resumos_encontrados(resumos: List[ResumoIndexado]) -> bytes:
    rows = []
    for r in resumos:
        rows.append(
            {
                "arquivo": r.arquivo,
                "competencia": r.competencia,
                "modelo": r.modelo.value,
                "subtipo": r.subtipo.value,
                "resumo_nome": r.resumo_nome,
                "pag_ini": r.pag_ini,
                "pag_fim": r.pag_fim,
                "confianca_modelo": r.confianca_modelo.value,
                "score_modelo": r.score_modelo,
                "sinais_detectados": "; ".join(r.sinais_detectados or []),
                "resumo_id": r.resumo_id,
                "arquivo_id": r.arquivo_id,
            }
        )

    df = pd.DataFrame(rows)

    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="RESUMOS_ENCONTRADOS")
    return bio.getvalue()