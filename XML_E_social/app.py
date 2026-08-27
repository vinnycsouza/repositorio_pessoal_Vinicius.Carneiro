import io
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from modules.auditoria import (
    _filtrar_movimentos_cp_exportacao,
    gerar_busca_recibos,
    gerar_resumo_visual,
    preparar_pacote_analitico,
)
from modules.excel_builder import FontePlanilha, gerar_workbook
from modules.busca_rubricas import (
    atualizar_selecao_rubricas,
    filtrar_rubricas_por_multibusca,
    termos_sem_correspondencia,
)
from modules.entrega_arquivo import copiar_para_downloads, exige_entrega_local
from modules.hud_progresso import extrair_hud_ingestao
from modules.data_source import SQLiteDataSource, WorkspaceContext
from modules.levantamento_sqlite import (
    FiltrosLevantamento,
    chave_ordenacao_competencia,
    competencias_no_intervalo,
    consultar_levantamento,
    consultar_rubricas,
    gerar_excel_levantamento_sqlite,
    obter_opcoes_filtros,
    rotulo_competencia,
)
from modules.processador_zip import (
    atualizar_workspace_incremental,
    carregar_resultado_sqlite_existente,
    organizar_fontes_carga_inicial,
    processar_fontes_esocial,
)
from modules.sqlite_relatorio import gerar_excel_saida_sqlite
from modules.workspace_manager import (
    abrir_workspace,
    enviar_workspace_para_lixeira,
    formatar_tamanho,
    listar_workspaces_disponiveis,
    obter_info_workspace,
    pasta_padrao_workspaces,
)
from utils.helpers import decimal_br


st.set_page_config(page_title="Composição da Incidência CP — eSocial", layout="wide")

st.title("Composição da Incidência CP — eSocial")
st.caption(
    "Versão 10.0 Engine V4: parsers versionados, migração segura, reconciliação S-5011 e Workspace persistente."
)


def _oferecer_arquivo_gerado(
    caminho: str | Path,
    *,
    label: str,
    nome: str,
    mime: str,
    key: str,
) -> None:
    arquivo = Path(caminho).expanduser().resolve()
    if not exige_entrega_local(arquivo):
        with arquivo.open("rb") as fp:
            st.download_button(
                label=label,
                data=fp,
                file_name=nome,
                mime=mime,
                use_container_width=True,
                key=key,
            )
        return

    st.warning(
        f"O arquivo possui {formatar_tamanho(arquivo.stat().st_size)} e não pode ser "
        "transferido pelo botão do navegador sem consumir memória excessiva. "
        "Ele está completo e salvo no Workspace."
    )
    coluna_abrir, coluna_copiar = st.columns(2)
    if coluna_abrir.button(
        "📂 Abrir pasta do relatório",
        use_container_width=True,
        key=f"{key}_abrir_pasta",
    ):
        abrir_workspace(arquivo.parent)
    if coluna_copiar.button(
        "Copiar relatório para Downloads",
        use_container_width=True,
        key=f"{key}_copiar_downloads",
    ):
        with st.spinner("Copiando o relatório sem carregá-lo na memória..."):
            destino = copiar_para_downloads(arquivo)
        st.success(f"Relatório copiado para: {destino}")


@st.cache_data(show_spinner=False, ttl=30)
def _catalogo_workspaces_disponiveis():
    return listar_workspaces_disponiveis()

if "modulo_ativo" not in st.session_state:
    st.session_state["modulo_ativo"] = "Relatório de Incidência CP"

