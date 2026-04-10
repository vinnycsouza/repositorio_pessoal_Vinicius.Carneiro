import streamlit as st
import pandas as pd

from modules.processador_zip import processar_zip_esocial
from modules.auditoria import gerar_auditoria
from utils.helpers import decimal_br

# =========================================================
# CONFIG
# =========================================================
st.set_page_config(
    page_title="Auditoria CPP indevida — eSocial",
    layout="wide",
)

st.title("Auditoria de CPP sobre verbas indenizatórias — eSocial")

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.header("Upload")

    arquivo_zip = st.file_uploader(
        "Selecione o ZIP do eSocial",
        type=["zip"],
        accept_multiple_files=False,
    )

    st.markdown("---")

    if st.button("Resetar aplicação", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# =========================================================
# SEM ARQUIVO
# =========================================================
if not arquivo_zip:
    st.info("Envie o ZIP do eSocial para iniciar a análise.")
    st.stop()

# =========================================================
# PROCESSAMENTO
# =========================================================
zip_bytes = arquivo_zip.getvalue()

with st.spinner("Processando ZIP..."):
    resultado = processar_zip_esocial(zip_bytes)

# =========================================================
# EXTRAÇÃO SEGURA DAS CHAVES
# =========================================================
df_inventario = resultado.get("inventario", pd.DataFrame())
df_rubricas = resultado.get("rubricas", pd.DataFrame())
df_exclusoes = resultado.get("exclusoes", pd.DataFrame())
df_remun = resultado.get("remuneracoes", pd.DataFrame())
df_bases = resultado.get("bases", pd.DataFrame())
df_bases_consolidadas = resultado.get("bases_consolidadas", pd.DataFrame())
df_erros = resultado.get("erros_xml", pd.DataFrame())
df_checagem = resultado.get("checagem_layout", pd.DataFrame())

# =========================================================
# AUDITORIA
# =========================================================
with st.spinner("Gerando auditoria..."):
    df_auditoria = gerar_auditoria(
        df_rubricas=df_rubricas,
        df_remun=df_remun,
        df_bases=df_bases,
        df_bases_consolidadas=df_bases_consolidadas,
    )

# =========================================================
# KPIs
# =========================================================
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Arquivos", len(df_inventario))

with col2:
    st.metric("Rubricas", len(df_rubricas))

with col3:
    st.metric("Remunerações", len(df_remun))

with col4:
    qtd_risco = 0
    if not df_auditoria.empty:
        qtd_risco = (df_auditoria["grau_risco"] == "ALTO").sum()
    st.metric("Riscos", int(qtd_risco))

# =========================================================
# RESUMO
# =========================================================
st.markdown("## Resumo dos eventos")

if not df_inventario.empty:
    resumo = (
        df_inventario.groupby("tipo")
        .size()
        .reset_index(name="qtd")
        .sort_values("qtd", ascending=False)
    )
    st.dataframe(resumo, use_container_width=True)

# =========================================================
# AUDITORIA
# =========================================================
st.markdown("## Auditoria CPP")

if df_auditoria.empty:
    st.warning("Nenhuma inconsistência encontrada ou dados insuficientes.")
else:
    total = df_auditoria["valor_rubrica"].sum()
    sinalizado = df_auditoria["valor_sinalizado"].sum()

    c1, c2 = st.columns(2)
    c1.metric("Total analisado", f"R$ {decimal_br(total)}")
    c2.metric("Total sinalizado", f"R$ {decimal_br(sinalizado)}")

    filtro = st.selectbox(
        "Filtro de risco",
        ["Todos", "ALTO", "BAIXO"],
    )

    df_view = df_auditoria.copy()

    if filtro != "Todos":
        df_view = df_view[df_view["grau_risco"] == filtro]

    st.dataframe(df_view, use_container_width=True)

# =========================================================
# ABAS DETALHADAS
# =========================================================
tabs = st.tabs([
    "Inventário",
    "Rubricas S-1010",
    "Remuneração S-1200",
    "Bases S-5001",
    "Bases S-5011",
    "Exclusões",
    "Checagem Layout",
    "Erros",
])

with tabs[0]:
    st.dataframe(df_inventario, use_container_width=True)

with tabs[1]:
    st.dataframe(df_rubricas, use_container_width=True)

with tabs[2]:
    st.dataframe(df_remun, use_container_width=True)

with tabs[3]:
    st.dataframe(df_bases, use_container_width=True)

with tabs[4]:
    st.dataframe(df_bases_consolidadas, use_container_width=True)

with tabs[5]:
    st.dataframe(df_exclusoes, use_container_width=True)

with tabs[6]:
    st.dataframe(df_checagem, use_container_width=True)

with tabs[7]:
    st.dataframe(df_erros, use_container_width=True)