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
from auditor_sped_integrado.conferencia_nfe import ConferenciaNFe
from auditor_sped_integrado.diagnostico_st import (
    COLUNAS as COLUNAS_ST_C170, COLUNAS_C100, COLUNAS_C190,
    diagnosticar_st_c100, diagnosticar_st_c170, diagnosticar_st_c190, diagnosticar_vendas_st_c175,
)
from auditor_sped_integrado.motor import COLUNAS as COLUNAS_TRIAGEM, TIPOS, hash_arquivo, inventariar_excel, triagem_c170
from auditor_sped_integrado.premissas_icms import (
    CODIGOS_POR_UF, simular_potencial, tabela_panorama_anual,
    tabela_premissas, validar_historico_regime,
)
from auditor_sped_integrado.relatorio_excel import gerar_relatorio_excel, resumir_candidatos

VERSAO_RESULTADO = 6


def limpar_resultado() -> None:
    st.session_state.pop("resultado_auditoria", None)


def limpar_analises() -> None:
    limpar_resultado()
    st.session_state.pop("preanalise_auditoria", None)


def aliquotas_pendentes(vendas: pd.DataFrame) -> list[dict]:
    if vendas.empty:
        return []
    filtro = (
        (vendas["cfop"].astype(str) == "5405")
        & (vendas["cst_pis"].astype(str).str.zfill(2) == "01")
        & (vendas["cst_cofins"].astype(str).str.zfill(2) == "01")
        & ((vendas["fonte_aliquota_pis"] == "Ausente") | (vendas["fonte_aliquota_cofins"] == "Ausente"))
    )
    pendencias = []
    chaves = set()
    for item in vendas.loc[filtro].to_dict("records"):
        pis = float(item["aliquota_pis"]) if item["fonte_aliquota_pis"] == "C175" else None
        cofins = float(item["aliquota_cofins"]) if item["fonte_aliquota_cofins"] == "C175" else None
        chave = (item["competencia"], item["cnpj_estabelecimento"], pis, cofins)
        if chave in chaves:
            continue
        chaves.add(chave)
        pendencias.append({
            "Competência": item["competencia"], "Estabelecimento": item["cnpj_estabelecimento"],
            "PIS no C175 (%)": pis, "COFINS no C175 (%)": cofins,
            "PIS a informar (%)": None, "COFINS a informar (%)": None,
        })
    return pendencias


