import streamlit as st
import pandas as pd
from src.validation import validar_abas
from src.processing import processar_arquivos
from src.exporter import exportar_excel

st.set_page_config(layout="wide")

st.title("Investigação ICMS na Base PIS/COFINS")

st.warning(
    "Arquivos acima de 500MB podem levar vários minutos para processamento."
)

modo = st.radio(
    "Escolha o modo de análise:",
    [
        "C170",
        "C175",
        "AMBOS"
    ]
)

uploaded_icms = st.file_uploader(
    "Upload SPED ICMS/IPI",
    type=["xlsx"]
)

uploaded_pis = st.file_uploader(
    "Upload SPED PIS/COFINS",
    type=["xlsx"]
)

if uploaded_icms and uploaded_pis:

    erros_icms = validar_abas(uploaded_icms, "ICMS")
    erros_pis = validar_abas(uploaded_pis, modo)

    erros = erros_icms + erros_pis

    if erros:
        for erro in erros:
            st.error(erro)

    else:
        with st.spinner("Processando arquivos..."):

            resultado = processar_arquivos(
                uploaded_icms,
                uploaded_pis,
                modo
            )

            caminho = exportar_excel(resultado)

            st.success("Processamento concluído.")

            with open(caminho, "rb") as f:
                st.download_button(
                    "Baixar Excel",
                    f,
                    file_name="analise_icms_pis_cofins.xlsx"
                )
