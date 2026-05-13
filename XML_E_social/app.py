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
    "Versão 6.6: relatório de incidência CP, seleção estável por checklist e resumo de competência em matriz por rubrica."
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
- uma aba separada para **levantamento interativo de verbas**;
- seleção múltipla, filtros e cálculo estimado de CPP;
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
df_empresa = resultado.get("empresa", pd.DataFrame())


def formatar_cnpj(cnpj: str) -> str:
    cnpj = "" if pd.isna(cnpj) else str(cnpj)
    cnpj = "".join(ch for ch in cnpj if ch.isdigit())
    if len(cnpj) == 14:
        return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
    return cnpj


def empresa_principal(df: pd.DataFrame) -> tuple[str, str]:
    if df.empty:
        return "", ""
    base = df.copy()
    if "nome_empresa" not in base.columns:
        base["nome_empresa"] = ""
    if "cnpj_empregador" not in base.columns:
        base["cnpj_empregador"] = ""
    base["tem_nome"] = base["nome_empresa"].fillna("").astype(str).str.strip().ne("")
    base = base.sort_values(["tem_nome"], ascending=False)
    linha = base.iloc[0]
    return str(linha.get("nome_empresa", "") or ""), formatar_cnpj(linha.get("cnpj_empregador", ""))


nome_empresa, cnpj_empresa = empresa_principal(df_empresa)

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

aba_relatorio, aba_levantamento = st.tabs([
    "Relatório de Incidência CP",
    "Levantamento de Verbas",
])

df_levantamento_export = pd.DataFrame()

if nome_empresa or cnpj_empresa:
    st.info(f"Empresa: {nome_empresa or 'Nome não localizado'} | CNPJ: {cnpj_empresa or 'CNPJ não localizado'}")

with aba_relatorio:
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

