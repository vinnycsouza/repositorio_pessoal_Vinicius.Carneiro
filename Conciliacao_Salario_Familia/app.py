from __future__ import annotations

import hashlib
import io

import pandas as pd
import streamlit as st

from modules.ecac_parser import processar_arquivos
from modules.excel_output import gerar_excel_comparativo, gerar_excel_ecac
from modules.maternidade import (
    GRUPOS, aplicar_classificacao, comparar_maternidade, ler_incidencia,
    ler_levantamento, ler_manad, sugerir_classificacao, validar,
)


st.set_page_config(page_title="Conciliação de Salário-Maternidade", layout="wide")
st.title("Conciliação de Salário-Maternidade")
st.caption("Levantamento, validação documental e comparação com as deduções da DCTFWeb. Arquivos processados em memória.")
modulo = st.sidebar.radio("Módulo", ["1. Extrair dados do e-CAC", "2. Comparar levantamentos"])


def dinheiro(valor):
    if pd.isna(valor):
        return "—"
    return f"R$ {valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


@st.cache_data(show_spinner=False, max_entries=3)
def carregar(conteudo, origem, nome, validador, nome_validador):
    levantamento = ler_levantamento(conteudo, origem, nome)
    if origem == "MANAD":
        fonte, avisos = ler_manad(validador, nome_validador)
    else:
        fonte, avisos = ler_incidencia(validador, nome_validador)
    detalhe, ocorrencias = validar(levantamento, fonte, origem)
    return detalhe, ocorrencias, avisos


def ler_ecac(arquivo):
    if arquivo.name.lower().endswith(".xlsx"):
        with pd.ExcelFile(io.BytesIO(arquivo.getvalue())) as excel:
            if "Salário Maternidade" not in excel.sheet_names:
                raise ValueError("Este Excel é da versão anterior. Reprocesse os PDFs para extrair salário-maternidade.")
            return pd.read_excel(excel, sheet_name="Salário Maternidade", dtype={"cnpj": str, "competencia": str}), pd.DataFrame()
    resumo, _, ocorrencias = processar_arquivos([(arquivo.name, arquivo.getvalue())])
    return resumo, ocorrencias


