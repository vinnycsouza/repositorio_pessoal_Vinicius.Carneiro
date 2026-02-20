import io
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

# Garante imports quando rodar como "streamlit run ..."
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from manadlib.spool import spool_por_evento
from manadlib.preview import gerar_previa_k300, ler_catalogo_k150, alertas_descricoes_repetidas
from manadlib.export import gerar_excel_interno


# =========================
# Streamlit UI
# =========================
st.set_page_config(page_title="MANAD — Verbas Indenizatórias", layout="wide")
st.title("📂 MANAD — Levantamento de Verbas Indenizatórias (K150/K300) + K050 (Trabalhadores)")

uploaded_file = st.file_uploader(
    "Envie o arquivo MANAD (.txt ou .xlsx)",
    type=["txt", "xlsx"],
    key="upload_manad",
)

# =========================
# Estado da sessão
# =========================
def ss_init():
    st.session_state.setdefault("uploaded_fingerprint", None)
    st.session_state.setdefault("manad_processado", False)

    st.session_state.setdefault("tmp_dir", None)
    st.session_state.setdefault("arquivos_evento", {})      # codigo -> str(path)
    st.session_state.setdefault("contagem_linhas", {})      # codigo -> int
    st.session_state.setdefault("eventos_encontrados", [])  # list[str]

    st.session_state.setdefault("df_rubricas", None)        # catálogo K150
    st.session_state.setdefault("selected_codigos", set())  # set[str]

    # filtros
    st.session_state.setdefault("filtro_ind_rubr", {"P"})       # P=provento (default)
    st.session_state.setdefault("filtro_ind_base_ps", {"1", "2"})  # default 1 e 2

    # outputs
    st.session_state.setdefault("preview_result", None)
    st.session_state.setdefault("excel_bytes", None)

ss_init()

# =========================
# Helper: reset quando troca arquivo
# =========================
def reset_for_new_upload(new_fp: str):
    st.session_state.uploaded_fingerprint = new_fp
    st.session_state.manad_processado = False

    st.session_state.tmp_dir = None
    st.session_state.arquivos_evento = {}
    st.session_state.contagem_linhas = {}
    st.session_state.eventos_encontrados = []

    st.session_state.df_rubricas = None
    st.session_state.selected_codigos = set()

    st.session_state.preview_result = None
    st.session_state.excel_bytes = None


# =========================
# Etapa 0: Upload (NÃO processa pesado aqui)
# =========================
if not uploaded_file:
    st.info("Envie um arquivo MANAD para começar.")
    st.stop()

fp = f"{uploaded_file.name}|{getattr(uploaded_file, 'size', '')}"
if st.session_state.uploaded_fingerprint != fp:
    reset_for_new_upload(fp)

st.success("Arquivo carregado! ✅")
st.caption("Agora você controla o processamento pelo botão (isso evita travar enquanto você busca rubricas).")

st.divider()

# =========================
# Etapa 1: Processar MANAD (spool pesado)
# =========================
col1, col2 = st.columns([1, 2])
with col1:
    processar = st.button("1) ⚙️ Processar MANAD (separar eventos)", key="btn_processar")
with col2:
    st.caption("Processa apenas K150, K300 e K050 (modo econômico de memória).")

if processar:
    # cria pasta temporária do processamento
    st.session_state.tmp_dir = str(Path(tempfile.mkdtemp(prefix="manad_")))
    tmp_dir = Path(st.session_state.tmp_dir)

    eventos_alvo = {"K150", "K300", "K050"}

    status = st.empty()
    prog = st.progress(0.0)

    try:
        status.info("Separando o arquivo por evento (K150/K300/K050)...")

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

        # carrega catálogo K150 (se houver)
        p_k150 = st.session_state.arquivos_evento.get("K150")
        if p_k150 and Path(p_k150).exists():
            st.session_state.df_rubricas = ler_catalogo_k150(Path(p_k150))
        else:
            st.session_state.df_rubricas = pd.DataFrame(columns=["COD_RUBRICA", "DESC_RUBRICA"])

        st.session_state.manad_processado = True

        prog.empty()
        status.success(f"Eventos prontos: {', '.join(eventos) if eventos else 'nenhum'}")

    except Exception as e:
        prog.empty()
        status.error(f"Falha ao processar o arquivo: {e}")
        st.session_state.manad_processado = False

