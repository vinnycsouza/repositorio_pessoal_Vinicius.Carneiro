from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import date
import os
import sys
from pathlib import Path, PureWindowsPath

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auditor_sped_integrado.catalogo import MODULOS_IMPLEMENTADOS, REGRAS
from auditor_sped_integrado.conferencia_nfe import ConferenciaNFe
from auditor_sped_integrado.diagnostico_st import (
    COLUNAS as COLUNAS_ST_C170, COLUNAS_C100, COLUNAS_C190,
    diagnosticar_st_c100, diagnosticar_st_c170, diagnosticar_st_c190,
    diagnosticar_vendas_st_c170, diagnosticar_vendas_st_c175, mapear_saidas_c190,
)
from auditor_sped_integrado.motor import COLUNAS as COLUNAS_TRIAGEM, TIPOS, hash_arquivo, inventariar_excel, triagem_c170
from auditor_sped_integrado.modulo_69 import gerar_relatorio_69, levantar_tema_69
from auditor_sped_integrado.premissas_icms import (
    CODIGOS_POR_UF, simular_potencial, tabela_panorama_anual,
    tabela_premissas, validar_historico_regime,
)
from auditor_sped_integrado.prazo import classificar_competencia, data_corte
from auditor_sped_integrado.relatorio_excel import gerar_relatorio_excel, resumir_candidatos

VERSAO_RESULTADO = 10


def limpar_resultado() -> None:
    st.session_state.pop("resultado_auditoria", None)


def limpar_resultado_1125() -> None:
    resultado = st.session_state.get("resultado_auditoria")
    if isinstance(resultado, dict):
        resultado["executado_1125"] = False
        resultado["relatorio"] = None
        resultado["erro_1125"] = None


def limpar_analises() -> None:
    limpar_resultado()
    st.session_state.pop("preanalise_auditoria", None)


def preparar_nova_analise() -> None:
    geracao = st.session_state.get("geracao_analise", 0) + 1
    st.session_state.clear()
    st.session_state["geracao_analise"] = geracao


class ProgressoEtapas:
    def __init__(self, titulo: str, total: int) -> None:
        self.titulo = titulo
        self.total = total
        self.concluidas = 0
        self.barra = st.progress(0, text=f"{titulo}: 0/{total} etapas concluídas")

    def iniciar(self, descricao: str) -> None:
        self.barra.progress(
            self.concluidas / self.total,
            text=f"{self.titulo}: {self.concluidas}/{self.total} etapas concluídas · {descricao}",
        )

    def concluir(self) -> None:
        self.concluidas += 1
        self.barra.progress(
            self.concluidas / self.total,
            text=f"{self.titulo}: {self.concluidas}/{self.total} etapas concluídas",
        )


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
        origem = item.get("fonte_registro", "C175")
        pis = float(item["aliquota_pis"]) if item["fonte_aliquota_pis"] == origem else None
        cofins = float(item["aliquota_cofins"]) if item["fonte_aliquota_cofins"] == origem else None
        chave = (item["competencia"], item["cnpj_estabelecimento"], pis, cofins, origem)
        if chave in chaves:
            continue
        chaves.add(chave)
        pendencias.append({
            "Competência": item["competencia"], "Estabelecimento": item["cnpj_estabelecimento"],
            "Registro": origem, "PIS escriturado (%)": pis, "COFINS escriturada (%)": cofins,
            "PIS a informar (%)": None, "COFINS a informar (%)": None,
        })
    return pendencias


