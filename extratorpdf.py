import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
import tempfile
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

            # Normalização simples (a mesma que funcionou no debug)
            texto_normalizado = " ".join(texto.split())

            if "Pagamento Indevido ou a Maior" not in texto_normalizado:
                continue
            if "eSOCIAL" not in texto_normalizado:
                continue

            match = re.search(
                r"Saldo\s+do\s+Cr[eé]dito\s+Original\s+([\d\.]+,\d{2})",
                texto_normalizado,
                re.IGNORECASE
            )

            if match:
                valor_str = match.group(1)
                return float(
                    valor_str.replace(".", "").replace(",", ".")
                )

    return None

# =========================
# CONFIGURAÇÃO STREAMLIT
# =========================
st.set_page_config(
    page_title="Extrator PER/DCOMP",
    layout="centered"
)

st.title("📄 Extrator PER/DCOMP – RFB")
st.write(
    "Extração do **Saldo do Crédito Original** "
    "para **eSOCIAL – Pagamento Indevido ou a Maior**"
)

# =========================
# UPLOAD DOS PDFs
# =========================
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
            # Salva PDF temporariamente
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(arquivo.read())
                caminho_pdf = tmp.name

            saldo = extrair_saldo_credito_original(caminho_pdf)

            dados.append({
                "Arquivo PDF": arquivo.name,
                "Tipo de Crédito": "eSOCIAL",
                "Área do Crédito": "Pagamento Indevido ou a Maior",
                "Saldo do Crédito Original": saldo
            })

            os.remove(caminho_pdf)

    # DataFrame final
    df = pd.DataFrame(dados)

    st.success("Processamento concluído!")
    st.dataframe(df, use_container_width=True)

    # =========================
    # GERAÇÃO DO EXCEL
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
