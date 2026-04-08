from __future__ import annotations

import pandas as pd
import streamlit as st

from core.analysis import run_analysis
from core.exporter import export_report_to_bytes
from core.io_excel import WorkbookReader
from core.normalize import normalize_icms_items, normalize_piscofins_items
from core.utils import validate_excel_path


st.set_page_config(page_title="Auditor ICMS x PIS/COFINS", layout="wide")
st.title("Auditor local — exclusão de PIS/COFINS da base de cálculo do ICMS")
st.caption(
    "Processamento local otimizado para arquivos grandes. "
    "A tela mostra apenas amostras; o detalhamento completo vai no Excel."
)

# =========================
# Reset da aplicação
# =========================
col_reset_1, col_reset_2 = st.columns([1, 4])
with col_reset_1:
    if st.button("🔄 Resetar aplicação", use_container_width=True):
        st.cache_data.clear()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# =========================
# Cache de leitura/análise
# =========================
@st.cache_data(show_spinner=False, ttl=3600)
def carregar_itens_icms(path_str: str) -> pd.DataFrame:
    path = validate_excel_path(path_str)
    reader = WorkbookReader(path)
    return normalize_icms_items(reader.read_sheet("c170"))


@st.cache_data(show_spinner=False, ttl=3600)
def carregar_itens_piscofins(path_str: str) -> pd.DataFrame:
    path = validate_excel_path(path_str)
    reader = WorkbookReader(path)
    return normalize_piscofins_items(reader.read_sheet("c170"))


@st.cache_data(show_spinner=False, ttl=3600)
def analisar_dados(
    df_icms: pd.DataFrame,
    df_pis: pd.DataFrame,
    tolerancia: float,
    aliq_pis: float,
    aliq_cofins: float,
):
    return run_analysis(
        icms_df=df_icms,
        pis_df=df_pis,
        tolerancia=tolerancia,
        aliq_pis=aliq_pis,
        aliq_cofins=aliq_cofins,
    )


# =========================
# Utilidades
# =========================
def fmt_int(value) -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except Exception:
        return "0"


def fmt_money(value) -> str:
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def contar_preenchidos(df: pd.DataFrame, col: str) -> int:
    if col not in df.columns:
        return 0
    return int((pd.to_numeric(df[col], errors="coerce").fillna(0) != 0).sum())


def encontrar_coluna_status(df: pd.DataFrame) -> str | None:
    for c in [
        "Status da Análise",
        "Status da Analise",
        "status_analise",
        "status da análise",
        "status da analise",
    ]:
        if c in df.columns:
            return c
    return None


def montar_diagnostico_relatorio(report: pd.DataFrame) -> dict:
    out = {
        "linhas_relatorio": len(report),
        "base_icms_final_preenchida": contar_preenchidos(report, "Base de ICMS Final"),
        "valor_icms_final_preenchido": contar_preenchidos(report, "Valor de ICMS Final"),
        "base_pis_preenchida": contar_preenchidos(report, "Base de PIS Informada"),
        "base_cofins_preenchida": contar_preenchidos(report, "Base de COFINS Informada"),
        "credito_total_estimado": 0.0,
        "join_sim": 0,
        "join_nao": 0,
    }

    if "Crédito Total Estimado" in report.columns:
        out["credito_total_estimado"] = float(
            pd.to_numeric(report["Crédito Total Estimado"], errors="coerce").fillna(0).sum()
        )

    if "Cruzou com ICMS/IPI" in report.columns:
        out["join_sim"] = int((report["Cruzou com ICMS/IPI"].astype(str) == "Sim").sum())
        out["join_nao"] = int((report["Cruzou com ICMS/IPI"].astype(str) == "Não").sum())

    return out


def filtrar_por_status(report: pd.DataFrame, status: str) -> pd.DataFrame:
    col = encontrar_coluna_status(report)
    if not col:
        return report.copy()
    return report[report[col] == status].copy()


def mostrar_amostra(df: pd.DataFrame, limite: int, mensagem: str, height: int = 420) -> None:
    st.write(f"Total de linhas: {fmt_int(len(df))}")
    if len(df) == 0:
        st.info("Nenhum registro encontrado.")
        return
    st.dataframe(df.head(limite), use_container_width=True, height=height)
    if len(df) > limite:
        st.info(mensagem)


# =========================
# Sidebar
# =========================
with st.sidebar:
    st.header("Parâmetros")

    tolerancia = st.number_input("Tolerância da comparação", min_value=0.0, value=0.01, step=0.01)
    aliq_pis = st.number_input("Alíquota estimada de PIS (%)", min_value=0.0, value=1.65, step=0.01)
    aliq_cofins = st.number_input("Alíquota estimada de COFINS (%)", min_value=0.0, value=7.60, step=0.01)

    operacoes = st.multiselect("Operações para análise", options=["Entrada", "Saída"], default=["Saída"])
    somente_regulares = st.checkbox("Considerar apenas documentos regulares", value=True)
    mostrar_diagnostico = st.checkbox("Mostrar diagnóstico técnico", value=False)

    st.caption(
        "Arquivos grandes podem demorar na primeira leitura. "
        "Nas próximas execuções, o cache ajuda a acelerar."
    )


# =========================
# Entradas
# =========================
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