def moeda_br(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def filtrar_diagnostico(quadro: pd.DataFrame, coluna_periodo: str, referencia: date) -> pd.DataFrame:
    if quadro.empty:
        return quadro
    return quadro.loc[
        quadro[coluna_periodo].map(lambda periodo: classificar_competencia(periodo, referencia) == "dentro")
    ].reset_index(drop=True)


def normalizar_caminho_informado(valor: str) -> str:
    """Remove caracteres de formatação que podem acompanhar um caminho copiado."""
    return valor.strip().strip('"\'\ufeff\u200b\u200e\u200f\u2060').strip()


def caminho_windows_indisponivel(caminho: str) -> bool:
    """Um servidor Linux não tem acesso ao disco C: do navegador do usuário."""
    return os.name != "nt" and bool(PureWindowsPath(caminho).drive)


st.set_page_config(page_title="Auditor SPED integrado", layout="wide")
st.title("Auditor SPED integrado")
st.caption("Análise integrada dos Excel do Sysconv com relatório único de evidências.")
geracao_analise = st.session_state.setdefault("geracao_analise", 0)
resultado_guardado = st.session_state.get("resultado_auditoria")
if resultado_guardado is not None and (
    not isinstance(resultado_guardado, dict)
    or resultado_guardado.get("versao") != VERSAO_RESULTADO
):
    limpar_analises()
    st.info("O resultado em memória foi gerado por uma versão anterior. Execute novamente as análises com os arquivos já informados.")

with st.sidebar:
    st.header("Contexto")
    st.button(
        "Nova análise · limpar tudo", key="nova_analise",
        on_click=preparar_nova_analise, width="stretch",
    )
    st.caption("Limpa arquivos, contexto, pré-análise e relatórios desta sessão.")
    data_referencia = st.date_input(
        "Data de referência do levantamento", value=date.today(),
        max_value=date.today(), key=f"data_referencia_{geracao_analise}", on_change=limpar_analises,
        help="Define o corte operacional móvel de cinco anos para os dois módulos.",
    )
    st.caption(f"Recorte automático de 5 anos desde {data_corte(data_referencia):%d/%m/%Y}; mês que cruza o corte fica pendente de revisão.")
    uf_escolha = st.selectbox(
        "UF de referência · Tema 1125", ["Automática pela chave da NF-e", *sorted(CODIGOS_POR_UF)],
        key=f"uf_referencia_{geracao_analise}", on_change=limpar_resultado_1125,
    )
    uf_selecionada = None if uf_escolha.startswith("Automática") else uf_escolha
    st.caption("A UF escolhida deve coincidir com a chave da NF-e. Premissas com vigência confirmada cobrem PE e MT. O relatório traz panorama anual das 27 UFs de 2022 a 2025 para consulta; ele não é usado no cálculo sem data de vigência.")
    if uf_selecionada:
        with st.expander("Alíquotas da UF selecionada"):
            premissas_uf = tabela_premissas().loc[lambda q: q["uf"] == uf_selecionada]
            if premissas_uf.empty:
                st.warning("Ainda não há vigência estadual confirmada para calcular nesta UF.")
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
        key=f"tolerancia_{geracao_analise}", on_change=limpar_resultado_1125,
    )

aba_entrada, aba_regras, aba_metodo = st.tabs(["Análise", "Catálogo de regras", "Método e limites"])

