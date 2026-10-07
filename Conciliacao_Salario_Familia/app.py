from __future__ import annotations

import io
import hashlib

import pandas as pd
import streamlit as st

from modules.comparador import comparar, localizar_coluna, preparar_levantamento
from modules.ecac_parser import processar_arquivos
from modules.levantamento_parser import identificar_modelo, importar_modelo
from modules.excel_output import gerar_excel_comparativo, gerar_excel_ecac


st.set_page_config(page_title="Conciliação de Salário-Família", layout="wide")
st.title("Conciliação de Salário-Família")
st.caption(
    "Extração das deduções informadas na DCTFWeb e comparação com levantamentos. "
    "Os arquivos são processados apenas durante a sessão."
)

modulo = st.sidebar.radio(
    "Módulo",
    ["1. Extrair dados do e-CAC", "2. Comparar levantamentos"],
)


def ler_planilha(arquivo) -> tuple[pd.DataFrame, str]:
    nome = arquivo.name.lower()
    conteudo = arquivo.getvalue()
    if nome.endswith(".csv"):
        return pd.read_csv(io.BytesIO(conteudo), sep=None, engine="python"), "CSV"
    excel = pd.ExcelFile(io.BytesIO(conteudo))
    aba = st.selectbox("Aba do arquivo", excel.sheet_names, key=f"aba_{arquivo.name}")
    return pd.read_excel(excel, sheet_name=aba), aba


