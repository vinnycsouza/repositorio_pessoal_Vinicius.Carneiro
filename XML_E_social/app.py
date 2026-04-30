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
    "Versão 6: relatório de incidência CP + levantamento interativo de verbas com cálculo estimado."
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
- levantamento interativo de verbas com seleção múltipla, filtros e cálculo estimado;
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

st.markdown("## Levantamento de verbas")
st.caption("Selecione rubricas já lidas no S-1200 e cruzadas com o S-1010 para calcular valores e estimar CPP.")

df_levantamento_export = pd.DataFrame()
if df_movimentos_cp.empty:
    st.warning("Sem movimentos do S-1200 para montar levantamento de verbas.")
else:
    l1, l2, l3, l4 = st.columns(4)
    status_ops = ["Todos"] + sorted(df_movimentos_cp["status_cp"].dropna().unique().tolist())
    carater_ops = ["Todos"] + sorted(df_movimentos_cp["carater_verba"].dropna().unique().tolist())
    tipo_ops = ["Todos"] + sorted(df_movimentos_cp["tipo_verba"].dropna().unique().tolist())
    cp_ops = ["Todos"] + sorted(df_movimentos_cp["cod_inc_cp"].fillna("").astype(str).replace("", "Sem S-1010").unique().tolist())

    status_lev = l1.selectbox("Levantamento — Status CP", status_ops, index=status_ops.index("Incide CP") if "Incide CP" in status_ops else 0)
    carater_lev = l2.selectbox("Levantamento — Caráter", carater_ops)
    tipo_lev = l3.selectbox("Levantamento — Tipo", tipo_ops)
    cp_lev = l4.selectbox("Levantamento — codIncCP", cp_ops)

    l5, l6, l7 = st.columns(3)
    competencias = sorted(df_movimentos_cp["per_apur"].dropna().astype(str).unique().tolist()) if "per_apur" in df_movimentos_cp.columns else []
    comp_lev = l5.multiselect("Competências", options=competencias, default=[])
    aliquota_lev = l6.number_input("Alíquota estimada CPP (%)", min_value=0.0, max_value=100.0, value=20.0, step=0.5)
    positivos_lev = l7.checkbox("Apenas valores positivos", value=True)

    df_base_lev = df_movimentos_cp.copy()
    if status_lev != "Todos":
        df_base_lev = df_base_lev[df_base_lev["status_cp"].eq(status_lev)]
    if carater_lev != "Todos":
        df_base_lev = df_base_lev[df_base_lev["carater_verba"].eq(carater_lev)]
    if tipo_lev != "Todos":
        df_base_lev = df_base_lev[df_base_lev["tipo_verba"].eq(tipo_lev)]
    if cp_lev != "Todos":
        if cp_lev == "Sem S-1010":
            df_base_lev = df_base_lev[df_base_lev["cod_inc_cp"].fillna("").astype(str).eq("")]
        else:
            df_base_lev = df_base_lev[df_base_lev["cod_inc_cp"].astype(str).eq(cp_lev)]
    if comp_lev:
        df_base_lev = df_base_lev[df_base_lev["per_apur"].astype(str).isin(comp_lev)]
    if positivos_lev:
        df_base_lev = df_base_lev[pd.to_numeric(df_base_lev["vr_rubr"], errors="coerce").fillna(0) > 0]

    if df_base_lev.empty:
        st.warning("Nenhuma rubrica encontrada com os filtros selecionados.")
    else:
        df_opts = (
            df_base_lev.groupby(["cod_rubr", "ide_tab_rubr", "dsc_rubr", "cod_inc_cp", "status_cp", "carater_verba", "tipo_verba"], dropna=False, as_index=False)
            .agg(valor_total=("vr_rubr", "sum"), qtd_lancamentos=("vr_rubr", "size"), qtd_cpfs=("cpf", "nunique"))
            .sort_values("valor_total", ascending=False)
        )
        df_opts["rubrica_label"] = df_opts.apply(lambda r: f"{r['cod_rubr']} | {r['dsc_rubr']} | CP {r['cod_inc_cp'] or 'sem S-1010'} | {r['carater_verba']} | R$ {decimal_br(r['valor_total'])}", axis=1)
        mapa_label_codigo = dict(zip(df_opts["rubrica_label"], df_opts["cod_rubr"].astype(str)))
        labels = st.multiselect(
            "Selecione uma ou mais rubricas para o cálculo",
            options=df_opts["rubrica_label"].tolist(),
            help="Digite parte do código ou descrição. Se deixar vazio, o cálculo usa todas as rubricas filtradas.",
        )
        codigos = [mapa_label_codigo[label] for label in labels]
        df_levantamento = df_base_lev.copy()
        if codigos:
            df_levantamento = df_levantamento[df_levantamento["cod_rubr"].astype(str).isin(codigos)]

        total_lev = float(pd.to_numeric(df_levantamento["vr_rubr"], errors="coerce").fillna(0).sum())
        cpp_lev = total_lev * (float(aliquota_lev) / 100.0)
        qtd_rubricas_lev = df_levantamento["cod_rubr"].nunique()
        qtd_cpfs_lev = df_levantamento["cpf"].nunique() if "cpf" in df_levantamento.columns else 0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total levantado", f"R$ {decimal_br(total_lev)}")
        m2.metric("CPP estimada", f"R$ {decimal_br(cpp_lev)}")
        m3.metric("Rubricas", f"{qtd_rubricas_lev:,}".replace(",", "."))
        m4.metric("CPFs", f"{qtd_cpfs_lev:,}".replace(",", "."))

        df_resumo_lev = (
            df_levantamento.groupby(["cod_rubr", "dsc_rubr", "nat_rubr", "cod_inc_cp", "status_cp", "carater_verba", "tipo_verba"], dropna=False, as_index=False)
            .agg(valor_total=("vr_rubr", "sum"), qtd_lancamentos=("vr_rubr", "size"), qtd_cpfs=("cpf", "nunique"), primeira_competencia=("per_apur", "min"), ultima_competencia=("per_apur", "max"))
            .sort_values("valor_total", ascending=False)
        )
        df_resumo_lev["cpp_estimado"] = pd.to_numeric(df_resumo_lev["valor_total"], errors="coerce").fillna(0) * (float(aliquota_lev) / 100.0)
        st.markdown("### Resumo das rubricas levantadas")
        st.dataframe(df_resumo_lev, use_container_width=True, hide_index=True)
        with st.expander("Ver movimentos detalhados do levantamento"):
            st.dataframe(df_levantamento, use_container_width=True, hide_index=True)
        df_levantamento_export = df_resumo_lev.copy()

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
    df_levantamento=df_levantamento_export,
)

st.download_button(
    label="Baixar relatório de incidência CP",
    data=excel_bytes,
    file_name="relatorio_incidencia_cp_esocial_v6.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