# Se ainda não processou, para aqui
if not st.session_state.manad_processado:
    st.info("Clique em **Processar MANAD** para liberar o checklist, filtros, prévia e exportação.")
    st.stop()

# =========================
# Diagnóstico rápido
# =========================
cA, cB, cC = st.columns(3)
with cA:
    st.metric("Linhas K150", st.session_state.contagem_linhas.get("K150", 0))
with cB:
    st.metric("Linhas K300", st.session_state.contagem_linhas.get("K300", 0))
with cC:
    st.metric("Linhas K050", st.session_state.contagem_linhas.get("K050", 0))

p_k300 = st.session_state.arquivos_evento.get("K300")
if not p_k300 or not Path(p_k300).exists():
    st.error("Arquivo temporário do K300 não encontrado.")
    st.stop()

st.divider()

# =========================
# Etapa 2: Seleção de Rubricas (Checklist + busca)
# =========================
st.subheader("2) Seleção de Rubricas (K150) — Checklist + busca")

df_rubricas = st.session_state.df_rubricas
if df_rubricas is None or df_rubricas.empty:
    st.warning("K150 vazio ou ausente. Você pode continuar, mas sem descrição de rubricas.")
    df_rubricas = pd.DataFrame(columns=["COD_RUBRICA", "DESC_RUBRICA"])

busca = st.text_input("Buscar rubrica (código ou descrição)", value="", key="busca_rubricas")

df_view = df_rubricas.copy()
df_view["COD_RUBRICA"] = df_view["COD_RUBRICA"].astype(str)
df_view["DESC_RUBRICA"] = df_view["DESC_RUBRICA"].astype(str)

if busca.strip():
    b = busca.strip().lower()
    df_view = df_view[
        df_view["COD_RUBRICA"].str.lower().str.contains(b, na=False)
        | df_view["DESC_RUBRICA"].str.lower().str.contains(b, na=False)
    ].copy()

if df_view.empty:
    st.info("Nenhuma rubrica encontrada com esse filtro.")
else:
    df_view["Selecionar"] = df_view["COD_RUBRICA"].isin(st.session_state.selected_codigos)

    b1, b2, b3 = st.columns(3)
    if b1.button("Selecionar tudo (resultado da busca)", key="sel_tudo_busca"):
        st.session_state.selected_codigos |= set(df_view["COD_RUBRICA"].tolist())
    if b2.button("Limpar seleção (resultado da busca)", key="limpar_busca"):
        st.session_state.selected_codigos -= set(df_view["COD_RUBRICA"].tolist())
    if b3.button("Limpar tudo", key="limpar_tudo"):
        st.session_state.selected_codigos = set()

    edited = st.data_editor(
        df_view[["Selecionar", "COD_RUBRICA", "DESC_RUBRICA"]],
        hide_index=True,
        use_container_width=True,
        disabled=["COD_RUBRICA", "DESC_RUBRICA"],
        key="editor_rubricas",
    )

    # sincroniza seleção
    marcados = set(edited.loc[edited["Selecionar"], "COD_RUBRICA"].astype(str).tolist())
    desmarcados = set(edited.loc[~edited["Selecionar"], "COD_RUBRICA"].astype(str).tolist())

    st.session_state.selected_codigos |= marcados
    st.session_state.selected_codigos -= (desmarcados & set(df_view["COD_RUBRICA"].astype(str).tolist()))

st.caption(f"✅ Rubricas selecionadas: {len(st.session_state.selected_codigos)}")

st.divider()

# =========================
# Etapa 3: Filtros do K300 (leve)
# =========================
st.subheader("3) Filtros do K300")

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

