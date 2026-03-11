from __future__ import annotations

import io
import pandas as pd


def gerar_excel_resumo(
    df_resumo_ano: pd.DataFrame,
    df_c170: pd.DataFrame,
    df_c175: pd.DataFrame,
    df_e316: pd.DataFrame,
) -> bytes:
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_resumo_ano.to_excel(writer, sheet_name="Resumo", index=False)
        df_c170.to_excel(writer, sheet_name="C170", index=False)
        df_c175.to_excel(writer, sheet_name="C175", index=False)
        df_e316.to_excel(writer, sheet_name="E316", index=False)

    output.seek(0)
    return output.read()