with st.sidebar:
    st.header("Módulo de funcionamento")
    modulo_ativo = st.radio(
        "Escolha o que deseja fazer",
        ["Relatório de Incidência CP", "Levantamento de Verbas"],
        horizontal=False,
        key="modulo_ativo",
    )

    st.markdown("---")
    st.header("Entrada")
    if modulo_ativo == "Relatório de Incidência CP":
        modo_entrada = st.radio(
            "Modo de entrada",
            ["ZIP(s) do eSocial", "SQLite existente"],
            help="Use SQLite existente para reaproveitar um processamento.db concluído sem reler os XMLs.",
        )
    else:
        modo_entrada = st.radio(
            "Modo de entrada",
            [
                "ZIP(s) do eSocial",
                "Excel consolidado / levantamento",
                "Workspace (SQLite existente)",
            ],
            help="O Workspace reutiliza processamento.db sem reler XML ou planilhas gigantes.",
        )

    arquivos_principais = []
    caminhos_principais = []
    arquivos_historico = []
    caminhos_historico = []
    arquivos_recibos = []
    caminhos_recibos = []
    arquivo_excel = None
    caminho_sqlite_existente = ""
    gerar_relatorio = False
    workspace_levantamento_reutilizavel = None
    if (
        modulo_ativo == "Levantamento de Verbas"
        and modo_entrada == "ZIP(s) do eSocial"
        and st.session_state.get("resultado_v82")
    ):
        try:
            workspace_levantamento_reutilizavel = WorkspaceContext.from_resultado(
                st.session_state["resultado_v82"]
            )
        except (OSError, ValueError):
            workspace_levantamento_reutilizavel = None

    if modo_entrada == "ZIP(s) do eSocial" and workspace_levantamento_reutilizavel is None:
        st.subheader("1. Arquivos principais")
        st.caption("Obrigatório: downloads normais do eSocial, como S-1010, S-1200, S-5001, S-5011 e S-3000.")
        origem_principal = st.radio(
            "Origem dos arquivos principais",
            ["Upload pelo navegador", "Arquivos/pasta local"],
            key="origem_principal",
        )
        if origem_principal == "Upload pelo navegador":
            arquivos_principais = st.file_uploader(
                "Selecione ZIP/XML principais",
                type=["zip", "xml"], accept_multiple_files=True,
                key="arquivos_principais",
            )
        else:
            texto_principal = st.text_area(
                "Caminhos dos arquivos principais",
                placeholder="C:\\eSocial\\cliente\\downloads\\\\nou\nC:\\eSocial\\cliente\\parte_01.zip",
                key="caminhos_principais",
            )
            caminhos_principais = [x.strip().strip('"') for x in texto_principal.splitlines() if x.strip()]

        incluir_historico = st.checkbox(
            "Incluir histórico complementar",
            value=False,
            key="incluir_historico_carga_inicial",
            help=(
                "Use quando a fonte principal contiver somente os períodos mais "
                "recentes e você já possuir os arquivos dos períodos anteriores."
            ),
        )
        if incluir_historico:
            st.caption(
                "Selecione os períodos anteriores. A Engine processará esse histórico "
                "antes da fonte principal no mesmo Workspace."
            )
            origem_historico = st.radio(
                "Origem do histórico complementar",
                ["Upload pelo navegador", "Arquivos/pasta local"],
                key="origem_historico_carga_inicial",
            )
            if origem_historico == "Upload pelo navegador":
                arquivos_historico = st.file_uploader(
                    "Selecione ZIP/XML do histórico complementar",
                    type=["zip", "xml"],
                    accept_multiple_files=True,
                    key="arquivos_historico_carga_inicial",
                )
            else:
                texto_historico = st.text_area(
                    "Caminhos do histórico complementar",
                    placeholder="C:\\eSocial\\cliente\\historico_2018_2021.zip",
                    key="caminhos_historico_carga_inicial",
                )
                caminhos_historico = [
                    x.strip().strip('"')
                    for x in texto_historico.splitlines()
                    if x.strip()
                ]

        st.markdown("---")
        st.subheader("2. Complementação opcional")
        st.caption("Recibos S-1010. Deixe vazio no primeiro relatório e use somente depois de identificar rubricas sem S-1010.")
        origem_recibos = st.radio(
            "Origem dos recibos",
            ["Upload pelo navegador", "Arquivos/pasta local"],
            key="origem_recibos",
        )
        if origem_recibos == "Upload pelo navegador":
            arquivos_recibos = st.file_uploader(
                "Selecione ZIP/XML de recibos",
                type=["zip", "xml"], accept_multiple_files=True,
                key="arquivos_recibos",
            )
        else:
            texto_recibos = st.text_area(
                "Caminhos dos recibos",
                placeholder="C:\\eSocial\\cliente\\recibos\\",
                key="caminhos_recibos_v82",
            )
            caminhos_recibos = [x.strip().strip('"') for x in texto_recibos.splitlines() if x.strip()]

        gerar_relatorio = st.button("Gerar Relatório", type="primary", use_container_width=True)
    elif modo_entrada == "ZIP(s) do eSocial":
        st.success(
            "Workspace atual reutilizado automaticamente. Os XMLs não serão processados novamente."
        )
        st.caption(f"SQLite: {workspace_levantamento_reutilizavel.db_path}")
    elif modo_entrada in {"SQLite existente", "Workspace (SQLite existente)"}:
        st.subheader("Banco já processado")
        contexto_ativo = None
        if modo_entrada == "Workspace (SQLite existente)" and st.session_state.get("resultado_v82"):
            try:
                contexto_ativo = WorkspaceContext.from_resultado(
                    st.session_state["resultado_v82"]
                )
            except (OSError, ValueError):
                contexto_ativo = None
        if contexto_ativo is not None:
            caminho_sqlite_existente = str(contexto_ativo.db_path)
            st.success("Workspace atual da sessão selecionado automaticamente.")
            try:
                info_ativo = obter_info_workspace(st.session_state["resultado_v82"])
                st.markdown(f"**Empresa:** {info_ativo.nome_empresa}")
                st.markdown(f"**CNPJ:** {info_ativo.cnpj}")
                st.markdown("**SQLite:** `processamento.db`")
                st.markdown("**Status:** Pronto")
            except (OSError, ValueError):
                st.caption(f"SQLite: {contexto_ativo.db_path}")
            if st.button(
                "Escolher outro Workspace",
                use_container_width=True,
                key="trocar_workspace_levantamento",
            ):
                st.session_state.pop("resultado_v82", None)
                st.session_state.pop("exibir_workspace_v952", None)
                st.rerun()
        else:
            forma_selecao_workspace = st.radio(
                "Como localizar o Workspace",
                ["Selecionar da lista", "Informar caminho manualmente"],
                horizontal=False,
                key="forma_selecao_workspace",
            )
            if forma_selecao_workspace == "Selecionar da lista":
                cabecalho_lista, atualizar_lista = st.columns([4, 1])
                cabecalho_lista.caption(
                    f"Pasta pesquisada: `{pasta_padrao_workspaces()}`"
                )
                if atualizar_lista.button(
                    "↻",
                    help="Atualizar lista de Workspaces",
                    key="atualizar_catalogo_workspaces",
                    use_container_width=True,
                ):
                    _catalogo_workspaces_disponiveis.clear()
                    st.rerun()
                catalogo_workspaces = _catalogo_workspaces_disponiveis()
                if not catalogo_workspaces:
                    st.warning(
                        "Nenhum Workspace foi encontrado na pasta padrão. "
                        "Use o caminho manual se ele estiver em outro local."
                    )
                else:
                    workspace_selecionado = st.selectbox(
                        "Workspace disponível",
                        catalogo_workspaces,
                        format_func=lambda item: item.rotulo,
                        key="workspace_catalogo_selecionado",
                    )
                    st.caption(
                        f"SQLite: {formatar_tamanho(workspace_selecionado.tamanho_sqlite)} · "
                        f"XMLs: {workspace_selecionado.quantidade_xml:,} · "
                        f"Caminho: {workspace_selecionado.caminho}".replace(",", ".")
                    )
                    if not workspace_selecionado.carregavel:
                        st.warning(
                            "Este Workspace está interrompido ou em processamento e não pode "
                            "ser aberto como base concluída."
                        )
                    if st.button(
                        "Carregar Workspace selecionado",
                        type="primary",
                        use_container_width=True,
                        disabled=not workspace_selecionado.carregavel,
                        key="carregar_workspace_catalogo",
                    ):
                        caminho_sqlite_existente = str(
                            workspace_selecionado.db_path
                        )
                        gerar_relatorio = True
            else:
                caminho_sqlite_existente = st.text_input(
                    "Caminho do processamento.db ou da pasta do Workspace",
                    placeholder=r"C:\Users\vinny\AppData\Local\XML_eSocial\workspaces\esocial_v3_...",
                    help="Informe a pasta ou o banco. Os XMLs não serão processados novamente.",
                )
                gerar_relatorio = st.button(
                    "Carregar Workspace" if modo_entrada == "Workspace (SQLite existente)" else "Carregar banco existente",
                    type="primary",
                    use_container_width=True,
                )
    else:
        arquivo_excel = st.file_uploader(
            "Selecione o Excel consolidado", type=["xlsx"], accept_multiple_files=False,
            help="Modelo esperado: abas 02_rubricas_cp e 03_movimentos_cp.",
        )

    st.markdown("---")
    mensagem_workspace = st.session_state.pop("mensagem_workspace_v952", None)
    if mensagem_workspace:
        st.success(mensagem_workspace)

    resultado_workspace = (
        st.session_state.get("resultado_v82")
        if modo_entrada in {"ZIP(s) do eSocial", "SQLite existente", "Workspace (SQLite existente)"}
        else None
    )
    if st.button(
        "Gerenciar Workspace Atual",
        use_container_width=True,
        help="Exibe e gerencia somente o Workspace atualmente carregado.",
    ):
        st.session_state["exibir_workspace_v952"] = True

    if resultado_workspace is None:
        st.caption("Carregue ou processe um Workspace para habilitar o gerenciamento.")
        st.session_state.pop("exibir_workspace_v952", None)
        st.session_state.pop("confirmar_lixeira_workspace_v952", None)
    elif st.session_state.get("exibir_workspace_v952"):
        try:
            info_workspace = obter_info_workspace(resultado_workspace)
        except (OSError, ValueError) as exc:
            st.error(str(exc))
        else:
            with st.expander("Workspace atualmente em uso", expanded=True):
                st.markdown(f"**Empresa:** {info_workspace.nome_empresa}")
                st.markdown(f"**CNPJ:** {info_workspace.cnpj}")
                st.markdown(f"**Workspace:** `{info_workspace.nome_workspace}`")
                st.markdown(f"**Caminho:** `{info_workspace.caminho}`")
                st.markdown(f"**Status:** {info_workspace.status}")
                st.markdown(
                    f"**Espaço ocupado:** {formatar_tamanho(info_workspace.tamanho_total)}"
                )
                st.markdown(
                    f"**Banco SQLite:** {formatar_tamanho(info_workspace.tamanho_sqlite)}"
                )
                periodo_workspace = (
                    f"{info_workspace.periodo_minimo} a {info_workspace.periodo_maximo}"
                    if info_workspace.periodo_minimo or info_workspace.periodo_maximo
                    else "Não identificado"
                )
                st.markdown(f"**Período carregado:** {periodo_workspace}")
                st.markdown(
                    f"**XMLs catalogados:** {info_workspace.quantidade_xml:,}".replace(",", ".")
                )
                st.markdown(
                    f"**Engine / parser:** {info_workspace.versao_engine or 'Legado'} / "
                    f"{info_workspace.versao_parser or 'Legado'}"
                )
                st.markdown(
                    f"**Consistência de recibos:** versão "
                    f"{info_workspace.versao_consistencia or 'pendente de verificação'}"
                )

                if st.button(
                    "📂 Abrir Workspace",
                    use_container_width=True,
                    key="abrir_workspace_v952",
                ):
                    try:
                        abrir_workspace(info_workspace.caminho)
                    except OSError as exc:
                        st.error(f"Não foi possível abrir o Workspace: {exc}")

                if st.button(
                    "➕ Adicionar complementos ao Workspace",
                    use_container_width=True,
                    disabled=info_workspace.status == "Em processamento",
                    key="abrir_complementos_workspace",
                ):
                    st.session_state["exibir_complementos_workspace"] = True

                if st.session_state.get("exibir_complementos_workspace"):
                    with st.container(border=True):
                        st.markdown("#### Adicionar complementos")
                        st.caption(
                            "XMLs já conhecidos serão obrigatoriamente ignorados pelo SHA-256. "
                            "A atualização ocorrerá no mesmo processamento.db."
                        )
                        origem_complementos = st.radio(
                            "Origem dos complementos",
                            ["Upload pelo navegador", "Arquivo/pasta local"],
                            key="origem_complementos_workspace",
                        )
                        uploads_complementos = []
                        caminhos_complementos = ""
                        if origem_complementos == "Upload pelo navegador":
                            uploads_complementos = st.file_uploader(
                                "ZIP/XML complementares",
                                type=["zip", "xml"],
                                accept_multiple_files=True,
                                key="uploads_complementos_workspace",
                            )
                        else:
                            caminhos_complementos = st.text_area(
                                "Caminhos de arquivos ou pastas (um por linha)",
                                key="caminhos_complementos_workspace",
                            )
                        st.checkbox(
                            "Ignorar XMLs já processados (obrigatório)",
                            value=True,
                            disabled=True,
                            key="ignorar_duplicados_complementos",
                        )
                        st.checkbox(
                            "Recalcular consolidações ao concluir (obrigatório)",
                            value=True,
                            disabled=True,
                            key="recalcular_complementos",
                        )
                        c_cancelar, c_processar = st.columns(2)
                        if c_cancelar.button(
                            "Cancelar", use_container_width=True, key="cancelar_complementos"
                        ):
                            st.session_state.pop("exibir_complementos_workspace", None)
                            st.rerun()
                        if c_processar.button(
                            "Processar complementos",
                            use_container_width=True,
                            key="processar_complementos",
                        ):
                            fontes_complementos = [
                                (arquivo.name, arquivo.getvalue())
                                for arquivo in uploads_complementos or []
                            ]
                            for linha in caminhos_complementos.splitlines():
                                caminho = Path(linha.strip().strip('"')).expanduser()
                                if not caminho.exists():
                                    st.error(f"Caminho não localizado: {caminho}")
                                    st.stop()
                                if caminho.is_dir():
                                    fontes_complementos.extend(
                                        (str(item), str(item))
                                        for item in caminho.rglob("*")
                                        if item.is_file()
                                        and item.suffix.lower() in {".zip", ".xml"}
                                    )
                                elif caminho.suffix.lower() in {".zip", ".xml"}:
                                    fontes_complementos.append((str(caminho), str(caminho)))
                            if not fontes_complementos:
                                st.error("Selecione ao menos um ZIP/XML complementar.")
                                st.stop()
                            st.markdown("### Atualização incremental do Workspace")
                            barra_etapa_inc = st.progress(0, text="Etapa atual — aguardando início...")
                            barra_inc = st.progress(0, text="Progresso geral — 0%")
                            status_inc = st.empty()
                            estado_progresso_inc = {"maior_geral": 0.0}

                            def atualizar_inc(valor: float, mensagem: str, info=None):
                                estado_progresso_inc["maior_geral"] = max(
                                    estado_progresso_inc["maior_geral"], float(valor)
                                )
                                geral = max(0, min(100, int(round(estado_progresso_inc["maior_geral"] * 100))))
                                etapa = geral if info is None else int(round(info.percentual_etapa * 100))
                                titulo_etapa = "Etapa atual" if info is None else info.titulo_etapa
                                detalhes = mensagem if info is None else (info.detalhes or mensagem)
                                barra_etapa_inc.progress(etapa, text=f"{titulo_etapa} — {etapa}%")
                                barra_inc.progress(geral, text=f"Progresso geral — {geral}%")
                                status_inc.caption(detalhes)

                            atualizar_inc._suporta_progresso_detalhado = True

                            try:
                                resultado_atualizado = atualizar_workspace_incremental(
                                    info_workspace.caminho,
                                    fontes_complementos,
                                    progress_callback=atualizar_inc,
                                    origem=origem_complementos,
                                )
                            except Exception as exc:
                                status_inc.error(f"Carga interrompida com segurança: {exc}")
                                st.exception(exc)
                                st.stop()
                            st.session_state["resultado_v82"] = resultado_atualizado
                            st.session_state.pop("exibir_complementos_workspace", None)
                            st.cache_data.clear()
                            resumo_inc = resultado_atualizado.get("carga_incremental", {})
                            st.session_state["mensagem_workspace_v952"] = (
                                "Carga incremental concluída — "
                                f"XMLs recebidos: {resumo_inc.get('quantidade_xml_localizados', 0):,}; "
                                f"novos: {resumo_inc.get('quantidade_xml_novos', 0):,}; "
                                f"duplicados: {resumo_inc.get('quantidade_duplicados', 0):,}; "
                                f"erros: {resumo_inc.get('quantidade_erros', 0):,}."
                            ).replace(",", ".")
                            st.rerun()

                if not st.session_state.get("confirmar_lixeira_workspace_v952"):
                    if st.button(
                        "🗑 Enviar Workspace para a Lixeira",
                        use_container_width=True,
                        disabled=info_workspace.status == "Em processamento",
                        key="solicitar_lixeira_workspace_v952",
                    ):
                        st.session_state["confirmar_lixeira_workspace_v952"] = True
                        st.rerun()
                    if info_workspace.status == "Em processamento":
                        st.warning(
                            "O Workspace não pode ser movido enquanto está em processamento."
                        )
                else:
                    st.warning(
                        "Deseja realmente enviar este Workspace para a Lixeira?\n\n"
                        f"**Workspace:** {info_workspace.nome_workspace}\n\n"
                        f"**Empresa:** {info_workspace.nome_empresa}\n\n"
                        f"**Espaço ocupado:** {formatar_tamanho(info_workspace.tamanho_total)}"
                    )
                    coluna_cancelar, coluna_enviar = st.columns(2)
                    with coluna_cancelar:
                        if st.button(
                            "Cancelar",
                            use_container_width=True,
                            key="cancelar_lixeira_workspace_v952",
                        ):
                            st.session_state.pop(
                                "confirmar_lixeira_workspace_v952", None
                            )
                            st.rerun()
                    with coluna_enviar:
                        if st.button(
                            "Enviar para Lixeira",
                            type="primary",
                            use_container_width=True,
                            key="confirmar_lixeira_workspace_v952",
                        ):
                            try:
                                enviar_workspace_para_lixeira(info_workspace.caminho)
                            except (OSError, ValueError) as exc:
                                st.error(
                                    f"Não foi possível enviar o Workspace para a Lixeira: {exc}"
                                )
                            else:
                                for chave in [
                                    "resultado_v82",
                                    "fontes_principais_v82",
                                    "fontes_historico_v82",
                                    "fontes_recibos_v82",
                                    "exibir_workspace_v952",
                                    "confirmar_lixeira_workspace_v952",
                                ]:
                                    st.session_state.pop(chave, None)
                                st.session_state["mensagem_workspace_v952"] = (
                                    "Workspace enviado para a Lixeira com segurança."
                                )
                                st.rerun()

    if st.button("Resetar aplicação", use_container_width=True):
        st.cache_data.clear()
        for chave in [
            "resultado_v82",
            "fontes_principais_v82",
            "fontes_historico_v82",
            "fontes_recibos_v82",
        ]:
            st.session_state.pop(chave, None)
        st.rerun()


