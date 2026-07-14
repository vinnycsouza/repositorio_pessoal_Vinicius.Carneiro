from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, Set

import pandas as pd

from .layout import extrair_codigo_evento


def spool_init_state() -> dict:
    """
    Estado serializável para processamento incremental no Streamlit Cloud.
    """
    return {
        "initialized": False,
        "done": False,
        "offset": 0,
        "buffer": "",
        "paths": {},
        "counts": {},
        "is_txt": None,
        "total_bytes": 1,
    }


def _get_path(paths: Dict[str, str], tmp_dir: Path, codigo: str) -> Path:
    if codigo not in paths:
        p = tmp_dir / f"{codigo}.txt"
        paths[codigo] = str(p)
    return Path(paths[codigo])


def _normalizar_valor_excel(valor) -> str:
    """
    Mantém os valores do Excel como texto e evita NaN/None.
    """
    if valor is None:
        return ""

    texto = str(valor).strip()

    if texto.lower() in {"nan", "none", "nat"}:
        return ""

    # Evita códigos inteiros lidos como 354.0.
    if texto.endswith(".0") and texto[:-2].lstrip("-").isdigit():
        return texto[:-2]

    return texto


def _processar_xlsx(
    uploaded_file,
    tmp_dir: Path,
    eventos_alvo: Set[str],
    paths: Dict[str, str],
    counts,
    progress_bar=None,
    status_slot=None,
) -> None:
    """
    Lê abas estruturadas em colunas e reconstrói as linhas MANAD usando "|".

    Exemplo:
    REG | CNPJ/CEI | DT_INC_ALT | COD_RUBRICA | DESC_RUBRICA

    vira:
    K150|20364206000108|22062022|354|Ajuda de Custos
    """
    uploaded_file.seek(0)
    xls = pd.ExcelFile(uploaded_file)
    total_abas = len(xls.sheet_names) or 1

    for i, aba in enumerate(xls.sheet_names, start=1):
        if progress_bar:
            progress_bar.progress(i / total_abas)

        if status_slot:
            status_slot.text(f"Lendo aba: {aba} ({i}/{total_abas})")

        codigo_aba = str(aba).strip().upper()

        # Ignora abas que não representam eventos usados pelo app.
        if codigo_aba not in eventos_alvo:
            continue

        df_aba = pd.read_excel(
            xls,
            sheet_name=aba,
            header=0,
            dtype=str,
            keep_default_na=False,
        )

        if df_aba.empty:
            continue

        p = _get_path(paths, tmp_dir, codigo_aba)

        with p.open("a", encoding="utf-8", newline="\n") as out:
            for valores_linha in df_aba.itertuples(index=False, name=None):
                valores = [_normalizar_valor_excel(v) for v in valores_linha]

                if not valores or not any(valores):
                    continue

                # A coluna REG deve ser o primeiro campo.
                # Se a planilha não trouxer REG, usa o nome da aba.
                if valores[0].strip().upper() != codigo_aba:
                    valores.insert(0, codigo_aba)

                linha_manad = "|".join(valores)
                out.write(linha_manad + "\n")
                counts[codigo_aba] += 1


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
    - TXT: leitura incremental por bytes.
    - XLSX: lê as abas estruturadas e reconstrói as linhas MANAD.
    """
    eventos_alvo = {str(e).strip().upper() for e in eventos_alvo}

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
    # XLSX: processa em um passo
    # ---------------------------
    if not state["is_txt"]:
        if status_slot:
            status_slot.info("Entrada XLSX: reconstruindo os eventos a partir das colunas.")

        counts = defaultdict(int, state.get("counts") or {})
        paths: Dict[str, str] = state.get("paths") or {}

        _processar_xlsx(
            uploaded_file=uploaded_file,
            tmp_dir=tmp_dir,
            eventos_alvo=eventos_alvo,
            paths=paths,
            counts=counts,
            progress_bar=progress_bar,
            status_slot=status_slot,
        )

        state["paths"] = paths
        state["counts"] = dict(counts)
        state["done"] = True

        if progress_bar:
            progress_bar.progress(1.0)

        return state

    # ---------------------------
    # TXT: incremental por bytes
    # ---------------------------
    counts = defaultdict(int, state.get("counts") or {})
    paths: Dict[str, str] = state.get("paths") or {}

    try:
        uploaded_file.seek(state["offset"])
        chunk = uploaded_file.read(batch_bytes)
    except Exception as erro:
        state["counts"] = dict(counts)
        state["paths"] = paths
        state["done"] = True
        state["error"] = str(erro)
        return state

    if not chunk:
        buf = (state.get("buffer") or "").strip("\r\n")

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

    text = chunk.decode("latin1", errors="ignore")
    text = (state.get("buffer") or "") + text

    lines = text.split("\n")
    state["buffer"] = lines[-1]
    lines = lines[:-1]

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

    state["offset"] += len(chunk)
    state["counts"] = dict(counts)
    state["paths"] = paths

    if progress_bar:
        progress_bar.progress(
            min(state["offset"] / (state["total_bytes"] or 1), 1.0)
        )

    if status_slot:
        status_slot.text(
            f"Spool em andamento... {state['offset']}/{state['total_bytes']} bytes"
        )

    return state
