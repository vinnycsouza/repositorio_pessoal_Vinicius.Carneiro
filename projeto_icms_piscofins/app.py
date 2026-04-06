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

st.set_page_config(page_title="Auditor local — ICMS x PIS/COFINS", layout="wide")
st.title("Auditor local — confronto entre base de ICMS e bases de PIS/COFINS")
st.caption("Leitura local por caminho dos Excel convertidos do SPED e teste de verdadeiro/falso com base no valor do ICMS.")


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


with st.sidebar:
    st.header("Parâmetros")
    tolerancia = st.number_input(
        "Tolerância para o verdadeiro/falso",
        min_value=0.0,
        value=0.02,
        step=0.01,
        help="Diferença máxima aceita entre (Base ICMS - Base PIS/COFINS) e o Valor de ICMS.",
    )
    operacoes = st.multiselect(
        "Operações para análise",
        options=["Entrada", "Saída"],
        default=["Saída"],
    )
    somente_regulares = st.checkbox("Considerar apenas documentos regulares", value=True)
    mostrar_diagnostico = st.checkbox("Mostrar diagnóstico técnico", value=True)

st.subheader("Arquivos de entrada")
col1, col2 = st.columns(2)
with col1:
    caminho_icms = st.text_input("Caminho do Excel ICMS/IPI", value="", placeholder=r"C:\Projetos\SPED\arquivo_icms_ipi.xlsx")
with col2:
    caminho_pis = st.text_input("Caminho do Excel PIS/COFINS", value="", placeholder=r"C:\Projetos\SPED\arquivo_pis_cofins.xlsx")

if st.button("Processar arquivos", type="primary", use_container_width=True):
    try:
        with st.spinner("Lendo, normalizando e comparando as bases..."):
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
        st.success("Processamento concluído.")
    except Exception as exc:
        st.exception(exc)

if "report" in st.session_state:
    report = st.session_state["report"]
    resumo = st.session_state.get("resumo", {})

    a, b, c, d, e, f = st.columns(6)
    a.metric("Itens analisados", fmt_int(resumo.get("itens_analisados", len(report))))
    b.metric("Exclusão identificada", fmt_int(resumo.get("exclusao_identificada", 0)))
    c.metric("Sem indício", fmt_int(resumo.get("sem_indicio", 0)))
    d.metric("Divergentes", fmt_int(resumo.get("divergente", 0)))
    e.metric("Sem dados", fmt_int(resumo.get("sem_dados", 0)))
    f.metric("Sem match", fmt_int(resumo.get("sem_match", 0)))

    if mostrar_diagnostico:
        st.subheader("Diagnóstico técnico")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Base de ICMS Final", fmt_int(resumo.get("com_base_icms_final", 0)))
        d2.metric("Valor de ICMS Final", fmt_int(resumo.get("com_valor_icms_final", 0)))
        d3.metric("Linhas no relatório", fmt_int(len(report)))
        d4.metric("Colunas no relatório", fmt_int(len(report.columns)))

        with st.expander("Colunas presentes no relatório"):
            st.write(list(report.columns))

    st.subheader("Exclusão identificada")
    identificadas = report[report["Status da Análise"] == "Exclusão identificada"].copy()
    st.dataframe(identificadas, use_container_width=True, height=420)

    with st.expander("Ver relatório completo"):
        st.dataframe(report, use_container_width=True, height=520)

    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)
    file_name = f"relatorio_confronto_icms_piscofins_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
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
    st.markdown(
        """
### Regra desta versão
- O relatório verifica se a diferença entre a **Base de ICMS** e a **Base de PIS/COFINS** equivale ao **Valor de ICMS**.
- Quando isso acontece dentro da tolerância, o status sai como **Exclusão identificada**.
- Quando a Base de ICMS coincide com as bases de PIS e COFINS, o status sai como **Sem indício de exclusão**.
- Casos intermediários ficam como **Divergente / Revisar** ou **Sem dados suficientes**.

### Observações
- O cruzamento entre os dois SPEDs serve para localizar o mesmo item e compor os campos, não para exigir igualdade absoluta de valores.
- A leitura prioriza a aba lógica **C170**.
- As colunas de ICMS são priorizadas do arquivo **ICMS/IPI**; se não houver valor, o app usa o valor disponível no **PIS/COFINS**.
        """
    )
