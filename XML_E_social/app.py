import pandas as pd
import streamlit as st

from modules.auditoria import (
    gerar_excel_saida,
    gerar_resumo_execucao,
    preparar_pacote_analitico,
)
from modules.processador_zip import processar_zip_esocial
from utils.helpers import decimal_br


st.set_page_config(
    page_title="Auditoria CPP indevida — eSocial",
    layout="wide",
)

st.title("Auditoria de CPP sobre verbas indenizatórias — eSocial")
st.caption(
    "Versão 3: leitura automática do ZIP original, triagem de CPP potencialmente indevida, rubricas sem S-1010, resumo por competência e ranking por CPF."
)

with st.sidebar:
    st.header("Entrada")
    arquivo_zip = st.file_uploader(
        "Selecione o ZIP original do eSocial",
        type=["zip"],
        accept_multiple_files=False,
    )

    aliquota_cpp = st.number_input(
        "Alíquota estimada da CPP (%)",
        min_value=0.0,
        max_value=100.0,
        value=20.0,
        step=0.5,
        help="Usada apenas para estimativa inicial do valor potencialmente recolhido a maior.",
    )

    st.markdown("---")
    st.subheader("Eventos usados")
    st.write("- S-1010 — rubricas")
    st.write("- S-1200 — remuneração")
    st.write("- S-3000 — exclusões")
    st.write("- S-5001 — apoio por trabalhador")
    st.write("- S-5011 — base patronal consolidada")

    st.markdown("---")
    if st.button("Resetar aplicação", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


@st.cache_data(show_spinner=False)
def executar_processamento(zip_bytes: bytes):
    return processar_zip_esocial(zip_bytes)


if not arquivo_zip:
    st.info(
        "Envie o ZIP original do eSocial. O app localiza automaticamente os XMLs relevantes, inclusive em subpastas e ZIP dentro de ZIP."
    )
    st.markdown(
        """
### O que esta versao entrega
- leitura automatica do ZIP original do eSocial;
- triagem de rubricas com `codIncCP = 00`;
- aba de rubricas do S-1200 sem correspondencia no S-1010;
- resumo por competencia;
- ranking por CPF/matricula;
- estimativa inicial da CPP potencialmente recolhida a maior.
        """
    )
    st.stop()

zip_bytes = arquivo_zip.getvalue()

with st.spinner("Processando ZIP original do eSocial..."):
    resultado = executar_processamento(zip_bytes)


df_inventario = resultado.get("inventario", pd.DataFrame())
df_rubricas = resultado.get("rubricas", pd.DataFrame())
df_exclusoes = resultado.get("exclusoes", pd.DataFrame())
df_remun = resultado.get("remuneracoes", pd.DataFrame())
df_bases_trab = resultado.get("bases_trabalhador", pd.DataFrame())
df_bases_contrib = resultado.get("bases_contribuicao", pd.DataFrame())
df_erros = resultado.get("erros_xml", pd.DataFrame())
df_layout = resultado.get("layout_check", pd.DataFrame())

with st.spinner("Montando painéis analíticos..."):
    df_auditoria, df_sem_cadastro, df_competencia, df_ranking = preparar_pacote_analitico(
        df_rubricas=df_rubricas,
        df_remun=df_remun,
        df_bases_trabalhador=df_bases_trab,
        df_bases_contribuicao=df_bases_contrib,
        aliquota_cpp_padrao=float(aliquota_cpp),
    )
    df_resumo_execucao = gerar_resumo_execucao(
        df_rubricas=df_rubricas,
        df_remun=df_remun,
        df_auditoria=df_auditoria,
        df_sem_cadastro=df_sem_cadastro,
    )


col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Arquivos inventariados", f"{len(df_inventario):,}".replace(",", "."))
with col2:
    alto = int((df_auditoria["grau_risco"] == "ALTO").sum()) if not df_auditoria.empty else 0
    st.metric("Riscos altos", f"{alto:,}".replace(",", "."))
with col3:
    sem_s1010 = len(df_sem_cadastro)
    st.metric("Rubricas sem S-1010", f"{sem_s1010:,}".replace(",", "."))
with col4:
    total_cpp = float(pd.to_numeric(df_auditoria.get("cpp_potencial_estimada", 0.0), errors="coerce").fillna(0.0).sum()) if not df_auditoria.empty else 0.0
    st.metric("CPP potencial estimada", f"R$ {decimal_br(total_cpp)}")

st.markdown("## Resumo executivo")
if df_resumo_execucao.empty:
    st.warning("Nao foi possivel montar o resumo executivo.")
else:
    st.dataframe(df_resumo_execucao, use_container_width=True, hide_index=True)

st.markdown("## Resumo por competencia")
if df_competencia.empty:
    st.warning("Sem linhas suficientes para resumir por competencia.")
else:
    st.dataframe(df_competencia, use_container_width=True, hide_index=True)

st.markdown("## Ranking por CPF / matricula")
if df_ranking.empty:
    st.warning("Sem linhas suficientes para montar ranking.")
else:
    st.dataframe(df_ranking, use_container_width=True, hide_index=True)

st.markdown("## Rubricas do S-1200 sem correspondencia no S-1010")
if df_sem_cadastro.empty:
    st.success("Nenhuma rubrica sem cadastro S-1010 foi localizada no cruzamento atual.")
else:
    st.dataframe(df_sem_cadastro, use_container_width=True, hide_index=True)

st.markdown("## Painel de auditoria")
if df_auditoria.empty:
    st.warning(
        "Nenhuma sinalizacao foi encontrada no cruzamento inicial. Isso pode significar ausencia de rubricas com codIncCP=00, base patronal nao compativel no recorte atual ou necessidade de refino adicional."
    )
else:
    c1, c2, c3 = st.columns(3)
    total_rubricas = float(pd.to_numeric(df_auditoria["valor_rubrica"], errors="coerce").fillna(0.0).sum())
    total_sinalizado = float(pd.to_numeric(df_auditoria["valor_sinalizado"], errors="coerce").fillna(0.0).sum())
    c1.metric("Total de rubricas nao incidentes", f"R$ {decimal_br(total_rubricas)}")
    c2.metric("Total sinalizado", f"R$ {decimal_br(total_sinalizado)}")
    c3.metric("Linhas de risco", str(int(df_auditoria["grau_risco"].isin(["ALTO", "MEDIO"]).sum())))

    filtro_risco = st.selectbox("Filtrar por grau de risco", ["Todos", "ALTO", "MEDIO", "BAIXO"], index=0)
    df_view = df_auditoria.copy()
    if filtro_risco != "Todos":
        df_view = df_view[df_view["grau_risco"] == filtro_risco].copy()
    st.dataframe(df_view, use_container_width=True, hide_index=True)


tabs = st.tabs([
    "Inventario",
    "Checagem layout",
    "Rubricas S-1010",
    "Remuneracao S-1200",
    "Bases S-5001",
    "Bases S-5011",
    "Exclusoes S-3000",
    "Erros XML",
])

with tabs[0]:
    st.dataframe(df_inventario, use_container_width=True, hide_index=True)
with tabs[1]:
    st.dataframe(df_layout, use_container_width=True, hide_index=True)
with tabs[2]:
    st.dataframe(df_rubricas, use_container_width=True, hide_index=True)
with tabs[3]:
    st.dataframe(df_remun, use_container_width=True, hide_index=True)
with tabs[4]:
    st.dataframe(df_bases_trab, use_container_width=True, hide_index=True)
with tabs[5]:
    st.dataframe(df_bases_contrib, use_container_width=True, hide_index=True)
with tabs[6]:
    st.dataframe(df_exclusoes, use_container_width=True, hide_index=True)
with tabs[7]:
    st.dataframe(df_erros, use_container_width=True, hide_index=True)

st.markdown("## Exportacao")
excel_bytes = gerar_excel_saida(
    df_inventario=df_inventario,
    df_rubricas=df_rubricas,
    df_exclusoes=df_exclusoes,
    df_remun=df_remun,
    df_bases_trabalhador=df_bases_trab,
    df_bases_contribuicao=df_bases_contrib,
    df_auditoria=df_auditoria,
    df_erros=df_erros,
    df_layout=df_layout,
    df_sem_cadastro=df_sem_cadastro,
    df_competencia=df_competencia,
    df_ranking_cpf=df_ranking,
    df_resumo_execucao=df_resumo_execucao,
)

st.download_button(
    label="Baixar Excel da auditoria",
    data=excel_bytes,
    file_name="auditoria_cpp_esocial_v3.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
