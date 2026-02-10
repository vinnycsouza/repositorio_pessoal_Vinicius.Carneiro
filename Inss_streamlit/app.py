import streamlit as st
from extrator_pdf import extrair_base_oficial, extrair_rubricas
from calculo_base import calcular_base
import pandas as pd


st.set_page_config(layout="wide")
st.title("📊 Analisador de Base INSS Patronal")

arquivos = st.file_uploader(
    "Envie PDF(s) de folha de pagamento",
    type="pdf",
    accept_multiple_files=True
)

if arquivos:
    for arquivo in arquivos:
        st.divider()
        st.subheader(f"📄 {arquivo.name}")

        base_oficial = extrair_base_oficial(arquivo)
        rubricas = extrair_rubricas(arquivo)

        if rubricas.empty:
            st.error("Nenhuma rubrica encontrada no PDF")
            continue

        base_calc, diff, tabela = calcular_base(rubricas, base_oficial)

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Base Oficial (PDF)",
            f"R$ {base_oficial:,.2f}" if base_oficial else "Não encontrada"
        )

        c2.metric(
            "Base Calculada",
            f"R$ {base_calc:,.2f}"
        )

        c3.metric(
            "Diferença",
            f"R$ {diff:,.2f}" if diff is not None else "-"
        )

        st.dataframe(
            tabela.sort_values("classificacao"),
            use_container_width=True
        )
import io

# cria arquivo Excel em memória
buffer = io.BytesIO()

with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
    tabela.to_excel(
        writer,
        index=False,
        sheet_name="Rubricas"
    )

buffer.seek(0)

st.download_button(
    label="📥 Baixar Excel – Rubricas da Base INSS",
    data=buffer,
    file_name=f"rubricas_base_inss_{arquivo.name}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
