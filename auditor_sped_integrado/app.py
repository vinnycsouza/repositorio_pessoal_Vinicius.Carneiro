from __future__ import annotations

from dataclasses import asdict
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auditor_sped_integrado.catalogo import REGRAS
from auditor_sped_integrado.diagnostico_st import (
    diagnosticar_st_c100, diagnosticar_st_c170, diagnosticar_st_c190, diagnosticar_vendas_st_c175,
)
from auditor_sped_integrado.motor import TIPOS, inventariar_excel, triagem_c170


def limpar_analises():
    st.session_state.pop("inventario", None)
    st.session_state.pop("achados", None)
    st.session_state.pop("diagnostico_st", None)
    st.session_state.pop("diagnostico_st_c100", None)
    st.session_state.pop("diagnostico_st_c175", None)
    st.session_state.pop("diagnostico_st_c190", None)


st.set_page_config(page_title="Auditor SPED integrado", layout="wide")
st.title("Auditor SPED integrado")
st.caption("Inventário local das quatro escriturações e triagem fiscal com evidências rastreáveis.")

with st.sidebar:
    st.header("Contexto")
    regime = st.selectbox("Regime de IRPJ/CSLL", ["Lucro real", "Lucro presumido"])
    tolerancia = st.number_input("Tolerância de comparação (R$)", min_value=0.0, value=0.01, step=0.01)
    st.info("O regime é registrado como contexto. A elegibilidade depende também da operação, competência e legislação aplicável.")

aba_entrada, aba_regras, aba_metodo = st.tabs(["Análise", "Catálogo de regras", "Método e limites"])

