import streamlit as st
import pdfplumber
import pandas as pd
import re
import tempfile
import os
from io import BytesIO

# =========================
# FUNÇÃO DE EXTRAÇÃO
# =========================
def extrair_saldo_credito_original(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if not texto:
                continue

            texto_normalizado = " ".join(texto.split())

            # Regex CONFIRMADA pelo debug real
            match = re.search(
                r"Saldo\s+do\s+Cr[eé]dito\s+Original\s+([\d\.]+,\d{2})",
                texto_normalizado,
                re.IGNORECASE
            )

            if match:
                return float(
                    match.group(1)
                    .replace(".", "")
                    .replace(",", ".")
                )

    return None

# =========================
# CONFIG STREAMLIT
# =========================
st.set_page_config(page_title="Extrator PER/DCOMP", layout="centered")
st.title("📄 Extrator PER/DCOMP – RFB")

st.write(
    "Extração do **Saldo do Crédito Original** "
    "(eSOCIAL – Pagamento Indevido ou a Maior)"
)

# =========================
# SESSION STATE
# =========================
if "arquivos" not in st.session_state:
    st.session_state.arquivos = []

# =========================
# UPLOAD
# =========================
uploads = st.file_uploader(
    "Envie os PDFs PER/DCOMP",
    type="pdf",
    accept_multiple_files=True,
    key="uploader"
)

if uploads:
    st.session_state.arquivos = uploads

# =========================
# BOTÃO PROCESSAR
# =========================
if st.session_state.arquivos:
    if st.button("🚀 Processar PDFs"):
        dados = []

        with st.spinner("Processando arquivos..."):
            for arquivo in st.session_state.arquivos:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(arquivo.read())
                    caminho_pdf = tmp.name

                saldo = extrair_saldo_credito_original(caminho_pdf)

                dados.append({
                    "Arquivo PDF": arquivo.name,
                    "Saldo do Crédito Original": saldo
                })

                os.remove(caminho_pdf)

        df = pd.DataFrame(dados)

        st.success("Processamento concluído!")
        st.dataframe(df, use_container_width=True)

        # =========================
        # EXCEL
        # =========================
        buffer = BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)

        st.download_button(
            label="📥 Baixar Excel",
            data=buffer,
            file_name="resultado_perdcomp.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