def _resolver_fontes_zip(arquivos_upload, caminhos_informados, prefixo=""):
    fontes = []
    erros = []
    for arquivo in arquivos_upload or []:
        fontes.append((f"{prefixo}{arquivo.name}", arquivo.getvalue()))

    for texto in caminhos_informados or []:
        caminho = Path(texto).expanduser()
        if caminho.is_dir():
            encontrados = sorted([p for p in caminho.rglob("*") if p.is_file() and p.suffix.lower() in {".zip", ".xml"}])
            if not encontrados:
                erros.append(f"Nenhum ZIP/XML encontrado em: {caminho}")
            for item in encontrados:
                fontes.append((f"{prefixo}{item.name}", str(item)))
        elif caminho.is_file() and caminho.suffix.lower() in {".zip", ".xml"}:
            fontes.append((f"{prefixo}{caminho.name}", str(caminho)))
        else:
            erros.append(f"Caminho não localizado ou não é ZIP/XML: {caminho}")
    return fontes, erros


def executar_processamento(fontes, progress_callback=None):
    return processar_fontes_esocial(fontes, progress_callback=progress_callback)


def _criar_progresso(titulo: str):
    st.markdown(f"### {titulo}")
    barra_etapa = st.progress(0, text="Etapa atual — aguardando início...")
    barra_geral = st.progress(0, text="Progresso geral — 0%")
    status = st.empty()
    maior_geral = 0.0
    hud_ingestao = None

    def criar_hud_ingestao():
        with st.container(border=True):
            st.markdown("### Fonte atual")
            fonte = st.empty()
            colunas = st.columns(3)
            itens_lidos = colunas[0].empty()
            itens_restantes = colunas[1].empty()
            volume_lido = colunas[2].empty()
            colunas = st.columns(3)
            xml_catalogados = colunas[0].empty()
            ritmo = colunas[1].empty()
            eta = colunas[2].empty()
            st.divider()
            st.markdown("### Total da ingestão")
            colunas = st.columns(3)
            fontes_descobertas = colunas[0].empty()
            fontes_concluidas = colunas[1].empty()
            fontes_em_leitura = colunas[2].empty()
            colunas = st.columns(3)
            fontes_pendentes = colunas[0].empty()
            fontes_com_erro = colunas[1].empty()
            volume_restante = colunas[2].empty()
            observacao = st.empty()
        return {
            "fonte": fonte, "itens_lidos": itens_lidos,
            "itens_restantes": itens_restantes, "volume_lido": volume_lido,
            "xml_catalogados": xml_catalogados, "ritmo": ritmo, "eta": eta,
            "fontes_descobertas": fontes_descobertas,
            "fontes_concluidas": fontes_concluidas,
            "fontes_em_leitura": fontes_em_leitura,
            "fontes_pendentes": fontes_pendentes,
            "fontes_com_erro": fontes_com_erro,
            "volume_restante": volume_restante, "observacao": observacao,
        }

    def atualizar_hud(campos):
        hud_ingestao["fonte"].caption(campos.fonte)
        hud_ingestao["itens_lidos"].metric("Itens lidos", campos.itens_lidos)
        hud_ingestao["itens_restantes"].metric("Itens restantes", campos.itens_restantes)
        hud_ingestao["volume_lido"].metric("Volume lido", campos.volume_lido)
        hud_ingestao["xml_catalogados"].metric("XMLs catalogados", campos.xml_catalogados)
        hud_ingestao["ritmo"].metric(
            "Ritmo",
            campos.ritmo,
            help="Ritmo observado na fonte atual; pode variar conforme o tamanho e a complexidade dos XMLs.",
        )
        hud_ingestao["eta"].metric("ETA desta fonte", campos.eta)
        hud_ingestao["fontes_descobertas"].metric("Fontes descobertas", campos.fontes_descobertas)
        hud_ingestao["fontes_concluidas"].metric("Concluídas", campos.fontes_concluidas)
        hud_ingestao["fontes_em_leitura"].metric("Em leitura", campos.fontes_em_leitura)
        hud_ingestao["fontes_pendentes"].metric("Pendentes", campos.fontes_pendentes)
        hud_ingestao["fontes_com_erro"].metric("Com erro", campos.fontes_com_erro)
        hud_ingestao["volume_restante"].metric(
            "Volume restante conhecido",
            campos.volume_restante,
            help="Considera as fontes já descobertas. ZIPs aninhados ainda não abertos podem ampliar esse total.",
        )
        hud_ingestao["observacao"].caption(
            f"Tempo decorrido nesta fonte: {campos.tempo_decorrido}. "
            "A estimativa pode variar conforme o tamanho e a complexidade dos XMLs."
        )

    def atualizar(valor: float, mensagem: str, info=None):
        nonlocal maior_geral, hud_ingestao
        maior_geral = max(maior_geral, max(0.0, min(1.0, float(valor))))
        percentual_geral = int(round(maior_geral * 100))
        if info is None:
            percentual_etapa = percentual_geral
            titulo_etapa = "Etapa atual"
            detalhes = mensagem
        else:
            percentual_etapa = int(round(info.percentual_etapa * 100))
            titulo_etapa = info.titulo_etapa
            detalhes = info.detalhes or mensagem
        barra_etapa.progress(
            percentual_etapa,
            text=f"{titulo_etapa} — {percentual_etapa}%",
        )
        barra_geral.progress(percentual_geral, text=f"Progresso geral — {percentual_geral}%")
        if info is not None and info.etapa == "ingestao":
            campos = extrair_hud_ingestao(detalhes, mensagem)
            if campos.fonte != "—":
                if hud_ingestao is None:
                    hud_ingestao = criar_hud_ingestao()
                atualizar_hud(campos)
                status.empty()
            else:
                status.caption(detalhes)
        else:
            status.caption(detalhes)

    atualizar._suporta_progresso_detalhado = True
    return atualizar, barra_geral, status


@st.cache_data(show_spinner=False)
def carregar_excel_consolidado(excel_bytes: bytes):
    origem = io.BytesIO(excel_bytes)
    xls = pd.ExcelFile(origem)

    def ler_aba(nome: str) -> pd.DataFrame:
        if nome in xls.sheet_names:
            return pd.read_excel(xls, sheet_name=nome)
        return pd.DataFrame()

    df_rubricas_cp = ler_aba("02_rubricas_cp")
    df_movimentos_cp = ler_aba("03_movimentos_cp")
    df_empresa = ler_aba("00_empresa")

    # Normalização mínima para aceitar planilhas fabricadas manualmente no padrão do app.
    for df in (df_rubricas_cp, df_movimentos_cp):
        if not df.empty:
            df.columns = [str(c).strip() for c in df.columns]

    return {
        "rubricas_cp": df_rubricas_cp,
        "movimentos_cp": df_movimentos_cp,
        "empresa": df_empresa,
        "abas": pd.DataFrame({"aba_excel": xls.sheet_names}),
    }


def _assinatura_banco_sqlite(db_path: str | Path) -> tuple[int, int]:
    """Assinatura leve para invalidar caches caso o banco seja substituído."""
    stat = Path(db_path).stat()
    return stat.st_mtime_ns, stat.st_size


@st.cache_data(show_spinner=False)
def _opcoes_levantamento_sqlite(
    db_path: str, mtime_ns: int, tamanho: int
) -> dict[str, list[str]]:
    contexto = WorkspaceContext.from_path(db_path, origem="cache_filtros")
    return obter_opcoes_filtros(SQLiteDataSource(contexto))


@st.cache_data(show_spinner=False)
def _rubricas_levantamento_sqlite(
    db_path: str,
    mtime_ns: int,
    tamanho: int,
    filtros: FiltrosLevantamento,
) -> pd.DataFrame:
    contexto = WorkspaceContext.from_path(db_path, origem="cache_rubricas")
    return consultar_rubricas(SQLiteDataSource(contexto), filtros)


@st.cache_data(show_spinner=False)
def _resultado_levantamento_sqlite(
    db_path: str,
    mtime_ns: int,
    tamanho: int,
    filtros: FiltrosLevantamento,
    chaves: tuple[str, ...],
):
    contexto = WorkspaceContext.from_path(db_path, origem="cache_resultado")
    # A alíquota não muda o recorte nem exige nova consulta. O percentual é
    # aplicado na interface sobre os totais já agregados.
    return consultar_levantamento(
        SQLiteDataSource(contexto), filtros, chaves, aliquota=0.0
    )




MAX_LINHAS_DADOS_EXCEL = 1_048_575


if modo_entrada == "ZIP(s) do eSocial":
    fontes_principais, erros_principais = _resolver_fontes_zip(
        arquivos_principais, caminhos_principais, prefixo="[PRINCIPAL] "
    )
    fontes_historico, erros_historico = _resolver_fontes_zip(
        arquivos_historico, caminhos_historico, prefixo="[HISTORICO] "
    )
    fontes_recibos, erros_recibos = _resolver_fontes_zip(
        arquivos_recibos, caminhos_recibos, prefixo="[RECIBOS] "
    )
    for erro in erros_principais + erros_historico + erros_recibos:
        st.warning(erro)

    if gerar_relatorio:
        if not fontes_principais:
            st.warning("Selecione pelo menos um ZIP/XML principal do eSocial.")
            st.stop()
        if st.session_state.get("incluir_historico_carga_inicial") and not fontes_historico:
            st.warning(
                "O modo de histórico complementar está ativo. Selecione pelo menos "
                "um ZIP/XML histórico ou desative essa opção."
            )
            st.stop()
        atualizar_progresso, barra_proc, status_proc = _criar_progresso("Progresso do processamento dos XMLs")
        fontes_carga = organizar_fontes_carga_inicial(
            fontes_principais,
            fontes_historico=fontes_historico,
            fontes_recibos=fontes_recibos,
        )
        st.session_state["resultado_v82"] = executar_processamento(fontes_carga, progress_callback=atualizar_progresso)
        st.session_state["fontes_principais_v82"] = len(fontes_principais)
        st.session_state["fontes_historico_v82"] = len(fontes_historico)
        st.session_state["fontes_recibos_v82"] = len(fontes_recibos)
        status_proc.success("Processamento dos XMLs concluído.")

    if "resultado_v82" not in st.session_state:
        st.info("Selecione os arquivos principais. Os recibos são opcionais. Depois clique em **Gerar Relatório**.")
        st.stop()

    resultado = st.session_state["resultado_v82"]
    df_inventario = resultado.get("inventario", pd.DataFrame())
    df_rubricas = resultado.get("rubricas", pd.DataFrame())
    df_exclusoes = resultado.get("exclusoes", pd.DataFrame())
    df_remun = resultado.get("remuneracoes", pd.DataFrame())
    df_bases_trab = resultado.get("bases_trabalhador", pd.DataFrame())
    df_bases_contrib = resultado.get("bases_contribuicao", pd.DataFrame())
    df_erros = resultado.get("erros_xml", pd.DataFrame())
    df_layout = resultado.get("layout_check", pd.DataFrame())
    df_empresa = resultado.get("empresa", pd.DataFrame())
    modo_excel_consolidado = False