def moeda_br(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


st.set_page_config(page_title="Auditor SPED integrado", layout="wide")
st.title("Auditor SPED integrado")
st.caption("Análise integrada dos Excel do Sysconv com relatório único de evidências.")
resultado_guardado = st.session_state.get("resultado_auditoria")
if resultado_guardado is not None and (
    not isinstance(resultado_guardado, dict)
    or resultado_guardado.get("versao") != VERSAO_RESULTADO
):
    limpar_analises()
    st.info("O resultado em memória foi gerado por uma versão anterior. Execute novamente as análises com os arquivos já informados.")

with st.sidebar:
    st.header("Contexto")
    uf_escolha = st.selectbox(
        "UF para a simulação", ["Automática pela chave da NF-e", *sorted(CODIGOS_POR_UF)],
        on_change=limpar_resultado,
    )
    uf_selecionada = None if uf_escolha.startswith("Automática") else uf_escolha
    st.caption("A UF escolhida deve coincidir com a chave da NF-e. Premissas com vigência confirmada cobrem PE e MT. O relatório traz panorama anual das 27 UFs de 2022 a 2025 para consulta; ele não é usado no cálculo sem data de vigência.")
    if uf_selecionada:
        with st.expander("Alíquotas da UF selecionada"):
            premissas_uf = tabela_premissas().loc[lambda q: q["uf"] == uf_selecionada]
            if premissas_uf.empty:
                st.warning("Ainda não há vigência estadual confirmada para simular esta UF.")
            else:
                st.dataframe(premissas_uf[["inicio", "fim", "aliquota_geral", "fonte"]], hide_index=True)
            st.caption("Referência anual do Comsefaz; não aplicada automaticamente ao cálculo:")
            st.dataframe(
                tabela_panorama_anual().loc[
                    lambda q: (q["uf"] == uf_selecionada) & q["ano"].between(2022, 2025),
                    ["ano", "aliquota_geral_referencia"],
                ], hide_index=True,
            )
    tolerancia = st.number_input(
        "Tolerância de comparação (R$)", min_value=0.0, value=0.01, step=0.01,
        on_change=limpar_resultado,
    )

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
    if st.button("1. Ler documentos e mostrar pré-análise", type="primary"):
        limpar_analises()
        try:
            if arquivo_pis is None:
                raise ValueError("Informe o Excel com EFD-Contribuições e aba C175.")
            with st.spinner("Lendo os Excel e levantando as alíquotas escrituradas..."):
                inventario = [
                    inventariar_excel(entrada[0], tipo, entrada[1])
                    for tipo, entrada in entradas.items() if entrada is not None
                ]
                abas = {item["tipo"]: set(item["abas"]) for item in inventario}
                if not any(nome.casefold().startswith("c175") for nome in abas["EFD-Contribuições"]):
                    raise ValueError("Aba C175 não encontrada no Excel de EFD-Contribuições.")
                vendas_previas = diagnosticar_vendas_st_c175(arquivo_pis[0])
                st.session_state["preanalise_auditoria"] = {
                    "versao": VERSAO_RESULTADO,
                    "inventario": inventario,
                    "vendas_c175": vendas_previas,
                }
            st.rerun()
        except Exception as erro:
            st.error(f"Não foi possível ler os documentos: {erro}")

    preanalise = st.session_state.get("preanalise_auditoria")
    if isinstance(preanalise, dict) and preanalise.get("versao") == VERSAO_RESULTADO:
        st.subheader("Pré-análise documental")
        vendas_previas = preanalise["vendas_c175"]
        candidatos_previos = vendas_previas.loc[
            (vendas_previas["cfop"].astype(str) == "5405")
            & (vendas_previas["cst_pis"].astype(str).str.zfill(2) == "01")
            & (vendas_previas["cst_cofins"].astype(str).str.zfill(2) == "01")
        ] if not vendas_previas.empty else vendas_previas
        st.write(f"Registros C175 no filtro principal: {int(candidatos_previos['registros_c175'].sum()) if not candidatos_previos.empty else 0:,}".replace(",", "."))
        st.caption("O 0110 descreve a incidência de PIS/COFINS; não comprova, por si só, o regime de IRPJ/CSLL. As alíquotas abaixo vieram do C175.")
        if not candidatos_previos.empty:
            panorama = candidatos_previos[[
                "competencia", "cnpj_estabelecimento", "regime_0110",
                "aliquota_pis", "fonte_aliquota_pis", "aliquota_cofins",
                "fonte_aliquota_cofins", "registros_c175",
            ]].copy()
            panorama["regime_0110"] = panorama["regime_0110"].map({
                "1": "Não cumulativo", "2": "Cumulativo", "3": "Cumulativo e não cumulativo",
            }).fillna("Não informado")
            panorama = panorama.rename(columns={"regime_0110": "incidencia_pis_cofins_0110"}).sort_values(
                ["competencia", "cnpj_estabelecimento", "aliquota_pis", "aliquota_cofins"]
            )
            with st.expander("Ver incidência e alíquotas por competência", expanded=True):
                st.dataframe(panorama, use_container_width=True, hide_index=True)

        identificador_pis = next(item["sha256"] for item in preanalise["inventario"] if item["tipo"] == "EFD-Contribuições")[:12]
        st.subheader("Contexto tributário após a leitura")
        regime = st.selectbox(
            "Regime de IRPJ/CSLL no período analisado",
            ["A confirmar por período", "Misto: real e presumido", "Lucro real em todo período", "Lucro presumido em todo período"],
            index=None, placeholder="Selecione após conferir a pré-análise",
            key=f"regime_pos_documentos_{identificador_pis}", on_change=limpar_resultado,
        )
        with st.expander("Períodos de regime informados (se houver mudança)"):
            st.caption("Use AAAA-MM. O histórico de IRPJ/CSLL não substitui as alíquotas escrituradas no C175.")
            historico_tabela = st.data_editor(
                pd.DataFrame(columns=["inicio", "fim", "regime"]),
                num_rows="dynamic", hide_index=True, key=f"historico_regime_{identificador_pis}",
                column_config={
                    "regime": st.column_config.SelectboxColumn(
                        "Regime IRPJ informado", options=["Lucro presumido", "Lucro real", "Misto"],
                    ),
                },
                on_change=limpar_resultado,
            )
        pendencias = aliquotas_pendentes(vendas_previas)
        escolhas_editor = None
        if pendencias:
            st.warning("O C175 tem alíquotas vazias no filtro principal. Informe apenas esses campos para continuar.")
            quadro_pendencias = pd.DataFrame(pendencias)
            for coluna in ("PIS no C175 (%)", "COFINS no C175 (%)", "PIS a informar (%)", "COFINS a informar (%)"):
                quadro_pendencias[coluna] = pd.to_numeric(quadro_pendencias[coluna], errors="coerce")
            escolhas_editor = st.data_editor(
                quadro_pendencias, key=f"editor_aliquotas_{identificador_pis}",
                hide_index=True, use_container_width=True,
                disabled=["Competência", "Estabelecimento", "PIS no C175 (%)", "COFINS no C175 (%)"],
                column_config={
                    "Estabelecimento": st.column_config.TextColumn(),
                    "PIS a informar (%)": st.column_config.NumberColumn(min_value=0.01, max_value=100.0, step=0.01),
                    "COFINS a informar (%)": st.column_config.NumberColumn(min_value=0.01, max_value=100.0, step=0.01),
                },
                on_change=limpar_resultado,
            )

        if st.button("2. Concluir análises e gerar Excel", type="primary"):
            limpar_resultado()
            try:
                if regime is None:
                    raise ValueError("Selecione o regime de IRPJ/CSLL ou 'A confirmar por período'.")
                historico = validar_historico_regime(historico_tabela)
                if regime == "Misto: real e presumido" and not historico:
                    raise ValueError("Informe os períodos de lucro real e presumido no histórico.")
                escolhas_aliquotas = {}
                if escolhas_editor is not None:
                    for item in escolhas_editor.to_dict("records"):
                        pis_c175, cofins_c175 = item["PIS no C175 (%)"], item["COFINS no C175 (%)"]
                        pis = pis_c175 if pd.notna(pis_c175) else item["PIS a informar (%)"]
                        cofins = cofins_c175 if pd.notna(cofins_c175) else item["COFINS a informar (%)"]
                        if pd.isna(pis) or pd.isna(cofins) or float(pis) <= 0 or float(cofins) <= 0:
                            raise ValueError(f"Informe as alíquotas ausentes para {item['Competência']} / {item['Estabelecimento']}.")
                        chave = (item["Competência"], item["Estabelecimento"],
                                 float(pis_c175) if pd.notna(pis_c175) else None,
                                 float(cofins_c175) if pd.notna(cofins_c175) else None)
                        escolhas_aliquotas[chave] = (float(pis), float(cofins))
                inventario = preanalise["inventario"]
                for item in inventario:
                    entrada = entradas[item["tipo"]]
                    if entrada is None or hash_arquivo(entrada[0]) != item["sha256"]:
                        raise ValueError(f"O arquivo {item['arquivo']} mudou desde a pré-análise. Leia os documentos novamente.")
                with st.spinner("Executando as demais análises e preparando o relatório..."):
                    abas = {item["tipo"]: set(item["abas"]) for item in inventario}
                    abas_pis = abas["EFD-Contribuições"]
                    abas_icms = abas.get("EFD ICMS/IPI", set())
                    tem_aba_pis = lambda prefixo: any(nome.casefold().startswith(prefixo) for nome in abas_pis)
                    tem_aba_icms = lambda prefixo: any(nome.casefold().startswith(prefixo) for nome in abas_icms)
                    if arquivo_icms is not None and tem_aba_pis("c170") and tem_aba_icms("c170"):
                        achados = triagem_c170(
                            arquivo_icms[0], arquivo_pis[0], tolerancia,
                            nome_icms=arquivo_icms[1], nome_pis=arquivo_pis[1],
                        )
                    else:
                        achados = pd.DataFrame(columns=COLUNAS_TRIAGEM)
                    st_c170 = diagnosticar_st_c170(arquivo_pis[0]) if tem_aba_pis("c170") else pd.DataFrame(columns=COLUNAS_ST_C170)
                    st_c100 = diagnosticar_st_c100(arquivo_pis[0]) if tem_aba_pis("c100") else pd.DataFrame(columns=COLUNAS_C100)
                    with ConferenciaNFe() as conferencia_nfe:
                        vendas_c175 = diagnosticar_vendas_st_c175(
                            arquivo_pis[0], coletor_nfe=conferencia_nfe,
                            aliquotas_informadas=escolhas_aliquotas,
                        )
                        if aliquotas_pendentes(vendas_c175):
                            raise ValueError("Ainda há alíquotas C175 ausentes. Complete as escolhas na pré-análise.")
                        simulacao = simular_potencial(vendas_c175, historico, uf_selecionada)
                        st_c190 = diagnosticar_st_c190(arquivo_icms[0]) if arquivo_icms is not None and tem_aba_icms("c190") else pd.DataFrame(columns=COLUNAS_C190)
                        relatorio = gerar_relatorio_excel(
                            inventario, achados, st_c170, st_c100, vendas_c175, st_c190, regime,
                            simulacao=simulacao, historico_regime=historico,
                            uf_selecionada=uf_selecionada, conferencia_nfe=conferencia_nfe,
                        )
                    st.session_state["resultado_auditoria"] = {
                        "versao": VERSAO_RESULTADO,
                        "inventario": inventario, "achados": achados,
                        "st_c170": st_c170, "st_c100": st_c100,
                        "vendas_c175": vendas_c175, "simulacao": simulacao,
                        "st_c190": st_c190, "icms_fornecido": arquivo_icms is not None,
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
            colunas = ["competencia", "cnpj_estabelecimento", "regime_0110", "aliquota_pis", "fonte_aliquota_pis", "aliquota_cofins", "fonte_aliquota_cofins"]
            st.dataframe(
                resultado["vendas_c175"][colunas].drop_duplicates().sort_values(
                    ["competencia", "cnpj_estabelecimento", "aliquota_pis", "aliquota_cofins"]
                ),
                use_container_width=True, hide_index=True,
            )
        st.download_button(
            "Baixar relatório executivo e conferência em Excel",
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
