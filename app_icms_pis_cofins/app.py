from datetime import datetime, date
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

from src.icms_st_processing import (
    listar_ufs_aliquotas,
    processar_icms_st,
)
from src.icms_st_exporter import gerar_excel_icms_st


st.set_page_config(page_title="ICMS na Base PIS/COFINS", layout="wide")

st.title("Investigação - ICMS na base do PIS/COFINS")
st.caption("Layout da versão 1 + módulo adicional para análise preliminar de ICMS-ST.")
st.warning("Para arquivos grandes, rode localmente. Esta versão aceita upload de até 1GB via .streamlit/config.toml.")


def obter_aliquotas_pis_cofins(regime_nome: str):
    if regime_nome == "Lucro Real":
        return 0.0165, 0.0760
    if regime_nome == "Lucro Presumido":
        return 0.0065, 0.0300
    return None, None


with st.sidebar:
    st.header("Parâmetros")

    tipo_analise = st.radio(
        "Tipo de análise",
        [
            "Exclusão ICMS da base PIS/COFINS",
            "ICMS-ST - análise preliminar",
        ],
        index=0,
    )

    if tipo_analise == "Exclusão ICMS da base PIS/COFINS":
        modo = st.radio(
            "Registro do SPED Contribuições para análise",
            ["C170", "C175", "C170 + C175"],
            index=2,
        )
        tolerancia = st.number_input("Tolerância para diferença", min_value=0.0, value=0.05, step=0.01)

        regime = st.radio(
            "Regime tributário",
            ["Lucro Real", "Lucro Presumido", "Alíquota personalizada"],
            index=0,
        )

        if regime == "Lucro Real":
            aliquota_pis = 0.0165
            aliquota_cofins = 0.0760
        elif regime == "Lucro Presumido":
            aliquota_pis = 0.0065
            aliquota_cofins = 0.0300
        else:
            aliquota_pis = st.number_input("Alíquota PIS", min_value=0.0, value=0.0165, format="%.4f")
            aliquota_cofins = st.number_input("Alíquota COFINS", min_value=0.0, value=0.0760, format="%.4f")

        st.caption(
            f"PIS: {aliquota_pis:.4%} | COFINS: {aliquota_cofins:.4%} | "
            f"Total: {(aliquota_pis + aliquota_cofins):.4%}"
        )

    else:
        modo_st = st.radio(
            "Registro do SPED Contribuições para ICMS-ST",
            ["C170", "C175", "C170 + C175"],
            index=1,
        )

        ufs_disponiveis = listar_ufs_aliquotas()
        uf_st = st.selectbox("UF para buscar alíquota ICMS", ufs_disponiveis, index=ufs_disponiveis.index("PE") if "PE" in ufs_disponiveis else 0)

        col_ini, col_fim = st.columns(2)
        with col_ini:
            data_ini_st = st.date_input("Início", value=date(2021, 1, 1), format="DD/MM/YYYY")
        with col_fim:
            data_fim_st = st.date_input("Fim", value=date.today(), format="DD/MM/YYYY")

        origem_aliquota_st = st.radio(
            "Origem da alíquota ICMS",
            ["Tabela interna por UF/competência", "Alíquota manual"],
            index=0,
        )

        aliquota_icms_manual = None
        if origem_aliquota_st == "Alíquota manual":
            aliquota_icms_manual = st.number_input(
                "Alíquota ICMS manual (%)",
                min_value=0.0,
                max_value=100.0,
                value=18.0,
                step=0.1,
            ) / 100

        tolerancia_bc_st = st.number_input(
            "Tolerância BC PIS vs operação",
            min_value=0.0,
            value=0.05,
            step=0.01,
        )

        regime_st = st.radio(
            "Regime PIS/COFINS",
            ["Lucro Real", "Lucro Presumido", "Alíquota personalizada"],
            index=0,
        )

        if regime_st == "Alíquota personalizada":
            aliquota_pis_st = st.number_input("Alíquota PIS ST", min_value=0.0, value=0.0165, format="%.4f")
            aliquota_cofins_st = st.number_input("Alíquota COFINS ST", min_value=0.0, value=0.0760, format="%.4f")
        else:
            aliquota_pis_st, aliquota_cofins_st = obter_aliquotas_pis_cofins(regime_st)

        st.caption(
            f"PIS: {aliquota_pis_st:.4%} | COFINS: {aliquota_cofins_st:.4%} | "
            f"Total: {(aliquota_pis_st + aliquota_cofins_st):.4%}"
        )


