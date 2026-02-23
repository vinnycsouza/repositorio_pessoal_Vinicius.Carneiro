# app.py
# ✅ Auditor INSS — NOVA ARQUITETURA (in-place) — sem gambiarra
# - UI limpa + orquestração
# - Indexação: Período -> Resumo (modelo-aware)
# - Cache de indexação (session_state)
# - Export: RESUMOS_ENCONTRADOS
# - Processamento: fase 1 pode usar legado de forma encapsulada (sem reabrir PDF toda hora)
# - Preparado para rules_v1 (base_min/base_max) depois

from __future__ import annotations

import io
import os
import zipfile
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd
import pdfplumber
import streamlit as st

# ===== NOVO NÚCLEO =====
from core.pipeline import run_index_only
from exports.excel_export import export_resumos_encontrados

# ===== LEGADO (opcional nesta fase) =====
LEGADO_DISPONIVEL = True
try:
    from extrator_pdf import (
        extrair_eventos_page,
        extrair_base_empresa_page,
        pagina_eh_de_bases,
    )
    from calculo_base import calcular_base_por_grupo
    from auditor_base import auditoria_por_exclusao_com_aproximacao
except Exception:
    LEGADO_DISPONIVEL = False


# ----------------------------
# Config UI
# ----------------------------
st.set_page_config(page_title="Auditor INSS (Nova Engine)", layout="wide")
st.title("🧾 Auditor INSS — Nova Engine (in-place)")

st.caption(
    "Objetivo: indexar e auditar folhas/resumos sem misturar blocos (GERAL, obras, centros, etc.). "
    "Arquitetura limpa: UI no app.py, lógica nos módulos."
)

# ----------------------------
# Helpers
# ----------------------------
def _safe_filename(name: str) -> str:
    name = (name or "").replace("\\", "/").split("/")[-1]
    return name.strip() or "arquivo.pdf"


def _is_pdf(name: str) -> bool:
    return Path(name).suffix.lower() == ".pdf"


