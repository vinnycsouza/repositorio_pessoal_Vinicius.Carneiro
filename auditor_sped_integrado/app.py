from __future__ import annotations

from dataclasses import asdict
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
from auditor_sped_integrado.relatorio_excel import gerar_relatorio_excel, resumir_candidatos


def limpar_analises() -> None:
    st.session_state.pop("resultado_auditoria", None)


def moeda_br(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


st.set_page_config(page_title="Auditor SPED integrado", layout="wide")
st.title("Auditor SPED integrado")
st.caption("Análise integrada dos Excel do Sysconv com relatório único de evidências.")

with st.sidebar:
    st.header("Contexto")
    regime = st.selectbox(
        "Regime de IRPJ/CSLL", ["Lucro real", "Lucro presumido"], on_change=limpar_analises,
    )
    tolerancia = st.number_input(
        "Tolerância de comparação (R$)", min_value=0.0, value=0.01, step=0.01,
        on_change=limpar_analises,
    )
    st.info("O regime é registrado como contexto. A elegibilidade depende da operação, competência e legislação aplicável.")

aba_entrada, aba_regras, aba_metodo = st.tabs(["Análise", "Catálogo de regras", "Método e limites"])

with aba_entrada:
    st.subheader("Arquivos Excel convertidos pelo Sysconv")
    st.write("Selecione os Excel ou informe os caminhos completos. ICMS/IPI e EFD-Contribuições são necessários para a análise integrada; ECD e ECF são opcionais no inventário.")
    entradas = {}
    for i, tipo in enumerate(TIPOS):
        modo = st.radio(
            f"Entrada {tipo}", ["Selecionar arquivo", "Informar caminho"],
            key=f"modo_excel_{i}", horizontal=True, on_change=limpar_analises,
        )
        if modo == "Selecionar arquivo":
            arquivo = st.file_uploader(
                f"Excel {tipo}", type=["xlsx", "xlsm"], key=f"excel_{i}",
                on_change=limpar_analises,
            )
            entradas[tipo] = (arquivo.getvalue(), arquivo.name) if arquivo is not None else None
        else:
            caminho = st.text_input(
                f"Caminho do Excel {tipo}", key=f"caminho_excel_{i}",
                placeholder=r"C:\Users\usuario\Downloads\arquivo.xlsx",
                on_change=limpar_analises,
            ).strip().strip('"')
            entradas[tipo] = (caminho, Path(caminho).name) if caminho else None

    arquivo_icms = entradas["EFD ICMS/IPI"]
    arquivo_pis = entradas["EFD-Contribuições"]
    if st.button("Executar todas as análises e preparar Excel", type="primary"):
        limpar_analises()
        try:
            if arquivo_icms is None or arquivo_pis is None:
                raise ValueError("Informe os Excel de EFD ICMS/IPI e EFD-Contribuições.")
            with st.spinner("Inventariando arquivos e executando as análises; Excel grandes podem levar alguns minutos..."):
                inventario = [
                    inventariar_excel(entrada[0], tipo, entrada[1])
                    for tipo, entrada in entradas.items() if entrada is not None
                ]
                achados = triagem_c170(
                    arquivo_icms[0], arquivo_pis[0], tolerancia,
                    nome_icms=arquivo_icms[1], nome_pis=arquivo_pis[1],
                )
                st_c170 = diagnosticar_st_c170(arquivo_pis[0])
                st_c100 = diagnosticar_st_c100(arquivo_pis[0])
                vendas_c175 = diagnosticar_vendas_st_c175(arquivo_pis[0])
                st_c190 = diagnosticar_st_c190(arquivo_icms[0])
                relatorio = gerar_relatorio_excel(
                    inventario, achados, st_c170, st_c100, vendas_c175, st_c190, regime,
                )
                st.session_state["resultado_auditoria"] = {
                    "inventario": inventario,
                    "achados": achados,
                    "st_c170": st_c170,
                    "st_c100": st_c100,
                    "vendas_c175": vendas_c175,
                    "st_c190": st_c190,
                    "relatorio": relatorio,
                }
        except Exception as erro:
            st.error(f"Não foi possível concluir a auditoria: {erro}")

    if "resultado_auditoria" in st.session_state:
        resultado = st.session_state["resultado_auditoria"]
        candidatos = resumir_candidatos(resultado["vendas_c175"])
        st.subheader("Resultado")
        st.info(
            "As contribuições escrituradas mostram o universo sob revisão. "
            "O campo de crédito calculado permanece vazio quando não há ICMS-ST documental vinculado às receitas."
        )
        a, b, c = st.columns(3)
        a.metric("Grupos C175 / CFOP 5405 / CST 01", len(candidatos))
        b.metric("PIS escriturado nesses grupos", moeda_br(candidatos["pis_escriturado"].sum()))
        c.metric("COFINS escriturada nesses grupos", moeda_br(candidatos["cofins_escriturada"].sum()))
        if candidatos.empty:
            st.warning("Nenhum registro foi localizado no filtro principal.")
        else:
            st.dataframe(candidatos, use_container_width=True, hide_index=True)
        with st.expander("Cobertura e outros diagnósticos"):
            st.write(f"Achados de conciliação C170: {len(resultado['achados'])}")
            if not resultado["achados"].empty:
                st.dataframe(
                    resultado["achados"]["estado"].value_counts().rename_axis("Estado").reset_index(name="Itens"),
                    use_container_width=True, hide_index=True,
                )
            st.write(f"Entradas com ST positivo no C170: {len(resultado['st_c170'])}")
            st.write(f"Grupos C100 com ST positivo: {len(resultado['st_c100'])}")
            st.write(f"Grupos C190 com ST positivo: {len(resultado['st_c190'])}")
        st.download_button(
            "Baixar relatório completo em Excel",
            data=resultado["relatorio"],
            file_name="relatorio_auditoria_sped.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

with aba_regras:
    st.write("Fontes fixadas nesta versão do programa. Cada achado informa o código da regra; a interpretação deve ser conferida conforme a competência analisada.")
    st.dataframe(pd.DataFrame([asdict(regra) for regra in REGRAS]), use_container_width=True, hide_index=True)
    for regra in REGRAS:
        st.markdown(f"[{regra.codigo}: {regra.fonte}]({regra.url})")

with aba_metodo:
    st.markdown("""
**Etapas de revisão**

1. Preservar os Excel do Sysconv e seus hashes SHA-256.
2. Identificar receitas C175 com CFOP 5405 e CST 01 de PIS/COFINS.
3. Conciliar aquisições, ICMS-ST documentado, estoque e receitas tributadas.
4. Conferir apuração, recolhimentos e aproveitamentos anteriores.
5. Somente com evidência suficiente, quantificar eventual valor recuperável.

O aplicativo gera uma triagem e um relatório de evidências. Não altera ou retifica arquivos SPED nem declarações.
""")