if tipo_analise == "ICMS-ST - análise preliminar":
    st.subheader("1. Upload do SPED Contribuições")
    arq_pis_st = st.file_uploader(
        "Excel SPED PIS/COFINS para análise preliminar de ICMS-ST",
        type=["xlsx", "xlsm", "xls"],
        key="upload_icms_st"
    )

    st.info(
        "Este módulo é preliminar e estimativo. Ele filtra CFOP 5405, CST PIS/COFINS 01, "
        "valida BC PIS contra valor da operação menos desconto e calcula crédito estimado por mês/ano."
    )

    if not arq_pis_st:
        st.stop()

    try:
        xls_pis_st = pd.ExcelFile(arq_pis_st)
    except Exception as e:
        st.error(f"Erro ao abrir o arquivo: {e}")
        st.stop()

    required_pis_st = []
    if modo_st in ["C170", "C170 + C175"]:
        required_pis_st.append("C170")
    if modo_st in ["C175", "C170 + C175"]:
        required_pis_st.append("C175")

    val_pis_st = validate_sheet_exists(xls_pis_st, required_pis_st, "SPED PIS/COFINS - ICMS-ST")
    if val_pis_st.errors:
        st.error("Validação não concluída. Corrija os pontos abaixo:")
        for err in val_pis_st.errors:
            st.write(f"- {err}")
        st.stop()

    st.success("Validação de abas concluída.")

    if st.button("Processar análise preliminar ICMS-ST", type="primary"):
        try:
            with st.spinner("Processando ICMS-ST preliminar..."):
                resultado_st = processar_icms_st(
                    xls_pis=xls_pis_st,
                    get_sheet_name=get_sheet_name,
                    modo=modo_st,
                    uf=uf_st,
                    data_inicio=data_ini_st,
                    data_fim=data_fim_st,
                    origem_aliquota=origem_aliquota_st,
                    aliquota_icms_manual=aliquota_icms_manual,
                    aliquota_pis=aliquota_pis_st,
                    aliquota_cofins=aliquota_cofins_st,
                    regime=regime_st,
                    tolerancia_bc=tolerancia_bc_st,
                )

                excel_st = gerar_excel_icms_st(resultado_st)

            st.subheader("2. Resultado ICMS-ST preliminar")
            resumo_mensal = resultado_st.get("01_resumo_mensal")
            if resumo_mensal is not None and not resumo_mensal.empty:
                st.dataframe(resumo_mensal, use_container_width=True)
            else:
                st.warning("Nenhuma operação elegível foi encontrada para os filtros do ICMS-ST.")

            st.download_button(
                "Baixar Excel ICMS-ST preliminar",
                data=excel_st,
                file_name="analise_preliminar_icms_st.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            with st.expander("Visualizar analítico 5405"):
                analitico = resultado_st.get("02_analitico_5405")
                if analitico is not None:
                    st.dataframe(analitico.head(200), use_container_width=True)

            limpar_memoria()

        except Exception as e:
            st.error("Erro durante o processamento do ICMS-ST.")
            st.exception(e)

    st.stop()


# Fluxo original preservado abaixo.
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

            # Melhoria v14:
            # C100 é a âncora documental e C170 ICMS/IPI passa a ser usado
            # item a item quando a aba existir. Se não existir, o sistema
            # continua usando C190 como base consolidada/varejo.
            try:
                c170_icms = load_sheet(xls_icms, get_sheet_name(xls_icms, "C170"))
            except Exception:
                c170_icms = pd.DataFrame()

            icms_linhas = prepare_icms_c190(c100_icms, c190_icms, c170_icms)
            icms_base = consolidate_icms_by_key(icms_linhas)

            cruzamentos = {}
            cruz_c170 = pd.DataFrame()
            cruz_c175 = pd.DataFrame()

            if modo in ["C170", "C170 + C175"]:
                c170 = load_sheet(xls_pis, get_sheet_name(xls_pis, "C170"))
                pis170 = prepare_pis_cofins(c170, "C170")
                pis170_key = consolidate_pis_by_key(pis170)
                cruz_c170 = cruzar_icms_pis(icms_base, pis170_key, tolerancia, aliquota_pis, aliquota_cofins)
                cruzamentos["C170"] = cruz_c170

            if modo in ["C175", "C170 + C175"]:
                c175 = load_sheet(xls_pis, get_sheet_name(xls_pis, "C175"))
                pis175 = prepare_pis_cofins(c175, "C175")
                pis175_key = consolidate_pis_by_key(pis175)
                cruz_c175 = cruzar_icms_pis(icms_base, pis175_key, tolerancia, aliquota_pis, aliquota_cofins)
                cruzamentos["C175"] = cruz_c175

            resumo = resumo_geral(cruzamentos)
            credito = potencial_credito(cruzamentos, aliquota_pis, aliquota_cofins, regime)
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
                {"PARAMETRO": "Regime tributário", "VALOR": regime},
                {"PARAMETRO": "Alíquota PIS", "VALOR": aliquota_pis},
                {"PARAMETRO": "Alíquota COFINS", "VALOR": aliquota_cofins},
                {"PARAMETRO": "Metodologia", "VALOR": "Crédito elegível = soma de CREDITO_PISCOFINS_BASE_ESPERADA da aba 04, filtrando CFOP 5102 + CST ICMS 000 + CST PIS/COFINS 01 + STATUS ICMS INCLUÍDO"},
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
            st.subheader("Potencial crédito elegível por competência")
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
