import streamlit as st

from src.validation import validar_abas
from src.processing import processar_arquivos
from src.exporter import exportar_excel
from src.utils import obter_aliquotas_por_regime


st.set_page_config(
    page_title="Investigação ICMS na Base PIS/COFINS",
    layout="wide"
)

st.title("Investigação ICMS na Base PIS/COFINS")

st.markdown(
    """
    Este app cruza informações do SPED ICMS/IPI com o SPED PIS/COFINS
    para investigar se o ICMS foi incluído na base de cálculo do PIS/COFINS.
    """
)

st.warning(
    "Arquivos acima de 500MB podem levar vários minutos para processamento. "
    "Para arquivos muito grandes, prefira rodar localmente."
)

st.divider()

col1, col2 = st.columns(2)

with col1:
    uploaded_icms = st.file_uploader(
        "Upload SPED ICMS/IPI em Excel",
        type=["xlsx"],
        key="icms"
    )

with col2:
    uploaded_pis = st.file_uploader(
        "Upload SPED PIS/COFINS em Excel",
        type=["xlsx"],
        key="pis"
    )

st.divider()

st.subheader("Configuração da análise")

modo = st.radio(
    "Qual registro do SPED PIS/COFINS deseja usar?",
    [
        "C170",
        "C175",
        "AMBOS"
    ],
    horizontal=True
)

regime = st.radio(
    "Regime tributário para cálculo do potencial crédito:",
    [
        "Lucro Real",
        "Lucro Presumido",
        "Alíquota personalizada"
    ],
    horizontal=True
)

if regime == "Alíquota personalizada":
    col_pis, col_cofins = st.columns(2)

    with col_pis:
        aliquota_pis = st.number_input(
            "Alíquota PIS (%)",
            min_value=0.0,
            max_value=100.0,
            value=1.65,
            step=0.01
        ) / 100

    with col_cofins:
        aliquota_cofins = st.number_input(
            "Alíquota COFINS (%)",
            min_value=0.0,
            max_value=100.0,
            value=7.60,
            step=0.01
        ) / 100

else:
    aliquota_pis, aliquota_cofins = obter_aliquotas_por_regime(regime)

st.info(
    f"Alíquota PIS: {aliquota_pis:.4%} | "
    f"Alíquota COFINS: {aliquota_cofins:.4%} | "
    f"Total: {(aliquota_pis + aliquota_cofins):.4%}"
)

st.caption(
    "Critério da aba 07_potencial_credito: "
    "CST ICMS = 000 + CST PIS/COFINS = 01 + STATUS = ICMS INCLUÍDO."
)

st.divider()

if st.button("Processar análise", type="primary"):

    if not uploaded_icms:
        st.error("Envie o arquivo SPED ICMS/IPI em Excel.")

    elif not uploaded_pis:
        st.error("Envie o arquivo SPED PIS/COFINS em Excel.")

    else:
        erros_icms = validar_abas(uploaded_icms, "ICMS")
        erros_pis = validar_abas(uploaded_pis, modo)
        erros = erros_icms + erros_pis

        if erros:
            st.error("Foram encontrados problemas na validação dos arquivos:")
            for erro in erros:
                st.write(f"- {erro}")

        else:
            with st.spinner("Processando cruzamento e recalculando potencial crédito..."):

                resultado = processar_arquivos(
                    arquivo_icms=uploaded_icms,
                    arquivo_pis=uploaded_pis,
                    modo=modo,
                    regime=regime,
                    aliquota_pis=aliquota_pis,
                    aliquota_cofins=aliquota_cofins
                )

                caminho_saida = exportar_excel(resultado)

            st.success("Análise concluída.")

            resumo = resultado.get("07_potencial_credito")
            if resumo is not None and not resumo.empty:
                st.subheader("Resumo do potencial crédito elegível")
                st.dataframe(resumo, use_container_width=True)
            else:
                st.warning(
                    "Nenhuma operação elegível encontrada para potencial crédito "
                    "com os critérios CST ICMS 000, CST PIS/COFINS 01 e ICMS incluído."
                )

            with open(caminho_saida, "rb") as f:
                st.download_button(
                    label="Baixar Excel investigativo",
                    data=f,
                    file_name="investigacao_icms_pis_cofins.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
