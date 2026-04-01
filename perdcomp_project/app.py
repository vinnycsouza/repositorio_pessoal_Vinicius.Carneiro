import pandas as pd
import streamlit as st

from perdcomp_core import (
    build_phase2_outputs,
    export_phase1_excel,
    export_phase2_excel,
    process_phase1_pdfs,
    read_levantamento_excel,
)

st.set_page_config(page_title="Extrator PER/DCOMP", layout="wide")
st.title("📄 Extrator e Cruzamento de PER/DCOMP")

st.markdown(
    """
Sistema em 2 fases independentes:

**Fase 1**
- Lê múltiplos PDFs de PER/DCOMP
- Extrai dados principais
- Identifica PIS e COFINS
- Gera Excel único em ordem cronológica

**Fase 2**
- Lê o Excel de levantamento mensal
- Converte mês para trimestre
- Soma PIS e COFINS separadamente
- Cruza com os dados da Fase 1
- Gera Excel único com abas auxiliares e cruzamento
"""
)

tab1, tab2 = st.tabs(["Fase 1 — Extrair PDFs", "Fase 2 — Cruzar com Levantamento"])

with tab1:
    st.subheader("Fase 1 — Extração dos PDFs de PER/DCOMP")

    uploaded_pdfs = st.file_uploader(
        "Selecione um ou mais PDFs de PER/DCOMP",
        type=["pdf"],
        accept_multiple_files=True,
        key="pdfs_fase1",
    )

    if uploaded_pdfs:
        if st.button("Processar PDFs", key="btn_fase1"):
            with st.spinner("Processando PDFs..."):
                df_phase1 = process_phase1_pdfs(uploaded_pdfs)

            if df_phase1.empty:
                st.warning("Nenhum dado foi extraído dos PDFs enviados.")
            else:
                st.success(f"{len(df_phase1)} registro(s) extraído(s) com sucesso.")
                st.dataframe(df_phase1, use_container_width=True)

                excel_phase1 = export_phase1_excel(df_phase1)

                st.download_button(
                    label="📥 Baixar Excel Fase 1",
                    data=excel_phase1,
                    file_name="perdcomp_fase1.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_fase1",
                )

with tab2:
    st.subheader("Fase 2 — Cruzamento com o levantamento mensal")

    st.markdown(
        """
### Entradas esperadas

**1. Excel da Fase 1**
- Pode ser o arquivo gerado na aba anterior
- Ou outro Excel com as colunas compatíveis

**2. Excel do levantamento mensal**
- Precisa conter, no mínimo:
  - `Ano`
  - `Mês`
  - `Crédito PIS`
  - `Crédito COFINS`
"""
    )

    fase1_excel = st.file_uploader(
        "Envie o Excel da Fase 1",
        type=["xlsx"],
        accept_multiple_files=False,
        key="fase1_excel",
    )

    levantamento_excel = st.file_uploader(
        "Envie o Excel do levantamento mensal",
        type=["xlsx"],
        accept_multiple_files=False,
        key="levantamento_excel",
    )

    if fase1_excel and levantamento_excel:
        if st.button("Processar Cruzamento", key="btn_fase2"):
            with st.spinner("Lendo arquivos e montando cruzamento..."):
                try:
                    df_phase1 = pd.read_excel(fase1_excel)
                    df_levantamento = read_levantamento_excel(levantamento_excel)

                    df_levant_trim, df_cruzamento = build_phase2_outputs(
                        df_phase1=df_phase1,
                        df_levantamento=df_levantamento,
                    )

                    excel_phase2 = export_phase2_excel(
                        df_levantamento_trim=df_levant_trim,
                        df_cruzamento=df_cruzamento,
                    )

                    st.success("Cruzamento gerado com sucesso.")

                    st.markdown("### Levantamento Trimestral")
                    st.dataframe(df_levant_trim, use_container_width=True)

                    st.markdown("### Cruzamento Final")
                    st.dataframe(df_cruzamento, use_container_width=True)

                    st.download_button(
                        label="📥 Baixar Excel Fase 2",
                        data=excel_phase2,
                        file_name="perdcomp_fase2.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_fase2",
                    )

                except Exception as e:
                    st.error(f"Erro ao processar a Fase 2: {e}")