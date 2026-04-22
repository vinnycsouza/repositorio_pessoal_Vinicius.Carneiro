import streamlit as st
from analise_base_inss import (
    ler_manad,
    ler_esocial,
    montar_base_manad,
    analisar_composicao_base,
)
from util_excel import gerar_excel_saida

st.set_page_config(page_title="Composição Base INSS x eSocial", layout="wide")

st.title("Composição da Base do eSocial dentro da Base do MANAD")

if "df_resumo" not in st.session_state:
    st.session_state.df_resumo = None

if "df_base_total" not in st.session_state:
    st.session_state.df_base_total = None

if "df_composicao" not in st.session_state:
    st.session_state.df_composicao = None

if "excel_saida" not in st.session_state:
    st.session_state.excel_saida = None

if "analise_gerada" not in st.session_state:
    st.session_state.analise_gerada = False


manad = st.file_uploader("Arquivo MANAD", type=["xlsx"], key="manad")
esocial = st.file_uploader("Arquivo eSocial", type=["xlsx"], key="esocial")

col1, col2 = st.columns(2)

with col1:
    gerar = st.button("Gerar análise", use_container_width=True)

with col2:
    limpar = st.button("Limpar análise", use_container_width=True)

if limpar:
    st.session_state.df_resumo = None
    st.session_state.df_base_total = None
    st.session_state.df_composicao = None
    st.session_state.excel_saida = None
    st.session_state.analise_gerada = False
    st.rerun()

if gerar:
    if not manad or not esocial:
        st.warning("Selecione os dois arquivos antes de gerar a análise.")
    else:
        try:
            df_k300, df_k150 = ler_manad(manad)
            df_esocial = ler_esocial(esocial)

            df_base_manad = montar_base_manad(df_k300, df_k150)

            df_resumo, df_base_total, df_composicao = analisar_composicao_base(
                df_base_manad,
                df_esocial,
                top_n=24
            )

            excel_saida = gerar_excel_saida(df_resumo, df_base_total, df_composicao)

            st.session_state.df_resumo = df_resumo
            st.session_state.df_base_total = df_base_total
            st.session_state.df_composicao = df_composicao
            st.session_state.excel_saida = excel_saida
            st.session_state.analise_gerada = True

            st.success("Análise gerada com sucesso.")

        except Exception as e:
            st.session_state.df_resumo = None
            st.session_state.df_base_total = None
            st.session_state.df_composicao = None
            st.session_state.excel_saida = None
            st.session_state.analise_gerada = False
            st.error(f"Erro ao processar os arquivos: {e}")

if (
    st.session_state.analise_gerada
    and st.session_state.df_resumo is not None
    and st.session_state.df_base_total is not None
):
    df_resumo = st.session_state.df_resumo.copy()
    df_base_total = st.session_state.df_base_total.copy()
    df_composicao = (
        st.session_state.df_composicao.copy()
        if st.session_state.df_composicao is not None
        else None
    )

    st.subheader("Resumo do confronto")
    st.dataframe(df_resumo, use_container_width=True)

    competencias = sorted(df_resumo["DT_COMP"].dropna().astype(str).unique().tolist())

    if competencias:
        comp = st.selectbox(
            "Selecione a competência para detalhar",
            competencias,
            key="competencia_select"
        )

        df_resumo_comp = df_resumo[df_resumo["DT_COMP"].astype(str) == str(comp)].copy()

        base_esocial = float(df_resumo_comp["BASE_INSS_ESOCIAL"].fillna(0).sum())
        soma_encontrada = float(df_resumo_comp["SOMA_ENCONTRADA_MANAD"].fillna(0).sum())
        diferenca = float(df_resumo_comp["DIFERENCA"].fillna(0).sum())

        c1, c2, c3 = st.columns(3)
        c1.metric("Base eSocial", f"{base_esocial:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        c2.metric("Soma encontrada no MANAD", f"{soma_encontrada:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        c3.metric("Diferença", f"{diferenca:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        st.subheader(f"Rubricas usadas na composição - {comp}")
        df_usadas = df_base_total[
            (df_base_total["DT_COMP"].astype(str) == str(comp)) &
            (df_base_total["FOI_USADA_NA_COMPOSICAO"] == "SIM")
        ].sort_values(["NATUREZA_ANALITICA", "VLR_RUBR"], ascending=[True, False])

        if df_usadas.empty:
            st.warning("Nenhuma rubrica foi selecionada para esta competência.")
        else:
            st.dataframe(df_usadas, use_container_width=True)

        st.subheader(f"Rubricas indenizatórias potenciais usadas - {comp}")
        df_inden = df_usadas[df_usadas["NATUREZA_ANALITICA"] == "INDENIZATORIA_POTENCIAL"].copy()
        if df_inden.empty:
            st.info("Nenhuma rubrica indenizatória potencial foi usada nesta composição.")
        else:
            st.dataframe(df_inden, use_container_width=True)

        with st.expander("Ver todas as rubricas da competência"):
            df_todas = df_base_total[
                df_base_total["DT_COMP"].astype(str) == str(comp)
            ].sort_values(["NATUREZA_ANALITICA", "VLR_RUBR"], ascending=[True, False])

            if df_todas.empty:
                st.info("Nenhuma rubrica encontrada para esta competência.")
            else:
                st.dataframe(df_todas, use_container_width=True)

        st.download_button(
            "Baixar Excel da análise",
            data=st.session_state.excel_saida,
            file_name="analise_composicao_base_inss.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )