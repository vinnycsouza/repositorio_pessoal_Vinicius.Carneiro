import pandas as pd

def processar_arquivos(arquivo_icms, arquivo_pis, modo):

    df_c190 = pd.read_excel(
        arquivo_icms,
        sheet_name="C190",
        dtype=str,
        engine="openpyxl"
    )

    resultado = {
        "resumo": pd.DataFrame(),
        "analitico": pd.DataFrame()
    }

    if modo in ["C170", "AMBOS"]:

        df_c170 = pd.read_excel(
            arquivo_pis,
            sheet_name="C170",
            dtype=str,
            engine="openpyxl"
        )

        resultado["c170"] = df_c170

    if modo in ["C175", "AMBOS"]:

        df_c175 = pd.read_excel(
            arquivo_pis,
            sheet_name="C175",
            dtype=str,
            engine="openpyxl"
        )

        resultado["c175"] = df_c175

    resultado["c190"] = df_c190

    return resultado
