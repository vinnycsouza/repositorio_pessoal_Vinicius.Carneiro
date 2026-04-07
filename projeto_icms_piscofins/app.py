from __future__ import annotations

import pandas as pd
import streamlit as st

from core.analysis import run_analysis
from core.exporter import export_report_to_bytes
from core.io_excel import WorkbookReader
from core.normalize import normalize_icms_items, normalize_piscofins_items
from core.utils import validate_excel_path


st.set_page_config(page_title="Auditor ICMS x PIS/COFINS", layout="wide")
st.title("Auditor local — comparação entre base de ICMS e bases de PIS/COFINS")
st.caption("Projeto local para leitura por caminho de arquivos Excel convertidos do SPED.")


@st.cache_data(show_spinner=False, ttl=3600)
def carregar_itens_icms(path_str: str) -> pd.DataFrame:
    path = validate_excel_path(path_str)
    reader = WorkbookReader(path)
    df = reader.read_sheet("c170")
    return normalize_icms_items(df)


@st.cache_data(show_spinner=False, ttl=3600)
def carregar_itens_piscofins(path_str: str) -> pd.DataFrame:
    path = validate_excel_path(path_str)
    reader = WorkbookReader(path)
    df = reader.read_sheet("c170")
    return normalize_piscofins_items(df)


def fmt_int(value) -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except Exception:
        return "0"


def contar_preenchidos(df: pd.DataFrame, col: str) -> int:
    if col not in df.columns:
        return 0
    serie = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return int((serie != 0).sum())


def encontrar_coluna_status(df: pd.DataFrame) -> str | None:
    candidatos = [
        "Status da Análise",
        "Status da Analise",
        "status_analise",
        "status da análise",
        "status da analise",
    ]
    for c in candidatos:
        if c in df.columns:
            return c
    return None


def montar_diagnostico_relatorio(report: pd.DataFrame) -> dict:
    diagnostico = {
        "linhas_relatorio": len(report),
        "base_icms_final_preenchida": contar_preenchidos(report, "Base de ICMS Final"),
        "valor_icms_final_preenchido": contar_preenchidos(report, "Valor de ICMS Final"),
        "base_pis_preenchida": contar_preenchidos(report, "Base de PIS Informada"),
        "base_cofins_preenchida": contar_preenchidos(report, "Base de COFINS Informada"),
        "join_sim": 0,
        "join_nao": 0,
    }

    if "Cruzou com ICMS/IPI" in report.columns:
        diagnostico["join_sim"] = int((report["Cruzou com ICMS/IPI"].astype(str) == "Sim").sum())
        diagnostico["join_nao"] = int((report["Cruzou com ICMS/IPI"].astype(str) == "Não").sum())

    return diagnostico


with st.sidebar:
    st.header("Parâmetros")

    tolerancia = st.number_input(
        "Tolerância da comparação",
        min_value=0.0,
        value=0.01,
        step=0.01,
    )

    operacoes = st.multiselect(
        "Operações para análise",
        options=["Entrada", "Saída"],
        default=["Saída"],
    )

    somente_regulares = st.checkbox(
        "Considerar apenas documentos regulares",
        value=True,
    )

    mostrar_diagnostico = st.checkbox(
        "Mostrar diagnóstico técnico",
        value=True,
    )

    st.caption("Dica: na primeira leitura arquivos grandes podem demorar alguns segundos. Nas próximas execuções, o cache ajuda a acelerar.")


st.subheader("Arquivos de entrada")
col1, col2 = st.columns(2)

with col1:
    caminho_icms = st.text_input(
        "Caminho do Excel ICMS/IPI",
        value="",
        placeholder=r"C:\Projetos\SPED\arquivo_icms_ipi.xlsx",
    )

with col2:
    caminho_pis = st.text_input(
        "Caminho do Excel PIS/COFINS",
        value="",
        placeholder=r"C:\Projetos\SPED\arquivo_pis_cofins.xlsx",
    )


