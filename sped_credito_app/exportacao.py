from __future__ import annotations

import io
import pandas as pd


def gerar_excel_resumo(
    df_resumo_ano: pd.DataFrame,
    df_resumo_abas: pd.DataFrame,
    df_bases_amostra: pd.DataFrame,
) -> bytes:
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_resumo_ano.to_excel(writer, sheet_name="Resumo por Ano", index=False)
        df_resumo_abas.to_excel(writer, sheet_name="Resumo por Aba", index=False)
        df_bases_amostra.to_excel(writer, sheet_name="Amostra Base", index=False)

    output.seek(0)
    return output.read()