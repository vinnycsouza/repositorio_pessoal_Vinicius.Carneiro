from io import BytesIO
import pandas as pd

def gerar_excel_saida(df_resumo, df_classificada, df_mapa):
    output = BytesIO()

    df_base = df_classificada[df_classificada["ENTRA_BASE_INSS"] == 1]
    df_fora = df_classificada[df_classificada["ENTRA_BASE_INSS"] == 0]
    df_revisar = df_classificada[df_classificada["ENTRA_BASE_INSS"].isna()]

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_resumo.to_excel(writer, sheet_name="RESUMO_CONFRONTO", index=False)
        df_base.to_excel(writer, sheet_name="BASE_ANALITICA_MANAD", index=False)
        df_fora.to_excel(writer, sheet_name="RUBRICAS_FORA_BASE", index=False)
        df_revisar.to_excel(writer, sheet_name="RUBRICAS_REVISAR", index=False)
        df_mapa.to_excel(writer, sheet_name="MAPA_RUBRICAS", index=False)

    output.seek(0)
    return output