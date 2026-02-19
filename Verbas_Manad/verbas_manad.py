import io
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

# Garante imports quando rodar como "streamlit run manad_extrator/manad_extrator.py"
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from manadlib.layout import (
    CAB_K150,
    CAB_K300,
    CAB_K050,
    extrair_codigo_evento,
)
from manadlib.spool import spool_por_evento
from manadlib.preview import gerar_previa_k300, ler_catalogo_k150, alertas_descricoes_repetidas
from manadlib.export import gerar_excel_interno


# =========================
# Streamlit UI
# =========================
st.set_page_config(page_title="MANAD Extrator - Indenizatórias", layout="wide")
st.title("📂 MANAD — Levantamento de Verbas (K150/K300) + K050 (Trabalhadores)")

uploaded_file = st.file_uploader(
    "Envie o arquivo MANAD (.txt ou .xlsx)",
    type=["txt", "xlsx"],
    key="upload_manad",
)

# =========================
# Session state init
# =========================
def ss_init():
    st.session_state.setdefault("tmp_dir", None)
    st.session_state.setdefault("arquivos_evento", {})      # codigo -> str(path)
    st.session_state.setdefault("contagem_linhas", {})      # codigo -> int
    st.session_state.setdefault("eventos_encontrados", [])  # list[str]

    st.session_state.setdefault("df_rubricas", None)        # catálogo K150
    st.session_state.setdefault("selected_codigos", set())  # rubricas selecionadas (set[str])

    st.session_state.setdefault("filtro_ind_rubr", {"P"})   # default: provento
    st.session_state.setdefault("filtro_ind_base_ps", {"1", "2"})  # default: base 1 e 2

    st.session_state.setdefault("preview_result", None)     # dict com dataframes e alertas
    st.session_state.setdefault("excel_bytes", None)

ss_init()


