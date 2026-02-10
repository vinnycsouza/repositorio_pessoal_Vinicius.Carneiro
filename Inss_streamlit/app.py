import streamlit as st
import pdfplumber
import pandas as pd

from competencia import extrair_competencia
from extrator_pdf import extrair_rubricas_page, extrair_base_oficial_page
from calculo_base import calcular_base

st.set_page_config(layout="wide")
st.title("📊 Analisador INSS Patronal por Competência")

arquivo = st.file_uploader("Envie o PDF da folha", type="pdf")

if arquivo:
    dados = {}
    competencia_atual = None

    with pdfplumber.open(arquivo) as pdf:
        for page in pdf.pages:
            competencia_atual = extrair_competencia(page, competencia_atual)
            if not competencia_atual:
                continue

            dados.setdefault(competencia_atual, {
                "rubricas": [],
                "base_empresa": None
            })

            rubricas = extrair_rubricas_page(page)
            dados[competencia_atual]["rubricas"].extend(rubricas)

            base = extrair_base_oficial_page(page)
            if base and not dados[competencia_atual]["base_empresa"]:
                dados[competencia_atual]["base_empresa"] = base

    for comp, info in dados.items():
        st.divider()
        st.subheader(f"📅 Competência {comp}")

        df = pd.DataFrame(info["rubricas"])
        df = df.drop_duplicates(subset=["rubrica", "valor", "tipo"])

        base_calc, df = calcular_base(df)

        c1, c2 = st.columns(2)
        c1.metric("Base calculada", f"R$ {base_calc:,.2f}")
        c2.metric(
            "Base oficial (empresa)",
            f"R$ {info['base_empresa']:,.2f}" if info["base_empresa"] else "Não encontrada"
        )

        st.dataframe(df, use_container_width=True)
