from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.analysis import run_analysis
from core.exporter import export_report
from core.io_excel import WorkbookReader
from core.normalize import normalize_icms_items, normalize_piscofins_items
from core.utils import validate_excel_path


st.set_page_config(page_title="Auditor ICMS x PIS/COFINS", layout="wide")
st.title("Auditor local — comparação entre base de ICMS e bases de PIS/COFINS")
st.caption("Projeto local para leitura por caminho de arquivos Excel convertidos do SPED.")


@st.cache_data(show_spinner=False)
def carregar_itens_icms(path_str: str) -> pd.DataFrame:
    path = validate_excel_path(path_str)
    reader = WorkbookReader(path)
    df = reader.read_sheet("c170")
    return normalize_icms_items(df)


@st.cache_data(show_spinner=False)
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


def fmt_money(value) -> str:
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


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
        "status da analise",
        "status da análise",
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
        with st.spinner("Lendo arquivos e cruzando itens..."):
            df_icms = carregar_itens_icms(caminho_icms)
            df_pis = carregar_itens_piscofins(caminho_pis)

            st.session_state["df_icms_bruto"] = df_icms.copy()
            st.session_state["df_pis_bruto"] = df_pis.copy()

            if operacoes:
                if "ind_oper_desc" in df_icms.columns:
                    df_icms = df_icms[df_icms["ind_oper_desc"].isin(operacoes)].copy()
                if "ind_oper_desc" in df_pis.columns:
                    df_pis = df_pis[df_pis["ind_oper_desc"].isin(operacoes)].copy()

            if somente_regulares and "situacao_ok" in df_pis.columns:
                df_pis = df_pis[df_pis["situacao_ok"]].copy()

            report, resumo = run_analysis(
                icms_df=df_icms,
                pis_df=df_pis,
                tolerancia=tolerancia,
            )

            st.session_state["report"] = report
            st.session_state["resumo"] = resumo
            st.session_state["diagnostico"] = montar_diagnostico_relatorio(report)
            st.session_state["origens"] = {
                "icms": caminho_icms,
                "pis": caminho_pis,
            }

        st.success("Processamento concluído.")
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

    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)
    file_name = f"relatorio_recuperacao_icms_piscofins_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    out_path = out_dir / file_name

    if st.button("Gerar Excel do relatório", use_container_width=True):
        try:
            export_report(report, resumo, out_path)

            with open(out_path, "rb") as f:
                file_bytes = f.read()

            st.download_button(
                label="Baixar Excel gerado",
                data=file_bytes,
                file_name=out_path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            st.info(f"Arquivo salvo também em: {out_path.resolve()}")
        except Exception as exc:
            st.exception(exc)

else:
    st.info("Informe os caminhos dos dois arquivos e clique em Processar arquivos.")