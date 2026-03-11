from __future__ import annotations

import io
import pandas as pd


def gerar_excel_saida(
    df_resumo_ano: pd.DataFrame,
    df_resumo_empresa: pd.DataFrame,
    df_resumo_cfop: pd.DataFrame,
    df_resultado_amostra: pd.DataFrame,
    df_resumo_abas_pis: pd.DataFrame,
    df_resumo_abas_icms: pd.DataFrame,
) -> bytes:
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_resumo_ano.to_excel(writer, sheet_name="Resumo por Ano", index=False)
        df_resumo_empresa.to_excel(writer, sheet_name="Resumo por Empresa", index=False)
        df_resumo_cfop.to_excel(writer, sheet_name="Resumo por CFOP", index=False)
        df_resumo_abas_pis.to_excel(writer, sheet_name="Abas PIS_COFINS", index=False)
        df_resumo_abas_icms.to_excel(writer, sheet_name="Abas ICMS_IPI", index=False)
        df_resultado_amostra.to_excel(writer, sheet_name="Amostra Resultado", index=False)

    output.seek(0)
    return output.read()