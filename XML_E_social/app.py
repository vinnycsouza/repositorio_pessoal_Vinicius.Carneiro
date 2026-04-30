import io
import zipfile

import pandas as pd
import streamlit as st

from modules.auditoria import gerar_excel_saida, preparar_pacote_analitico
from modules.processador_zip import processar_zip_esocial
from utils.helpers import decimal_br


st.set_page_config(page_title="Composição da Incidência CP — eSocial", layout="wide")

st.title("Composição da Incidência CP — eSocial")
st.caption(
    "Versão 5: relatório simplificado para identificar quais rubricas têm incidência de CP e classificar o caráter da verba."
)

with st.sidebar:
    st.header("Entrada")
    arquivos_zip = st.file_uploader(
        "Selecione um ou mais ZIPs do eSocial",
        type=["zip"],
        accept_multiple_files=True,
        help="Pode enviar pacotes separados: S-1010, S-1200 e consolidado S-5001/S-5011.",
    )

    st.markdown("---")
    st.subheader("Conjunto recomendado")
    st.write("- S-1010 — tabela de rubricas / codIncCP")
    st.write("- S-1200 — movimentos de remuneração")
    st.write("- S-5001 — conferência da base por trabalhador")
    st.write("- S-5011 — apoio consolidado, quando existir")
    st.write("- S-3000 — exclusões")

    st.markdown("---")
    if st.button("Resetar aplicação", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


@st.cache_data(show_spinner=False)
def executar_processamento(pacotes: list[tuple[str, bytes]]):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome, conteudo in pacotes:
            zf.writestr(nome, conteudo)
    return processar_zip_esocial(buffer.getvalue())


if not arquivos_zip:
    st.info(
        "Envie um ou mais ZIPs do eSocial. O app localiza automaticamente os XMLs relevantes, inclusive em subpastas e ZIP dentro de ZIP."
    )
    st.markdown(
        """
### O que esta versão entrega
- relatório direto de rubricas com **incidência CP** e **sem incidência CP**;
- classificação visual por caráter da verba: remuneratório, rescisório, férias, 13º, desconto ou informativo/técnico;
- base por trabalhador para confrontar S-1200 x S-5001;
- aba específica para rubricas do S-1200 sem correspondência no S-1010;
- abas de apoio com os dados brutos extraídos.
        """
    )
    st.stop()

pacotes = [(arquivo.name, arquivo.getvalue()) for arquivo in arquivos_zip]

with st.spinner("Processando ZIP(s) do eSocial..."):
    resultado = executar_processamento(pacotes)


df_inventario = resultado.get("inventario", pd.DataFrame())
df_rubricas = resultado.get("rubricas", pd.DataFrame())
df_exclusoes = resultado.get("exclusoes", pd.DataFrame())
df_remun = resultado.get("remuneracoes", pd.DataFrame())
df_bases_trab = resultado.get("bases_trabalhador", pd.DataFrame())
df_bases_contrib = resultado.get("bases_contribuicao", pd.DataFrame())
df_erros = resultado.get("erros_xml", pd.DataFrame())
df_layout = resultado.get("layout_check", pd.DataFrame())

with st.spinner("Montando relatório de composição da incidência CP..."):
    (
        df_resumo_visual,
        df_rubricas_cp,
        df_movimentos_cp,
        df_base_trabalhador,
        df_sem_cadastro,
        df_s5001_resumo,
    ) = preparar_pacote_analitico(
        df_rubricas=df_rubricas,
        df_remun=df_remun,
        df_bases_trabalhador=df_bases_trab,
        df_bases_contribuicao=df_bases_contrib,
    )


qtd_rubricas = len(df_rubricas_cp) if not df_rubricas_cp.empty else 0
qtd_incide = int(df_rubricas_cp["status_cp"].eq("Incide CP").sum()) if not df_rubricas_cp.empty else 0
qtd_nao_incide = int(df_rubricas_cp["status_cp"].eq("Não incide CP").sum()) if not df_rubricas_cp.empty else 0
qtd_sem_s1010 = len(df_sem_cadastro) if not df_sem_cadastro.empty else 0
valor_incide = float(pd.to_numeric(df_movimentos_cp.loc[df_movimentos_cp["considerado_cp"].eq("Sim"), "vr_rubr"], errors="coerce").fillna(0).sum()) if not df_movimentos_cp.empty else 0.0

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Rubricas únicas", f"{qtd_rubricas:,}".replace(",", "."))
col2.metric("Com incidência CP", f"{qtd_incide:,}".replace(",", "."))
col3.metric("Sem incidência CP", f"{qtd_nao_incide:,}".replace(",", "."))
col4.metric("Sem S-1010", f"{qtd_sem_s1010:,}".replace(",", "."))
col5.metric("Valor com incidência CP", f"R$ {decimal_br(valor_incide)}")

st.markdown("## Resumo")
if df_resumo_visual.empty:
    st.warning("Não foi possível montar o resumo.")
else:
    st.dataframe(df_resumo_visual, use_container_width=True, hide_index=True)

st.markdown("## Rubricas por incidência CP")
if df_rubricas_cp.empty:
    st.warning("Não há rubricas do S-1200 para classificar. Confira se o ZIP contém S-1200 e S-1010 compatíveis.")
else:
    f1, f2, f3 = st.columns(3)
    status_opcoes = ["Todos"] + sorted(df_rubricas_cp["status_cp"].dropna().unique().tolist())
    carater_opcoes = ["Todos"] + sorted(df_rubricas_cp["carater_verba"].dropna().unique().tolist())
    prioridade_opcoes = ["Todos"] + sorted(df_rubricas_cp["prioridade_revisao"].dropna().unique().tolist())
    status_sel = f1.selectbox("Status CP", status_opcoes)
    carater_sel = f2.selectbox("Caráter da verba", carater_opcoes)
    prioridade_sel = f3.selectbox("Prioridade de revisão", prioridade_opcoes)

    df_view = df_rubricas_cp.copy()
    if status_sel != "Todos":
        df_view = df_view[df_view["status_cp"].eq(status_sel)]
    if carater_sel != "Todos":
        df_view = df_view[df_view["carater_verba"].eq(carater_sel)]
    if prioridade_sel != "Todos":
        df_view = df_view[df_view["prioridade_revisao"].eq(prioridade_sel)]
    st.dataframe(df_view, use_container_width=True, hide_index=True)

st.markdown("## Base por trabalhador")
if df_base_trabalhador.empty:
    st.warning("Sem dados suficientes para montar base por trabalhador.")
else:
    st.dataframe(df_base_trabalhador, use_container_width=True, hide_index=True)

st.markdown("## Rubricas sem correspondência no S-1010")
if df_sem_cadastro.empty:
    st.success("Nenhuma rubrica sem S-1010 foi localizada no cruzamento atual.")
else:
    st.dataframe(df_sem_cadastro, use_container_width=True, hide_index=True)

with st.expander("Abas de apoio / dados brutos"):
    tabs = st.tabs([
        "Movimentos CP",
        "S-1010",
        "S-1200",
        "S-5001",
        "S-5011",
        "S-3000",
        "Layout",
        "Inventário",
        "Erros",
    ])
    with tabs[0]:
        st.dataframe(df_movimentos_cp, use_container_width=True, hide_index=True)
    with tabs[1]:
        st.dataframe(df_rubricas, use_container_width=True, hide_index=True)
    with tabs[2]:
        st.dataframe(df_remun, use_container_width=True, hide_index=True)
    with tabs[3]:
        st.dataframe(df_bases_trab, use_container_width=True, hide_index=True)
    with tabs[4]:
        st.dataframe(df_bases_contrib, use_container_width=True, hide_index=True)
    with tabs[5]:
        st.dataframe(df_exclusoes, use_container_width=True, hide_index=True)
    with tabs[6]:
        st.dataframe(df_layout, use_container_width=True, hide_index=True)
    with tabs[7]:
        st.dataframe(df_inventario, use_container_width=True, hide_index=True)
    with tabs[8]:
        st.dataframe(df_erros, use_container_width=True, hide_index=True)

st.markdown("## Exportação")
excel_bytes = gerar_excel_saida(
    df_inventario=df_inventario,
    df_rubricas=df_rubricas,
    df_exclusoes=df_exclusoes,
    df_remun=df_remun,
    df_bases_trabalhador=df_bases_trab,
    df_bases_contribuicao=df_bases_contrib,
    df_erros=df_erros,
    df_layout=df_layout,
    df_resumo_visual=df_resumo_visual,
    df_rubricas_cp=df_rubricas_cp,
    df_movimentos_cp=df_movimentos_cp,
    df_base_trabalhador=df_base_trabalhador,
    df_sem_cadastro=df_sem_cadastro,
    df_s5001_resumo=df_s5001_resumo,
)

st.download_button(
    label="Baixar relatório de incidência CP",
    data=excel_bytes,
    file_name="relatorio_incidencia_cp_esocial_v5.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
