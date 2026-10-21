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
    COLUNAS as COLUNAS_ST_C170, COLUNAS_C100, COLUNAS_C190,
    diagnosticar_st_c100, diagnosticar_st_c170, diagnosticar_st_c190, diagnosticar_vendas_st_c175,
)
from auditor_sped_integrado.motor import COLUNAS as COLUNAS_TRIAGEM, TIPOS, inventariar_excel, triagem_c170
from auditor_sped_integrado.premissas_icms import simular_potencial, validar_historico_regime
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
        "IRPJ/CSLL declarado", [
            "A confirmar por período", "Misto: real e presumido",
            "Lucro real em todo período", "Lucro presumido em todo período",
        ], on_change=limpar_analises,
    )
    with st.expander("Períodos de regime informados (opcional)"):
        st.caption("Use AAAA-MM. O 0110 prevalece; divergências bloqueiam a simulação.")
        historico_tabela = st.data_editor(
            pd.DataFrame(columns=["inicio", "fim", "regime"]),
            num_rows="dynamic", hide_index=True, key="historico_regime",
            column_config={
                "regime": st.column_config.SelectboxColumn(
                    "Regime IRPJ informado", options=["Lucro presumido", "Lucro real", "Misto"],
                ),
            },
            on_change=limpar_analises,
        )
    tolerancia = st.number_input(
        "Tolerância de comparação (R$)", min_value=0.0, value=0.01, step=0.01,
        on_change=limpar_analises,
    )
    st.info("Esta escolha registra o contexto geral. O cálculo por competência usa o registro 0110 e as alíquotas efetivas do C175.")

aba_entrada, aba_regras, aba_metodo = st.tabs(["Análise", "Catálogo de regras", "Método e limites"])