elif modo_entrada in {"SQLite existente", "Workspace (SQLite existente)"}:
    if gerar_relatorio:
        try:
            atualizar_consistencia, _, status_consistencia = _criar_progresso(
                "Verificação de consistência do Workspace"
            )
            st.session_state["resultado_v82"] = carregar_resultado_sqlite_existente(
                caminho_sqlite_existente,
                somente_levantamento=(modulo_ativo == "Levantamento de Verbas"),
                progress_callback=atualizar_consistencia,
            )
            consistencia = st.session_state["resultado_v82"].get(
                "consistencia_workspace", {}
            )
            repetidos = int(consistencia.get("eventos_inativados", 0) or 0)
            if repetidos:
                status_consistencia.success(
                    f"Workspace atualizado: {repetidos:,} cópia(s) S-1200 por recibo "
                    "foram preservadas no inventário e desconsideradas dos relatórios."
                    .replace(",", ".")
                )
            else:
                status_consistencia.success(
                    "Workspace consistente para geração dos relatórios."
                )
            st.success("Banco SQLite carregado. O processamento dos XMLs não será repetido.")
        except Exception as exc:
            st.error(f"Não foi possível carregar o banco: {exc}")
            st.stop()
    if "resultado_v82" not in st.session_state:
        st.info("Informe o caminho do processamento.db e clique em **Carregar banco existente**.")
        st.stop()
    resultado = st.session_state["resultado_v82"]
    df_inventario = resultado.get("inventario", pd.DataFrame())
    df_rubricas = resultado.get("rubricas", pd.DataFrame())
    df_exclusoes = resultado.get("exclusoes", pd.DataFrame())
    df_remun = resultado.get("remuneracoes", pd.DataFrame())
    df_bases_trab = resultado.get("bases_trabalhador", pd.DataFrame())
    df_bases_contrib = resultado.get("bases_contribuicao", pd.DataFrame())
    df_erros = resultado.get("erros_xml", pd.DataFrame())
    df_layout = resultado.get("layout_check", pd.DataFrame())
    df_empresa = resultado.get("empresa", pd.DataFrame())
    modo_excel_consolidado = False

else:
    if arquivo_excel is None:
        st.info("Envie um Excel consolidado com as abas 02_rubricas_cp e 03_movimentos_cp.")
        st.stop()

    with st.spinner("Carregando Excel consolidado..."):
        resultado_excel = carregar_excel_consolidado(arquivo_excel.getvalue())

    df_inventario = pd.DataFrame()
    df_rubricas = pd.DataFrame()
    df_exclusoes = pd.DataFrame()
    df_remun = resultado_excel.get("movimentos_cp", pd.DataFrame()).copy()
    df_bases_trab = pd.DataFrame()
    df_bases_contrib = pd.DataFrame()
    df_erros = pd.DataFrame()
    df_layout = resultado_excel.get("abas", pd.DataFrame())
    df_empresa = resultado_excel.get("empresa", pd.DataFrame())
    df_rubricas_cp_excel = resultado_excel.get("rubricas_cp", pd.DataFrame()).copy()
    df_movimentos_cp_excel = resultado_excel.get("movimentos_cp", pd.DataFrame()).copy()
    modo_excel_consolidado = True


def formatar_cnpj(cnpj: str) -> str:
    cnpj = "" if pd.isna(cnpj) else str(cnpj)
    cnpj = "".join(ch for ch in cnpj if ch.isdigit())
    if len(cnpj) == 14:
        return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
    return cnpj


def empresa_principal(df: pd.DataFrame) -> tuple[str, str]:
    if df.empty:
        return "", ""
    base = df.copy()
    if "nome_empresa" not in base.columns:
        base["nome_empresa"] = ""
    if "cnpj_empregador" not in base.columns:
        base["cnpj_empregador"] = ""
    base["tem_nome"] = base["nome_empresa"].fillna("").astype(str).str.strip().ne("")
    base = base.sort_values(["tem_nome"], ascending=False)
    linha = base.iloc[0]
    return str(linha.get("nome_empresa", "") or ""), formatar_cnpj(linha.get("cnpj_empregador", ""))


nome_empresa, cnpj_empresa = empresa_principal(df_empresa)

atualizar_analise, barra_analise, status_analise = _criar_progresso("Progresso da preparação do relatório")
modo_sqlite_seguro = bool(resultado.get("modo_sqlite_seguro", False)) if modo_entrada in {"ZIP(s) do eSocial", "SQLite existente", "Workspace (SQLite existente)"} else False
pacote_sqlite = resultado.get("pacote_sqlite", {}) if modo_entrada in {"ZIP(s) do eSocial", "SQLite existente", "Workspace (SQLite existente)"} else {}
db_path_sqlite = resultado.get("db_path", "") if modo_entrada in {"ZIP(s) do eSocial", "SQLite existente", "Workspace (SQLite existente)"} else ""
if modo_sqlite_seguro:
        atualizar_analise(0.20, "Carregando resumos consolidados diretamente do SQLite...")
        df_resumo_visual = pacote_sqlite.get("resumo_visual", pd.DataFrame()).copy()
        df_rubricas_cp = pacote_sqlite.get("rubricas_cp", pd.DataFrame()).copy()
        df_movimentos_cp = pacote_sqlite.get("movimentos_cp", pd.DataFrame()).copy()
        df_base_trabalhador = pacote_sqlite.get("base_trabalhador", pd.DataFrame()).copy()
        df_sem_cadastro = pacote_sqlite.get("sem_cadastro", pd.DataFrame()).copy()
        df_s5001_resumo = pacote_sqlite.get("s5001_resumo", pd.DataFrame()).copy()
        df_reconciliacao_s5011 = pacote_sqlite.get(
            "reconciliacao_s5011", pd.DataFrame()
        ).copy()
        total_movimentos_s2299 = int(
            pacote_sqlite.get("total_movimentos_s2299", 0)
        )
        atualizar_analise(1.0, "Relatório consolidado no SQLite carregado sem bases gigantes na memória.")
elif modo_excel_consolidado:
        atualizar_analise(0.15, "Carregando dados consolidados do Excel...")
        df_rubricas_cp = df_rubricas_cp_excel.copy()
        df_movimentos_cp = df_movimentos_cp_excel.copy()
        df_base_trabalhador = pd.DataFrame()
        df_sem_cadastro = pd.DataFrame()
        df_s5001_resumo = pd.DataFrame()
        df_reconciliacao_s5011 = pd.DataFrame()
        total_movimentos_s2299 = 0
        df_resumo_visual = gerar_resumo_visual(df_rubricas_cp, df_movimentos_cp, df_sem_cadastro, df_bases_trab)
        atualizar_analise(1.0, "Relatório consolidado carregado.")
else:
        (
            df_resumo_visual,
            df_rubricas_cp,
            df_movimentos_cp,
            df_base_trabalhador,
            df_sem_cadastro,
            df_s5001_resumo,
        ) = preparar_pacote_analitico(
            df_rubricas=df_rubricas,
            df_remun=df_remun,
            df_bases_trabalhador=df_bases_trab,
            df_bases_contribuicao=df_bases_contrib,
            progress_callback=atualizar_analise,
        )
        df_reconciliacao_s5011 = pd.DataFrame()
        total_movimentos_s2299 = 0
status_analise.success("Preparação do relatório concluída.")

# Consolidação específica para orientar a busca dos recibos faltantes.
df_busca_recibos = gerar_busca_recibos(df_sem_cadastro)

# Resumo claro da complementação por recibos.
if modo_entrada == "ZIP(s) do eSocial":
    st.markdown("---")
    st.markdown("## Conferência dos recibos")
    if df_inventario.empty or "arquivo" not in df_inventario.columns:
        st.caption("Nenhum recibo foi informado nesta execução.")
    else:
        inv_rec = df_inventario[df_inventario["arquivo"].fillna("").astype(str).str.startswith("[RECIBOS] ")].copy()
        if inv_rec.empty:
            st.caption("Nenhum recibo foi informado nesta execução.")
        else:
            total_xml_rec = len(inv_rec)
            s1010_rec = int((inv_rec.get("tipo", "").astype(str).eq("S-1010") & inv_rec.get("envelope_recibo", "").astype(str).eq("Sim")).sum())
            outros_rec = total_xml_rec - s1010_rec
            c1, c2, c3 = st.columns(3)
            c1.metric("XMLs nos arquivos de recibos", f"{total_xml_rec:,}".replace(",", "."))
            c2.metric("Recibos S-1010 encontrados", f"{s1010_rec:,}".replace(",", "."))
            c3.metric("Outros eventos ignorados", f"{outros_rec:,}".replace(",", "."))
            if s1010_rec:
                st.success("Os recibos S-1010 encontrados foram incorporados automaticamente ao catálogo antes da geração do relatório.")
            else:
                st.warning("Foram enviados arquivos na área de recibos, mas nenhum envelope de recibo S-1010 foi reconhecido.")

st.markdown("---")
st.caption(f"Módulo ativo: {modulo_ativo}")

if not df_rubricas.empty and "fonte_dados" in df_rubricas.columns:
    qtd_s1010_recibos = int(df_rubricas["fonte_dados"].eq("Recibo S-1010").sum())
    if qtd_s1010_recibos:
        st.success(f"Foram incorporados {qtd_s1010_recibos:,} registros de rubricas provenientes de recibos S-1010.".replace(",", "."))

df_levantamento_export = pd.DataFrame()

if nome_empresa or cnpj_empresa:
    st.info(f"Empresa: {nome_empresa or 'Nome não localizado'} | CNPJ: {cnpj_empresa or 'CNPJ não localizado'}")

