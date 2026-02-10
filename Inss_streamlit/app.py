import streamlit as st
import pandas as pd
import io

from extrator_pdf import extrair_base_oficial, extrair_rubricas
from calculo_base import calcular_base

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

        # --- extração ---
        base_oficial = extrair_base_oficial(arquivo)
        rubricas = extrair_rubricas(arquivo)

        if rubricas.empty:
            st.error("Nenhuma rubrica encontrada no PDF")
            continue

        # --- cálculo ---
        base_calc, diff, tabela = calcular_base(rubricas, base_oficial)

        # --- métricas ---
        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Base Oficial (PDF)",
            f"R$ {base_oficial:,.2f}" if base_oficial else "Não encontrada"
        )

        c2.metric(
    "Soma das Rubricas Identificadas",
    f"R$ {base_calc:,.2f}"
        )

c3.metric(
    "Diferença p/ Base Oficial (indicativa)",
    f"R$ {diff:,.2f}" if diff is not None else "-"
        )

        # --- tabela ---
st.subheader("Rubricas identificadas")
      
st.dataframe(
            tabela.sort_values("classificacao"),
            use_container_width=True
        )

        # --- exportar Excel ---
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