with aba_levantamento:
    st.markdown("## Levantamento de verbas")
    st.caption("Selecione rubricas já lidas no S-1200 e cruzadas com o S-1010 para calcular valores e estimar CPP.")

    if df_movimentos_cp.empty:
        st.warning("Sem movimentos do S-1200 para montar levantamento de verbas.")
    else:
        l1, l2, l3, l4 = st.columns(4)
        status_ops = ["Todos"] + sorted(df_movimentos_cp["status_cp"].dropna().unique().tolist())
        carater_ops = ["Todos"] + sorted(df_movimentos_cp["carater_verba"].dropna().unique().tolist())
        tipo_ops = ["Todos"] + sorted(df_movimentos_cp["tipo_verba"].dropna().unique().tolist())
        cp_ops = ["Todos"] + sorted(df_movimentos_cp["cod_inc_cp"].fillna("").astype(str).replace("", "Sem S-1010").unique().tolist())

        status_lev = l1.selectbox("Status CP", status_ops, index=status_ops.index("Incide CP") if "Incide CP" in status_ops else 0, key="lev_status_cp")
        carater_lev = l2.selectbox("Caráter", carater_ops, key="lev_carater")
        tipo_lev = l3.selectbox("Tipo", tipo_ops, key="lev_tipo")
        cp_lev = l4.selectbox("codIncCP", cp_ops, key="lev_codinc")

        l5, l6, l7 = st.columns(3)
        competencias = sorted(df_movimentos_cp["per_apur"].dropna().astype(str).unique().tolist()) if "per_apur" in df_movimentos_cp.columns else []
        comp_lev = l5.multiselect("Competências", options=competencias, default=[], key="lev_comp")
        aliquota_lev = l6.number_input("Alíquota estimada CPP (%)", min_value=0.0, max_value=100.0, value=20.0, step=0.5, key="lev_aliquota")
        positivos_lev = l7.checkbox("Apenas valores positivos", value=True, key="lev_positivos")

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
                .sort_values(["dsc_rubr", "cod_rubr"], ascending=[True, True])
            )
            df_opts["chave_rubrica"] = (
                df_opts["cod_rubr"].fillna("").astype(str)
                + "||"
                + df_opts["ide_tab_rubr"].fillna("").astype(str)
            )

            if "lev_chaves_rubricas_selecionadas" not in st.session_state:
                st.session_state["lev_chaves_rubricas_selecionadas"] = []

            st.markdown("### Seleção de rubricas")
            busca_lev = st.text_input(
                "Buscar rubrica por código ou descrição",
                value="",
                key="lev_busca_rubrica",
            )

            df_opts_busca = df_opts.copy()
            if busca_lev.strip():
                termo = busca_lev.strip().lower()
                mascara_busca = (
                    df_opts_busca["cod_rubr"].fillna("").astype(str).str.lower().str.contains(termo, na=False)
                    | df_opts_busca["dsc_rubr"].fillna("").astype(str).str.lower().str.contains(termo, na=False)
                    | df_opts_busca["cod_inc_cp"].fillna("").astype(str).str.lower().str.contains(termo, na=False)
                    | df_opts_busca["carater_verba"].fillna("").astype(str).str.lower().str.contains(termo, na=False)
                )
                df_opts_busca = df_opts_busca[mascara_busca].copy()

            b1, b2, b3, b4 = st.columns([1.4, 1.4, 0.8, 1.4])
            chaves_resultado = set(df_opts_busca["chave_rubrica"].astype(str).tolist())
            chaves_filtradas = set(df_opts["chave_rubrica"].astype(str).tolist())
            chaves_atuais = set(st.session_state["lev_chaves_rubricas_selecionadas"])

            if b1.button("Selecionar resultado da busca", use_container_width=True, key="lev_btn_sel_busca"):
                st.session_state["lev_chaves_rubricas_selecionadas"] = sorted(chaves_atuais | chaves_resultado)
                st.rerun()
            if b2.button("Limpar resultado da busca", use_container_width=True, key="lev_btn_limpa_busca"):
                st.session_state["lev_chaves_rubricas_selecionadas"] = sorted(chaves_atuais - chaves_resultado)
                st.rerun()
            if b3.button("Limpar tudo", use_container_width=True, key="lev_btn_limpa_tudo"):
                st.session_state["lev_chaves_rubricas_selecionadas"] = []
                st.rerun()
            if b4.button("Selecionar tudo filtrado", use_container_width=True, key="lev_btn_sel_filtrado"):
                st.session_state["lev_chaves_rubricas_selecionadas"] = sorted(chaves_atuais | chaves_filtradas)
                st.rerun()

            df_editor = df_opts_busca[[
                "chave_rubrica",
                "cod_rubr",
                "dsc_rubr",
                "cod_inc_cp",
                "status_cp",
                "carater_verba",
                "tipo_verba",
                "valor_total",
                "qtd_lancamentos",
                "qtd_cpfs",
            ]].copy()
            selecionadas = set(st.session_state["lev_chaves_rubricas_selecionadas"])
            df_editor.insert(0, "Selecionar", df_editor["chave_rubrica"].astype(str).isin(selecionadas))
            df_editor = df_editor.rename(columns={
                "cod_rubr": "codRubr",
                "dsc_rubr": "Descrição",
                "cod_inc_cp": "codIncCP",
                "status_cp": "Status CP",
                "carater_verba": "Caráter",
                "tipo_verba": "Tipo",
                "valor_total": "Valor total",
                "qtd_lancamentos": "Lançamentos",
                "qtd_cpfs": "CPFs",
            })

            with st.form("form_selecao_rubricas_levantamento"):
                df_editado = st.data_editor(
                    df_editor.drop(columns=["chave_rubrica"]),
                    use_container_width=True,
                    hide_index=True,
                    height=420,
                    disabled=["codRubr", "Descrição", "codIncCP", "Status CP", "Caráter", "Tipo", "Valor total", "Lançamentos", "CPFs"],
                    column_config={
                        "Selecionar": st.column_config.CheckboxColumn("Selecionar"),
                        "Valor total": st.column_config.NumberColumn("Valor total", format="R$ %.2f"),
                    },
                    key="lev_editor_rubricas",
                )
                aplicar_selecao = st.form_submit_button("Aplicar seleção", use_container_width=True)

            if aplicar_selecao:
                novas_resultado = set(df_opts_busca.loc[df_editado["Selecionar"].fillna(False).tolist(), "chave_rubrica"].astype(str).tolist())
                fora_resultado = set(st.session_state["lev_chaves_rubricas_selecionadas"]) - chaves_resultado
                st.session_state["lev_chaves_rubricas_selecionadas"] = sorted(fora_resultado | novas_resultado)
                st.rerun()

            chaves_selecionadas = set(st.session_state["lev_chaves_rubricas_selecionadas"])
            st.caption(f"Rubricas selecionadas: {len(chaves_selecionadas)}. Se nenhuma rubrica for selecionada, o cálculo usa todas as rubricas filtradas.")

            df_levantamento = df_base_lev.copy()
            df_levantamento["chave_rubrica"] = (
                df_levantamento["cod_rubr"].fillna("").astype(str)
                + "||"
                + df_levantamento["ide_tab_rubr"].fillna("").astype(str)
            )
            if chaves_selecionadas:
                df_levantamento = df_levantamento[df_levantamento["chave_rubrica"].astype(str).isin(chaves_selecionadas)].copy()
            df_levantamento = df_levantamento.drop(columns=["chave_rubrica"], errors="ignore")

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

            df_resumo_competencia_rubrica_lev = (
                df_levantamento.groupby(["per_apur", "cod_rubr", "dsc_rubr", "cod_inc_cp", "status_cp", "carater_verba", "tipo_verba"], dropna=False, as_index=False)
                .agg(valor_total=("vr_rubr", "sum"), qtd_lancamentos=("vr_rubr", "size"), qtd_cpfs=("cpf", "nunique"))
                .sort_values(["per_apur", "valor_total"], ascending=[True, False])
            )
            df_resumo_competencia_rubrica_lev["cpp_estimado"] = pd.to_numeric(df_resumo_competencia_rubrica_lev["valor_total"], errors="coerce").fillna(0) * (float(aliquota_lev) / 100.0)

            # Resumo em matriz: período de apuração na coluna A e uma coluna para cada rubrica selecionada.
            # Esse é o formato usado para facilitar conferência mensal e copiar para planilhas de levantamento.
            df_matriz_competencia = df_levantamento.copy()
            df_matriz_competencia["rubrica_resumo"] = (
                df_matriz_competencia["cod_rubr"].fillna("").astype(str).str.strip()
                + " - "
                + df_matriz_competencia["dsc_rubr"].fillna("").astype(str).str.strip()
            ).str.strip(" -")
            df_resumo_competencia_lev = (
                df_matriz_competencia.pivot_table(
                    index="per_apur",
                    columns="rubrica_resumo",
                    values="vr_rubr",
                    aggfunc="sum",
                    fill_value=0,
                )
                .reset_index()
                .rename(columns={"per_apur": "Periodo de apuracao"})
            )
            colunas_rubricas = [col for col in df_resumo_competencia_lev.columns if col != "Periodo de apuracao"]
            if colunas_rubricas:
                df_resumo_competencia_lev["Total"] = df_resumo_competencia_lev[colunas_rubricas].sum(axis=1)
                df_resumo_competencia_lev["CPP estimada"] = df_resumo_competencia_lev["Total"] * (float(aliquota_lev) / 100.0)
            else:
                df_resumo_competencia_lev["Total"] = 0.0
                df_resumo_competencia_lev["CPP estimada"] = 0.0
            df_resumo_competencia_lev = df_resumo_competencia_lev.sort_values("Periodo de apuracao")

            st.markdown("### Resumo das rubricas levantadas")
            st.dataframe(df_resumo_lev, use_container_width=True, hide_index=True)

            st.markdown("### Resumo por competência")
            st.caption("Período de apuração na primeira coluna e rubricas selecionadas nas demais colunas.")
            st.dataframe(df_resumo_competencia_lev, use_container_width=True, hide_index=True)

            with st.expander("Ver movimentos detalhados do levantamento"):
                st.dataframe(df_levantamento, use_container_width=True, hide_index=True)

            df_parametros_lev = pd.DataFrame({
                "Indicador": [
                    "Status CP filtrado",
                    "Caráter filtrado",
                    "Tipo filtrado",
                    "codIncCP filtrado",
                    "Competências filtradas",
                    "Apenas valores positivos",
                    "Alíquota CPP (%)",
                    "Total levantado",
                    "CPP estimada",
                    "Quantidade de rubricas",
                    "Quantidade de CPFs",
                ],
                "Valor": [
                    status_lev,
                    carater_lev,
                    tipo_lev,
                    cp_lev,
                    ", ".join(comp_lev) if comp_lev else "Todas",
                    "Sim" if positivos_lev else "Não",
                    float(aliquota_lev),
                    total_lev,
                    cpp_lev,
                    qtd_rubricas_lev,
                    qtd_cpfs_lev,
                ],
            })

            buffer_levantamento = io.BytesIO()
            with pd.ExcelWriter(buffer_levantamento, engine="openpyxl") as writer:
                df_empresa.to_excel(writer, index=False, sheet_name="00_empresa")
                df_parametros_lev.to_excel(writer, index=False, sheet_name="01_resumo")
                df_resumo_lev.to_excel(writer, index=False, sheet_name="02_resumo_rubricas")
                df_levantamento.to_excel(writer, index=False, sheet_name="03_movimentos")
                df_resumo_competencia_lev.to_excel(writer, index=False, sheet_name="04_resumo_competencia")
                df_resumo_competencia_rubrica_lev.to_excel(writer, index=False, sheet_name="05_competencia_rubrica")

            st.download_button(
                label="Baixar levantamento de verbas",
                data=buffer_levantamento.getvalue(),
                file_name="levantamento_verbas_cp_v6_6.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="download_levantamento_verbas",
            )

            df_levantamento_export = df_resumo_lev.copy()

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
    df_empresa=df_empresa,
)

st.download_button(
    label="Baixar relatório de incidência CP",
    data=excel_bytes,
    file_name="relatorio_incidencia_cp_esocial_v6_6.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