if modulo_ativo == "Relatório de Incidência CP":
    qtd_rubricas = len(df_rubricas_cp) if not df_rubricas_cp.empty else 0
    qtd_incide = int(df_rubricas_cp["status_cp"].eq("Incide CP").sum()) if not df_rubricas_cp.empty else 0
    qtd_nao_incide = int(df_rubricas_cp["status_cp"].eq("Não incide CP").sum()) if not df_rubricas_cp.empty else 0
    qtd_sem_s1010 = int((df_rubricas_cp["status_cp"].eq("Sem S-1010")).sum()) if modo_sqlite_seguro and not df_rubricas_cp.empty else (len(df_sem_cadastro) if not df_sem_cadastro.empty else 0)
    if modo_sqlite_seguro and not df_resumo_visual.empty:
        linha_valor = df_resumo_visual[df_resumo_visual["indicador"].eq("Valor com incidência CP")]
        valor_incide = float(linha_valor["valor"].iloc[0]) if not linha_valor.empty else 0.0
    else:
        valor_incide = float(pd.to_numeric(df_movimentos_cp.loc[df_movimentos_cp["considerado_cp"].eq("Sim"), "vr_rubr"], errors="coerce").fillna(0).sum()) if not df_movimentos_cp.empty else 0.0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Rubricas únicas", f"{qtd_rubricas:,}".replace(",", "."))
    col2.metric("Com incidência CP", f"{qtd_incide:,}".replace(",", "."))
    col3.metric("Sem incidência CP", f"{qtd_nao_incide:,}".replace(",", "."))
    col4.metric("Sem S-1010", f"{qtd_sem_s1010:,}".replace(",", "."))
    col5.metric("Valor com incidência CP", f"R$ {decimal_br(valor_incide)}")

    if modo_sqlite_seguro:
        revisoes_s5011 = int(
            df_reconciliacao_s5011.get(
                "status_reconciliacao", pd.Series(dtype=str)
            ).eq("Revisar").sum()
        )
        v10a, v10b, v10c = st.columns(3)
        v10a.metric("S-2299 segregados", f"{total_movimentos_s2299:,}".replace(",", "."))
        v10b.metric("Reconciliações S-5011", f"{len(df_reconciliacao_s5011):,}".replace(",", "."))
        v10c.metric("Reconciliações a revisar", f"{revisoes_s5011:,}".replace(",", "."))
        st.caption(
            "Na V10, valores S-2299 permanecem separados do Relatório de Incidência CP "
            "e são usados somente no controle de reconciliação, sem alterar regras tributárias."
        )

    st.markdown("## Resumo")
    if df_resumo_visual.empty:
        st.warning("Não foi possível montar o resumo.")
    else:
        st.dataframe(df_resumo_visual, use_container_width=True, hide_index=True)

    st.markdown("## Rubricas por incidência CP")
    if df_rubricas_cp.empty:
        st.warning("Não há rubricas do S-1200 para classificar. Confira se o ZIP contém S-1200 e S-1010 compatíveis.")
    else:
        f1, f2, f3 = st.columns(3)
        status_opcoes = ["Todos"] + sorted(df_rubricas_cp["status_cp"].dropna().unique().tolist())
        carater_opcoes = ["Todos"] + sorted(df_rubricas_cp["carater_verba"].dropna().unique().tolist())
        prioridade_opcoes = ["Todos"] + sorted(df_rubricas_cp["prioridade_revisao"].dropna().unique().tolist())
        status_sel = f1.selectbox("Status CP", status_opcoes)
        carater_sel = f2.selectbox("Caráter da verba", carater_opcoes)
        prioridade_sel = f3.selectbox("Prioridade de revisão", prioridade_opcoes)

        df_view = df_rubricas_cp.copy()
        if status_sel != "Todos":
            df_view = df_view[df_view["status_cp"].eq(status_sel)]
        if carater_sel != "Todos":
            df_view = df_view[df_view["carater_verba"].eq(carater_sel)]
        if prioridade_sel != "Todos":
            df_view = df_view[df_view["prioridade_revisao"].eq(prioridade_sel)]
        st.dataframe(df_view, use_container_width=True, hide_index=True)

    st.markdown("## Base por trabalhador")
    if df_base_trabalhador.empty:
        st.warning("Sem dados suficientes para montar base por trabalhador.")
    else:
        st.dataframe(df_base_trabalhador, use_container_width=True, hide_index=True)

    if modo_sqlite_seguro:
        st.markdown("## Reconciliação com S-5011")
        if df_reconciliacao_s5011.empty:
            st.caption("Não há chaves suficientes para reconciliação S-1200/S-2299 versus S-5011.")
        else:
            st.dataframe(
                df_reconciliacao_s5011,
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("## Rubricas sem correspondência no S-1010")
    if df_sem_cadastro.empty:
        st.success("Nenhuma rubrica sem S-1010 foi localizada no cruzamento atual.")
    else:
        st.dataframe(df_sem_cadastro, use_container_width=True, hide_index=True)

    with st.expander("Abas de apoio / dados brutos"):
        tabs = st.tabs([
            "Movimentos CP",
            "S-1010",
            "S-1200",
            "S-5001",
            "S-5011",
            "S-3000",
            "Layout",
            "Inventário",
            "Erros",
        ])
        with tabs[0]:
            if modo_sqlite_seguro:
                st.caption("Prévia das primeiras 5.000 linhas. A base completa permanece no SQLite e será exportada integralmente em streaming.")
            st.dataframe(df_movimentos_cp, use_container_width=True, hide_index=True)
        with tabs[1]:
            st.dataframe(df_rubricas, use_container_width=True, hide_index=True)
        with tabs[2]:
            st.dataframe(df_remun, use_container_width=True, hide_index=True)
        with tabs[3]:
            st.dataframe(df_bases_trab, use_container_width=True, hide_index=True)
        with tabs[4]:
            st.dataframe(df_bases_contrib, use_container_width=True, hide_index=True)
        with tabs[5]:
            st.dataframe(df_exclusoes, use_container_width=True, hide_index=True)
        with tabs[6]:
            st.dataframe(df_layout, use_container_width=True, hide_index=True)
        with tabs[7]:
            st.dataframe(df_inventario, use_container_width=True, hide_index=True)
        with tabs[8]:
            st.dataframe(df_erros, use_container_width=True, hide_index=True)

if modulo_ativo == "Levantamento de Verbas":
    levantamento_sqlite = bool(db_path_sqlite)
    identificador_fonte_levantamento = (
        f"sqlite:{Path(db_path_sqlite).resolve()}"
        if levantamento_sqlite
        else f"{modo_entrada}:{getattr(arquivo_excel, 'name', '')}"
    )
    if st.session_state.get("lev_fonte_assinatura") != identificador_fonte_levantamento:
        st.session_state["lev_fonte_assinatura"] = identificador_fonte_levantamento
        st.session_state.pop("lev_chaves_rubricas_selecionadas", None)
        st.session_state.pop("lev_editor_versao", None)
        st.session_state.pop("lev_catalogo_rubricas", None)
        st.session_state.pop("lev_comp", None)
        st.session_state.pop("lev_comp_inicio", None)
        st.session_state.pop("lev_comp_fim", None)
        st.session_state.pop("levantamento_excel_path", None)
        st.session_state.pop("levantamento_ultima_geracao", None)
    fonte_levantamento_sqlite = None
    opcoes_sqlite = None
    assinatura_sqlite = None
    if levantamento_sqlite:
        contexto_levantamento = WorkspaceContext.from_path(
            db_path_sqlite, origem="sessao"
        )
        fonte_levantamento_sqlite = SQLiteDataSource(contexto_levantamento)
        assinatura_sqlite = _assinatura_banco_sqlite(db_path_sqlite)
        opcoes_sqlite = _opcoes_levantamento_sqlite(
            str(Path(db_path_sqlite).resolve()), *assinatura_sqlite
        )
        st.success(
            "Levantamento conectado diretamente ao SQLite do Workspace. "
            "Nenhum XML será reprocessado."
        )
    st.markdown("## Levantamento de verbas")
    st.caption("Selecione rubricas já lidas no S-1200 e cruzadas com o S-1010 para calcular valores e estimar CPP.")

    total_movimentos_levantamento = (
        int(pacote_sqlite.get("total_movimentos_cp", 0))
        if levantamento_sqlite
        else len(df_movimentos_cp)
    )
    if total_movimentos_levantamento == 0:
        st.warning("Sem movimentos do S-1200 para montar levantamento de verbas.")
    else:
        l1, l2, l3, l4 = st.columns(4)
        if levantamento_sqlite:
            status_ops = ["Todos"] + opcoes_sqlite["status_cp"]
            carater_ops = ["Todos"] + opcoes_sqlite["carater"]
            tipo_ops = ["Todos"] + opcoes_sqlite["tipo"]
            cp_ops = ["Todos"] + opcoes_sqlite["cod_inc_cp"]
            competencias = opcoes_sqlite["competencias"]
        else:
            status_ops = ["Todos"] + sorted(df_movimentos_cp["status_cp"].dropna().unique().tolist())
            carater_ops = ["Todos"] + sorted(df_movimentos_cp["carater_verba"].dropna().unique().tolist())
            tipo_ops = ["Todos"] + sorted(df_movimentos_cp["tipo_verba"].dropna().unique().tolist())
            cp_ops = ["Todos"] + sorted(df_movimentos_cp["cod_inc_cp"].fillna("").astype(str).replace("", "Sem S-1010").unique().tolist())
            competencias = sorted(df_movimentos_cp["per_apur"].dropna().astype(str).unique().tolist()) if "per_apur" in df_movimentos_cp.columns else []

        status_lev = l1.selectbox("Status CP", status_ops, index=status_ops.index("Incide CP") if "Incide CP" in status_ops else 0, key="lev_status_cp")
        carater_lev = l2.selectbox("Caráter", carater_ops, key="lev_carater")
        tipo_lev = l3.selectbox("Tipo", tipo_ops, key="lev_tipo")
        cp_lev = l4.selectbox("codIncCP", cp_ops, key="lev_codinc")

        st.markdown("#### Período do levantamento")
        if competencias:
            periodo_inicio, periodo_fim, periodo_acao = st.columns([1, 1, 1.2])
            inicio_lev = periodo_inicio.selectbox(
                "Competência inicial",
                competencias,
                index=0,
                key="lev_comp_inicio",
                format_func=rotulo_competencia,
            )
            fim_lev = periodo_fim.selectbox(
                "Competência final",
                competencias,
                index=len(competencias) - 1,
                key="lev_comp_fim",
                format_func=rotulo_competencia,
            )
            intervalo_valido = (
                chave_ordenacao_competencia(inicio_lev)
                <= chave_ordenacao_competencia(fim_lev)
            )
            incluir_anuais_lev = periodo_acao.checkbox(
                "Incluir períodos anuais do 13º salário",
                value=True,
                key="lev_incluir_periodos_anuais",
            )

            def _aplicar_intervalo_levantamento():
                st.session_state["lev_comp"] = competencias_no_intervalo(
                    competencias,
                    inicio_lev,
                    fim_lev,
                    incluir_anuais=incluir_anuais_lev,
                )

            def _limpar_intervalo_levantamento():
                st.session_state["lev_comp"] = []

            periodo_acao.caption("Aplicar o intervalo completo ou limpar o recorte.")
            acao_aplicar, acao_limpar = periodo_acao.columns(2)
            acao_aplicar.button(
                "Aplicar período",
                use_container_width=True,
                disabled=not intervalo_valido,
                on_click=_aplicar_intervalo_levantamento,
                key="lev_aplicar_periodo",
            )
            acao_limpar.button(
                "Todo o período",
                use_container_width=True,
                on_click=_limpar_intervalo_levantamento,
                key="lev_limpar_periodo",
            )
            if not intervalo_valido:
                st.warning("A competência inicial deve ser anterior ou igual à competência final.")

        l5, l6, l7 = st.columns(3)
        comp_lev = l5.multiselect(
            "Competências selecionadas",
            options=competencias,
            key="lev_comp",
            format_func=rotulo_competencia,
            help="Use o intervalo acima ou ajuste manualmente meses específicos. Vazio considera todo o período.",
        )
        aliquota_lev = l6.number_input("Alíquota estimada CPP (%)", min_value=0.0, max_value=100.0, value=20.0, step=0.5, key="lev_aliquota")
        positivos_lev = l7.checkbox("Apenas valores positivos", value=True, key="lev_positivos")
        if comp_lev:
            comp_ordenadas = sorted(comp_lev, key=chave_ordenacao_competencia)
            qtd_anuais = sum(1 for comp in comp_lev if len(str(comp)) == 4)
            st.caption(
                f"Período aplicado: {rotulo_competencia(comp_ordenadas[0])} a "
                f"{rotulo_competencia(comp_ordenadas[-1])} · {len(comp_lev)} período(s), "
                f"incluindo {qtd_anuais} anual(is) de 13º salário."
            )
        else:
            st.caption("Período aplicado: todas as competências disponíveis.")

        filtros_levantamento = FiltrosLevantamento(
            status_cp=status_lev,
            carater=carater_lev,
            tipo=tipo_lev,
            cod_inc_cp=cp_lev,
            competencias=tuple(comp_lev),
            apenas_positivos=positivos_lev,
        )
        if levantamento_sqlite:
            df_base_lev = pd.DataFrame()
            df_opts = _rubricas_levantamento_sqlite(
                str(Path(db_path_sqlite).resolve()),
                *assinatura_sqlite,
                filtros_levantamento,
            )
        else:
            df_base_lev = df_movimentos_cp.copy()
            if status_lev != "Todos":
                df_base_lev = df_base_lev[df_base_lev["status_cp"].eq(status_lev)]
            if carater_lev != "Todos":
                df_base_lev = df_base_lev[df_base_lev["carater_verba"].eq(carater_lev)]
            if tipo_lev != "Todos":
                df_base_lev = df_base_lev[df_base_lev["tipo_verba"].eq(tipo_lev)]
            if cp_lev != "Todos":
                if cp_lev == "Sem S-1010":
                    df_base_lev = df_base_lev[df_base_lev["cod_inc_cp"].fillna("").astype(str).eq("")]
                else:
                    df_base_lev = df_base_lev[df_base_lev["cod_inc_cp"].astype(str).eq(cp_lev)]
            if comp_lev:
                df_base_lev = df_base_lev[df_base_lev["per_apur"].astype(str).isin(comp_lev)]
            if positivos_lev:
                df_base_lev = df_base_lev[pd.to_numeric(df_base_lev["vr_rubr"], errors="coerce").fillna(0) > 0]

        if (levantamento_sqlite and df_opts.empty) or (not levantamento_sqlite and df_base_lev.empty):
            st.warning("Nenhuma rubrica encontrada com os filtros selecionados.")
        else:
            if not levantamento_sqlite:
                df_opts = (
                    df_base_lev.groupby(["cod_rubr", "ide_tab_rubr", "dsc_rubr", "cod_inc_cp", "status_cp", "carater_verba", "tipo_verba"], dropna=False, as_index=False)
                    .agg(valor_total=("vr_rubr", "sum"), qtd_lancamentos=("vr_rubr", "size"), qtd_cpfs=("cpf", "nunique"))
                    .sort_values(["dsc_rubr", "cod_rubr"], ascending=[True, True])
                )
                df_opts["chave_rubrica"] = (
                    df_opts["cod_rubr"].fillna("").astype(str)
                    + "||"
                    + df_opts["ide_tab_rubr"].fillna("").astype(str)
                )

            if "lev_chaves_rubricas_selecionadas" not in st.session_state:
                st.session_state["lev_chaves_rubricas_selecionadas"] = []
            if "lev_editor_versao" not in st.session_state:
                st.session_state["lev_editor_versao"] = 0
            if "lev_catalogo_rubricas" not in st.session_state:
                st.session_state["lev_catalogo_rubricas"] = {}

            catalogo_rubricas = st.session_state["lev_catalogo_rubricas"]
            for linha in df_opts[["chave_rubrica", "cod_rubr", "ide_tab_rubr", "dsc_rubr"]].itertuples(index=False):
                catalogo_rubricas[str(linha.chave_rubrica)] = {
                    "cod_rubr": str(linha.cod_rubr or ""),
                    "ide_tab_rubr": str(linha.ide_tab_rubr or ""),
                    "dsc_rubr": str(linha.dsc_rubr or ""),
                }

            st.markdown("### Seleção de rubricas")
            busca_lev = st.text_area(
                "Buscar rubricas por código ou descrição",
                value="",
                key="lev_busca_rubrica",
                height=90,
                help="Aceita múltiplos termos separados por ponto e vírgula, vírgula, tabulação ou quebra de linha. Você pode colar uma lista direto do Excel.",
                placeholder="Ex.: 0324P; BONUS; MATERNIDADE\nou cole uma coluna do Excel aqui",
            )

            df_opts_busca, termos_busca = filtrar_rubricas_por_multibusca(
                df_opts, busca_lev
            )
            termos_ausentes = termos_sem_correspondencia(df_opts, termos_busca)
            if termos_busca:
                st.caption(
                    f"Busca ativa: {len(termos_busca)} termo(s) · "
                    f"{len(df_opts_busca):,} rubrica(s) encontrada(s). "
                    "O código exige correspondência exata; a descrição aceita trechos e ignora acentos.".replace(",", ".")
                )
                if termos_ausentes:
                    st.warning(
                        "Sem correspondência no catálogo filtrado: "
                        + "; ".join(termos_ausentes)
                    )
            else:
                st.caption(
                    "Digite um código exato ou parte da descrição. A busca vazia não seleciona rubricas automaticamente."
                )
            if levantamento_sqlite:
                st.caption(
                    "O catálogo usa o resumo consolidado e a sobreposição do período para manter a tela rápida. "
                    "As competências selecionadas e a condição de movimentos positivos serão aplicadas "
                    "com exatidão no cálculo e na exportação."
                )

            b1, b2, b3, b4 = st.columns([1.7, 1.2, 1.2, 0.8])
            chaves_resultado = set(df_opts_busca["chave_rubrica"].astype(str).tolist())
            chaves_filtradas = set(df_opts["chave_rubrica"].astype(str).tolist())
            chaves_atuais = set(st.session_state["lev_chaves_rubricas_selecionadas"])

            if b1.button(
                f"Usar somente resultados ({len(chaves_resultado)})",
                type="primary",
                use_container_width=True,
                disabled=not termos_busca or not chaves_resultado,
                key="lev_btn_substituir_busca",
            ):
                st.session_state["lev_chaves_rubricas_selecionadas"] = atualizar_selecao_rubricas(
                    chaves_atuais, chaves_resultado, "substituir"
                )
                st.session_state["lev_editor_versao"] += 1
                st.rerun()
            if b2.button(
                f"Adicionar resultados ({len(chaves_resultado)})",
                use_container_width=True,
                disabled=not termos_busca or not chaves_resultado,
                key="lev_btn_adicionar_busca",
            ):
                st.session_state["lev_chaves_rubricas_selecionadas"] = atualizar_selecao_rubricas(
                    chaves_atuais, chaves_resultado, "adicionar"
                )
                st.session_state["lev_editor_versao"] += 1
                st.rerun()
            if b3.button(
                f"Remover resultados ({len(chaves_resultado)})",
                use_container_width=True,
                disabled=not termos_busca or not chaves_resultado,
                key="lev_btn_limpa_busca",
            ):
                st.session_state["lev_chaves_rubricas_selecionadas"] = atualizar_selecao_rubricas(
                    chaves_atuais, chaves_resultado, "remover"
                )
                st.session_state["lev_editor_versao"] += 1
                st.rerun()
            if b4.button(
                f"Limpar seleção ({len(chaves_atuais)})",
                use_container_width=True,
                disabled=not chaves_atuais,
                key="lev_btn_limpa_tudo",
            ):
                st.session_state["lev_chaves_rubricas_selecionadas"] = atualizar_selecao_rubricas(
                    chaves_atuais, set(), "limpar"
                )
                st.session_state["lev_editor_versao"] += 1
                st.rerun()

            limite_tabela_rubricas = 250
            df_opts_visiveis = df_opts_busca.head(limite_tabela_rubricas).copy()
            if len(df_opts_busca) > limite_tabela_rubricas:
                st.info(
                    f"A tabela mostra as primeiras {limite_tabela_rubricas} de "
                    f"{len(df_opts_busca):,} rubricas. Refine a busca para editar uma rubrica específica; "
                    "os botões de seleção continuam considerando todos os resultados.".replace(",", ".")
                )
            colunas_editor = [
                "chave_rubrica",
                "cod_rubr",
                "dsc_rubr",
                "cod_inc_cp",
                "status_cp",
                "carater_verba",
                "tipo_verba",
                "valor_total",
                "qtd_lancamentos",
                "qtd_cpfs",
            ]
            if termos_busca and "correspondencia_busca" in df_opts_visiveis.columns:
                colunas_editor.append("correspondencia_busca")
            df_editor = df_opts_visiveis[colunas_editor].copy()
            selecionadas = set(st.session_state["lev_chaves_rubricas_selecionadas"])
            df_editor.insert(0, "Selecionar", df_editor["chave_rubrica"].astype(str).isin(selecionadas))
            df_editor = df_editor.rename(columns={
                "cod_rubr": "codRubr",
                "dsc_rubr": "Descrição",
                "cod_inc_cp": "codIncCP",
                "status_cp": "Status CP",
                "carater_verba": "Caráter",
                "tipo_verba": "Tipo",
                "valor_total": "Valor total",
                "qtd_lancamentos": "Lançamentos",
                "qtd_cpfs": "CPFs",
                "correspondencia_busca": "Correspondência",
            })
            colunas_bloqueadas = [
                coluna for coluna in (
                    "codRubr", "Descrição", "codIncCP", "Status CP", "Caráter",
                    "Tipo", "Valor total", "Lançamentos", "CPFs", "Correspondência",
                ) if coluna in df_editor.columns
            ]

            with st.form("form_selecao_rubricas_levantamento"):
                df_editado = st.data_editor(
                    df_editor.drop(columns=["chave_rubrica"]),
                    use_container_width=True,
                    hide_index=True,
                    height=420,
                    disabled=colunas_bloqueadas,
                    column_config={
                        "Selecionar": st.column_config.CheckboxColumn("Selecionar"),
                        "Valor total": st.column_config.NumberColumn("Valor total", format="R$ %.2f"),
                    },
                    key=f"lev_editor_rubricas_{st.session_state['lev_editor_versao']}",
                )
                aplicar_selecao = st.form_submit_button("Aplicar alterações visíveis", use_container_width=True)

            if aplicar_selecao:
                chaves_visiveis = set(df_opts_visiveis["chave_rubrica"].astype(str))
                novas_visiveis = set(df_opts_visiveis.loc[df_editado["Selecionar"].fillna(False).tolist(), "chave_rubrica"].astype(str).tolist())
                fora_da_tabela = set(st.session_state["lev_chaves_rubricas_selecionadas"]) - chaves_visiveis
                st.session_state["lev_chaves_rubricas_selecionadas"] = sorted(fora_da_tabela | novas_visiveis)
                st.session_state["lev_editor_versao"] += 1
                st.rerun()

            chaves_selecionadas = set(st.session_state["lev_chaves_rubricas_selecionadas"])
            selecionadas_visiveis = chaves_selecionadas & chaves_filtradas
            selecionadas_fora = chaves_selecionadas - chaves_filtradas
            with st.expander(
                f"Rubricas que entrarão no levantamento — {len(chaves_selecionadas)}",
                expanded=bool(chaves_selecionadas),
            ):
                st.caption(
                    f"Visíveis nos filtros atuais: {len(selecionadas_visiveis)} · "
                    f"Fora dos filtros atuais: {len(selecionadas_fora)}"
                )
                if chaves_selecionadas:
                    linhas_selecionadas = []
                    rotulos_selecionados = {}
                    for chave in sorted(chaves_selecionadas):
                        item = catalogo_rubricas.get(chave, {})
                        codigo = item.get("cod_rubr", chave.partition("||")[0])
                        tabela = item.get("ide_tab_rubr", chave.partition("||")[2])
                        descricao = item.get("dsc_rubr", "")
                        rotulo = f"{codigo} | {tabela} | {descricao}".strip(" |")
                        rotulos_selecionados[chave] = rotulo
                        linhas_selecionadas.append({
                            "Código": codigo,
                            "Tabela": tabela,
                            "Descrição": descricao,
                            "No filtro atual": "Sim" if chave in chaves_filtradas else "Não",
                        })
                    st.dataframe(
                        pd.DataFrame(linhas_selecionadas),
                        use_container_width=True,
                        hide_index=True,
                        height=min(280, 38 + 35 * len(linhas_selecionadas)),
                    )
                    chave_remover = st.selectbox(
                        "Remover uma rubrica da seleção",
                        sorted(chaves_selecionadas),
                        format_func=lambda chave: rotulos_selecionados[chave],
                        key="lev_remover_rubrica_individual",
                    )
                    if st.button(
                        "Remover rubrica escolhida",
                        use_container_width=True,
                        key="lev_btn_remover_individual",
                    ):
                        st.session_state["lev_chaves_rubricas_selecionadas"] = sorted(
                            chaves_selecionadas - {chave_remover}
                        )
                        st.session_state["lev_editor_versao"] += 1
                        st.rerun()
                else:
                    st.caption("Nenhuma rubrica selecionada.")

            if not chaves_selecionadas:
                st.info("Selecione uma ou mais rubricas e clique em Aplicar alterações visíveis. O levantamento e o Excel só serão montados depois disso, para evitar processamento desnecessário em arquivos grandes.")
                df_levantamento_export = pd.DataFrame()
                st.stop()

            # A partir deste ponto apenas o recorte selecionado é consultado.
            if levantamento_sqlite:
                resultado_lev_sqlite = _resultado_levantamento_sqlite(
                    str(Path(db_path_sqlite).resolve()),
                    *assinatura_sqlite,
                    filtros_levantamento,
                    tuple(sorted(chaves_selecionadas)),
                )
                df_levantamento = resultado_lev_sqlite.movimentos_previa
                total_movimentos_lev = resultado_lev_sqlite.qtd_movimentos
                total_lev = resultado_lev_sqlite.total
                cpp_lev = total_lev * (float(aliquota_lev) / 100.0)
                qtd_rubricas_lev = resultado_lev_sqlite.qtd_rubricas
                qtd_cpfs_lev = resultado_lev_sqlite.qtd_cpfs
                df_resumo_lev = resultado_lev_sqlite.resumo_rubricas
                df_resumo_competencia_rubrica_lev = (
                    resultado_lev_sqlite.resumo_competencia_rubrica
                )
                df_resumo_competencia_lev = resultado_lev_sqlite.resumo_competencia
                for resumo in (df_resumo_lev, df_resumo_competencia_rubrica_lev):
                    if not resumo.empty:
                        resumo["cpp_estimado"] = (
                            pd.to_numeric(resumo["valor_total"], errors="coerce").fillna(0)
                            * (float(aliquota_lev) / 100.0)
                        )
                if not df_resumo_competencia_lev.empty:
                    df_resumo_competencia_lev["CPP estimada"] = (
                        pd.to_numeric(
                            df_resumo_competencia_lev["Total"], errors="coerce"
                        ).fillna(0)
                        * (float(aliquota_lev) / 100.0)
                    )
            else:
                df_levantamento = df_base_lev.copy()
                df_levantamento["chave_rubrica"] = (
                    df_levantamento["cod_rubr"].fillna("").astype(str)
                    + "||"
                    + df_levantamento["ide_tab_rubr"].fillna("").astype(str)
                )
                df_levantamento = df_levantamento[df_levantamento["chave_rubrica"].astype(str).isin(chaves_selecionadas)].copy()
                df_levantamento = df_levantamento.drop(columns=["chave_rubrica"], errors="ignore")
                total_movimentos_lev = len(df_levantamento)
                total_lev = float(pd.to_numeric(df_levantamento["vr_rubr"], errors="coerce").fillna(0).sum())
                cpp_lev = total_lev * (float(aliquota_lev) / 100.0)
                qtd_rubricas_lev = df_levantamento["cod_rubr"].nunique()
                qtd_cpfs_lev = df_levantamento["cpf"].nunique() if "cpf" in df_levantamento.columns else 0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total levantado", f"R$ {decimal_br(total_lev)}")
            m2.metric("CPP estimada", f"R$ {decimal_br(cpp_lev)}")
            m3.metric("Rubricas", f"{qtd_rubricas_lev:,}".replace(",", "."))
            m4.metric("CPFs", f"{qtd_cpfs_lev:,}".replace(",", "."))

            if not levantamento_sqlite:
                df_resumo_lev = (
                    df_levantamento.groupby(["cod_rubr", "dsc_rubr", "nat_rubr", "cod_inc_cp", "status_cp", "carater_verba", "tipo_verba"], dropna=False, as_index=False)
                    .agg(valor_total=("vr_rubr", "sum"), qtd_lancamentos=("vr_rubr", "size"), qtd_cpfs=("cpf", "nunique"), primeira_competencia=("per_apur", "min"), ultima_competencia=("per_apur", "max"))
                    .sort_values("valor_total", ascending=False)
                )
                df_resumo_lev["cpp_estimado"] = pd.to_numeric(df_resumo_lev["valor_total"], errors="coerce").fillna(0) * (float(aliquota_lev) / 100.0)
                df_resumo_competencia_rubrica_lev = (
                    df_levantamento.groupby(["per_apur", "cod_rubr", "dsc_rubr", "cod_inc_cp", "status_cp", "carater_verba", "tipo_verba"], dropna=False, as_index=False)
                    .agg(valor_total=("vr_rubr", "sum"), qtd_lancamentos=("vr_rubr", "size"), qtd_cpfs=("cpf", "nunique"))
                    .sort_values(["per_apur", "valor_total"], ascending=[True, False])
                )
                df_resumo_competencia_rubrica_lev["cpp_estimado"] = pd.to_numeric(df_resumo_competencia_rubrica_lev["valor_total"], errors="coerce").fillna(0) * (float(aliquota_lev) / 100.0)
                df_matriz_competencia = df_levantamento.copy()
                df_matriz_competencia["rubrica_resumo"] = (
                    df_matriz_competencia["cod_rubr"].fillna("").astype(str).str.strip()
                    + " - "
                    + df_matriz_competencia["dsc_rubr"].fillna("").astype(str).str.strip()
                ).str.strip(" -")
                df_resumo_competencia_lev = (
                    df_matriz_competencia.pivot_table(index="per_apur", columns="rubrica_resumo", values="vr_rubr", aggfunc="sum", fill_value=0)
                    .reset_index()
                    .rename(columns={"per_apur": "Periodo de apuracao"})
                )
                colunas_rubricas = [col for col in df_resumo_competencia_lev.columns if col != "Periodo de apuracao"]
                df_resumo_competencia_lev["Total"] = df_resumo_competencia_lev[colunas_rubricas].sum(axis=1) if colunas_rubricas else 0.0
                df_resumo_competencia_lev["CPP estimada"] = df_resumo_competencia_lev["Total"] * (float(aliquota_lev) / 100.0)
                df_resumo_competencia_lev = df_resumo_competencia_lev.sort_values("Periodo de apuracao")

            st.markdown("### Resumo das rubricas levantadas")
            st.dataframe(df_resumo_lev, use_container_width=True, hide_index=True)

            st.markdown("### Resumo por competência")
            st.caption("Período de apuração na primeira coluna e rubricas selecionadas nas demais colunas.")
            st.dataframe(df_resumo_competencia_lev, use_container_width=True, hide_index=True)

            with st.expander("Ver movimentos detalhados do levantamento"):
                if levantamento_sqlite and total_movimentos_lev > len(df_levantamento):
                    st.caption(
                        f"Prévia das primeiras {len(df_levantamento):,} de {total_movimentos_lev:,} linhas. "
                        "O conjunto completo permanece no SQLite."
                    )
                st.dataframe(df_levantamento, use_container_width=True, hide_index=True)

            df_parametros_lev = pd.DataFrame({
                "Indicador": [
                    "Status CP filtrado",
                    "Caráter filtrado",
                    "Tipo filtrado",
                    "codIncCP filtrado",
                    "Competências filtradas",
                    "Apenas valores positivos",
                    "Alíquota CPP (%)",
                    "Total levantado",
                    "CPP estimada",
                    "Quantidade de rubricas",
                    "Quantidade de CPFs",
                ],
                "Valor": [
                    status_lev,
                    carater_lev,
                    tipo_lev,
                    cp_lev,
                    ", ".join(comp_lev) if comp_lev else "Todas",
                    "Sim" if positivos_lev else "Não",
                    float(aliquota_lev),
                    total_lev,
                    cpp_lev,
                    qtd_rubricas_lev,
                    qtd_cpfs_lev,
                ],
            })


            st.markdown("### Exportação do levantamento")
            incluir_movimentos_detalhados = st.checkbox(
                "Incluir aba 03_movimentos detalhada no Excel",
                value=False,
                help="Desmarcado por padrão para arquivos grandes. Os resumos continuam sendo gerados normalmente. Marque apenas quando precisar auditar movimento a movimento.",
                key="lev_incluir_movimentos_detalhados",
            )
            if incluir_movimentos_detalhados and total_movimentos_lev > MAX_LINHAS_DADOS_EXCEL:
                st.warning(
                    f"A aba 03_movimentos do levantamento possui {total_movimentos_lev:,} linhas e será dividida automaticamente em partes no Excel.".replace(",", ".")
                )
            elif not incluir_movimentos_detalhados:
                st.caption("Para melhor performance, o Excel será gerado sem a aba detalhada 03_movimentos. Use os resumos por rubrica e competência para o levantamento.")

            if st.button("Preparar Excel do levantamento", use_container_width=True, key="btn_preparar_excel_levantamento"):
                st.session_state["levantamento_status_geracao"] = "gerando"
                atualizar_lev, barra_lev, status_lev_prog = _criar_progresso("Progresso da geração do levantamento")
                atualizar_lev(0.03, "Preparando o arquivo Excel...")
                pasta_base_levantamento = (
                    Path(resultado.get("workspace_temporario", tempfile.gettempdir()))
                    if modo_entrada != "Excel consolidado / levantamento"
                    else Path(tempfile.gettempdir()) / "XML_eSocial" / "levantamentos"
                )
                pasta_levantamento = pasta_base_levantamento / "output"
                if levantamento_sqlite:
                    resultado_levantamento = gerar_excel_levantamento_sqlite(
                        fonte_levantamento_sqlite,
                        pasta_levantamento / "levantamento_verbas_cp_v10.xlsx",
                        filtros_levantamento,
                        chaves_selecionadas,
                        resultado_lev_sqlite,
                        df_empresa,
                        df_parametros_lev,
                        incluir_movimentos_detalhados,
                        progress_callback=atualizar_lev,
                    )
                else:
                    if incluir_movimentos_detalhados:
                        movimentos_levantamento = df_levantamento
                    else:
                        movimentos_levantamento = pd.DataFrame({
                            "Informação": [
                                "A aba detalhada 03_movimentos não foi incluída nesta exportação.",
                                "Para incluir os movimentos detalhados, marque a opção correspondente antes de preparar o arquivo.",
                                "Os valores do levantamento estão preservados nas abas de resumo.",
                            ],
                            "Valor": [
                                f"Movimentos detalhados disponíveis no recorte: {total_movimentos_lev:,}".replace(",", "."),
                                "Exportação otimizada para arquivos grandes",
                                f"Total levantado: R$ {decimal_br(total_lev)}",
                            ],
                        })
                    resultado_levantamento = gerar_workbook(
                        pasta_levantamento / "levantamento_verbas_cp_v10.xlsx",
                        [
                            FontePlanilha("00_empresa", dataframe=df_empresa),
                            FontePlanilha("01_resumo", dataframe=df_parametros_lev),
                            FontePlanilha("02_resumo_rubricas", dataframe=df_resumo_lev),
                            FontePlanilha("03_movimentos", dataframe=movimentos_levantamento),
                            FontePlanilha("04_resumo_competencia", dataframe=df_resumo_competencia_lev),
                            FontePlanilha("05_competencia_rubrica", dataframe=df_resumo_competencia_rubrica_lev),
                        ],
                        progress_callback=atualizar_lev,
                    )
                agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                st.session_state["levantamento_excel_path"] = resultado_levantamento.caminho
                st.session_state.pop("levantamento_excel_bytes", None)
                st.session_state["levantamento_excel_nome"] = Path(resultado_levantamento.caminho).name
                st.session_state["levantamento_status_geracao"] = "pronto"
                st.session_state["levantamento_ultima_geracao"] = {
                        "data_hora": agora,
                        "qtd_rubricas": int(qtd_rubricas_lev),
                        "qtd_movimentos": int(total_movimentos_lev),
                        "qtd_cpfs": int(qtd_cpfs_lev),
                        "total_levantado": float(total_lev),
                        "cpp_estimado": float(cpp_lev),
                        "incluiu_movimentos": "Sim" if incluir_movimentos_detalhados else "Não",
                }
                atualizar_lev(1.0, "Levantamento concluído.")
                status_lev_prog.success("Excel do levantamento pronto para download.")
                st.success("Levantamento atualizado. O botão de download abaixo corresponde à última geração concluída.")

            if st.session_state.get("levantamento_status_geracao") == "gerando":
                st.warning("Excel do levantamento em geração. Aguarde a conclusão antes de baixar.")

            caminho_levantamento = st.session_state.get("levantamento_excel_path")
            if caminho_levantamento and Path(caminho_levantamento).exists():
                meta = st.session_state.get("levantamento_ultima_geracao", {})
                if meta:
                    st.info(
                        "Último levantamento gerado: "
                        f"{meta.get('data_hora', '')} | "
                        f"Rubricas: {meta.get('qtd_rubricas', 0)} | "
                        f"Movimentos: {meta.get('qtd_movimentos', 0):,} | "
                        f"CPFs: {meta.get('qtd_cpfs', 0):,} | "
                        f"03_movimentos detalhado: {meta.get('incluiu_movimentos', 'Não')}".replace(",", ".")
                    )
                _oferecer_arquivo_gerado(
                    caminho_levantamento,
                    label="Baixar levantamento de verbas",
                    nome=st.session_state.get("levantamento_excel_nome", "levantamento_verbas_cp_v10.xlsx"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_levantamento_verbas",
                )

            df_levantamento_export = df_resumo_lev.copy()

if modulo_ativo == "Relatório de Incidência CP":
    st.markdown("## Exportação")

    total_movimentos_cp = int(pacote_sqlite.get("total_movimentos_cp", 0)) if modo_sqlite_seguro else (len(df_movimentos_cp) if df_movimentos_cp is not None else 0)
    excede_limite_excel = total_movimentos_cp > MAX_LINHAS_DADOS_EXCEL

    if excede_limite_excel:
        st.warning(
            f"A aba 03_movimentos_cp possui {total_movimentos_cp:,} linhas e ultrapassa o limite de uma aba do Excel.".replace(",", ".")
        )

    escolha_movimentos_cp = st.radio(
        "Como deseja exportar a aba 03_movimentos_cp?",
        [
            "Análise prioritária: Incide CP + Revisar codIncCP",
            "Apenas Incide CP",
            "Todos os classificados: Incide + Não incide + Revisar",
            "Todos os movimentos, inclusive Sem S-1010",
        ],
        index=0,
        help=(
            "A opção recomendada exporta Incide CP e Revisar codIncCP na aba 03, reduzindo o tamanho sem esconder pendências. "
            "Os movimentos Sem S-1010 são sempre exportados separadamente no arquivo/aba 05_sem_s1010, exceto na opção "
            "'Todos os movimentos', em que também aparecem na aba 03."
        ),
        key="relatorio_modo_exportacao_movimentos_cp",
    )

    if escolha_movimentos_cp.startswith("Análise prioritária"):
        modo_exportacao_movimentos_cp = "analise_prioritaria"
    elif escolha_movimentos_cp.startswith("Apenas Incide"):
        modo_exportacao_movimentos_cp = "incidencia_cp_padrao"
    elif escolha_movimentos_cp.startswith("Todos os classificados"):
        modo_exportacao_movimentos_cp = "classificados"
    else:
        modo_exportacao_movimentos_cp = "todos"

    if modo_sqlite_seguro:
        totais_modo = {
            "incidencia_cp_padrao": int(pacote_sqlite.get("total_movimentos_cp_padrao", 0)),
            "analise_prioritaria": int(pacote_sqlite.get("total_movimentos_analise_prioritaria", 0)),
            "classificados": int(pacote_sqlite.get("total_movimentos_classificados", 0)),
            "todos": total_movimentos_cp,
        }
        qtd_exportacao = totais_modo[modo_exportacao_movimentos_cp]
        qtd_sem_s1010 = int(pacote_sqlite.get("total_movimentos_sem_s1010", 0))
    else:
        qtd_exportacao = len(_filtrar_movimentos_cp_exportacao(df_movimentos_cp, modo_exportacao_movimentos_cp))
        qtd_sem_s1010 = int(df_movimentos_cp["status_cp"].eq("Sem S-1010").sum()) if not df_movimentos_cp.empty and "status_cp" in df_movimentos_cp.columns else len(df_sem_cadastro)

    descricoes_modo = {
        "incidencia_cp_padrao": "somente movimentos classificados como Incide CP",
        "analise_prioritaria": "movimentos Incide CP e Revisar codIncCP",
        "classificados": "todos os movimentos classificados (Incide, Não incide e Revisar)",
        "todos": "todos os movimentos, inclusive Sem S-1010",
    }
    st.caption(
        f"A aba 03 será preparada com {qtd_exportacao:,} linhas: {descricoes_modo[modo_exportacao_movimentos_cp]}.".replace(",", ".")
    )
    st.info(
        f"Segurança da auditoria: {qtd_sem_s1010:,} movimento(s) Sem S-1010 serão mantidos separadamente em 05_sem_s1010.".replace(",", ".")
    )

    if qtd_exportacao > MAX_LINHAS_DADOS_EXCEL:
        qtd_partes = (qtd_exportacao + MAX_LINHAS_DADOS_EXCEL - 1) // MAX_LINHAS_DADOS_EXCEL
        st.info(
            f"A aba 03_movimentos_cp será dividida automaticamente em {qtd_partes} abas, sem perda de linhas."
        )

    gerar_manifesto_rel = st.checkbox(
        "Gerar manifesto CSV opcional",
        value=False,
        key="gerar_manifesto_relatorio_v95",
    )
    assinatura_exportacao = f"v10:{modo_exportacao_movimentos_cp}:{total_movimentos_cp}:{qtd_exportacao}:{qtd_sem_s1010}:{gerar_manifesto_rel}"
    if st.session_state.get("relatorio_excel_assinatura") != assinatura_exportacao:
        st.session_state.pop("relatorio_excel_bytes", None)
        st.session_state.pop("relatorio_excel_path", None)
        st.session_state.pop("relatorio_pacote_saida", None)
        st.session_state.pop("relatorio_excel_nome", None)

    preparar_excel_rel = st.button(
        "Preparar Excel do relatório",
        type="primary",
        use_container_width=True,
        key="preparar_excel_relatorio_incidencia",
    )
    if preparar_excel_rel:
        atualizar_excel_rel, barra_excel_rel, status_excel_rel = _criar_progresso("Progresso da geração do Excel do relatório")
        pasta_saida = (
            Path(resultado.get("workspace_temporario", tempfile.gettempdir()))
            / "output"
        )
        caminho_saida = pasta_saida / "relatorio_incidencia_cp_esocial_v10.xlsx"
        if caminho_saida.exists():
            caminho_saida = pasta_saida / (
                "relatorio_incidencia_cp_esocial_v10_revisado_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".xlsx"
            )
        # Na V10, todo Workspace SQLite usa a mesma exportação por cursor,
        # independentemente do porte. O caminho DataFrame permanece apenas
        # para a origem Excel legada.
        if db_path_sqlite:
            caminho_relatorio = gerar_excel_saida_sqlite(
                db_path=db_path_sqlite,
                caminho_saida=caminho_saida,
                df_empresa=df_empresa,
                df_resumo_visual=df_resumo_visual,
                df_rubricas_cp=df_rubricas_cp,
                df_levantamento=df_levantamento_export,
                modo_exportacao_movimentos_cp=modo_exportacao_movimentos_cp,
                progress_callback=atualizar_excel_rel,
                gerar_manifesto=gerar_manifesto_rel,
            )
        else:
            movimentos_export = _filtrar_movimentos_cp_exportacao(
                df_movimentos_cp, modo_exportacao_movimentos_cp
            )
            fontes = [
                FontePlanilha("00_empresa", dataframe=df_empresa),
                FontePlanilha("01_resumo", dataframe=df_resumo_visual),
                FontePlanilha("02_rubricas_cp", dataframe=df_rubricas_cp),
                FontePlanilha("03_movimentos_cp", dataframe=movimentos_export),
                FontePlanilha("04_base_trabalhador", dataframe=df_base_trabalhador),
                FontePlanilha("05_sem_s1010", dataframe=df_sem_cadastro),
                FontePlanilha("05_busca_recibos", dataframe=df_busca_recibos),
                FontePlanilha("06_s5001_tpvalor", dataframe=df_s5001_resumo),
                FontePlanilha("07_levantamento", dataframe=df_levantamento_export),
                FontePlanilha("apoio_s1010", dataframe=df_rubricas),
                FontePlanilha("apoio_s1200", dataframe=df_remun),
                FontePlanilha("apoio_s5001", dataframe=df_bases_trab),
                FontePlanilha("apoio_s5011", dataframe=df_bases_contrib),
                FontePlanilha("apoio_s3000", dataframe=df_exclusoes),
                FontePlanilha("checagem_layout", dataframe=df_layout),
                FontePlanilha("inventario", dataframe=df_inventario),
                FontePlanilha("erros_xml", dataframe=df_erros),
            ]
            resultado_workbook = gerar_workbook(
                caminho_saida,
                fontes,
                progress_callback=atualizar_excel_rel,
                gerar_manifesto=gerar_manifesto_rel,
            )
            caminho_relatorio = resultado_workbook.caminho
        st.session_state["relatorio_excel_path"] = caminho_relatorio
        st.session_state.pop("relatorio_excel_bytes", None)
        st.session_state.pop("relatorio_pacote_saida", None)
        st.session_state["relatorio_excel_nome"] = Path(caminho_relatorio).name
        st.session_state["relatorio_excel_assinatura"] = assinatura_exportacao
        status_excel_rel.success("Relatório único consolidado e validado.")

    caminho_relatorio_pronto = st.session_state.get("relatorio_excel_path")
    if caminho_relatorio_pronto and Path(caminho_relatorio_pronto).exists():
        st.success("Relatório consolidado pronto: um único arquivo Excel.")
        _oferecer_arquivo_gerado(
            caminho_relatorio_pronto,
            label="Baixar relatório de incidência CP",
            nome=st.session_state.get("relatorio_excel_nome", Path(caminho_relatorio_pronto).name),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_relatorio_incidencia_sqlite",
        )
        manifesto_pronto = Path(caminho_relatorio_pronto).with_name(
            f"{Path(caminho_relatorio_pronto).stem}_manifesto.csv"
        )
        if gerar_manifesto_rel and manifesto_pronto.exists():
            with open(manifesto_pronto, "rb") as arquivo_manifesto:
                st.download_button(
                    "Baixar manifesto opcional",
                    data=arquivo_manifesto,
                    file_name=manifesto_pronto.name,
                    mime="text/csv",
                    use_container_width=True,
                    key="download_manifesto_v95",
                )
