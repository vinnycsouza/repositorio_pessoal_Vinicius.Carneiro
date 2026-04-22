import streamlit as st
from analise_base_inss import *
from util_excel import gerar_excel_saida

st.title("Confronto Base INSS x eSocial")

manad = st.file_uploader("Arquivo MANAD", type=["xlsx"])
esocial = st.file_uploader("Arquivo eSocial", type=["xlsx"])

if manad and esocial:
    if st.button("Gerar Análise"):

        df_k300, df_k150 = ler_manad(manad)
        df_esocial = ler_esocial(esocial)

        df_base = montar_base(df_k300, df_k150)
        df_base = aplicar_regras(df_base)

        df_resumo = gerar_confronto(df_base, df_esocial)

        st.subheader("Resumo")
        st.dataframe(df_resumo)

        comp = st.selectbox("Competência", df_resumo["DT_COMP"].unique())

        st.subheader("Detalhamento")
        st.dataframe(
            df_base[
                (df_base["DT_COMP"] == comp) &
                (df_base["ENTRA_BASE_INSS"] == 1)
            ].sort_values("VLR_RUBR", ascending=False)
        )

        excel = gerar_excel_saida(df_resumo, df_base, df_base)

        st.download_button(
            "Baixar Excel",
            data=excel,
            file_name="analise_inss.xlsx"
        )