# =========================
# Processamento
# =========================
if st.button("Processar arquivos", type="primary", use_container_width=True):
    try:
        progress = st.progress(0, text="Iniciando processamento...")
        status_box = st.empty()

        with st.spinner("Processando arquivos..."):
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

            if operacoes:
                progress.progress(70, text="Aplicando filtros...")
                if "ind_oper_desc" in df_icms.columns:
                    df_icms = df_icms[df_icms["ind_oper_desc"].isin(operacoes)].copy()
                if "ind_oper_desc" in df_pis.columns:
                    df_pis = df_pis[df_pis["ind_oper_desc"].isin(operacoes)].copy()

            if somente_regulares and "situacao_ok" in df_pis.columns:
                df_pis = df_pis[df_pis["situacao_ok"]].copy()

            status_box.info("Cruzando dados e executando análise...")
            progress.progress(85, text="Cruzando dados e analisando...")
            report, resumo = analisar_dados(
                df_icms=df_icms,
                df_pis=df_pis,
                tolerancia=tolerancia,
                aliq_pis=aliq_pis,
                aliq_cofins=aliq_cofins,
            )

            st.session_state["report"] = report
            st.session_state["resumo"] = resumo
            st.session_state["diagnostico"] = montar_diagnostico_relatorio(report)
            st.session_state.pop("excel_bytes", None)

            progress.progress(100, text="Finalizado.")
            status_box.success("Processamento concluído com sucesso.")

        st.success("Arquivos processados.")
    except Exception as exc:
        st.exception(exc)


# =========================
# Resultado
# =========================
if "report" in st.session_state:
    report = st.session_state["report"]
    resumo = st.session_state.get("resumo", {})
    diagnostico = st.session_state.get("diagnostico", {})

    st.subheader("Resumo da análise")
    a, b, c, d, e = st.columns(5)
    a.metric("Itens analisados", fmt_int(resumo.get("itens_analisados", len(report))))
    b.metric("Exclusão identificada", fmt_int(resumo.get("itens_exclusao_identificada", 0)))
    c.metric("Sem indício", fmt_int(resumo.get("itens_sem_indicio", 0)))
    d.metric("Divergente / Revisar", fmt_int(resumo.get("itens_divergente_revisar", 0)))
    e.metric("Sem dados suficientes", fmt_int(resumo.get("itens_sem_dados", 0)))

    st.subheader("Crédito estimado")
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Crédito PIS estimado",
        fmt_money(
            pd.to_numeric(report.get("Crédito PIS Estimado", 0), errors="coerce").fillna(0).sum()
            if "Crédito PIS Estimado" in report.columns else 0
        ),
    )
    c2.metric(
        "Crédito COFINS estimado",
        fmt_money(
            pd.to_numeric(report.get("Crédito COFINS Estimado", 0), errors="coerce").fillna(0).sum()
            if "Crédito COFINS Estimado" in report.columns else 0
        ),
    )
    c3.metric("Crédito total estimado", fmt_money(diagnostico.get("credito_total_estimado", 0.0)))

    st.subheader("Baixar relatório")

    if st.button("Preparar Excel para download", use_container_width=True):
        progress_excel = st.progress(0, text="Iniciando geração do Excel...")
        status_excel = st.empty()

        def callback_excel(atual: int, total: int, mensagem: str):
            pct = int((atual / total) * 100) if total else 0
            progress_excel.progress(min(pct, 100), text=mensagem)
            status_excel.info(mensagem)

        with st.spinner("Gerando Excel em modo otimizado..."):
            st.session_state["excel_bytes"] = export_report_to_bytes(
                report,
                resumo,
                progress_callback=callback_excel,
            )

        progress_excel.progress(100, text="Excel finalizado.")
        status_excel.success("Arquivo pronto para download.")

    if "excel_bytes" in st.session_state:
        st.download_button(
            "Baixar Excel do relatório",
            data=st.session_state["excel_bytes"],
            file_name="relatorio_recuperacao_icms_piscofins.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    if mostrar_diagnostico:
        st.subheader("Diagnóstico técnico")
        d1, d2, d3, d4, d5, d6 = st.columns(6)
        d1.metric("Linhas no relatório", fmt_int(diagnostico.get("linhas_relatorio", len(report))))
        d2.metric("Base ICMS final", fmt_int(diagnostico.get("base_icms_final_preenchida", 0)))
        d3.metric("Valor ICMS final", fmt_int(diagnostico.get("valor_icms_final_preenchido", 0)))
        d4.metric("Base PIS", fmt_int(diagnostico.get("base_pis_preenchida", 0)))
        d5.metric("Join Sim", fmt_int(diagnostico.get("join_sim", 0)))
        d6.metric("Join Não", fmt_int(diagnostico.get("join_nao", 0)))

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Exclusão Identificada", "Sem Indício", "Divergente / Revisar", "Relatório Completo"]
    )

    with tab1:
        mostrar_amostra(
            filtrar_por_status(report, "Exclusão identificada"),
            1000,
            "Mostrando apenas as primeiras 1.000 linhas. O detalhamento completo está no Excel.",
        )

    with tab2:
        mostrar_amostra(
            filtrar_por_status(report, "Sem indício de exclusão"),
            1000,
            "Mostrando apenas as primeiras 1.000 linhas. O detalhamento completo está no Excel.",
        )

    with tab3:
        divergente = pd.concat(
            [
                filtrar_por_status(report, "Divergente / Revisar"),
                filtrar_por_status(report, "Sem dados suficientes"),
            ],
            ignore_index=True,
        ).drop_duplicates()

        mostrar_amostra(
            divergente,
            300,
            "Mostrando apenas as primeiras 300 linhas. Use o Excel para o conjunto completo.",
        )

    with tab4:
        st.write(f"Total de linhas: {fmt_int(len(report))}")
        st.write(f"Total de colunas: {fmt_int(len(report.columns))}")
        st.dataframe(report.head(100), use_container_width=True, height=420)
        if len(report) > 100:
            st.warning("O relatório completo não é exibido integralmente na tela para evitar lentidão. Use o Excel.")

else:
    st.info("Informe os caminhos dos dois arquivos e clique em Processar arquivos.")