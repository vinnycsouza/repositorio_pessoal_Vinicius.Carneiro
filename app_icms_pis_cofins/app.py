from datetime import datetime
import pandas as pd
import streamlit as st

from src.validation import validate_sheet_exists, get_sheet_name
from src.processing import (
    load_sheet,
    prepare_icms_c190,
    consolidate_icms_by_key,
    prepare_pis_cofins,
    consolidate_pis_by_key,
    cruzar_icms_pis,
    resumo_geral,
    potencial_credito,
    comparativo_c170_c175,
)
from src.exporter import gerar_excel
from src.memory_manager import limpar_memoria

st.set_page_config(page_title="ICMS na Base PIS/COFINS", layout="wide")

st.title("Investigação - ICMS na base do PIS/COFINS")
st.caption("Layout da versão 1 + validação corrigida para abas com nomes descritivos, como C190 - Analítico e C170 - Itens da Nota.")
st.warning("Para arquivos grandes, rode localmente. Esta versão aceita upload de até 1GB via .streamlit/config.toml.")

with st.sidebar:
    st.header("Parâmetros")
    modo = st.radio(
        "Registro do SPED Contribuições para análise",
        ["C170", "C175", "C170 + C175"],
        index=2,
    )
    tolerancia = st.number_input("Tolerância para diferença", min_value=0.0, value=0.05, step=0.01)
    aliquota_pis = st.number_input("Alíquota PIS", min_value=0.0, value=0.0165, format="%.4f")
    aliquota_cofins = st.number_input("Alíquota COFINS", min_value=0.0, value=0.0760, format="%.4f")

st.subheader("1. Upload dos arquivos")
col1, col2 = st.columns(2)
with col1:
    arq_icms = st.file_uploader("Excel SPED ICMS/IPI", type=["xlsx", "xlsm", "xls"])
with col2:
    arq_pis = st.file_uploader("Excel SPED PIS/COFINS", type=["xlsx", "xlsm", "xls"])

if not arq_icms or not arq_pis:
    st.info("Envie os dois arquivos para iniciar a validação.")
    st.stop()

try:
    xls_icms = pd.ExcelFile(arq_icms)
    xls_pis = pd.ExcelFile(arq_pis)
except Exception as e:
    st.error(f"Erro ao abrir os arquivos: {e}")
    st.stop()

required_icms = ["C100", "C190"]
required_pis = []
if modo in ["C170", "C170 + C175"]:
    required_pis.append("C170")
if modo in ["C175", "C170 + C175"]:
    required_pis.append("C175")

val_icms = validate_sheet_exists(xls_icms, required_icms, "SPED ICMS/IPI")
val_pis = validate_sheet_exists(xls_pis, required_pis, "SPED PIS/COFINS")

errors = val_icms.errors + val_pis.errors
if errors:
    st.error("Validação não concluída. Corrija os pontos abaixo:")
    for err in errors:
        st.write(f"- {err}")
    st.stop()

st.success("Validação de abas concluída.")

if st.button("Processar análise", type="primary"):
    try:
        with st.spinner("Processando arquivos..."):
            c100_icms = load_sheet(xls_icms, get_sheet_name(xls_icms, "C100"))
            c190_icms = load_sheet(xls_icms, get_sheet_name(xls_icms, "C190"))

            icms_linhas = prepare_icms_c190(c100_icms, c190_icms)
            icms_base = consolidate_icms_by_key(icms_linhas)

            cruzamentos = {}
            cruz_c170 = pd.DataFrame()
            cruz_c175 = pd.DataFrame()

            if modo in ["C170", "C170 + C175"]:
                c170 = load_sheet(xls_pis, get_sheet_name(xls_pis, "C170"))
                pis170 = prepare_pis_cofins(c170, "C170")
                pis170_key = consolidate_pis_by_key(pis170)
                cruz_c170 = cruzar_icms_pis(icms_base, pis170_key, tolerancia)
                cruzamentos["C170"] = cruz_c170

            if modo in ["C175", "C170 + C175"]:
                c175 = load_sheet(xls_pis, get_sheet_name(xls_pis, "C175"))
                pis175 = prepare_pis_cofins(c175, "C175")
                pis175_key = consolidate_pis_by_key(pis175)
                cruz_c175 = cruzar_icms_pis(icms_base, pis175_key, tolerancia)
                cruzamentos["C175"] = cruz_c175

            resumo = resumo_geral(cruzamentos)
            credito = potencial_credito(cruzamentos, aliquota_pis, aliquota_cofins)
            comparativo = comparativo_c170_c175(cruz_c170, cruz_c175) if modo == "C170 + C175" else pd.DataFrame()

            divergencias_lista = []
            for nome, df in cruzamentos.items():
                tmp = df[df["STATUS"].isin(["DIVERGENTE / REVISAR", "SEM PIS/COFINS", "SEM ICMS/IPI"])].copy()
                tmp.insert(0, "ANALISE", nome)
                divergencias_lista.append(tmp)
            divergencias = pd.concat(divergencias_lista, ignore_index=True) if divergencias_lista else pd.DataFrame()

            parametros = pd.DataFrame([
                {"PARAMETRO": "Data da análise", "VALOR": datetime.now().strftime("%d/%m/%Y %H:%M:%S")},
                {"PARAMETRO": "Modo selecionado", "VALOR": modo},
                {"PARAMETRO": "Tolerância", "VALOR": tolerancia},
                {"PARAMETRO": "Alíquota PIS", "VALOR": aliquota_pis},
                {"PARAMETRO": "Alíquota COFINS", "VALOR": aliquota_cofins},
                {"PARAMETRO": "Metodologia", "VALOR": "Base esperada = VL_OPR_ICMS - VL_ICMS; comparação com VL_BC_PIS e VL_BC_COFINS"},
            ])

            excel_bytes = gerar_excel(
                resumo=resumo,
                icms_base=icms_base,
                cruz_c170=cruz_c170,
                cruz_c175=cruz_c175,
                comparativo=comparativo,
                divergencias=divergencias,
                credito=credito,
                parametros=parametros,
            )

        st.subheader("2. Resultado")
        st.dataframe(resumo, use_container_width=True)

        if not credito.empty:
            st.subheader("Potencial crédito por competência")
            st.dataframe(credito, use_container_width=True)

        limpar_memoria()

        st.download_button(
            "Baixar Excel investigativo",
            data=excel_bytes,
            file_name="investigacao_icms_pis_cofins.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        with st.expander("Visualizar amostra do cruzamento"):
            for nome, df in cruzamentos.items():
                st.write(f"### {nome}")
                st.dataframe(df.head(100), use_container_width=True)

    except Exception as e:
        st.error("Erro durante o processamento.")
        st.exception(e)