# =========================
# Upload -> Spool
# =========================
if uploaded_file:
    st.success("Arquivo carregado com sucesso!")

    # cria pasta temporária por upload (guarda no session_state)
    if not st.session_state.tmp_dir:
        st.session_state.tmp_dir = str(Path(tempfile.mkdtemp(prefix="manad_")))

    tmp_dir = Path(st.session_state.tmp_dir)
    st.caption(f"📌 Pasta temporária em uso: {tmp_dir}")

    # Spool focado (somente o que interessa para este fluxo)
    # K150 (rubricas), K300 (itens), K050 (cadastro trab)
    eventos_alvo = {"K150", "K300", "K050"}

    status = st.empty()
    prog = st.progress(0.0)

    try:
        status.info("Separando o arquivo por evento (focado em K150/K300/K050)...")

        arquivos_evento, contagem_linhas, eventos = spool_por_evento(
            uploaded_file=uploaded_file,
            tmp_dir=tmp_dir,
            eventos_alvo=eventos_alvo,
            progress_bar=prog,
            status_slot=status,
        )

        st.session_state.arquivos_evento = {k: str(v) for k, v in arquivos_evento.items()}
        st.session_state.contagem_linhas = {k: int(v) for k, v in contagem_linhas.items()}
        st.session_state.eventos_encontrados = list(eventos)

        prog.empty()
        status.success(f"Eventos encontrados (alvo): {', '.join(eventos) if eventos else 'nenhum'}")

    except Exception as e:
        prog.empty()
        status.error(f"Falha ao processar o arquivo: {e}")
        st.stop()

    # =========================
    # Diagnóstico rápido
    # =========================
    colA, colB, colC = st.columns(3)
    with colA:
        st.metric("Linhas K150", st.session_state.contagem_linhas.get("K150", 0))
    with colB:
        st.metric("Linhas K300", st.session_state.contagem_linhas.get("K300", 0))
    with colC:
        st.metric("Linhas K050", st.session_state.contagem_linhas.get("K050", 0))

    if st.session_state.contagem_linhas.get("K300", 0) <= 0:
        st.error("Não encontrei K300 no arquivo — não é possível levantar verbas sem os itens de folha.")
        st.stop()

    # =========================
    # Carregar catálogo K150 (rubricas)
    # =========================
    if st.session_state.df_rubricas is None:
        p_k150 = st.session_state.arquivos_evento.get("K150")
        if p_k150 and Path(p_k150).exists():
            st.session_state.df_rubricas = ler_catalogo_k150(Path(p_k150))
        else:
            st.warning("K150 não encontrado. Você poderá filtrar por código (K300), mas sem descrição.")
            st.session_state.df_rubricas = pd.DataFrame(columns=["COD_RUBRICA", "DESC_RUBRICA"])

    df_rubricas = st.session_state.df_rubricas

    st.divider()
    st.subheader("1) Seleção de Rubricas (Checklist + busca)")

    busca = st.text_input("Buscar rubrica (código ou descrição)", value="", key="busca_rubricas")

    # filtra catálogo por busca
    df_view = df_rubricas.copy()
    if busca.strip():
        b = busca.strip().lower()
        df_view = df_view[
            df_view["COD_RUBRICA"].astype(str).str.lower().str.contains(b, na=False)
            | df_view["DESC_RUBRICA"].astype(str).str.lower().str.contains(b, na=False)
        ].copy()

    if df_view.empty:
        st.info("Nenhuma rubrica encontrada com esse filtro.")
    else:
        # coluna checkbox
        df_view["Selecionar"] = df_view["COD_RUBRICA"].astype(str).isin(st.session_state.selected_codigos)

        c1, c2, c3 = st.columns(3)
        if c1.button("Selecionar tudo (resultado da busca)"):
            st.session_state.selected_codigos |= set(df_view["COD_RUBRICA"].astype(str).tolist())
        if c2.button("Limpar seleção (resultado da busca)"):
            st.session_state.selected_codigos -= set(df_view["COD_RUBRICA"].astype(str).tolist())
        if c3.button("Limpar tudo"):
            st.session_state.selected_codigos = set()

        edited = st.data_editor(
            df_view[["Selecionar", "COD_RUBRICA", "DESC_RUBRICA"]],
            hide_index=True,
            use_container_width=True,
            disabled=["COD_RUBRICA", "DESC_RUBRICA"],
        )

        # sincroniza seleção com o que foi marcado/desmarcado na tela (apenas no resultado filtrado)
        marcados = set(edited.loc[edited["Selecionar"], "COD_RUBRICA"].astype(str).tolist())
        desmarcados = set(edited.loc[~edited["Selecionar"], "COD_RUBRICA"].astype(str).tolist())
        # adiciona marcados
        st.session_state.selected_codigos |= marcados
        # remove apenas os desmarcados que estavam no df_view atual
        st.session_state.selected_codigos -= (desmarcados & set(df_view["COD_RUBRICA"].astype(str).tolist()))

    st.caption(f"✅ Rubricas selecionadas: {len(st.session_state.selected_codigos)}")

    st.divider()
    st.subheader("2) Filtros do K300")

    colf1, colf2 = st.columns(2)
    with colf1:
        ind_rubr_opts = ["P", "D", "O"]
        ind_rubr_sel = st.multiselect(
            "IND_RUBR (ex.: P=Provento, D=Desconto, O=Outros)",
            options=ind_rubr_opts,
            default=sorted(st.session_state.filtro_ind_rubr),
            key="ui_ind_rubr",
        )
        st.session_state.filtro_ind_rubr = set(ind_rubr_sel) if ind_rubr_sel else set()

    with colf2:
        base_ps_opts = [str(i) for i in range(0, 10)]
        base_ps_sel = st.multiselect(
            "IND_BASE_PS (selecione os códigos desejados)",
            options=base_ps_opts,
            default=sorted(st.session_state.filtro_ind_base_ps),
            key="ui_base_ps",
        )
        st.session_state.filtro_ind_base_ps = set(base_ps_sel) if base_ps_sel else set()

    st.divider()
    st.subheader("3) Prévia (antes de gerar o Excel)")

    p_k300 = st.session_state.arquivos_evento.get("K300")
    if not p_k300 or not Path(p_k300).exists():
        st.error("Arquivo temporário do K300 não encontrado.")
        st.stop()

    # alerta de descrições repetidas (códigos diferentes com mesma descrição)
    df_repetidas = alertas_descricoes_repetidas(df_rubricas, st.session_state.selected_codigos)

    # botão para gerar prévia (evita recalcular a cada clique/tecla)
    if st.button("🔎 Gerar/Atualizar prévia", key="btn_previa"):
        if not st.session_state.selected_codigos:
            st.warning("Selecione ao menos uma rubrica no checklist (K150) para gerar a prévia.")
        else:
            with st.spinner("Calculando prévia (scan no K300 linha a linha)..."):
                st.session_state.preview_result = gerar_previa_k300(
                    path_k300=Path(p_k300),
                    selected_codigos=set(st.session_state.selected_codigos),
                    allowed_ind_rubr=set(st.session_state.filtro_ind_rubr),
                    allowed_ind_base_ps=set(st.session_state.filtro_ind_base_ps),
                    df_rubricas=df_rubricas,
                    sample_size=200,
                )

    prev = st.session_state.preview_result
    if prev:
        # Cards
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("📌 Rubricas selecionadas", prev["rubricas_selecionadas"])
        with m2:
            st.metric("📄 Linhas K300 filtradas", prev["linhas_filtradas"])
        with m3:
            st.metric("💰 Total (Σ VLR_RUBR)", prev["total_geral_formatado"])
        with m4:
            st.metric("📆 Competências distintas", prev["competencias_distintas"])

        # Totais por rubrica
        st.markdown("### Totais por rubrica (após filtros)")
        st.dataframe(prev["df_totais_rubrica"], use_container_width=True)

        # Totais por competência
        st.markdown("### Totais por competência (DT_COMP)")
        st.dataframe(prev["df_totais_competencia"], use_container_width=True)

        # Alertas
        st.markdown("### Alertas")
        if prev["rubricas_sem_movimento"]:
            st.warning(
                f"Rubricas selecionadas sem movimento (com esses filtros): {len(prev['rubricas_sem_movimento'])}"
            )
            st.dataframe(prev["df_sem_movimento"], use_container_width=True)
        else:
            st.success("Nenhuma rubrica selecionada ficou sem movimento com os filtros atuais.")

        if df_repetidas is not None and not df_repetidas.empty:
            st.info("Descrições com múltiplos códigos (revisar se você marcou todos os códigos desejados):")
            st.dataframe(df_repetidas, use_container_width=True)

        # Amostra
        st.markdown("### Amostra (primeiras linhas que irão para o Excel)")
        st.dataframe(prev["df_amostra"], use_container_width=True)

    st.divider()
    st.subheader("4) Gerar Excel interno")

    colg1, colg2 = st.columns([1, 2])
    with colg1:
        gerar = st.button("⚙️ Gerar Excel interno", key="btn_gerar_excel")

    if gerar:
        if not st.session_state.selected_codigos:
            st.warning("Selecione ao menos uma rubrica antes de gerar o Excel.")
        else:
            p_k150 = st.session_state.arquivos_evento.get("K150")
            p_k050 = st.session_state.arquivos_evento.get("K050")

            with st.spinner("Gerando Excel (K300 filtrado + K150 selecionadas + K050 completo)..."):
                excel_bytes = gerar_excel_interno(
                    path_k300=Path(p_k300),
                    path_k150=Path(p_k150) if p_k150 and Path(p_k150).exists() else None,
                    path_k050=Path(p_k050) if p_k050 and Path(p_k050).exists() else None,
                    selected_codigos=set(st.session_state.selected_codigos),
                    allowed_ind_rubr=set(st.session_state.filtro_ind_rubr),
                    allowed_ind_base_ps=set(st.session_state.filtro_ind_base_ps),
                    df_rubricas=df_rubricas,
                )
                st.session_state.excel_bytes = excel_bytes

            st.success("✅ Excel interno gerado!")

    if st.session_state.excel_bytes:
        st.download_button(
            label="📥 Baixar Excel interno (K300 filtrado + K150 + K050)",
            data=st.session_state.excel_bytes,
            file_name="MANAD_Levantamento_Interno.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_excel_interno",
        )
