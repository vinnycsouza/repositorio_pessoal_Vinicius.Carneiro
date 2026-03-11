from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from calculos import ALIQUOTAS_PADRAO, resumo_geral, resumo_por_ano
from excel_parser import listar_abas, processar_planilha_grande
from exportacao import gerar_excel_resumo


st.set_page_config(page_title="Apurador SPED Excel Grande", layout="wide")
st.title("📊 Apurador SPED em Excel Grande")
st.caption("Cálculo em Python/Streamlit para arquivos .xlsb/.xlsx grandes, com foco em C170, C175 e E316.")

st.markdown("""
### Regras implementadas
- **Lucro Real**
  - exclusão do **ICMS ST** da base do PIS/COFINS
  - exclusão do **PIS/COFINS por dentro**
- **Lucro Presumido**
  - exclusão do **ICMS ST**
  - exclusão do **DIFAL**
  - exclusão do **PIS/COFINS por dentro**
""")

c1, c2 = st.columns([3, 1])

with c1:
    caminho_arquivo = st.text_input(
        "Caminho completo do arquivo Excel",
        placeholder=r"C:\Users\vinny\Documents\SPED\arquivo.xlsb",
    )

with c2:
    regime = st.selectbox(
        "Regime tributário",
        options=["real", "presumido"],
        format_func=lambda x: "Lucro Real" if x == "real" else "Lucro Presumido",
    )

c3, c4, c5 = st.columns(3)

with c3:
    aliquota_pis = st.number_input(
        "Alíquota PIS",
        min_value=0.0,
        max_value=1.0,
        value=float(ALIQUOTAS_PADRAO[regime]["pis"]),
        step=0.0001,
        format="%.4f",
    )

with c4:
    aliquota_cofins = st.number_input(
        "Alíquota COFINS",
        min_value=0.0,
        max_value=1.0,
        value=float(ALIQUOTAS_PADRAO[regime]["cofins"]),
        step=0.0001,
        format="%.4f",
    )

with c5:
    skiprows = st.number_input(
        "Linhas iniciais a ignorar",
        min_value=0,
        max_value=50,
        value=0,
        step=1,
        help="Use se a planilha tiver linhas acima do cabeçalho real.",
    )


def brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


if caminho_arquivo:
    caminho = Path(caminho_arquivo)

    if not caminho.exists():
        st.error("Arquivo não encontrado.")
        st.stop()

    if caminho.suffix.lower() not in {".xlsx", ".xlsb"}:
        st.error("Formato não suportado. Use .xlsx ou .xlsb.")
        st.stop()

    with st.expander("Conferir abas detectadas", expanded=False):
        try:
            abas = listar_abas(str(caminho))
            st.write(abas)
        except Exception as e:
            st.error(f"Não foi possível listar as abas: {e}")

    if st.button("Processar arquivo", type="primary"):
        barra = st.progress(0, text="Iniciando...")
        status = st.empty()

        def progresso(valor: float, texto: str):
            barra.progress(min(max(valor, 0.0), 1.0), text=texto)
            status.info(texto)

        try:
            df_bases, df_resumo_abas = processar_planilha_grande(
                caminho_arquivo=str(caminho),
                skiprows=int(skiprows),
                progress_callback=progresso,
            )

            barra.progress(1.0, text="Processamento concluído.")
            status.success("Arquivo processado com sucesso.")

            st.subheader("Resumo geral")
            resultado = resumo_geral(
                df_bases=df_bases,
                regime=regime,
                aliquota_pis=aliquota_pis,
                aliquota_cofins=aliquota_cofins,
            )

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Base original", brl(resultado["base_original"]))
            m2.metric("ICMS ST excluído", brl(resultado["icms_st_excluido"]))
            m3.metric("DIFAL excluído", brl(resultado["icms_difal_excluido"]))
            m4.metric("Base ajustada", brl(resultado["base_ajustada"]))

            m5, m6, m7 = st.columns(3)
            m5.metric("PIS a recuperar", brl(resultado["pis_recuperar"]))
            m6.metric("COFINS a recuperar", brl(resultado["cofins_recuperar"]))
            m7.metric("Total a recuperar", brl(resultado["total_recuperar"]))

            st.subheader("Resumo por ano")
            df_resumo_ano = resumo_por_ano(
                df_bases=df_bases,
                regime=regime,
                aliquota_pis=aliquota_pis,
                aliquota_cofins=aliquota_cofins,
            )
            st.dataframe(df_resumo_ano, use_container_width=True)

            st.subheader("Resumo por aba")
            st.dataframe(df_resumo_abas, use_container_width=True)

            st.subheader("Conferência da base consolidada")
            st.caption("Abaixo é exibida apenas uma amostra para não pesar a interface.")
            st.dataframe(df_bases.head(1000), use_container_width=True)

            excel_saida = gerar_excel_resumo(
                df_resumo_ano=df_resumo_ano,
                df_resumo_abas=df_resumo_abas,
                df_bases_amostra=df_bases.head(5000),
            )

            st.download_button(
                label="📥 Baixar resumo em Excel",
                data=excel_saida,
                file_name="resumo_apuracao_sped.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            st.info(
                "Neste esqueleto, o C170 e o C175 estão sendo lidos com base nas colunas A, D e I; "
                "e o E316 também. Ajuste essas colunas em `excel_parser.py` conforme o layout real do seu arquivo."
            )

        except Exception as e:
            st.error(f"Erro ao processar o arquivo: {e}")