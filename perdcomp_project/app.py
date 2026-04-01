from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from perdcomp_core import (
    build_crosswalk,
    export_phase1_excel,
    export_phase2_excel,
    load_levantamento_excel,
    process_pdf_files,
)


st.set_page_config(page_title="PER/DCOMP — Extrator e Cruzamento", layout="wide")
st.title("📄 PER/DCOMP — Extrator e Cruzamento de Créditos")
st.caption(
    "Fase 1: extrai vários PDFs de PER/DCOMP para um Excel único. "
    "Fase 2: cruza o Excel extraído com um levantamento mensal em Excel, separando PIS e COFINS."
)


def make_download_name(prefix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}.xlsx"


tab1, tab2 = st.tabs(["Fase 1 — Extrair PDFs", "Fase 2 — Cruzar com levantamento"])

with tab1:
    st.subheader("Extrair informações de múltiplos PDFs de PER/DCOMP")
    st.write(
        "Campos extraídos: tipo do crédito, tipo de período do crédito, trimestre, ano, valor original do crédito, saldo do crédito original, crédito utilizado, crédito atualizado e datas."
    )

    pdfs = st.file_uploader(
        "Envie os PDFs de PER/DCOMP",
        type=["pdf"],
        accept_multiple_files=True,
        key="fase1_pdfs",
    )

    if st.button("Processar PDFs", type="primary", use_container_width=True):
        if not pdfs:
            st.warning("Envie pelo menos um PDF.")
        else:
            files = [(f.name, f.read()) for f in pdfs]
            df = process_pdf_files(files)
            st.session_state["perdcomp_df"] = df
            st.success(f"{len(df)} arquivo(s) processado(s) com sucesso.")

    df_phase1 = st.session_state.get("perdcomp_df", pd.DataFrame())
    if not df_phase1.empty:
        st.dataframe(df_phase1, use_container_width=True, hide_index=True)

        output_name = make_download_name("perdcomp_fase1")
        output_path = Path("/tmp") / output_name
        export_phase1_excel(df_phase1, output_path)
        with open(output_path, "rb") as f:
            st.download_button(
                "⬇️ Baixar Excel da Fase 1",
                data=f.read(),
                file_name=output_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

with tab2:
    st.subheader("Cruzar PER/DCOMP com levantamento mensal")
    st.write(
        "O Excel de levantamento deve ter colunas compatíveis com Ano, Mês, Crédito PIS e Crédito COFINS. "
        "O sistema converte os meses para trimestre, soma PIS e COFINS separadamente e cruza com os PER/DCOMP."
    )

    col1, col2 = st.columns(2)
    with col1:
        pdfs_f2 = st.file_uploader(
            "Envie novamente os PDFs de PER/DCOMP ou use os já processados na Fase 1",
            type=["pdf"],
            accept_multiple_files=True,
            key="fase2_pdfs",
        )
    with col2:
        levantamento_file = st.file_uploader(
            "Envie o Excel de levantamento",
            type=["xlsx", "xls"],
            key="levantamento_excel",
        )

    if st.button("Gerar cruzamento", type="primary", use_container_width=True):
        try:
            if pdfs_f2:
                df_perdcomp = process_pdf_files([(f.name, f.read()) for f in pdfs_f2])
                st.session_state["perdcomp_df"] = df_perdcomp
            else:
                df_perdcomp = st.session_state.get("perdcomp_df", pd.DataFrame())

            if df_perdcomp.empty:
                st.warning("Envie os PDFs na Fase 2 ou processe antes na Fase 1.")
            elif levantamento_file is None:
                st.warning("Envie o Excel de levantamento.")
            else:
                levantamento_normalizado, levantamento_trimestral = load_levantamento_excel(
                    levantamento_file.read(), levantamento_file.name
                )
                cruzamento = build_crosswalk(df_perdcomp, levantamento_trimestral)

                st.session_state["levantamento_normalizado"] = levantamento_normalizado
                st.session_state["levantamento_trimestral"] = levantamento_trimestral
                st.session_state["cruzamento"] = cruzamento
                st.success("Cruzamento gerado com sucesso.")
        except Exception as exc:
            st.error(f"Erro ao gerar cruzamento: {exc}")

    cruzamento = st.session_state.get("cruzamento", pd.DataFrame())
    levantamento_trimestral = st.session_state.get("levantamento_trimestral", pd.DataFrame())
    levantamento_normalizado = st.session_state.get("levantamento_normalizado", pd.DataFrame())
    df_perdcomp = st.session_state.get("perdcomp_df", pd.DataFrame())

    if not levantamento_trimestral.empty:
        st.markdown("### Levantamento trimestral")
        st.dataframe(levantamento_trimestral, use_container_width=True, hide_index=True)

    if not cruzamento.empty:
        st.markdown("### Cruzamento final")
        st.dataframe(cruzamento, use_container_width=True, hide_index=True)

        output_name = make_download_name("perdcomp_fase2_cruzamento")
        output_path = Path("/tmp") / output_name
        export_phase2_excel(
            df_perdcomp,
            levantamento_normalizado,
            levantamento_trimestral,
            cruzamento,
            output_path,
        )
        with open(output_path, "rb") as f:
            st.download_button(
                "⬇️ Baixar Excel da Fase 2",
                data=f.read(),
                file_name=output_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