# =========================
# Etapa 4: Prévia (pesado) — só roda no botão
# =========================
st.subheader("4) Prévia (antes de gerar o Excel)")

df_repetidas = alertas_descricoes_repetidas(df_rubricas, st.session_state.selected_codigos)

colp1, colp2 = st.columns([1, 3])
with colp1:
    btn_previa = st.button("🔎 Gerar/Atualizar prévia", key="btn_previa")
with colp2:
    st.caption("A prévia faz scan no K300 linha a linha (pode demorar em arquivos grandes).")

if btn_previa:
    if not st.session_state.selected_codigos:
        st.warning("Selecione ao menos uma rubrica no checklist (K150) para gerar a prévia.")
    else:
        with st.spinner("Calculando prévia (scan no K300)..."):
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
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("📌 Rubricas selecionadas", prev["rubricas_selecionadas"])
    with m2:
        st.metric("📄 Linhas K300 filtradas", prev["linhas_filtradas"])
    with m3:
        st.metric("💰 Total (Σ VLR_RUBR)", prev["total_geral_formatado"])
    with m4:
        st.metric("📆 Competências distintas", prev["competencias_distintas"])

    st.markdown("### Totais por rubrica (após filtros)")
    st.dataframe(prev["df_totais_rubrica"], use_container_width=True)

    st.markdown("### Totais por competência (DT_COMP)")
    st.dataframe(prev["df_totais_competencia"], use_container_width=True)

    st.markdown("### Alertas")
    if prev["rubricas_sem_movimento"]:
        st.warning(f"Rubricas selecionadas sem movimento (com esses filtros): {len(prev['rubricas_sem_movimento'])}")
        st.dataframe(prev["df_sem_movimento"], use_container_width=True)
    else:
        st.success("Nenhuma rubrica selecionada ficou sem movimento com os filtros atuais.")

    if df_repetidas is not None and not df_repetidas.empty:
        st.info("Descrições com múltiplos códigos (revisar se você marcou todos os códigos desejados):")
        st.dataframe(df_repetidas, use_container_width=True)

    st.markdown("### Amostra (primeiras linhas que irão para o Excel)")
    st.dataframe(prev["df_amostra"], use_container_width=True)
else:
    st.info("Gere a prévia para visualizar totais e validar filtros antes de exportar.")

st.divider()

# =========================
# Etapa 5: Gerar Excel (pesado) — só roda no botão
# =========================
st.subheader("5) Gerar Excel interno")

colg1, colg2 = st.columns([1, 3])
with colg1:
    btn_excel = st.button("⚙️ Gerar Excel interno", key="btn_gerar_excel")
with colg2:
    st.caption("Gera K300_FILTRADO + (se atualizado) RESUMO_DT_COMP + K150_SELECIONADAS + K050_TRABALHADORES.")

if btn_excel:
    if not st.session_state.selected_codigos:
        st.warning("Selecione ao menos uma rubrica antes de gerar o Excel.")
    else:
        p_k150 = st.session_state.arquivos_evento.get("K150")
        p_k050 = st.session_state.arquivos_evento.get("K050")

        with st.spinner("Gerando Excel (pode demorar em arquivos grandes)..."):
            st.session_state.excel_bytes = gerar_excel_interno(
                path_k300=Path(p_k300),
                path_k150=Path(p_k150) if p_k150 and Path(p_k150).exists() else None,
                path_k050=Path(p_k050) if p_k050 and Path(p_k050).exists() else None,
                selected_codigos=set(st.session_state.selected_codigos),
                allowed_ind_rubr=set(st.session_state.filtro_ind_rubr),
                allowed_ind_base_ps=set(st.session_state.filtro_ind_base_ps),
                df_rubricas=df_rubricas,
            )

        st.success("✅ Excel interno gerado!")

if st.session_state.excel_bytes:
    st.download_button(
        label="📥 Baixar Excel interno",
        data=st.session_state.excel_bytes,
        file_name="MANAD_Levantamento_Interno.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_excel_interno",
    )