if modulo.startswith("1"):
    st.header("Extrair salário-maternidade da DCTFWeb")
    enviados = st.file_uploader("Declarações completas da DCTFWeb", type=["pdf", "zip"], accept_multiple_files=True)
    assinatura = hashlib.sha256(b"".join(a.name.encode() + a.getvalue() for a in enviados or [])).hexdigest()
    if st.session_state.get("extracao_arquivos") != assinatura:
        st.session_state.pop("ecac_resultado", None)
        st.session_state["extracao_arquivos"] = assinatura
    if st.button("Processar documentos", type="primary", disabled=not enviados):
        with st.spinner("Extraindo declarações..."):
            st.session_state["ecac_resultado"] = processar_arquivos((a.name, a.getvalue()) for a in enviados)
    if "ecac_resultado" in st.session_state:
        resumo, documentos, ocorrencias = st.session_state["ecac_resultado"]
        if resumo.empty:
            st.warning("Nenhuma declaração reconhecida.")
        else:
            st.success(f"{len(resumo)} apuração(ões) consolidada(s), incluindo períodos anuais quando presentes.")
            st.caption("Competências com apenas o ano representam apuração anual de 13º. Campo ausente permanece não informado.")
            st.dataframe(resumo.drop(columns="salario_familia", errors="ignore").style.format({"salario_maternidade": dinheiro}), hide_index=True)
            st.download_button("Baixar Excel e-CAC", gerar_excel_ecac(resumo, documentos, ocorrencias), "salario_maternidade_ecac.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if not ocorrencias.empty:
            with st.expander("Ocorrências da extração", expanded=resumo.empty):
                st.dataframe(ocorrencias, hide_index=True)
else:
    st.header("Conciliar principal e apoios")
    origem = st.selectbox("Origem do levantamento", ["MANAD", "Relatórios eSocial"])
    levantamento = st.file_uploader("Levantamento de maternidade (Excel)", type=["xlsx"], key="levantamento")
    validador = st.file_uploader(
        "MANAD completo (TXT)" if origem == "MANAD" else "Relatório de incidência eSocial (Excel)",
        type=["txt"] if origem == "MANAD" else ["xlsx"], key=f"validador_{origem}",
    )
    ecac_arquivo = st.file_uploader("DCTFWeb: Excel e-CAC de maternidade, ZIP ou PDF", type=["xlsx", "zip", "pdf"], key="ecac")
    st.caption("O levantamento direciona; o validador confere. Não são importados XMLs. As sugestões de classificação precisam ser revisadas.")
    if origem != "MANAD":
        st.info("A comparação usa o CNPJ do estabelecimento. Confira a correspondência com o CNPJ da DCTFWeb.")
    if levantamento and validador and ecac_arquivo:
        assinatura = hashlib.sha256(origem.encode() + levantamento.getvalue() + validador.getvalue() + ecac_arquivo.getvalue()).hexdigest()
        try:
            with st.spinner("Conferindo documentos..."):
                detalhe, ocorrencias, avisos = carregar(levantamento.getvalue(), origem, levantamento.name, validador.getvalue(), validador.name)
                ecac, ocorrencias_ecac = ler_ecac(ecac_arquivo)
            for aviso in avisos:
                st.warning(aviso)
            if not ocorrencias_ecac.empty:
                st.warning("Há ocorrências na leitura da DCTFWeb. Confira antes de interpretar os resultados.")
                st.dataframe(ocorrencias_ecac, hide_index=True)
            if not ocorrencias.empty:
                st.warning(f"{len(ocorrencias)} lançamento(s) relacionado(s) à maternidade no validador não constam no levantamento. Não foram adicionados aos valores.")
                with st.expander("Lançamentos ausentes do levantamento"):
                    st.dataframe(ocorrencias, hide_index=True)
            if detalhe.empty:
                st.warning("Nenhuma rubrica relacionada à maternidade foi identificada no levantamento. Ausência não representa zero.")
            elif ecac.empty:
                st.warning("Nenhuma declaração disponível para conciliar.")
            else:
                st.subheader("Classificação das rubricas")
                st.caption("Principal e Apoio são sugestões pela descrição. Exclua itens não relacionados. Para 13º em período mensal, rescisão e períodos anteriores, registre a justificativa e, se necessário, a competência de destino. Um destino não pode reunir anos diferentes.")
                st.info("Para considerar uma rubrica, escolha Principal ou Apoio. Para não considerá-la nos cálculos, escolha Excluir. Revisar significa que a decisão está pendente.")
                classificacao = sugerir_classificacao(detalhe)
                for indice, rubrica in classificacao.iterrows():
                    chave = hashlib.sha256(f"{assinatura}|{rubrica.cnpj}|{rubrica.codigo}|{rubrica.tabela}".encode()).hexdigest()
                    st.markdown(f"**{rubrica.codigo} — {rubrica.descricao}**")
                    st.caption(f"CNPJ: {rubrica.cnpj}" + (f" · Tabela: {rubrica.tabela}" if rubrica.tabela else ""))
                    classificacao.loc[indice, "grupo"] = st.selectbox(
                        "Como considerar esta rubrica?", GRUPOS,
                        index=GRUPOS.index(rubrica.grupo), key=f"grupo_{chave}",
                    )
                    with st.expander("Justificativa e ajuste de período", expanded=bool(detalhe.loc[(detalhe.cnpj == rubrica.cnpj) & (detalhe.codigo == rubrica.codigo) & (detalhe.tabela == rubrica.tabela), "periodo_revisar"].any())):
                        classificacao.loc[indice, "justificativa"] = st.text_input("Justificativa da classificação", key=f"justificativa_{chave}")
                        classificacao.loc[indice, "competencia_destino"] = st.text_input("Competência de destino (opcional)", key=f"destino_{chave}", help="MM/AAAA ou AAAA para apuração anual. Deixe vazio para manter a origem.")
                with st.expander("Resumo da classificação"):
                    st.dataframe(classificacao, hide_index=True)
                pendentes = classificacao.loc[~classificacao.grupo.isin(["Principal", "Apoio", "Excluir"])]
                composto = None
                if not pendentes.empty:
                    st.warning(f"Faltam classificar {len(pendentes)} rubrica(s). Nos seletores acima, troque Revisar por Principal, Apoio ou Excluir.")
                    st.dataframe(pendentes[["codigo", "descricao", "grupo"]], hide_index=True)
                    st.caption("Principal: verba principal de maternidade. Apoio: componente que será apresentado no cenário com apoios. Excluir: item fora dos dois cenários; continuará registrado no detalhe. A classificação pode ser revisada depois pela responsável jurídica.")
                else:
                    try:
                        composto = aplicar_classificacao(detalhe, classificacao)
                    except ValueError as exc:
                        st.warning(str(exc))
                with st.expander("Conferência dos lançamentos"):
                    st.dataframe(detalhe, hide_index=True)
                confirmado = st.checkbox("Revisei a classificação e os períodos das rubricas", key=f"revisao_{assinatura}")
                if composto is not None and not confirmado:
                    st.info("Classificação preenchida. Marque a confirmação de revisão acima para habilitar Gerar conciliação.")
                configuracao = hashlib.sha256((assinatura + classificacao.to_json()).encode()).hexdigest()
                if st.session_state.get("resultado_configuracao") != configuracao or not confirmado:
                    st.session_state.pop("comparativo_maternidade", None)
                if st.button("Gerar conciliação", type="primary", disabled=not confirmado or composto is None):
                    resultado = comparar_maternidade(ecac, composto)
                    resultado["Escopo da validação"] = "Conferência parcial; consultar ocorrências" if avisos or not ocorrencias.empty or not ocorrencias_ecac.empty else "Conferência dos documentos recebidos"
                    controles = [ocorrencias, pd.DataFrame([{"ocorrencia": a} for a in avisos]), ocorrencias_ecac.rename(columns={"mensagem": "ocorrencia"})]
                    st.session_state["comparativo_maternidade"] = (resultado, ecac, composto, classificacao, pd.concat(controles, ignore_index=True))
                    st.session_state["resultado_configuracao"] = configuracao
                if "comparativo_maternidade" in st.session_state:
                    resultado, dados_ecac, composto, classes, controles = st.session_state["comparativo_maternidade"]
                    st.subheader("Resultado da conciliação")
                    st.caption("Potencial crédito = excedente positivo sobre o declarado, sujeito à validação jurídica. Valor declarado superior aparece separadamente. Campos ausentes permanecem indisponíveis.")
                    monetarias = [c for c in resultado if c not in ["cnpj", "competencia", "Validação documental", "Situação", "Escopo da validação"]]
                    st.dataframe(resultado.style.format({c: dinheiro for c in monetarias}), hide_index=True)
                    consolidado = composto.groupby(["cnpj", "competencia", "grupo"], as_index=False)["valor"].sum(min_count=1)
                    excel = gerar_excel_comparativo(resultado, dados_ecac, consolidado, composto, classes, controles)
                    st.download_button("Baixar relatório final", excel, "conciliacao_salario_maternidade.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except (ValueError, KeyError, OSError) as exc:
            st.session_state.pop("comparativo_maternidade", None)
            st.error(f"Não foi possível concluir: {exc}")
    else:
        st.session_state.pop("comparativo_maternidade", None)
        st.info("Envie os três documentos para iniciar a conferência.")
