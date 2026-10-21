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
from auditor_sped_integrado.motor import TIPOS, inventariar_excel, triagem_c170


def limpar_analises():
    st.session_state.pop("inventario", None)
    st.session_state.pop("achados", None)


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
    st.write("A triagem usa os Excel de ICMS/IPI e Contribuições informados acima. O cruzamento exige chave de NF-e de 44 dígitos e número do item únicos em cada base.")
    arquivo_icms = entradas["EFD ICMS/IPI"]
    arquivo_pis = entradas["EFD-Contribuições"]
    if st.button("Executar triagem", type="primary"):
        try:
            if arquivo_icms is None or arquivo_pis is None:
                raise ValueError("Informe os Excel de ICMS/IPI e EFD-Contribuições.")
            st.session_state["achados"] = triagem_c170(
                arquivo_icms[0], arquivo_pis[0], tolerancia,
                nome_icms=arquivo_icms[1], nome_pis=arquivo_pis[1],
            )
        except Exception as erro:
            st.error(str(erro))
    if "achados" in st.session_state:
        achados = st.session_state["achados"]
        st.metric("Itens sinalizados para revisão", len(achados))
        if achados.empty:
            st.info("Nenhum indício encontrado nos itens comparáveis. Isso não atesta ausência de crédito.")
        else:
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