with aba_entrada:
    st.subheader("1. Arquivos Excel convertidos pelo Sysconv")
    st.write("Para cada escrituração, selecione o Excel ou informe seu caminho completo. O inventário registra nome, hash SHA-256 e quantidade de linhas por aba.")
    entradas = {}
    for i, tipo in enumerate(TIPOS):
        modo = st.radio(
            f"Entrada {tipo}", ["Selecionar arquivo", "Informar caminho"],
            key=f"modo_excel_{i}", horizontal=True, on_change=limpar_analises,
        )
        if modo == "Selecionar arquivo":
            arquivo = st.file_uploader(
                f"Excel {tipo}", type=["xlsx", "xlsm"], key=f"excel_{i}", on_change=limpar_analises,
            )
            entradas[tipo] = (arquivo.getvalue(), arquivo.name) if arquivo is not None else None
        else:
            caminho = st.text_input(
                f"Caminho do Excel {tipo}", key=f"caminho_excel_{i}",
                placeholder=r"C:\Users\usuario\Downloads\arquivo.xlsx", on_change=limpar_analises,
            ).strip().strip('"')
            entradas[tipo] = (caminho, Path(caminho).name) if caminho else None
    if st.button("Inventariar Excel"):
        try:
            if not any(entrada is not None for entrada in entradas.values()):
                raise ValueError("Informe ao menos um arquivo Excel.")
            with st.spinner("Contando as linhas de todas as abas; arquivos grandes podem levar alguns instantes..."):
                inventario = [
                    inventariar_excel(entrada[0], tipo, entrada[1])
                    for tipo, entrada in entradas.items() if entrada is not None
                ]
            st.session_state["inventario"] = inventario
        except Exception as erro:
            st.error(str(erro))
    if "inventario" in st.session_state:
        inventario = st.session_state["inventario"]
        st.dataframe(pd.DataFrame([{k: v for k, v in item.items() if k != "abas"} for item in inventario]), use_container_width=True)
        for item in inventario:
            with st.expander(f"Abas: {item['tipo']}"):
                st.dataframe(pd.DataFrame(item["abas"].items(), columns=["Aba", "Linhas de dados"]), use_container_width=True)
        st.download_button(
            "Baixar inventário JSON",
            data=json.dumps({"regime_informado": regime, "arquivos": inventario}, ensure_ascii=False, indent=2),
            file_name="inventario_sped.json", mime="application/json",
        )

    st.subheader("2. Triagem dos itens C170")
    st.write("A triagem usa as abas C170 dos Excel de ICMS/IPI e Contribuições. Antes de comparar valores, confere chave da NF-e, item, estabelecimento, competência e tipo de operação. A cobertura do ICMS/IPI é identificada pela aba 0000.")
    arquivo_icms = entradas["EFD ICMS/IPI"]
    arquivo_pis = entradas["EFD-Contribuições"]
    if st.button("Executar triagem", type="primary"):
        try:
            if arquivo_icms is None or arquivo_pis is None:
                raise ValueError("Informe os Excel de ICMS/IPI e EFD-Contribuições.")
            with st.spinner("Lendo C170 e verificando a cobertura por estabelecimento e competência..."):
                st.session_state["achados"] = triagem_c170(
                    arquivo_icms[0], arquivo_pis[0], tolerancia,
                    nome_icms=arquivo_icms[1], nome_pis=arquivo_pis[1],
                )
        except Exception as erro:
            st.error(str(erro))
    if "achados" in st.session_state:
        achados = st.session_state["achados"]
        st.metric("Resultados da triagem C170", len(achados))
        if achados.empty:
            st.info("Nenhum indício encontrado nos itens comparáveis. Isso não atesta ausência de crédito.")
        else:
            st.dataframe(achados["estado"].value_counts().rename_axis("Estado").reset_index(name="Itens"),
                         use_container_width=True, hide_index=True)
            editavel = achados.copy()
            editavel["decisao_analista"] = "Pendente"
            editavel["justificativa_analista"] = ""
            revisado = st.data_editor(
                editavel,
                column_config={
                    "decisao_analista": st.column_config.SelectboxColumn(
                        "Decisão do analista", options=["Pendente", "Descartado", "Solicitar documentos", "Validado externamente"]
                    ),
                    "justificativa_analista": st.column_config.TextColumn("Justificativa do analista"),
                },
                disabled=list(achados.columns),
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "Baixar achados revisados CSV",
                data=revisado.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig"),
                file_name="achados_sped_revisados.csv", mime="text/csv",
            )

    st.subheader("3. ICMS-ST escriturado")
    st.write("Verifica separadamente os itens C170 e as notas C100 de Contribuições, inclusive abas divididas. Transferências aparecem separadas nos itens. Estes valores ainda não são crédito recuperável.")
    if st.button("Diagnosticar ICMS-ST nos itens C170"):
        try:
            if arquivo_pis is None:
                raise ValueError("Informe o Excel de EFD-Contribuições.")
            with st.spinner("Lendo itens C170 e somando o ICMS-ST destacado..."):
                st.session_state["diagnostico_st"] = diagnosticar_st_c170(arquivo_pis[0])
        except Exception as erro:
            st.error(str(erro))
    if "diagnostico_st" in st.session_state:
        quadro_st = st.session_state["diagnostico_st"]
        if quadro_st.empty:
            st.info("Não foram encontrados itens de entrada com ICMS-ST positivo no C170. Isso não prova ausência de ST; confira a nota de aquisição emitida pelo substituto.")
        else:
            resumo_st = quadro_st.groupby("tipo_operacao", as_index=False).agg(
                itens_com_st=("itens_com_st", "sum"),
                valor_icms_st_destacado=("valor_icms_st_destacado", "sum"),
            )
            st.dataframe(resumo_st, use_container_width=True, hide_index=True)
            st.dataframe(quadro_st, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar diagnóstico de ICMS-ST CSV",
                data=quadro_st.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig"),
                file_name="diagnostico_icms_st_c170.csv", mime="text/csv",
            )
    if st.button("Diagnosticar ICMS-ST nas notas C100"):
        try:
            if arquivo_pis is None:
                raise ValueError("Informe o Excel de EFD-Contribuições.")
            with st.spinner("Lendo todas as abas C100 e somando o ICMS-ST destacado..."):
                st.session_state["diagnostico_st_c100"] = diagnosticar_st_c100(arquivo_pis[0])
        except Exception as erro:
            st.error(str(erro))
    if "diagnostico_st_c100" in st.session_state:
        quadro_c100 = st.session_state["diagnostico_st_c100"]
        if quadro_c100.empty:
            st.info("Não foram encontradas notas C100 com ICMS-ST positivo no arquivo informado. Isso não prova ausência de ST nas aquisições.")
        else:
            st.dataframe(quadro_c100, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar diagnóstico de ICMS-ST em C100 CSV",
                data=quadro_c100.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig"),
                file_name="diagnostico_icms_st_c100.csv", mime="text/csv",
            )
    st.write("As vendas com CFOP 5405 são resumidas à parte pelo C175. O registro informa PIS/COFINS, mas não o valor de ICMS-ST retido na aquisição.")
    if st.button("Resumir vendas CFOP 5405 no C175"):
        try:
            if arquivo_pis is None:
                raise ValueError("Informe o Excel de EFD-Contribuições.")
            with st.spinner("Lendo todas as abas C175 e separando CST e alíquotas..."):
                st.session_state["diagnostico_st_c175"] = diagnosticar_vendas_st_c175(arquivo_pis[0])
        except Exception as erro:
            st.error(str(erro))
    if "diagnostico_st_c175" in st.session_state:
        quadro_c175 = st.session_state["diagnostico_st_c175"]
        if quadro_c175.empty:
            st.info("Não foram encontrados registros C175 com CFOP 5405.")
        else:
            resumo_c175 = quadro_c175.groupby(["cst_pis", "cst_cofins"], as_index=False).agg(
                registros_c175=("registros_c175", "sum"), valor_operacao=("valor_operacao", "sum"),
                valor_pis=("valor_pis", "sum"), valor_cofins=("valor_cofins", "sum"),
            )
            st.dataframe(resumo_c175, use_container_width=True, hide_index=True)
            st.dataframe(quadro_c175, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar resumo de vendas CFOP 5405 CSV",
                data=quadro_c175.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig"),
                file_name="vendas_cfop_5405_c175.csv", mime="text/csv",
            )
    if st.button("Verificar ICMS-ST agregado C190 no ICMS/IPI"):
        try:
            if arquivo_icms is None:
                raise ValueError("Informe o Excel de EFD ICMS/IPI.")
            with st.spinner("Lendo C190 do ICMS/IPI..."):
                st.session_state["diagnostico_st_c190"] = diagnosticar_st_c190(arquivo_icms[0])
        except Exception as erro:
            st.error(str(erro))
    if "diagnostico_st_c190" in st.session_state:
        quadro_c190 = st.session_state["diagnostico_st_c190"]
        st.caption("O C190 é agregado por documento e CFOP. Seus valores não devem ser somados aos de C100/C170 nem presumidos como ST da aquisição.")
        if quadro_c190.empty:
            st.info("Não foram encontrados valores positivos de ICMS-ST no C190 informado.")
        else:
            st.dataframe(quadro_c190, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar diagnóstico C190 CSV",
                data=quadro_c190.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig"),
                file_name="diagnostico_icms_st_c190.csv", mime="text/csv",
            )

with aba_regras:
    st.write("Fontes fixadas nesta versão do programa. Cada achado informa o código da regra; a interpretação deve ser conferida conforme a competência analisada.")
    st.dataframe(pd.DataFrame([asdict(regra) for regra in REGRAS]), use_container_width=True, hide_index=True)
    for regra in REGRAS:
        st.markdown(f"[{regra.codigo}: {regra.fonte}]({regra.url})")

with aba_metodo:
    st.markdown("""
**Etapas de revisão**

1. Preservar os quatro Excel do Sysconv e seus hashes SHA-256.
2. Conciliar as saídas por chave da NF-e e item, registrando linhas e arquivos de origem.
3. Confirmar a hipótese jurídica, a condição do contribuinte e a regra vigente na competência.
4. Conferir notas fiscais, apuração transmitida, recolhimentos, retificações e compensações anteriores.
5. Somente após essa conferência, calcular e validar eventual valor recuperável.

**Escopo implementado:** inventário dos quatro tipos de Excel SPED e triagem de ICMS próprio e ICMS-ST em C170. ECD e ECF ainda são inventariados, sem interpretação contábil automática. O aplicativo não transmite arquivos, não retifica declarações e não gera pedido de compensação.
""")