with aba_entrada:
    st.subheader("Arquivos Excel convertidos pelo Sysconv")
    st.write("Selecione os Excel ou informe os caminhos completos. EFD-Contribuições com C170 ou C175 permite o levantamento de ICMS-ST; ICMS/IPI completa a conciliação. ECD e ECF são opcionais no inventário.")
    entradas = {}
    for i, tipo in enumerate(TIPOS):
        modo = st.radio(
            f"Entrada {tipo}", ["Selecionar arquivo", "Informar caminho"],
            key=f"modo_excel_{geracao_analise}_{i}", horizontal=True, on_change=limpar_analises,
        )
        if modo == "Selecionar arquivo":
            arquivo = st.file_uploader(
                f"Excel {tipo}", type=["xlsx", "xlsm"], key=f"excel_{geracao_analise}_{i}",
                on_change=limpar_analises,
            )
            entradas[tipo] = (arquivo.getvalue(), arquivo.name) if arquivo is not None else None
        else:
            caminho = normalizar_caminho_informado(st.text_input(
                f"Caminho do Excel {tipo}", key=f"caminho_excel_{geracao_analise}_{i}",
                placeholder=r"C:\Users\usuario\Downloads\arquivo.xlsx",
                on_change=limpar_analises,
            ))
            if caminho:
                if caminho_windows_indisponivel(caminho):
                    st.warning("Este caminho é do seu computador. No app online, use 'Selecionar arquivo' para enviar o Excel.")
                elif Path(caminho).is_file():
                    st.caption("Arquivo localizado no caminho informado.")
                else:
                    st.warning("Arquivo não localizado neste caminho. Confira o endereço ou selecione o arquivo acima.")
            entradas[tipo] = (caminho, Path(caminho).name) if caminho else None

    arquivo_icms = entradas["EFD ICMS/IPI"]
    arquivo_pis = entradas["EFD-Contribuições"]
    if st.button("1. Ler documentos e mostrar pré-análise", type="primary"):
        limpar_analises()
        try:
            if arquivo_pis is None:
                raise ValueError("Informe o Excel com EFD-Contribuições.")
            if any(
                isinstance(entrada[0], str) and caminho_windows_indisponivel(entrada[0])
                for entrada in entradas.values() if entrada is not None
            ):
                raise ValueError("O app online não acessa caminhos C: do seu computador. Use 'Selecionar arquivo' para enviar os Excel.")
            with st.spinner("Lendo os Excel e levantando as alíquotas escrituradas..."):
                arquivos_informados = [(tipo, entrada) for tipo, entrada in entradas.items() if entrada is not None]
                progresso = ProgressoEtapas("Pré-análise", len(arquivos_informados) + 4)
                inventario = []
                for tipo, entrada in arquivos_informados:
                    progresso.iniciar(f"Inventariando {tipo}")
                    inventario.append(inventariar_excel(entrada[0], tipo, entrada[1]))
                    progresso.concluir()
                progresso.iniciar("Conferindo abas disponíveis")
                abas = {item["tipo"]: set(item["abas"]) for item in inventario}
                tem_c170 = any(nome.casefold().startswith("c170") for nome in abas["EFD-Contribuições"])
                tem_c175 = any(nome.casefold().startswith("c175") for nome in abas["EFD-Contribuições"])
                if not (tem_c170 or tem_c175):
                    raise ValueError("Nenhuma aba C170 ou C175 encontrada na EFD-Contribuições.")
                progresso.concluir()
                partes = []
                progresso.iniciar("Lendo vendas C170, quando presentes")
                if tem_c170:
                    partes.append(diagnosticar_vendas_st_c170(arquivo_pis[0], data_referencia=data_referencia))
                progresso.concluir()
                progresso.iniciar("Lendo vendas C175, quando presentes")
                if tem_c175:
                    partes.append(diagnosticar_vendas_st_c175(arquivo_pis[0], data_referencia=data_referencia))
                progresso.concluir()
                progresso.iniciar("Mapeando C190 e consolidando a pré-análise")
                mapa_cfop = Counter()
                recorte_prazo = Counter()
                cobertura_pis = Counter()
                for parte in partes:
                    mapa_cfop.update(parte.attrs.get("mapa_cfop", {}))
                    recorte_prazo.update(parte.attrs.get("recorte_prazo", {}))
                    cobertura_pis.update(parte.attrs.get("cobertura_mensal", {}))
                cobertura_icms = Counter()
                mapa_c190 = (
                    mapear_saidas_c190(arquivo_icms[0], data_referencia=data_referencia,
                                       cobertura_mensal=cobertura_icms)
                    if arquivo_icms is not None and any(
                        nome.casefold().startswith("c190") for nome in abas.get("EFD ICMS/IPI", ())
                    ) else []
                )
                vendas_previas = pd.concat(partes, ignore_index=True)
                vendas_previas.attrs.clear()
                st.session_state["preanalise_auditoria"] = {
                    "versao": VERSAO_RESULTADO,
                    "inventario": inventario,
                    "vendas_c175": vendas_previas,
                    "data_referencia": data_referencia,
                    "recorte_prazo": dict(recorte_prazo),
                    "cobertura_fontes": {
                        "EFD-Contribuições": dict(cobertura_pis),
                        "EFD ICMS/IPI": dict(cobertura_icms),
                        "icms_fornecido": arquivo_icms is not None,
                    },
                    "mapa_cfop": [
                        {"Registro": fonte, "CFOP": cfop, "CST PIS": cst_pis,
                         "CST COFINS": cst_cofins, "Linhas": total,
                         "No cálculo 1125": cfop == "5405" and cst_pis == "01" and cst_cofins == "01"}
                        for (fonte, cfop, cst_pis, cst_cofins), total in sorted(mapa_cfop.items())
                    ] + mapa_c190,
                }
                progresso.concluir()
            st.rerun()
        except Exception as erro:
            st.error(f"Não foi possível ler os documentos: {erro}")

    preanalise = st.session_state.get("preanalise_auditoria")
    if isinstance(preanalise, dict) and preanalise.get("versao") == VERSAO_RESULTADO:
        st.subheader("Pré-análise documental")
        st.info(
            f"Corte operacional em {data_corte(data_referencia):%d/%m/%Y}. "
            "O mês que cruza o corte e competências anteriores não entram nos valores automáticos; "
            "a prescrição jurídica depende da data de pagamento e do histórico da medida adotada."
        )
        recorte = preanalise.get("recorte_prazo", {})
        st.caption(
            f"Linhas C170/C175 no recorte: {recorte.get('dentro', 0):,}; "
            f"mês do corte para revisão: {recorte.get('limite', 0):,}; "
            f"anteriores excluídas: {recorte.get('anterior', 0):,}.".replace(",", ".")
        )
        vendas_previas = preanalise["vendas_c175"]
        candidatos_previos = vendas_previas.loc[
            (vendas_previas["cfop"].astype(str) == "5405")
            & (vendas_previas["cst_pis"].astype(str).str.zfill(2) == "01")
            & (vendas_previas["cst_cofins"].astype(str).str.zfill(2) == "01")
        ] if not vendas_previas.empty else vendas_previas
        st.write(f"Registros C170/C175 no filtro principal: {int(candidatos_previos['registros_c175'].sum()) if not candidatos_previos.empty else 0:,}".replace(",", "."))
        if not candidatos_previos.empty:
            st.dataframe(candidatos_previos.groupby("fonte_registro")["registros_c175"].sum().rename("Registros").reset_index(), hide_index=True)
        with st.expander("Mapa da escrituração: CFOP e CST por registro", expanded=True):
            st.caption("Confira registros fora do filtro principal antes de interpretar os totais. C100/C190 têm outra granularidade e não são somados às vendas C170/C175.")
            registros = [
                {"Arquivo": item["tipo"], "Aba": aba, "Linhas no Excel": linhas}
                for item in preanalise["inventario"]
                for aba, linhas in item["abas"].items()
                if aba.casefold().startswith("c") and aba[1:4].isdigit() and int(aba[1:4]) >= 100
            ]
            st.dataframe(pd.DataFrame(registros), use_container_width=True, hide_index=True)
            st.dataframe(pd.DataFrame(preanalise.get("mapa_cfop", [])), use_container_width=True, hide_index=True)
        st.caption("O 0110 descreve a incidência de PIS/COFINS; não comprova, por si só, o regime de IRPJ/CSLL. As alíquotas abaixo vieram do registro de origem.")
        if not candidatos_previos.empty:
            panorama = candidatos_previos[[
                "competencia", "cnpj_estabelecimento", "fonte_registro", "regime_0110",
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
            key=f"regime_pos_documentos_{geracao_analise}_{identificador_pis}", on_change=limpar_resultado_1125,
        )
        with st.expander("Períodos de regime informados (se houver mudança)"):
            st.caption("Use AAAA-MM. O histórico de IRPJ/CSLL não substitui as alíquotas escrituradas.")
            historico_tabela = st.data_editor(
                pd.DataFrame(columns=["inicio", "fim", "regime"]),
                num_rows="dynamic", hide_index=True, key=f"historico_regime_{geracao_analise}_{identificador_pis}",
                column_config={
                    "regime": st.column_config.SelectboxColumn(
                        "Regime IRPJ informado", options=["Lucro presumido", "Lucro real", "Misto"],
                    ),
                },
                on_change=limpar_resultado_1125,
            )
        pendencias = aliquotas_pendentes(vendas_previas)
        escolhas_editor = None
        if pendencias:
            st.warning("Há alíquotas vazias no filtro principal do Tema 1125. Informe as disponíveis; as linhas restantes ficarão pendentes sem bloquear o Tema 69.")
            quadro_pendencias = pd.DataFrame(pendencias)
            for coluna in ("PIS escriturado (%)", "COFINS escriturada (%)", "PIS a informar (%)", "COFINS a informar (%)"):
                quadro_pendencias[coluna] = pd.to_numeric(quadro_pendencias[coluna], errors="coerce")
            escolhas_editor = st.data_editor(
                quadro_pendencias, key=f"editor_aliquotas_{geracao_analise}_{identificador_pis}",
                hide_index=True, use_container_width=True,
                disabled=["Competência", "Estabelecimento", "Registro", "PIS escriturado (%)", "COFINS escriturada (%)"],
                column_config={
                    "Estabelecimento": st.column_config.TextColumn(),
                    "PIS a informar (%)": st.column_config.NumberColumn(min_value=0.01, max_value=100.0, step=0.01),
                    "COFINS a informar (%)": st.column_config.NumberColumn(min_value=0.01, max_value=100.0, step=0.01),
                },
                on_change=limpar_resultado_1125,
            )

        st.subheader("Oportunidades do catálogo")
        st.caption("Cada bloco corresponde a uma linha de investigação. Apenas os módulos com cálculo implementado podem gerar relatório.")
        resultado_atual = st.session_state.get("resultado_auditoria") or {}
        abas_inventario = {item["tipo"]: set(item["abas"]) for item in preanalise["inventario"]}
        icms_com_saidas = arquivo_icms is not None and any(
            nome.casefold().startswith(("c170", "c190"))
            for nome in abas_inventario.get("EFD ICMS/IPI", ())
        )
        executar_1125 = executar_69 = False
        colunas_blocos = st.columns(2)
        regras_ordenadas = sorted(REGRAS, key=lambda regra: (
            {"PISCOFINS_ICMS_ST_1125": 0, "PISCOFINS_ICMS_69": 1}.get(regra.codigo, 2),
            regra.titulo,
        ))
        for indice, regra in enumerate(regras_ordenadas):
            with colunas_blocos[indice % 2]:
                with st.container(border=True):
                    st.markdown(f"**{regra.titulo}**")
                    st.caption(regra.codigo)
                    if regra.codigo not in MODULOS_IMPLEMENTADOS:
                        st.write("Em preparação")
                        st.caption(regra.tratamento)
                    elif regra.codigo == "PISCOFINS_ICMS_ST_1125":
                        concluido = bool(resultado_atual.get("executado_1125") and resultado_atual.get("relatorio"))
                        st.write("Concluído" if concluido else "Falha na última execução" if resultado_atual.get("erro_1125") else "Disponível")
                        executar_1125 = st.button("Concluir análise e gerar Excel", key="executar_tema_1125")
                        if concluido:
                            st.download_button(
                                "Baixar relatório do Tema 1125", data=resultado_atual["relatorio"],
                                file_name="relatorio_tema_1125_icms_st.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key="baixar_bloco_1125",
                            )
                    elif regra.codigo == "PISCOFINS_ICMS_69":
                        concluido = bool(resultado_atual.get("executado_69") and resultado_atual.get("relatorio_69"))
                        st.write("Concluído" if concluido else "Falha na última execução" if resultado_atual.get("erro_69") else "Disponível" if icms_com_saidas else "Falta ICMS/IPI com saídas C170 ou C190")
                        executar_69 = st.button(
                            "Concluir análise e gerar Excel", key="executar_tema_69",
                            disabled=not icms_com_saidas,
                        )
                        if concluido:
                            st.download_button(
                                "Baixar relatório do Tema 69", data=resultado_atual["relatorio_69"],
                                file_name="relatorio_tema_69_icms_proprio.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key="baixar_bloco_69",
                            )
                    else:
                        st.error("Módulo sem rotina de execução configurada.")

        if executar_1125 or executar_69:
            try:
                regime_efetivo = regime or "A confirmar por período"
                historico = validar_historico_regime(historico_tabela) if executar_1125 else ()
                if executar_1125 and regime_efetivo == "Misto: real e presumido" and not historico:
                    st.warning("Períodos de lucro real/presumido não informados; o 0110 e as alíquotas escrituradas continuarão registrados para conferência.")
                escolhas_aliquotas = {}
                if executar_1125 and escolhas_editor is not None:
                    for item in escolhas_editor.to_dict("records"):
                        pis_c175, cofins_c175 = item["PIS escriturado (%)"], item["COFINS escriturada (%)"]
                        pis = pis_c175 if pd.notna(pis_c175) else item["PIS a informar (%)"]
                        cofins = cofins_c175 if pd.notna(cofins_c175) else item["COFINS a informar (%)"]
                        if pd.isna(pis) or pd.isna(cofins) or float(pis) <= 0 or float(cofins) <= 0:
                            continue
                        chave = (item["Competência"], item["Estabelecimento"],
                                 float(pis_c175) if pd.notna(pis_c175) else None,
                                 float(cofins_c175) if pd.notna(cofins_c175) else None, item["Registro"])
                        escolhas_aliquotas[chave] = (float(pis), float(cofins))
                titulo_modulo = "Tema 1125" if executar_1125 else "Tema 69"
                progresso = ProgressoEtapas(titulo_modulo, 5 if executar_1125 else 3)
                progresso.iniciar("Conferindo os arquivos da pré-análise")
                inventario = preanalise["inventario"]
                fontes_do_modulo = {"EFD-Contribuições"}
                if arquivo_icms is not None:
                    fontes_do_modulo.add("EFD ICMS/IPI")
                for item in inventario:
                    if item["tipo"] not in fontes_do_modulo:
                        continue
                    entrada = entradas[item["tipo"]]
                    if entrada is None or hash_arquivo(entrada[0]) != item["sha256"]:
                        raise ValueError(f"O arquivo {item['arquivo']} mudou desde a pré-análise. Leia os documentos novamente.")
                progresso.concluir()
                resultado = {
                    "versao": VERSAO_RESULTADO, "inventario": inventario,
                    "achados": pd.DataFrame(columns=COLUNAS_TRIAGEM),
                    "st_c170": pd.DataFrame(columns=COLUNAS_ST_C170),
                    "st_c100": pd.DataFrame(columns=COLUNAS_C100),
                    "st_c190": pd.DataFrame(columns=COLUNAS_C190),
                    "vendas_c175": preanalise["vendas_c175"],
                    "simulacao": pd.DataFrame(), "relatorio": None,
                    "icms_fornecido": arquivo_icms is not None,
                    "candidatos_69": pd.DataFrame(), "qualidade_69": {},
                    "relatorio_69": None, "erro_1125": None, "erro_69": None,
                    "executado_1125": False, "executado_69": False,
                    "data_referencia": data_referencia,
                    "recorte_prazo": preanalise.get("recorte_prazo", {}),
                }
                resultado.update(resultado_atual)
                with st.spinner(f"Executando o {'Tema 1125' if executar_1125 else 'Tema 69'} e preparando o relatório..."):
                    abas = {item["tipo"]: set(item["abas"]) for item in inventario}
                    abas_pis = abas["EFD-Contribuições"]
                    abas_icms = abas.get("EFD ICMS/IPI", set())
                    tem_aba_pis = lambda prefixo: any(nome.casefold().startswith(prefixo) for nome in abas_pis)
                    tem_aba_icms = lambda prefixo: any(nome.casefold().startswith(prefixo) for nome in abas_icms)
                    if executar_1125:
                        erro_1125 = None
                        try:
                            progresso.iniciar("Conciliando C170 e identificando ICMS-ST escriturado")
                            if arquivo_icms is not None and tem_aba_pis("c170") and tem_aba_icms("c170"):
                                achados = triagem_c170(
                                    arquivo_icms[0], arquivo_pis[0], tolerancia,
                                    nome_icms=arquivo_icms[1], nome_pis=arquivo_pis[1],
                                )
                                achados = filtrar_diagnostico(achados, "competencia_pis", data_referencia)
                            else:
                                achados = pd.DataFrame(columns=COLUNAS_TRIAGEM)
                            st_c170 = diagnosticar_st_c170(arquivo_pis[0]) if tem_aba_pis("c170") else pd.DataFrame(columns=COLUNAS_ST_C170)
                            st_c100 = diagnosticar_st_c100(arquivo_pis[0]) if tem_aba_pis("c100") else pd.DataFrame(columns=COLUNAS_C100)
                            st_c170 = filtrar_diagnostico(st_c170, "competencia", data_referencia)
                            st_c100 = filtrar_diagnostico(st_c100, "competencia", data_referencia)
                            progresso.concluir()
                            progresso.iniciar("Conferindo vendas C170/C175 e duplicidades por NF-e")
                            with ConferenciaNFe() as conferencia_nfe:
                                partes = []
                                if tem_aba_pis("c170"):
                                    partes.append(diagnosticar_vendas_st_c170(
                                        arquivo_pis[0], coletor_nfe=conferencia_nfe,
                                        aliquotas_informadas=escolhas_aliquotas,
                                        data_referencia=data_referencia,
                                    ))
                                if tem_aba_pis("c175"):
                                    partes.append(diagnosticar_vendas_st_c175(
                                        arquivo_pis[0], coletor_nfe=conferencia_nfe,
                                        aliquotas_informadas={k[:4]: v for k, v in escolhas_aliquotas.items() if k[4] == "C175"},
                                        data_referencia=data_referencia,
                                    ))
                                vendas_st = pd.concat(partes, ignore_index=True)
                                vendas_st.attrs.clear()
                                sobreposicoes = conferencia_nfe.sobreposicoes()
                                if sobreposicoes:
                                    afetados = {(p, c, chave[:2]) for p, c, chave in sobreposicoes}
                                    for indice, item in vendas_st.iterrows():
                                        if (item["competencia"], item["cnpj_estabelecimento"], item["uf_nfe"]) in afetados:
                                            vendas_st.at[indice, "registros_duplicados_entre_abas"] += 1
                                progresso.concluir()
                                progresso.iniciar("Aplicando as premissas e conferindo C190")
                                simulacao = simular_potencial(vendas_st, historico, uf_selecionada)
                                st_c190 = diagnosticar_st_c190(arquivo_icms[0]) if arquivo_icms is not None and tem_aba_icms("c190") else pd.DataFrame(columns=COLUNAS_C190)
                                st_c190 = filtrar_diagnostico(st_c190, "competencia", data_referencia)
                                progresso.concluir()
                                progresso.iniciar("Gerando o Excel do Tema 1125")
                                relatorio = gerar_relatorio_excel(
                                    inventario, achados, st_c170, st_c100, vendas_st, st_c190, regime_efetivo,
                                    simulacao=simulacao, historico_regime=historico,
                                    uf_selecionada=uf_selecionada, conferencia_nfe=conferencia_nfe,
                                    data_referencia=data_referencia,
                                    recorte_prazo=preanalise.get("recorte_prazo", {}),
                                    cobertura_fontes=preanalise.get("cobertura_fontes"),
                                )
                                progresso.concluir()
                        except Exception as erro:
                            erro_1125 = str(erro)
                            achados = pd.DataFrame(columns=COLUNAS_TRIAGEM)
                            st_c170 = pd.DataFrame(columns=COLUNAS_ST_C170)
                            st_c100 = pd.DataFrame(columns=COLUNAS_C100)
                            st_c190 = pd.DataFrame(columns=COLUNAS_C190)
                            vendas_st = preanalise["vendas_c175"]
                            simulacao = pd.DataFrame()
                            relatorio = None
                        resultado.update({
                            "executado_1125": True, "erro_1125": erro_1125,
                            "achados": achados, "st_c170": st_c170, "st_c100": st_c100,
                            "st_c190": st_c190, "vendas_c175": vendas_st,
                            "simulacao": simulacao, "relatorio": relatorio,
                            "icms_fornecido": arquivo_icms is not None,
                        })
                    if executar_69:
                        erro_69 = None
                        if (arquivo_icms is not None and (tem_aba_pis("c170") or tem_aba_pis("c175"))
                                and (tem_aba_icms("c170") or tem_aba_icms("c190"))):
                            try:
                                progresso.iniciar("Cruzando saídas e conferindo o ICMS próprio")
                                candidatos_69, qualidade_69 = levantar_tema_69(arquivo_icms[0], arquivo_pis[0], data_referencia=data_referencia)
                                progresso.concluir()
                                progresso.iniciar("Gerando o Excel do Tema 69")
                                relatorio_69 = gerar_relatorio_69(
                                    inventario, candidatos_69, qualidade_69,
                                    data_referencia=data_referencia,
                                    cobertura_fontes=preanalise.get("cobertura_fontes"),
                                )
                                progresso.concluir()
                            except Exception as erro:
                                erro_69 = str(erro)
                                candidatos_69 = pd.DataFrame()
                                qualidade_69 = {}
                                relatorio_69 = None
                        else:
                            candidatos_69 = pd.DataFrame()
                            qualidade_69 = {}
                            relatorio_69 = None
                        resultado.update({
                            "executado_69": True, "erro_69": erro_69,
                            "candidatos_69": candidatos_69,
                            "qualidade_69": qualidade_69, "relatorio_69": relatorio_69,
                        })
                    st.session_state["resultado_auditoria"] = resultado
                st.rerun()
            except Exception as erro:
                st.error(f"Não foi possível concluir a auditoria: {erro}")

    if "resultado_auditoria" in st.session_state:
        resultado = st.session_state["resultado_auditoria"]
        candidatos = resumir_candidatos(resultado["vendas_c175"], resultado["simulacao"])
        st.subheader("Resultado")
        aba_1125, aba_69 = st.tabs(["Tema 1125 · ICMS-ST", "Tema 69 · ICMS próprio"])
        with aba_1125:
            if not resultado.get("executado_1125"):
                st.info("Este módulo ainda não foi concluído. Use o botão do bloco Tema 1125 acima.")
            else:
                if resultado.get("erro_1125"):
                    st.error(f"Tema 1125 não concluído: {resultado['erro_1125']}")
                st.info(
                    "Possível crédito identificado nas receitas e contribuições escrituradas em C170/C175. "
                    "A parcela de ICMS-ST usa a premissa estadual até a conferência das notas de aquisição."
                )
                a, b, c, d = st.columns(4)
                a.metric("Grupos C170/C175 · CFOP 5405 · CST 01", len(candidatos))
                b.metric("PIS escriturado", moeda_br(candidatos["pis_escriturado"].sum()))
                c.metric("COFINS escriturada", moeda_br(candidatos["cofins_escriturada"].sum()))
                d.metric("Contribuições sob análise", moeda_br(candidatos["contribuicoes_sob_analise"].sum()))
                potenciais = candidatos["simulacao_pis_cofins_uf"].dropna()
                if not potenciais.empty:
                    st.metric("Possível crédito pelo método da alíquota geral da UF", moeda_br(potenciais.sum()))
                else:
                    st.caption("Sem premissa estadual aplicável às notas fornecidas.")
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
                    colunas = ["competencia", "cnpj_estabelecimento", "fonte_registro", "regime_0110", "aliquota_pis", "fonte_aliquota_pis", "aliquota_cofins", "fonte_aliquota_cofins"]
                    st.dataframe(
                        resultado["vendas_c175"][colunas].drop_duplicates().sort_values(
                            ["competencia", "cnpj_estabelecimento", "fonte_registro", "aliquota_pis", "aliquota_cofins"]
                        ),
                        use_container_width=True, hide_index=True,
                    )
                if resultado["relatorio"] is not None:
                    st.download_button(
                        "Baixar relatório do Tema 1125",
                        data=resultado["relatorio"], file_name="relatorio_tema_1125_icms_st.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
        with aba_69:
            if not resultado.get("executado_69"):
                st.info("Este módulo ainda não foi concluído. Use o botão do bloco Tema 69 acima.")
            else:
                if resultado.get("erro_69"):
                    st.error(f"Tema 69 não concluído: {resultado['erro_69']}")
                elif resultado["relatorio_69"] is None:
                    st.warning("Para analisar o Tema 69, forneça as EFDs ICMS/IPI e Contribuições. O ICMS/IPI precisa trazer saídas em C170 ou C190.")
                else:
                    quadro_69 = resultado["candidatos_69"]
                    st.info("O ICMS próprio vem do C170 do ICMS/IPI e é conciliado com o C170 de Contribuições. Os valores dependem de conferir NF-e, apuração e exclusões anteriores.")
                    a, b, c = st.columns(3)
                    a.metric("Grupos NF/CFOP sob análise", len(quadro_69))
                    b.metric("Grupos com cálculo preliminar", int(quadro_69["total_potencial"].notna().sum()) if not quadro_69.empty else 0)
                    c.metric("Possível valor sob conferência", moeda_br(quadro_69["total_potencial"].sum()) if not quadro_69.empty else moeda_br(0))
                    if not quadro_69.empty:
                        st.dataframe(quadro_69, use_container_width=True, hide_index=True)
                    with st.expander("Cobertura e pendências do Tema 69"):
                        st.dataframe(
                            pd.DataFrame([resultado["qualidade_69"]]).T.rename(columns={0: "Quantidade"}),
                            use_container_width=True,
                        )
                    st.download_button(
                        "Baixar relatório do Tema 69", data=resultado["relatorio_69"],
                        file_name="relatorio_tema_69_icms_proprio.xlsx",
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
2. Mapear saídas C170/C175 por CFOP, CST, estabelecimento e competência antes do cálculo.
3. Tema 1125: examinar CFOP 5405/CST 01, conferir duplicidades e conciliar aquisições, ICMS-ST documentado, estoque e vendas.
4. Tema 69: confrontar ICMS próprio das saídas C170/C190 com receitas C170/C175, sem somar registros de granularidades diferentes.
5. Aplicar recorte operacional de cinco anos e conferir a prescrição pela data de extinção/recolhimento e eventuais medidas administrativas ou judiciais.
6. Conferir NF-e, apuração, recolhimentos e exclusões ou aproveitamentos anteriores antes de validar qualquer valor.

O aplicativo gera uma triagem e um relatório de evidências. Não altera ou retifica arquivos SPED nem declarações.
""")
