import streamlit as st


st.set_page_config(
    page_title="Analisador PER/DCOMP",
    page_icon="📊",
    layout="wide",
)

st.title("Analisador de créditos PER/DCOMP")
st.caption(
    "Organize declarações por competência, transmissão e cadeia de utilização do crédito."
)

individual_tab, consolidated_tab = st.tabs(
    ["PDFs individuais", "Relatório consolidado"]
)

with individual_tab:
    st.file_uploader(
        "Envie PDFs ou arquivos ZIP",
        type=["pdf", "zip"],
        accept_multiple_files=True,
        key="individual_files",
    )
    st.info("O mecanismo de extração e conciliação será implementado nesta etapa.")

with consolidated_tab:
    st.file_uploader(
        "Envie o PDF consolidado",
        type=["pdf"],
        accept_multiple_files=True,
        key="consolidated_files",
    )
    st.info("Esta aba será usada para validar a cadeia e a situação dos PER/DCOMPs.")

