from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auditor_sped_integrado.catalogo import REGRAS
from auditor_sped_integrado.motor import TIPOS, inventariar_sped, triagem_c170


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
    st.subheader("1. Inventário dos TXT originais")
    st.write("Informe os caminhos locais dos arquivos exportados pelo ReceitanetBX. O app lê os arquivos no computador e guarda no relatório somente nome, hash e contagem de registros.")
    caminhos = {tipo: st.text_input(tipo, key=f"txt_{i}") for i, tipo in enumerate(TIPOS)}
    if st.button("Inventariar TXT"):
        try:
            if not any(caminhos.values()):
                raise ValueError("Informe ao menos um TXT.")
            inventario = [inventariar_sped(caminho, tipo) for tipo, caminho in caminhos.items() if caminho.strip()]
            st.session_state["inventario"] = inventario
        except Exception as erro:
            st.error(str(erro))
    if "inventario" in st.session_state:
        inventario = st.session_state["inventario"]
        st.dataframe(pd.DataFrame([{k: v for k, v in item.items() if k != "registros"} for item in inventario]), use_container_width=True)
        for item in inventario:
            with st.expander(f"Registros: {item['tipo']}"):
                st.dataframe(pd.DataFrame(item["registros"].items(), columns=["Registro", "Ocorrências"]), use_container_width=True)
        st.download_button(
            "Baixar inventário JSON",
            data=json.dumps({"regime_informado": regime, "arquivos": inventario}, ensure_ascii=False, indent=2),
            file_name="inventario_sped.json", mime="application/json",
        )

    st.subheader("2. Triagem de itens C170 convertidos em Excel")
    st.write("Use os mesmos Excel dos projetos anteriores. O cruzamento exige chave de NF-e de 44 dígitos e número do item únicos em cada base.")
    col1, col2 = st.columns(2)
    with col1:
        caminho_icms = st.text_input("Excel EFD ICMS/IPI")
    with col2:
        caminho_pis = st.text_input("Excel EFD-Contribuições")
    if st.button("Executar triagem", type="primary"):
        try:
            if not caminho_icms or not caminho_pis:
                raise ValueError("Informe os dois arquivos Excel.")
            for caminho in (caminho_icms, caminho_pis):
                if not Path(caminho).is_file():
                    raise FileNotFoundError(caminho)
            st.session_state["achados"] = triagem_c170(caminho_icms, caminho_pis, tolerancia)
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

1. Preservar os quatro TXT originais e seus hashes SHA-256.
2. Conciliar as saídas por chave da NF-e e item, registrando linhas e arquivos de origem.
3. Confirmar a hipótese jurídica, a condição do contribuinte e a regra vigente na competência.
4. Conferir notas fiscais, apuração transmitida, recolhimentos, retificações e compensações anteriores.
5. Somente após essa conferência, calcular e validar eventual valor recuperável.

**Escopo implementado:** inventário dos quatro tipos de SPED e triagem de ICMS próprio e ICMS-ST em C170 convertido. ECD e ECF ainda são inventariados, sem interpretação contábil automática. O aplicativo não transmite arquivos, não retifica declarações e não gera pedido de compensação.
""")

