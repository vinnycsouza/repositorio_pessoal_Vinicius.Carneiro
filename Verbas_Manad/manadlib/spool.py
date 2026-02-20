from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional, Set

import pandas as pd

from .layout import extrair_codigo_evento


def spool_init_state() -> dict:
    """
    Estado serializável para processamento incremental no Streamlit Cloud.
    """
    return {
        "initialized": False,
        "done": False,
        "offset": 0,          # bytes consumidos (TXT)
        "buffer": "",         # sobra de linha entre chunks (TXT)
        "paths": {},          # codigo -> str(path)
        "counts": {},         # codigo -> int
        "is_txt": None,
        "total_bytes": 1,
    }


def _get_path(paths: Dict[str, str], tmp_dir: Path, codigo: str) -> Path:
    if codigo not in paths:
        p = tmp_dir / f"{codigo}.txt"
        paths[codigo] = str(p)
    return Path(paths[codigo])


def spool_step(
    state: dict,
    uploaded_file,
    tmp_dir: Path,
    eventos_alvo: Set[str],
    batch_bytes: int = 8_000_000,
    progress_bar=None,
    status_slot=None,
) -> dict:
    """
    Processa o MANAD em passos:
    - TXT: lê em chunks por bytes, separa por evento e grava em arquivos temporários.
    - XLSX: processa inteiro em 1 passo (pandas não é amigável a chunk real em Excel).
    """
    eventos_alvo = set(eventos_alvo)

    if state.get("done"):
        return state

    if not state.get("initialized"):
        state["is_txt"] = str(uploaded_file.name).lower().endswith(".txt")
        state["total_bytes"] = getattr(uploaded_file, "size", None) or 1
        state["offset"] = 0
        state["buffer"] = ""
        state["paths"] = state.get("paths") or {}
        state["counts"] = state.get("counts") or {}
        state["initialized"] = True

        if status_slot:
            status_slot.info("Iniciando spool (modo incremental)...")

    # ---------------------------
    # XLSX: faz tudo em um passo
    # ---------------------------
    if not state["is_txt"]:
        if status_slot:
            status_slot.info("Entrada XLSX: processando em um passo (pode demorar).")

        counts = defaultdict(int, state["counts"])
        paths: Dict[str, str] = state["paths"]

        xls = pd.ExcelFile(uploaded_file)
        total_abas = len(xls.sheet_names) or 1

        for i, aba in enumerate(xls.sheet_names, start=1):
            if progress_bar:
                progress_bar.progress(i / total_abas)
            if status_slot:
                status_slot.text(f"Lendo aba: {aba} ({i}/{total_abas})")

            df_aba = pd.read_excel(xls, sheet_name=aba, header=None)
            if 0 not in df_aba.columns:
                continue

            for v in df_aba[0].dropna().astype(str).tolist():
                v = v.strip()
                codigo = extrair_codigo_evento(v)
                if not codigo or codigo not in eventos_alvo:
                    continue

                p = _get_path(paths, tmp_dir, codigo)
                with p.open("a", encoding="utf-8", newline="\n") as out:
                    out.write(v + "\n")
                counts[codigo] += 1

        state["paths"] = paths
        state["counts"] = dict(counts)
        state["done"] = True
        return state

    # ---------------------------
    # TXT: incremental por bytes
    # ---------------------------
    counts = defaultdict(int, state["counts"])
    paths: Dict[str, str] = state["paths"]

    try:
        uploaded_file.seek(state["offset"])
        chunk = uploaded_file.read(batch_bytes)
    except Exception:
        # se der problema no seek/read, encerra
        state["counts"] = dict(counts)
        state["paths"] = paths
        state["done"] = True
        return state

    if not chunk:
        # fim
        # flush do buffer restante (se virar linha válida)
        buf = (state.get("buffer") or "").strip("\n")
        if buf:
            codigo = extrair_codigo_evento(buf)
            if codigo and codigo in eventos_alvo:
                p = _get_path(paths, tmp_dir, codigo)
                with p.open("a", encoding="utf-8", newline="\n") as out:
                    out.write(buf + "\n")
                counts[codigo] += 1

        state["counts"] = dict(counts)
        state["paths"] = paths
        state["done"] = True
        if progress_bar:
            progress_bar.progress(1.0)
        if status_slot:
            status_slot.success("Spool finalizado (TXT).")
        return state

    # decodifica e divide linhas preservando sobra
    text = chunk.decode("latin1", errors="ignore")
    text = (state.get("buffer") or "") + text

    lines = text.split("\n")
    state["buffer"] = lines[-1]  # sobra
    lines = lines[:-1]           # linhas completas

    # grava linhas por evento
    for linha in lines:
        linha = linha.rstrip("\r")
        if not linha:
            continue

        codigo = extrair_codigo_evento(linha)
        if not codigo or codigo not in eventos_alvo:
            continue

        p = _get_path(paths, tmp_dir, codigo)
        with p.open("a", encoding="utf-8", newline="\n") as out:
            out.write(linha + "\n")
        counts[codigo] += 1

    # atualiza offset e progresso
    state["offset"] += len(chunk)
    state["counts"] = dict(counts)
    state["paths"] = paths

    if progress_bar:
        progress_bar.progress(min(state["offset"] / (state["total_bytes"] or 1), 1.0))
    if status_slot:
        status_slot.text(f"Spool em andamento... {state['offset']}/{state['total_bytes']} bytes")

    return state