def _extract_pdfs_from_zip(zip_bytes: bytes, out_dir: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            fname = _safe_filename(info.filename)
            if not _is_pdf(fname):
                continue
            target = os.path.join(out_dir, fname)
            base, ext = os.path.splitext(target)
            i = 1
            while os.path.exists(target):
                target = f"{base}__{i}{ext}"
                i += 1
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            out.append((target, Path(target).name))
    return out


def _save_uploaded_pdf(up, out_dir: str) -> Tuple[str, str]:
    name = _safe_filename(up.name)
    target = os.path.join(out_dir, name)
    base, ext = os.path.splitext(target)
    i = 1
    while os.path.exists(target):
        target = f"{base}__{i}{ext}"
        i += 1
    with open(target, "wb") as f:
        f.write(up.getvalue())
    return target, Path(target).name


def _resumos_to_df(resumos) -> pd.DataFrame:
    rows = []
    for r in resumos:
        rows.append(
            {
                "arquivo": r.arquivo,
                "arquivo_id": r.arquivo_id,
                "competencia": r.competencia,
                "modelo": r.modelo.value,
                "subtipo": r.subtipo.value,
                "resumo_nome": r.resumo_nome,
                "resumo_id": r.resumo_id,
                "pag_ini": r.pag_ini,
                "pag_fim": r.pag_fim,
                "confianca_modelo": r.confianca_modelo.value,
                "score_modelo": r.score_modelo,
                "sinais_detectados": "; ".join(r.sinais_detectados or []),
            }
        )
    return pd.DataFrame(rows)


def _key_for_index(pdf_filenames: List[str], max_pages: int) -> str:
    joined = "|".join(sorted(pdf_filenames))
    return f"{joined}::max_pages={max_pages}"


# ----------------------------
# Sidebar: configs
# ----------------------------
st.sidebar.header("⚙️ Configurações")

max_pages = st.sidebar.number_input(
    "Limite de páginas por PDF (0 = todas)",
    min_value=0,
    max_value=5000,
    value=0,
    step=50,
    help="Use para PDFs anuais grandes. 0 processa todas as páginas.",
)
max_pages = int(max_pages)
limit_pages = None if max_pages == 0 else max_pages

st.sidebar.divider()
st.sidebar.header("🧪 Modos")

modo = st.sidebar.radio(
    "Escolha o modo",
    options=[
        "1) Indexar (RESUMOS_ENCONTRADOS)",
        "2) Processar bloco (legado encapsulado) — opcional",
    ],
    index=0,
)

if modo.startswith("2") and not LEGADO_DISPONIVEL:
    st.sidebar.warning("Módulos do legado não puderam ser importados. Ative o modo 1 por enquanto.")


# ----------------------------
# Upload
# ----------------------------
st.subheader("📥 Entrada")
uploads = st.file_uploader(
    "Envie PDFs (ou ZIPs com PDFs)",
    type=["pdf", "zip"],
    accept_multiple_files=True,
)

if not uploads:
    st.info("Envie ao menos um PDF ou ZIP para começar.")
    st.stop()

# ----------------------------
# Materializa PDFs em disco temp (1x)
# ----------------------------
with tempfile.TemporaryDirectory() as tmpdir:
    pdfs: List[Tuple[str, str]] = []  # (path, display_name)
    for up in uploads:
        if up.name.lower().endswith(".zip"):
            pdfs.extend(_extract_pdfs_from_zip(up.getvalue(), tmpdir))
        elif up.name.lower().endswith(".pdf"):
            pdfs.append(_save_uploaded_pdf(up, tmpdir))

    if not pdfs:
        st.error("Não encontrei PDFs válidos nos uploads.")
        st.stop()

    st.write(f"📄 PDFs prontos para leitura: **{len(pdfs)}**")

    pdf_names = [name for _, name in pdfs]
    cache_key = _key_for_index(pdf_names, max_pages)

    # ----------------------------
    # Indexação com cache (session_state)
    # ----------------------------
    if "index_cache" not in st.session_state:
        st.session_state["index_cache"] = {}

    if modo.startswith("1"):
        st.subheader("1) Indexar PDFs e listar RESUMOS_ENCONTRADOS")

        colA, colB = st.columns([1, 3], vertical_alignment="top")
        with colA:
            force = st.checkbox("Reindexar (ignorar cache)", value=False)
            run_btn = st.button("▶️ Indexar agora", type="primary")
        with colB:
            st.caption(
                "A indexação detecta modelo por página (MVP) e tenta extrair um nome de resumo. "
                "Depois vamos mesclar páginas por resumo e extrair competência por bloco."
            )

        if not run_btn:
            st.stop()

        if (not force) and (cache_key in st.session_state["index_cache"]):
            all_resumos = st.session_state["index_cache"][cache_key]
        else:
            progress = st.progress(0)
            status = st.empty()
            all_resumos = []

            for i, (path, display_name) in enumerate(pdfs, start=1):
                status.write(f"Indexando **{display_name}** ({i}/{len(pdfs)}) ...")
                try:
                    resumos = run_index_only(path, arquivo_nome=display_name, max_pages=limit_pages)
                    all_resumos.extend(resumos)
                except Exception as e:
                    st.error(f"Erro ao indexar {display_name}: {e}")
                progress.progress(int((i / len(pdfs)) * 100))

            progress.empty()
            status.empty()

            st.session_state["index_cache"][cache_key] = all_resumos

        df = _resumos_to_df(all_resumos)
        if df.empty:
            st.warning("Nenhum resumo foi encontrado. Pode ser PDF imagem (sem texto) ou layout não detectado.")
            st.stop()

        m1, m2, m3 = st.columns(3)
        m1.metric("Linhas (páginas indexadas)", f"{len(df):,}".replace(",", "."))
        m2.metric("Arquivos", str(df["arquivo"].nunique()))
        m3.metric("Resumos distintos", str(df["resumo_nome"].nunique()))

        st.dataframe(df, use_container_width=True, height=420)

        xlsx = export_resumos_encontrados(all_resumos)
        st.download_button(
            "⬇️ Baixar Excel (RESUMOS_ENCONTRADOS)",
            data=xlsx,
            file_name="resumos_encontrados.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.success("Indexação concluída. Próximo passo: mesclar páginas por resumo e extrair competência por bloco.")
        st.stop()

    # ----------------------------
    # Processar bloco (legado encapsulado, sem reabrir PDF em loop)
    # ----------------------------
    if modo.startswith("2") and LEGADO_DISPONIVEL:
        st.subheader("2) Processar bloco (legado encapsulado)")

        # garante índice em cache
        if cache_key not in st.session_state["index_cache"]:
            st.info("Você ainda não indexou neste lote. Clique abaixo para indexar automaticamente.")
            if st.button("Indexar agora (necessário)", type="primary"):
                all_resumos = []
                for path, display_name in pdfs:
                    all_resumos.extend(run_index_only(path, arquivo_nome=display_name, max_pages=limit_pages))
                st.session_state["index_cache"][cache_key] = all_resumos
            else:
                st.stop()

        all_resumos = st.session_state["index_cache"][cache_key]
        df_idx = _resumos_to_df(all_resumos)

        # Seleção
        arqs = sorted(df_idx["arquivo"].unique().tolist())
        arq_sel = st.selectbox("Arquivo", arqs, index=0)

        df_arq = df_idx[df_idx["arquivo"] == arq_sel].copy()
        # Competência ainda vazia no MVP, então usamos "SEM_COMP" por enquanto
        comps = sorted([c for c in df_arq["competencia"].unique().tolist() if c] or ["SEM_COMP"])
        comp_sel = st.selectbox("Competência", comps, index=max(0, len(comps) - 1))

        df_comp = df_arq[df_arq["competencia"] == comp_sel].copy() if comp_sel != "SEM_COMP" else df_arq
        # agrupa por resumo_nome (MVP por página) — depois vamos mesclar certo
        resumos = sorted(df_comp["resumo_nome"].unique().tolist())
        resumo_nome = st.selectbox("Resumo (nome)", resumos, index=0)

        df_res = df_comp[df_comp["resumo_nome"] == resumo_nome].copy()
        # pega as páginas do “resumo”
        pag_idxs = sorted(df_res["pag_ini"].astype(int).tolist())
        st.caption(f"Páginas selecionadas: {pag_idxs[:20]}{' ...' if len(pag_idxs)>20 else ''}")

        # parâmetros do legado
        c1, c2, c3 = st.columns(3)
        with c1:
            tol_totalizador = st.number_input("Tolerância totalizador (R$)", min_value=0.0, value=1.00, step=0.50)
        with c2:
            banda_ok = st.number_input("Banda OK (|erro| ≤)", min_value=0.0, value=10.0, step=1.0)
        with c3:
            banda_aceitavel = st.number_input("Banda ACEITÁVEL (|erro| ≤)", min_value=0.0, value=10000.0, step=100.0)

        run = st.button("▶️ Processar bloco (legado)", type="primary")
        if not run:
            st.stop()

        # encontra o PDF path do arquivo selecionado
        pdf_path = None
        for p, nm in pdfs:
            if nm == arq_sel:
                pdf_path = p
                break
        if not pdf_path:
            st.error("Não achei o arquivo selecionado no lote atual.")
            st.stop()

        # abre UMA vez
        linhas_resumo = []
        linhas_erros = []
        eventos_dump = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                base_empresa = None
                totais_pdf = None
                eventos = []

                for idx in pag_idxs:
                    page = pdf.pages[idx]
                    try:
                        if pagina_eh_de_bases(page):
                            b = extrair_base_empresa_page(page)
                            if b and base_empresa is None:
                                base_empresa = b
                            continue
                        eventos.extend(extrair_eventos_page(page))
                    except Exception as e:
                        linhas_erros.append({"pagina": idx, "erro": f"{type(e).__name__}: {e}"})

                df = pd.DataFrame(eventos)
                if df.empty:
                    st.warning("Sem eventos extraídos neste bloco.")
                    if linhas_erros:
                        st.dataframe(pd.DataFrame(linhas_erros), use_container_width=True)
                    st.stop()

                # cálculo e auditoria
                try:
                    _, df = calcular_base_por_grupo(df)
                except Exception:
                    pass

                prov = df[df.get("tipo", "") == "PROVENTO"].copy()
                totais_usados = {"total": float(prov.get("total", pd.Series([0.0])).sum())}

                # usa “total” como grupo único neste encapsulamento rápido
                res = auditoria_por_exclusao_com_aproximacao(
                    df=df,
                    base_oficial=base_empresa,
                    totais_proventos=totais_usados,
                    grupo="total",
                    top_n_subset=44,
                )

                erro = res.get("erro_por_baixo")
                erro_abs = None if erro is None else abs(float(erro))
                if not base_empresa:
                    status = "INCOMPLETO_BASE"
                elif erro_abs is None:
                    status = "SEM_ERRO"
                elif erro_abs <= banda_ok:
                    status = "OK"
                elif erro_abs <= banda_aceitavel:
                    status = "ACEITAVEL"
                else:
                    status = "RUIM"

                linhas_resumo.append(
                    {
                        "arquivo": arq_sel,
                        "competencia": comp_sel,
                        "resumo_nome": resumo_nome,
                        "paginas": f"{min(pag_idxs)}-{max(pag_idxs)}" if pag_idxs else "",
                        "proventos_total": float(prov.get("total", pd.Series([0.0])).sum()),
                        "base_oficial": (base_empresa.get("total") if isinstance(base_empresa, dict) else None),
                        "erro_por_baixo": erro,
                        "status": status,
                    }
                )
                eventos_dump.append(df)

        except Exception as e:
            st.error(f"Falha ao abrir/processar o PDF: {type(e).__name__}: {e}")
            st.stop()

        df_resumo = pd.DataFrame(linhas_resumo)
        st.subheader("Resumo do bloco (legado encapsulado)")
        st.dataframe(df_resumo, use_container_width=True)

        st.subheader("Eventos extraídos (amostra)")
        df_eventos = pd.concat(eventos_dump, ignore_index=True) if eventos_dump else pd.DataFrame()
        st.dataframe(df_eventos.head(3000), use_container_width=True)

        if linhas_erros:
            st.subheader("Erros capturados")
            st.dataframe(pd.DataFrame(linhas_erros), use_container_width=True)

        st.info(
            "Este modo 2 é apenas uma ponte para você não perder a auditoria atual enquanto o novo motor "
            "(modelos + regras_v1 + base_min/base_max) é plugado."
        )