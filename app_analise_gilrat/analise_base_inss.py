import pandas as pd
import numpy as np
from util_formatacao import *

def ler_manad(arquivo):
    df_k300 = pd.read_excel(arquivo, sheet_name="K300_FILTRADO")
    df_k150 = pd.read_excel(arquivo, sheet_name="K150_SELECIONADAS")

    df_k300 = normalizar_colunas(df_k300)
    df_k150 = normalizar_colunas(df_k150)

    df_k300["DT_COMP"] = df_k300["DT_COMP"].apply(padronizar_dt_comp)
    df_k300["COD_RUBR"] = df_k300["COD_RUBR"].astype(str).str.strip()
    df_k300["VLR_RUBR"] = converter_valor(df_k300["VLR_RUBR"])

    df_k150["COD_RUBRICA"] = df_k150["COD_RUBRICA"].astype(str).str.strip()

    return df_k300, df_k150


def ler_esocial(arquivo):
    df = pd.read_excel(arquivo)
    df = normalizar_colunas(df)

    df["DT_COMP"] = df["DT_COMP"].apply(padronizar_dt_comp)
    df["BASE_INSS_ESOCIAL"] = converter_valor(df["BASE_INSS_ESOCIAL"])

    return df[["DT_COMP", "BASE_INSS_ESOCIAL"]]


def montar_base(df_k300, df_k150):
    df = df_k300.groupby(["DT_COMP", "COD_RUBR"], as_index=False)["VLR_RUBR"].sum()

    df = df.merge(
        df_k150,
        left_on="COD_RUBR",
        right_on="COD_RUBRICA",
        how="left"
    )

    df["DESC_RUBRICA"] = df["DESC_RUBRICA"].fillna("SEM DESCRICAO")
    return df


def aplicar_regras(df):
    regras = {
        "5": 1,
        "401": 1,
        "411": 1,
        "101": 1,
        "116": 1,
        "131": 1,
        "315": 0,
    }

    df["ENTRA_BASE_INSS"] = df["COD_RUBR"].map(regras)

    return df


def gerar_confronto(df, df_esocial):
    df_base = (
        df[df["ENTRA_BASE_INSS"] == 1]
        .groupby("DT_COMP", as_index=False)["VLR_RUBR"]
        .sum()
        .rename(columns={"VLR_RUBR": "BASE_MANAD"})
    )

    df_final = df_esocial.merge(df_base, on="DT_COMP", how="left")
    df_final["BASE_MANAD"] = df_final["BASE_MANAD"].fillna(0)

    df_final["DIFERENCA"] = df_final["BASE_INSS_ESOCIAL"] - df_final["BASE_MANAD"]

    df_final["STATUS"] = np.where(
        df_final["DIFERENCA"].abs() < 0.05,
        "OK",
        "DIVERGENTE"
    )

    return df_final