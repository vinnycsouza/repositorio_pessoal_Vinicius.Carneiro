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

            # Normaliza completamente o texto
            texto_normalizado = " ".join(texto.replace("\n", " ").split())

            # Garante que está no bloco correto
            if "Pagamento Indevido ou a Maior" not in texto_normalizado:
                continue

            if "eSOCIAL" not in texto_normalizado:
                continue

            # Estratégia:
            # procura "Saldo de Crédito" e captura o PRIMEIRO valor monetário depois
            match = re.search(
                r"Saldo de Crédito.*?(R?\$?\s*[\d\.]+,\d{2})",
                texto_normalizado
            )

            if match:
                # Limpa o valor (remove R$ e espaços)
                valor = match.group(1)
                valor = valor.replace("R$", "").replace(" ", "").strip()
                return valor

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
    "Extração do **Saldo de Crédito Original** "
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
                "Saldo de Crédito Original": saldo
            })

            os.remove(caminho_pdf)

    # Cria DataFrame
    df = pd.DataFrame(dados)

    # Exibe resultado
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
