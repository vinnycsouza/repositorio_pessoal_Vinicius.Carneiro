import streamlit as st
from analise_base_inss import ler_manad, ler_esocial, montar_base, aplicar_regras, gerar_confronto
from util_excel import gerar_excel_saida

st.set_page_config(page_title="Confronto Base INSS x eSocial", layout="wide")

st.title("Confronto Base INSS x eSocial")

# =========================
# Inicialização do estado
# =========================
if "df_resumo" not in st.session_state:
    st.session_state.df_resumo = None

if "df_base" not in st.session_state:
    st.session_state.df_base = None

if "excel_saida" not in st.session_state:
    st.session_state.excel_saida = None

if "analise_gerada" not in st.session_state:
    st.session_state.analise_gerada = False

# =========================
# Uploads
# =========================
manad = st.file_uploader("Arquivo MANAD", type=["xlsx"], key="manad")
esocial = st.file_uploader("Arquivo eSocial", type=["xlsx"], key="esocial")

col1, col2 = st.columns(2)

with col1:
    gerar = st.button("Gerar Análise", use_container_width=True)

with col2:
    limpar = st.button("Limpar análise", use_container_width=True)

# =========================
# Limpar análise
# =========================
if limpar:
    st.session_state.df_resumo = None
    st.session_state.df_base = None
    st.session_state.excel_saida = None
    st.session_state.analise_gerada = False
    st.rerun()

# =========================
# Gerar análise
# =========================
if gerar:
    if not manad or not esocial:
        st.warning("Selecione os dois arquivos antes de gerar a análise.")
    else:
        try:
            df_k300, df_k150 = ler_manad(manad)
            df_esocial = ler_esocial(esocial)

            df_base = montar_base(df_k300, df_k150)
            df_base = aplicar_regras(df_base)

            df_resumo = gerar_confronto(df_base, df_esocial)
            excel_saida = gerar_excel_saida(df_resumo, df_base, df_base)

            st.session_state.df_resumo = df_resumo
            st.session_state.df_base = df_base
            st.session_state.excel_saida = excel_saida
            st.session_state.analise_gerada = True

            st.success("Análise gerada com sucesso.")

        except Exception as e:
            st.session_state.df_resumo = None
            st.session_state.df_base = None
            st.session_state.excel_saida = None
            st.session_state.analise_gerada = False
            st.error(f"Erro ao processar os arquivos: {e}")

# =========================
# Exibição dos resultados
# =========================
if st.session_state.analise_gerada and st.session_state.df_resumo is not None:
    df_resumo = st.session_state.df_resumo.copy()
    df_base = st.session_state.df_base.copy()

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

        base_esocial = float(df_resumo_comp["BASE_INSS_ESOCIAL"].fillna(0).sum()) if "BASE_INSS_ESOCIAL" in df_resumo_comp.columns else 0.0
        base_manad = float(df_resumo_comp["BASE_MANAD"].fillna(0).sum()) if "BASE_MANAD" in df_resumo_comp.columns else 0.0
        diferenca = float(df_resumo_comp["DIFERENCA"].fillna(0).sum()) if "DIFERENCA" in df_resumo_comp.columns else 0.0

        c1, c2, c3 = st.columns(3)
        c1.metric("Base eSocial", f"{base_esocial:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        c2.metric("Base MANAD", f"{base_manad:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        c3.metric("Diferença", f"{diferenca:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        st.subheader(f"Rubricas consideradas na base - {comp}")

        df_filtrado = df_base[
            (df_base["DT_COMP"].astype(str) == str(comp)) &
            (df_base["ENTRA_BASE_INSS"] == 1)
        ].sort_values("VLR_RUBR", ascending=False)

        if df_filtrado.empty:
            st.warning("Não há rubricas classificadas como base para esta competência.")
        else:
            st.dataframe(df_filtrado, use_container_width=True)

        with st.expander("Ver todas as rubricas da competência"):
            df_todas = df_base[
                df_base["DT_COMP"].astype(str) == str(comp)
            ].sort_values("VLR_RUBR", ascending=False)

            if df_todas.empty:
                st.info("Nenhuma rubrica encontrada para esta competência.")
            else:
                st.dataframe(df_todas, use_container_width=True)

        st.download_button(
            "Baixar Excel",
            data=st.session_state.excel_saida,
            file_name="analise_inss.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    else:
        st.info("Nenhuma competência encontrada para exibição.")