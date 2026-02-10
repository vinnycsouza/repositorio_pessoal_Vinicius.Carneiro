import streamlit as st
import pandas as pd
import io

from extrator_pdf import extrair_rubricas
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
        rubricas = extrair_rubricas(arquivo)

        if rubricas.empty:
            st.error("Nenhuma rubrica encontrada no PDF")
            continue

        # --- cálculo ---
        base_calc, tabela = calcular_base(rubricas)

        # --- métricas ---
        c1, c2 = st.columns(2)

        c1.metric(
            "Base calculada (rubricas ENTRA)",
            f"R$ {base_calc:,.2f}"
        )

        c2.metric(
            "Total de rubricas identificadas",
            f"{len(tabela)}"
        )

        # --- tabela geral ---
        st.subheader("Rubricas identificadas")
        st.dataframe(
            tabela.sort_values(["tipo", "classificacao"]),
            use_container_width=True
        )

        # --- abas provento x desconto ---
        tab1, tab2 = st.tabs(["🔵 Proventos", "🔴 Descontos"])

        with tab1:
            proventos = tabela[tabela["tipo"] == "PROVENTO"]
            st.dataframe(proventos, use_container_width=True)
            st.metric(
                "Total Proventos",
                f"R$ {proventos['valor'].sum():,.2f}"
            )

        with tab2:
            descontos = tabela[tabela["tipo"] == "DESCONTO"]
            st.dataframe(descontos, use_container_width=True)
            st.metric(
                "Total Descontos",
                f"R$ {descontos['valor'].sum():,.2f}"
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
