from io import BytesIO
import pandas as pd


def gerar_excel_saida(df_resumo, df_base_total, df_composicao):
    output = BytesIO()

    df_usadas = df_base_total[df_base_total["FOI_USADA_NA_COMPOSICAO"] == "SIM"].copy()
    df_nao_usadas = df_base_total[df_base_total["FOI_USADA_NA_COMPOSICAO"] == "NAO"].copy()
    df_indenizatorias_usadas = df_usadas[
        df_usadas["NATUREZA_ANALITICA"] == "INDENIZATORIA_POTENCIAL"
    ].copy()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_resumo.to_excel(writer, sheet_name="RESUMO_CONFRONTO", index=False)
        df_composicao.to_excel(writer, sheet_name="COMPOSICAO_ENCONTRADA", index=False)
        df_usadas.to_excel(writer, sheet_name="RUBRICAS_USADAS", index=False)
        df_nao_usadas.to_excel(writer, sheet_name="RUBRICAS_NAO_USADAS", index=False)
        df_indenizatorias_usadas.to_excel(writer, sheet_name="INDENIZATORIAS_USADAS", index=False)
        df_base_total.to_excel(writer, sheet_name="BASE_ANALITICA_TOTAL", index=False)

    output.seek(0)
    return output