if st.button("Processar arquivos", type="primary", use_container_width=True):
    try:
        progress = st.progress(0, text="Iniciando processamento...")
        status_box = st.empty()

        with st.spinner("Processando arquivos... Isso pode levar alguns segundos dependendo do tamanho."):
            status_box.info("Validando caminhos dos arquivos...")
            progress.progress(10, text="Validando caminhos...")

            validate_excel_path(caminho_icms)
            validate_excel_path(caminho_pis)

            status_box.info("Lendo SPED ICMS/IPI...")
            progress.progress(30, text="Lendo SPED ICMS/IPI...")
            df_icms = carregar_itens_icms(caminho_icms)

            status_box.info("Lendo SPED PIS/COFINS...")
            progress.progress(55, text="Lendo SPED PIS/COFINS...")
            df_pis = carregar_itens_piscofins(caminho_pis)

            st.session_state["df_icms_bruto"] = df_icms.copy()
            st.session_state["df_pis_bruto"] = df_pis.copy()

            if operacoes:
                status_box.info("Aplicando filtros de operação...")
                progress.progress(70, text="Aplicando filtros...")

                if "ind_oper_desc" in df_icms.columns:
                    df_icms = df_icms[df_icms["ind_oper_desc"].isin(operacoes)].copy()

                if "ind_oper_desc" in df_pis.columns:
                    df_pis = df_pis[df_pis["ind_oper_desc"].isin(operacoes)].copy()

            if somente_regulares and "situacao_ok" in df_pis.columns:
                df_pis = df_pis[df_pis["situacao_ok"]].copy()

            status_box.info("Cruzando dados e executando análise...")
            progress.progress(85, text="Cruzando dados e analisando...")
            report, resumo = run_analysis(
                icms_df=df_icms,
                pis_df=df_pis,
                tolerancia=tolerancia,
            )

            st.session_state["report"] = report
            st.session_state["resumo"] = resumo
            st.session_state["diagnostico"] = montar_diagnostico_relatorio(report)

            progress.progress(100, text="Finalizado.")
            status_box.success("Processamento concluído com sucesso.")

        st.success("Arquivos processados.")
    except Exception as exc:
        st.exception(exc)


if "report" in st.session_state:
    report = st.session_state["report"]
    resumo = st.session_state.get("resumo", {})
    diagnostico = st.session_state.get("diagnostico", {})
    coluna_status = encontrar_coluna_status(report)

    st.subheader("Resumo da análise")
    a, b, c, d, e = st.columns(5)

    a.metric("Itens analisados", fmt_int(resumo.get("itens_analisados", len(report))))
    b.metric("Exclusão identificada", fmt_int(resumo.get("itens_exclusao_identificada", 0)))
    c.metric("Sem indício", fmt_int(resumo.get("itens_sem_indicio", 0)))
    d.metric("Divergente / Revisar", fmt_int(resumo.get("itens_divergente_revisar", 0)))
    e.metric("Sem dados suficientes", fmt_int(resumo.get("itens_sem_dados", 0)))

    if mostrar_diagnostico:
        st.subheader("Diagnóstico técnico")
        d1, d2, d3, d4, d5, d6 = st.columns(6)

        d1.metric("Linhas no relatório", fmt_int(diagnostico.get("linhas_relatorio", len(report))))
        d2.metric("Base ICMS final", fmt_int(diagnostico.get("base_icms_final_preenchida", 0)))
        d3.metric("Valor ICMS final", fmt_int(diagnostico.get("valor_icms_final_preenchido", 0)))
        d4.metric("Base PIS", fmt_int(diagnostico.get("base_pis_preenchida", 0)))
        d5.metric("Join Sim", fmt_int(diagnostico.get("join_sim", 0)))
        d6.metric("Join Não", fmt_int(diagnostico.get("join_nao", 0)))

        with st.expander("Colunas presentes no relatório"):
            st.write(list(report.columns))

        if "df_icms_bruto" in st.session_state and "df_pis_bruto" in st.session_state:
            with st.expander("Prévia dos dados normalizados"):
                st.markdown("**ICMS/IPI normalizado**")
                st.dataframe(st.session_state["df_icms_bruto"].head(10), use_container_width=True)

                st.markdown("**PIS/COFINS normalizado**")
                st.dataframe(st.session_state["df_pis_bruto"].head(10), use_container_width=True)

    st.subheader("Itens com exclusão identificada")
    if coluna_status:
        identificadas = report[report[coluna_status] == "Exclusão identificada"].copy()
    else:
        st.warning("A coluna de status da análise não foi encontrada no relatório. Mostrando o relatório completo.")
        identificadas = report.copy()

    st.dataframe(identificadas, use_container_width=True, height=420)

    with st.expander("Ver relatório completo"):
        st.dataframe(report, use_container_width=True, height=520)

    st.subheader("Baixar relatório")

    try:
        excel_bytes = export_report_to_bytes(report, resumo)

        st.download_button(
            label="Baixar Excel do relatório",
            data=excel_bytes,
            file_name="relatorio_recuperacao_icms_piscofins.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        st.info("O arquivo é gerado apenas para download. Nada é salvo na pasta do projeto.")
    except Exception as exc:
        st.exception(exc)

else:
    st.info("Informe os caminhos dos dois arquivos e clique em Processar arquivos.")