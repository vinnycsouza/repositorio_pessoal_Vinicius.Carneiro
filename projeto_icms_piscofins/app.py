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
st.title("Auditor local — exclusão de ICMS da base de PIS/COFINS")
st.caption("Projeto local para leitura por caminho de arquivos Excel convertidos do SPED.")


@st.cache_data(show_spinner=False)
def carregar_itens_icms(path_str: str) -> pd.DataFrame:
    path = validate_excel_path(path_str)
    reader = WorkbookReader(path)
    return normalize_icms_items(reader.read_sheet("c170"))


@st.cache_data(show_spinner=False)
def carregar_itens_piscofins(path_str: str) -> pd.DataFrame:
    path = validate_excel_path(path_str)
    reader = WorkbookReader(path)
    return normalize_piscofins_items(reader.read_sheet("c170"))


with st.sidebar:
    st.header("Parâmetros")
    tolerancia = st.number_input("Tolerância da diferença de base", min_value=0.0, value=0.01, step=0.01)
    aliq_pis = st.number_input("Alíquota padrão de PIS (%)", min_value=0.0, value=1.65, step=0.01)
    aliq_cofins = st.number_input("Alíquota padrão de COFINS (%)", min_value=0.0, value=7.60, step=0.01)
    operacoes = st.multiselect(
        "Operações para análise",
        options=["Entrada", "Saída"],
        default=["Saída"],
        help="Por padrão, a análise vem focada em saídas. Marque entrada apenas quando quiser revisar esse grupo também.",
    )
    somente_regulares = st.checkbox("Considerar apenas documentos regulares", value=True)

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

            if operacoes:
                df_icms = df_icms[df_icms["ind_oper_desc"].isin(operacoes)].copy()
                df_pis = df_pis[df_pis["ind_oper_desc"].isin(operacoes)].copy()
            if somente_regulares and "situacao_ok" in df_pis.columns:
                df_pis = df_pis[df_pis["situacao_ok"]].copy()

            report, resumo = run_analysis(
                icms_df=df_icms,
                pis_df=df_pis,
                tolerancia=tolerancia,
                aliq_pis_padrao=aliq_pis,
                aliq_cofins_padrao=aliq_cofins,
            )

            st.session_state["report"] = report
            st.session_state["resumo"] = resumo
            st.session_state["origens"] = {
                "icms": caminho_icms,
                "pis": caminho_pis,
            }

        st.success("Processamento concluído.")
    except Exception as exc:
        st.exception(exc)

if "report" in st.session_state:
    report = st.session_state["report"]
    resumo = st.session_state["resumo"]

    a, b, c, d, e = st.columns(5)
    a.metric("Itens analisados", f"{resumo['itens_analisados']:,}".replace(",", "."))
    b.metric("Potencial alto", f"{resumo['itens_potencial_alto']:,}".replace(",", "."))
    c.metric("Potencial moderado", f"{resumo['itens_potencial_moderado']:,}".replace(",", "."))
    d.metric("Revisão manual", f"{resumo['itens_revisao_manual']:,}".replace(",", "."))
    e.metric("Crédito estimado", f"R$ {resumo['credito_total_estimado']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    st.subheader("Itens com maior potencial")
    potencial = report[report["Nível de Oportunidade"].isin(["Potencial alto", "Potencial moderado"])].copy()
    st.dataframe(potencial, use_container_width=True, height=420)

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
                st.download_button(
                    label="Baixar Excel gerado",
                    data=f.read(),
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
### Escopo desta versão
- Leitura local por caminho de arquivos Excel convertidos do SPED.
- Cruzamento prioritário em nível de item pela chave da NF-e; na falta dela, usa fallback com CNPJ + nota + série + item + competência.
- Classificação em **Potencial alto**, **Potencial moderado**, **Revisão manual** e **Sem oportunidade**.
- Separação de casos com **ICMS-ST** e itens sem correspondência no arquivo ICMS/IPI.
- Tratamento flexível de colunas para variantes de cabeçalhos geradas pelo SysConv.

### Observações técnicas
- O relatório é **indiciário**, não conclusivo.
- A tese jurídica aplicada, o período, o regime da empresa e o tratamento de entradas/saídas precisam ser validados antes de qualquer aproveitamento.
- Se o seu conversor mudar o nome das abas ou colunas, ajuste os aliases em `core/normalize.py` e `core/utils.py`.
        """
    )