with aba_entrada:
    st.subheader("Arquivos Excel convertidos pelo Sysconv")
    st.write("Selecione os Excel ou informe os caminhos completos. EFD-Contribuições com C175 permite o teste preliminar; ICMS/IPI completa a conciliação C170. ECD e ECF são opcionais no inventário.")
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
            if arquivo_pis is None:
                raise ValueError("Informe o Excel com EFD-Contribuições e aba C175.")
            historico = validar_historico_regime(historico_tabela)
            with st.spinner("Inventariando arquivos e executando as análises; Excel grandes podem levar alguns minutos..."):
                inventario = [
                    inventariar_excel(entrada[0], tipo, entrada[1])
                    for tipo, entrada in entradas.items() if entrada is not None
                ]
                abas = {item["tipo"]: set(item["abas"]) for item in inventario}
                abas_pis = abas["EFD-Contribuições"]
                abas_icms = abas.get("EFD ICMS/IPI", set())
                tem_aba_pis = lambda prefixo: any(nome.casefold().startswith(prefixo) for nome in abas_pis)
                tem_aba_icms = lambda prefixo: any(nome.casefold().startswith(prefixo) for nome in abas_icms)
                if not tem_aba_pis("c175"):
                    raise ValueError("Aba C175 não encontrada no Excel de EFD-Contribuições.")
                if arquivo_icms is not None and tem_aba_pis("c170") and tem_aba_icms("c170"):
                    achados = triagem_c170(
                        arquivo_icms[0], arquivo_pis[0], tolerancia,
                        nome_icms=arquivo_icms[1], nome_pis=arquivo_pis[1],
                    )
                else:
                    achados = pd.DataFrame(columns=COLUNAS_TRIAGEM)
                st_c170 = diagnosticar_st_c170(arquivo_pis[0]) if tem_aba_pis("c170") else pd.DataFrame(columns=COLUNAS_ST_C170)
                st_c100 = diagnosticar_st_c100(arquivo_pis[0]) if tem_aba_pis("c100") else pd.DataFrame(columns=COLUNAS_C100)
                vendas_c175 = diagnosticar_vendas_st_c175(arquivo_pis[0])
                simulacao = simular_potencial(vendas_c175, historico)
                st_c190 = diagnosticar_st_c190(arquivo_icms[0]) if arquivo_icms is not None and tem_aba_icms("c190") else pd.DataFrame(columns=COLUNAS_C190)
                relatorio = gerar_relatorio_excel(
                    inventario, achados, st_c170, st_c100, vendas_c175, st_c190, regime,
                    simulacao=simulacao, historico_regime=historico,
                )
                st.session_state["resultado_auditoria"] = {
                    "inventario": inventario,
                    "achados": achados,
                    "st_c170": st_c170,
                    "st_c100": st_c100,
                    "vendas_c175": vendas_c175,
                    "simulacao": simulacao,
                    "st_c190": st_c190,
                    "icms_fornecido": arquivo_icms is not None,
                    "relatorio": relatorio,
                }
        except Exception as erro:
            st.error(f"Não foi possível concluir a auditoria: {erro}")

    if "resultado_auditoria" in st.session_state:
        resultado = st.session_state["resultado_auditoria"]
        candidatos = resumir_candidatos(resultado["vendas_c175"], resultado["simulacao"])
        st.subheader("Resultado")
        st.info(
            "Resultado preliminar: o filtro identifica receitas e PIS/COFINS escriturados sob análise. "
            "A parcela possivelmente recuperável será quantificada após comprovar o ICMS-ST e seu vínculo com essas receitas."
        )
        a, b, c, d = st.columns(4)
        a.metric("Grupos C175 / CFOP 5405 / CST 01", len(candidatos))
        b.metric("PIS escriturado nesses grupos", moeda_br(candidatos["pis_escriturado"].sum()))
        c.metric("COFINS escriturada nesses grupos", moeda_br(candidatos["cofins_escriturada"].sum()))
        d.metric("Contribuições sob análise", moeda_br(candidatos["contribuicoes_sob_analise"].sum()))
        simulados = candidatos["simulacao_pis_cofins_uf"].dropna()
        if not simulados.empty:
            st.metric("Simulação preliminar pela alíquota geral da UF", moeda_br(simulados.sum()))
            st.caption("A simulação usa a alíquota interna geral documentada de PE ou MT, conforme a UF da nota. Não verifica a alíquota específica da mercadoria, o ICMS-ST destacado nem crédito confirmado.")
        else:
            st.caption("Sem simulação estadual automática para os dados fornecidos. A triagem e o relatório continuam disponíveis.")
        if candidatos.empty:
            st.warning("Nenhum registro foi localizado no filtro principal.")
        else:
            st.dataframe(candidatos, use_container_width=True, hide_index=True)
        with st.expander("Cobertura e outros diagnósticos"):
            if not resultado["icms_fornecido"]:
                st.warning("ICMS/IPI não fornecido: conciliação C170 e diagnóstico C190 não executados.")
            st.write(f"Achados de conciliação C170: {len(resultado['achados'])}")
            if not resultado["achados"].empty:
                st.dataframe(
                    resultado["achados"]["estado"].value_counts().rename_axis("Estado").reset_index(name="Itens"),
                    use_container_width=True, hide_index=True,
                )
            st.write(f"Entradas com ST positivo no C170: {len(resultado['st_c170'])}")
            st.write(f"Grupos C100 com ST positivo: {len(resultado['st_c100'])}")
            st.write(f"Grupos C190 com ST positivo: {len(resultado['st_c190'])}")
            if not resultado["simulacao"].empty:
                st.dataframe(
                    resultado["simulacao"]["estado_simulacao"].value_counts().rename_axis("Estado").reset_index(name="Grupos"),
                    use_container_width=True, hide_index=True,
                )
        with st.expander("Regime e alíquotas por competência"):
            colunas = ["competencia", "cnpj_estabelecimento", "regime_0110", "aliquota_pis", "aliquota_cofins"]
            st.dataframe(
                resultado["vendas_c175"][colunas].drop_duplicates().sort_values(
                    ["competencia", "cnpj_estabelecimento", "aliquota_pis", "aliquota_cofins"]
                ),
                use_container_width=True, hide_index=True,
            )
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