if modulo.startswith("1"):
    st.header("Extrair salário-família do e-CAC")
    enviados = st.file_uploader(
        "Declarações completas da DCTFWeb",
        type=["pdf", "zip"],
        accept_multiple_files=True,
        help="Aceita PDFs individuais ou ZIPs contendo vários PDFs.",
    )
    if st.button("Processar documentos", type="primary", disabled=not enviados):
        resumo, documentos, ocorrencias = processar_arquivos(
            (arquivo.name, arquivo.getvalue()) for arquivo in enviados
        )
        st.session_state["ecac_resumo"] = resumo
        st.session_state["ecac_documentos"] = documentos
        st.session_state["ecac_ocorrencias"] = ocorrencias

    resumo = st.session_state.get("ecac_resumo")
    if isinstance(resumo, pd.DataFrame):
        if resumo.empty:
            st.warning("Nenhum valor de salário-família foi extraído.")
        else:
            exibicao = resumo.copy()
            st.success(f"{len(exibicao)} competência(s) consolidada(s).")
            st.dataframe(
                exibicao.style.format({"salario_familia": "R$ {:,.2f}"}),
                use_container_width=True,
                hide_index=True,
            )
            excel = gerar_excel_ecac(
                resumo,
                st.session_state["ecac_documentos"],
                st.session_state["ecac_ocorrencias"],
            )
            st.download_button(
                "Baixar Excel do salário-família",
                data=excel,
                file_name="salario_familia_ecac.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
        ocorrencias = st.session_state.get("ecac_ocorrencias")
        if isinstance(ocorrencias, pd.DataFrame) and not ocorrencias.empty:
            with st.expander("Ocorrências"):
                st.dataframe(ocorrencias, use_container_width=True, hide_index=True)

else:
    st.header("Comparar com levantamentos")
    arquivo_ecac = st.file_uploader(
        "Excel gerado pelo módulo do e-CAC",
        type=["xlsx"],
        key="comparacao_ecac",
    )
    arquivo_levantamento = st.file_uploader(
        "Levantamento MANAD, XML/eSocial ou planilha padronizada",
        type=["xlsx", "csv"],
        key="comparacao_levantamento",
    )
    origem = st.selectbox("Origem do levantamento", ["MANAD", "XML/eSocial", "Outro"])

    if arquivo_ecac and arquivo_levantamento:
        assinatura = hashlib.sha256(arquivo_ecac.getvalue() + arquivo_levantamento.getvalue()).hexdigest()
        if st.session_state.get("comparativo_arquivos") != assinatura:
            st.session_state.pop("comparativo", None)
            st.session_state["comparativo_arquivos"] = assinatura
        ecac = pd.read_excel(io.BytesIO(arquivo_ecac.getvalue()), sheet_name="Salário Família")
        modelo = None
        if arquivo_levantamento.name.lower().endswith(".xlsx"):
            with pd.ExcelFile(io.BytesIO(arquivo_levantamento.getvalue())) as excel_modelo:
                modelo = identificar_modelo(excel_modelo.sheet_names)
        automatico = modelo and st.checkbox(f"Usar leitura automática do modelo {modelo}", value=True)
        preparado = None
        detalhe = None
        if automatico:
            try:
                preparado, detalhe, avisos = importar_modelo(arquivo_levantamento.getvalue(), modelo)
                if preparado.empty:
                    st.session_state.pop("comparativo", None)
                for aviso in avisos:
                    st.warning(aviso)
                st.dataframe(preparado, use_container_width=True, hide_index=True)
            except (ValueError, KeyError) as exc:
                st.session_state.pop("comparativo", None)
                st.error(f"Não foi possível importar o modelo: {exc}")
        else:
            levantamento, _ = ler_planilha(arquivo_levantamento)
            colunas = list(map(str, levantamento.columns))

            sugestao_cnpj = localizar_coluna(colunas, ["cnpj", "cnpj_empregador"])
            sugestao_comp = localizar_coluna(colunas, ["competencia", "per_apur", "periodo"])
            sugestao_valor = localizar_coluna(colunas, ["valor", "vr_rubr", "valor_pago"])
            sugestao_desc = localizar_coluna(colunas, ["descricao", "dsc_rubr", "rubrica"])

            def indice(coluna):
                return colunas.index(coluna) if coluna in colunas else 0

            c1, c2, c3 = st.columns(3)
            coluna_cnpj = c1.selectbox("Coluna do CNPJ", colunas, index=indice(sugestao_cnpj))
            coluna_comp = c2.selectbox("Coluna da competência", colunas, index=indice(sugestao_comp))
            coluna_valor = c3.selectbox("Coluna do valor", colunas, index=indice(sugestao_valor))
            opcoes_desc = ["Não filtrar"] + colunas
            indice_desc = opcoes_desc.index(sugestao_desc) if sugestao_desc in opcoes_desc else 0
            coluna_desc = st.selectbox("Coluna para localizar salário-família", opcoes_desc, index=indice_desc)
            filtro = st.text_input(
                "Descrições consideradas (separe por ponto e vírgula)",
                value="salário família;salario familia",
                disabled=coluna_desc == "Não filtrar",
            )


        if st.button("Gerar comparação", type="primary", disabled=bool(automatico and (preparado is None or preparado.empty))):
            st.session_state.pop("comparativo", None)
            try:
                if not automatico:
                    preparado = preparar_levantamento(
                        levantamento, coluna_cnpj, coluna_comp, coluna_valor, origem,
                        None if coluna_desc == "Não filtrar" else coluna_desc, filtro,
                    )
                if preparado.empty:
                    st.warning("Nenhum lançamento encontrado para comparar. Ausência não representa zero.")
                else:
                    resultado = comparar(ecac, preparado)
                    st.session_state["comparativo"] = resultado
                    st.session_state["comparativo_ecac"] = ecac
                    st.session_state["comparativo_levantamento"] = preparado
                    st.session_state["comparativo_detalhe"] = detalhe
            except (ValueError, KeyError) as exc:
                st.error(f"Não foi possível comparar: {exc}")

    resultado = st.session_state.get("comparativo")
    if isinstance(resultado, pd.DataFrame):
        st.dataframe(
            resultado.style.format(
                {
                    "valor_levantamento": "R$ {:,.2f}",
                    "valor_ecac": "R$ {:,.2f}",
                    "diferença_potencial": "R$ {:,.2f}",
                },
                na_rep="—",
            ),
            use_container_width=True,
            hide_index=True,
        )
        excel = gerar_excel_comparativo(
            resultado,
            st.session_state["comparativo_ecac"],
            st.session_state["comparativo_levantamento"],
            st.session_state.get("comparativo_detalhe"),
        )
        st.download_button(
            "Baixar Excel comparativo",
            data=excel,
            file_name="comparativo_salario_familia.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

