import io
import zipfile

import pandas as pd
import streamlit as st

from modules.auditoria import (
    gerar_excel_saida,
    gerar_resumo_execucao,
    preparar_pacote_analitico,
)
from modules.processador_zip import processar_zip_esocial
from utils.helpers import decimal_br


st.set_page_config(page_title="Auditoria CPP indevida — eSocial", layout="wide")

st.title("Auditoria de CPP sobre verbas indenizatórias — eSocial")
st.caption(
    "Versão 4: múltiplos ZIPs, extração detalhada do S-5001 por tpValor, composição teórica pelo S-1200/S-1010 e conciliação com a base oficial."
)

with st.sidebar:
    st.header("Entrada")
    arquivos_zip = st.file_uploader(
        "Selecione um ou mais ZIPs do eSocial",
        type=["zip"],
        accept_multiple_files=True,
        help="Pode enviar pacotes separados: tabelas S-1010, remunerações S-1200 e consolidado S-5001/S-5011.",
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
    st.write("- S-1010 — rubricas / incidência CP")
    st.write("- S-1200 — remuneração / itens de folha")
    st.write("- S-5001 — base oficial por trabalhador")
    st.write("- S-5011 — base patronal consolidada, quando existir")
    st.write("- S-3000 — exclusões")

    st.markdown("---")
    if st.button("Resetar aplicação", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


@st.cache_data(show_spinner=False)
def executar_processamento(pacotes: list[tuple[str, bytes]]):
    """Monta um ZIP-mãe em memória; o processador já lê ZIP dentro de ZIP."""
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
- leitura automática de um ou mais ZIPs do eSocial;
- cruzamento S-1010 x S-1200;
- leitura detalhada do S-5001 por trabalhador, lotação, categoria e `tpValor`;
- conciliação entre composição teórica do S-1200 e base oficial do S-5001;
- aba de rubricas do S-1200 sem correspondência no S-1010;
- estimativa inicial da CPP potencialmente recolhida a maior.
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

with st.spinner("Montando painéis analíticos..."):
    (
        df_auditoria,
        df_sem_cadastro,
        df_competencia,
        df_ranking,
        df_composicao_teorica,
        df_conciliacao,
        df_s5001_resumo,
    ) = preparar_pacote_analitico(
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
        df_bases_trabalhador=df_bases_trab,
    )


col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Arquivos inventariados", f"{len(df_inventario):,}".replace(",", "."))
with col2:
    alto = int((df_auditoria["grau_risco"] == "ALTO").sum()) if not df_auditoria.empty else 0
    st.metric("Riscos altos", f"{alto:,}".replace(",", "."))
with col3:
    st.metric("Rubricas sem S-1010", f"{len(df_sem_cadastro):,}".replace(",", "."))
with col4:
    st.metric("Linhas S-5001", f"{len(df_bases_trab):,}".replace(",", "."))
with col5:
    total_cpp = float(pd.to_numeric(df_auditoria.get("cpp_potencial_estimada", 0.0), errors="coerce").fillna(0.0).sum()) if not df_auditoria.empty else 0.0
    st.metric("CPP potencial estimada", f"R$ {decimal_br(total_cpp)}")

st.markdown("## Resumo executivo")
if df_resumo_execucao.empty:
    st.warning("Não foi possível montar o resumo executivo.")
else:
    st.dataframe(df_resumo_execucao, use_container_width=True, hide_index=True)

st.markdown("## Conciliação S-1200 x S-5001")
if df_conciliacao.empty:
    st.warning("Sem dados suficientes para conciliar S-1200 x S-5001.")
else:
    st.dataframe(df_conciliacao, use_container_width=True, hide_index=True)

st.markdown("## Resumo por competência")
if df_competencia.empty:
    st.warning("Sem linhas suficientes para resumir por competência.")
else:
    st.dataframe(df_competencia, use_container_width=True, hide_index=True)

st.markdown("## Ranking por CPF / matrícula")
if df_ranking.empty:
    st.warning("Sem linhas suficientes para montar ranking.")
else:
    st.dataframe(df_ranking, use_container_width=True, hide_index=True)

st.markdown("## Rubricas do S-1200 sem correspondência no S-1010")
if df_sem_cadastro.empty:
    st.success("Nenhuma rubrica sem cadastro S-1010 foi localizada no cruzamento atual.")
else:
    st.dataframe(df_sem_cadastro, use_container_width=True, hide_index=True)

st.markdown("## Painel de auditoria")
if df_auditoria.empty:
    st.warning(
        "Nenhuma sinalização foi encontrada no cruzamento inicial. Confira se foram enviados S-1010, S-1200 e S-5001 do mesmo período/empresa."
    )
else:
    c1, c2, c3 = st.columns(3)
    total_rubricas = float(pd.to_numeric(df_auditoria["valor_rubrica"], errors="coerce").fillna(0.0).sum())
    total_sinalizado = float(pd.to_numeric(df_auditoria["valor_sinalizado"], errors="coerce").fillna(0.0).sum())
    c1.metric("Total de rubricas não incidentes", f"R$ {decimal_br(total_rubricas)}")
    c2.metric("Total sinalizado", f"R$ {decimal_br(total_sinalizado)}")
    c3.metric("Linhas de risco", str(int(df_auditoria["grau_risco"].isin(["ALTO", "MEDIO"]).sum())))

    filtro_risco = st.selectbox("Filtrar por grau de risco", ["Todos", "ALTO", "MEDIO", "BAIXO"], index=0)
    df_view = df_auditoria.copy()
    if filtro_risco != "Todos":
        df_view = df_view[df_view["grau_risco"] == filtro_risco].copy()
    st.dataframe(df_view, use_container_width=True, hide_index=True)


tabs = st.tabs([
    "Inventário",
    "Checagem layout",
    "Rubricas S-1010",
    "Remuneração S-1200",
    "Bases S-5001 detalhe",
    "Resumo S-5001 tpValor",
    "Composição teórica",
    "Bases S-5011",
    "Exclusões S-3000",
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
    st.dataframe(df_s5001_resumo, use_container_width=True, hide_index=True)
with tabs[6]:
    st.dataframe(df_composicao_teorica, use_container_width=True, hide_index=True)
with tabs[7]:
    st.dataframe(df_bases_contrib, use_container_width=True, hide_index=True)
with tabs[8]:
    st.dataframe(df_exclusoes, use_container_width=True, hide_index=True)
with tabs[9]:
    st.dataframe(df_erros, use_container_width=True, hide_index=True)

st.markdown("## Exportação")
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
    df_composicao_teorica=df_composicao_teorica,
    df_conciliacao=df_conciliacao,
    df_s5001_resumo=df_s5001_resumo,
)

st.download_button(
    label="Baixar Excel da auditoria",
    data=excel_bytes,
    file_name="auditoria_cpp_esocial_v4.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
