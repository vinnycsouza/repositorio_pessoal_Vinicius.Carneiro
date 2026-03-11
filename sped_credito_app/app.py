from __future__ import annotations

import streamlit as st
import pandas as pd

from sped_credito_app.excel_parser import (
    ler_linhas_sped,
    separar_registros,
    df_registro,
    preparar_c170,
    preparar_c175,
    preparar_e316,
)
from calculos import (
    ALIQUOTAS_PADRAO,
    resumir_bases,
    calcular_creditos_totais,
    resumo_por_ano,
)
from exportacao import gerar_excel_resumo


st.set_page_config(page_title="Apurador SPED - PIS/COFINS", layout="wide")
st.title("📊 Apurador SPED — Exclusões de ICMS ST / DIFAL da base de PIS e COFINS")

st.markdown("""
Este esqueleto foi preparado para:
- **Lucro Real**: excluir **ICMS ST** da base e retirar **PIS/COFINS por dentro**
- **Lucro Presumido**: excluir **ICMS ST + DIFAL** da base e retirar **PIS/COFINS por dentro**
""")

arquivo = st.file_uploader("Envie o arquivo SPED (.txt)", type=["txt"])

col1, col2, col3 = st.columns(3)

with col1:
    regime = st.selectbox(
        "Regime tributário",
        options=["real", "presumido"],
        format_func=lambda x: "Lucro Real" if x == "real" else "Lucro Presumido"
    )

with col2:
    aliquota_pis = st.number_input(
        "Alíquota PIS",
        min_value=0.0,
        max_value=1.0,
        value=ALIQUOTAS_PADRAO[regime]["pis"],
        step=0.0001,
        format="%.4f",
    )

with col3:
    aliquota_cofins = st.number_input(
        "Alíquota COFINS",
        min_value=0.0,
        max_value=1.0,
        value=ALIQUOTAS_PADRAO[regime]["cofins"],
        step=0.0001,
        format="%.4f",
    )

st.subheader("Mapeamento inicial dos campos")
st.caption("Ajuste esses índices conforme o layout real do seu SPED.")

with st.expander("Mapeamento C170", expanded=True):
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        idx_c170_num_item = st.text_input("C170 num_item", "campo_2")
    with c2:
        idx_c170_cod_item = st.text_input("C170 cod_item", "campo_3")
    with c3:
        idx_c170_cfop = st.text_input("C170 cfop", "campo_11")
    with c4:
        idx_c170_vl_item = st.text_input("C170 vl_item", "campo_7")
    with c5:
        idx_c170_vl_icms_st = st.text_input("C170 vl_icms_st", "campo_15")

    idx_c170_ano = st.text_input("C170 ano", "")

with st.expander("Mapeamento C175", expanded=True):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        idx_c175_cfop = st.text_input("C175 cfop", "campo_2")
    with c2:
        idx_c175_vl_operacao = st.text_input("C175 vl_operacao", "campo_5")
    with c3:
        idx_c175_vl_icms_st = st.text_input("C175 vl_icms_st", "campo_6")
    with c4:
        idx_c175_ano = st.text_input("C175 ano", "")

with st.expander("Mapeamento E316", expanded=True):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        idx_e316_uf = st.text_input("E316 uf", "campo_2")
    with c2:
        idx_e316_vl_or = st.text_input("E316 vl_or", "campo_4")
    with c3:
        idx_e316_vl_difal = st.text_input("E316 vl_difal", "campo_5")
    with c4:
        idx_e316_ano = st.text_input("E316 ano", "")

if arquivo:
    try:
        linhas = ler_linhas_sped(arquivo)
        separados = separar_registros(linhas, registros_interesse={"C100", "C170", "C175", "E316"})

        df_c170_raw = df_registro(separados["C170"])
        df_c175_raw = df_registro(separados["C175"])
        df_e316_raw = df_registro(separados["E316"])

        mapa_c170 = {
            "num_item": idx_c170_num_item or None,
            "cod_item": idx_c170_cod_item or None,
            "cfop": idx_c170_cfop or None,
            "vl_item": idx_c170_vl_item or None,
            "vl_icms_st": idx_c170_vl_icms_st or None,
            "ano": idx_c170_ano or None,
        }

        mapa_c175 = {
            "cfop": idx_c175_cfop or None,
            "vl_operacao": idx_c175_vl_operacao or None,
            "vl_icms_st": idx_c175_vl_icms_st or None,
            "ano": idx_c175_ano or None,
        }

        mapa_e316 = {
            "uf": idx_e316_uf or None,
            "vl_or": idx_e316_vl_or or None,
            "vl_difal": idx_e316_vl_difal or None,
            "ano": idx_e316_ano or None,
        }

        df_c170 = preparar_c170(df_c170_raw, mapa_c170)
        df_c175 = preparar_c175(df_c175_raw, mapa_c175)
        df_e316 = preparar_e316(df_e316_raw, mapa_e316)

        st.subheader("Estatísticas do arquivo")
        a1, a2, a3 = st.columns(3)
        a1.metric("Qtd. registros C170", f"{len(df_c170):,}".replace(",", "."))
        a2.metric("Qtd. registros C175", f"{len(df_c175):,}".replace(",", "."))
        a3.metric("Qtd. registros E316", f"{len(df_e316):,}".replace(",", "."))

        bases = resumir_bases(df_c170, df_c175, df_e316)

        resultado = calcular_creditos_totais(
            base_original=bases["base_original"],
            icms_st=bases["icms_st_total"],
            icms_difal=bases["icms_difal_total"],
            regime=regime,
            aliquota_pis=aliquota_pis,
            aliquota_cofins=aliquota_cofins,
        )

        st.subheader("Resumo geral")

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Base original", f"R$ {resultado['base_original']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        r2.metric("ICMS ST excluído", f"R$ {resultado['icms_st_excluido']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        r3.metric("DIFAL excluído", f"R$ {resultado['icms_difal_excluido']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        r4.metric("Base ajustada", f"R$ {resultado['base_ajustada']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        r5, r6, r7 = st.columns(3)
        r5.metric("PIS a recuperar", f"R$ {resultado['pis_recuperar']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        r6.metric("COFINS a recuperar", f"R$ {resultado['cofins_recuperar']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        r7.metric("Total a recuperar", f"R$ {resultado['total_recuperar']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        st.subheader("Resumo por ano")
        df_resumo_ano = resumo_por_ano(
            df_c170=df_c170,
            df_c175=df_c175,
            df_e316=df_e316,
            regime=regime,
            aliquota_pis=aliquota_pis,
            aliquota_cofins=aliquota_cofins,
        )
        st.dataframe(df_resumo_ano, use_container_width=True)

        st.subheader("Conferência das bases")

        aba1, aba2, aba3 = st.tabs(["C170", "C175", "E316"])

        with aba1:
            st.dataframe(df_c170.head(1000), use_container_width=True)
        with aba2:
            st.dataframe(df_c175.head(1000), use_container_width=True)
        with aba3:
            st.dataframe(df_e316.head(1000), use_container_width=True)

        arquivo_excel = gerar_excel_resumo(
            df_resumo_ano=df_resumo_ano,
            df_c170=df_c170.head(50000),
            df_c175=df_c175.head(50000),
            df_e316=df_e316.head(50000),
        )

        st.download_button(
            label="📥 Baixar resumo em Excel",
            data=arquivo_excel,
            file_name="resumo_apuracao_sped.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")