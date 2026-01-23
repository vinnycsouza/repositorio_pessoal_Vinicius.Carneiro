import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
import tempfile

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

            if (
                "Pagamento Indevido ou a Maior" in texto_normalizado
                and "eSOCIAL" in texto_normalizado
                and "Saldo de Crédito Original" in texto_normalizado
            ):
                match = re.search(
                    r"Saldo de Crédito Original\s*[:\-]?\s*R?\$?\s*([\d\.]+,\d{2})",
                    texto_normalizado
                )

                if match:
                    return match.group(1)

    return None

# =========================
# INTERFACE STREAMLIT
# =========================
st.set_page_config(page_title="Extrator PER/DCOMP", layout="centered")

st.title("📄 Extrator PER/DCOMP – RFB")
st.write("Extração do **Saldo de Crédito Original** para **eSOCIAL – Pagamento Indevido ou a Maior**")

arquivos_pdf = st.file_uploader(
    "Envie os arquivos PDF PER/DCOMP",
    type="pdf",
    accept_multiple_files=True
)

# =========================
# PROCESSAMENTO
# =========================
if arquivos_pdf:
    dados = []

    with st.spinner("Processando arquivos..."):
        for arquivo in arquivos_pdf:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(arquivo.read())
                caminho_pdf = tmp.name

            saldo = extrair_saldo_credito_original(caminho_pdf)

            dados.append({
                "Arquivo PDF": arquivo.name,
                "Tipo de Crédito": "eSOCIAL",
                "Área do Crédito": "Pagamento Indevido ou a Maior",
                "Saldo de Crédito Original": saldo
            })

            os.remove(caminho_pdf)

    df = pd.DataFrame(dados)

    st.success("Processamento concluído!")
    st.dataframe(df, use_container_width=True)

    # =========================
    # DOWNLOAD DO EXCEL
    # =========================
    excel_bytes = df.to_excel(
        index=False,
        engine="openpyxl"
    )

    st.download_button(
        label="📥 Baixar Excel",
        data=excel_bytes,
        file_name="resultado_perdcomp.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
