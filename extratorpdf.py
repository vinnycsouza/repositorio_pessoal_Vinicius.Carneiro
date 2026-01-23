import streamlit as st
import pdfplumber
import pandas as pd
import re
import tempfile
import os
from io import BytesIO

st.set_page_config(page_title="Extrator PDF", layout="centered")
st.title("📄 Extrator – PER/DCOMP eSOCIAL")

def extrair_valor(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if not texto:
                continue

            texto = " ".join(texto.split())

            match = re.search(
                r"Saldo\s+do\s+Cr[eé]dito\s+Original\s+([\d\.]+,\d{2})",
                texto,
                re.IGNORECASE
            )

            if match:
                return float(
                    match.group(1)
                    .replace(".", "")
                    .replace(",", ".")
                )
    return None

# uploader MULTIPLO
arquivos = st.file_uploader(
    "Envie os PDFs PER/DCOMP",
    type="pdf",
    accept_multiple_files=True
)

# botão de execução
if arquivos and st.button("🚀 Processar PDFs"):
    resultados = []

    for arquivo in arquivos:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(arquivo.getbuffer())
            caminho_pdf = tmp.name

        valor = extrair_valor(caminho_pdf)

        resultados.append({
            "Arquivo": arquivo.name,
            "Saldo do Crédito Original": valor
        })

        os.remove(caminho_pdf)

    df = pd.DataFrame(resultados)

    st.success("Processamento concluído ✅")
    st.dataframe(df, use_container_width=True)

    buffer = BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)

    st.download_button(
        "📥 Baixar Excel",
        buffer,
        "resultado_creditos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
