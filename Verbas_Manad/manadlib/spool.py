from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional, Set, Tuple, Any

import pandas as pd

from .layout import extrair_codigo_evento


def spool_por_evento(
    uploaded_file,
    tmp_dir: Path,
    eventos_alvo: Set[str],
    progress_bar=None,
    status_slot=None,
) -> Tuple[Dict[str, Path], Dict[str, int], list[str]]:
    """
    (Modo antigo — mantém compatibilidade)
    Separa o arquivo em TXT temporários por evento (somente eventos_alvo).
    """
    arquivos_evento: Dict[str, Path] = {}
    contagem_linhas = defaultdict(int)
    handles = {}

    def get_handle(codigo: str):
        if codigo not in handles:
            p = tmp_dir / f"{codigo}.txt"
            arquivos_evento[codigo] = p
            handles[codigo] = p.open("w", encoding="utf-8", newline="\n")
        return handles[codigo]

    is_txt = uploaded_file.name.lower().endswith(".txt")

    # garante início do arquivo
    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    if is_txt:
        total_bytes = getattr(uploaded_file, "size", None) or 1
        bytes_lidos = 0

        for raw in uploaded_file:
            try:
                bytes_lidos += len(raw)
                if progress_bar:
                    progress_bar.progress(min(bytes_lidos / total_bytes, 1.0))

                linha = raw.decode("latin1", errors="ignore").rstrip("\n")
                codigo = extrair_codigo_evento(linha)
                if not codigo or codigo not in eventos_alvo:
                    continue

                h = get_handle(codigo)
                h.write(linha + "\n")
                contagem_linhas[codigo] += 1
            except Exception:
                continue

    else:
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
                h = get_handle(codigo)
                h.write(v + "\n")
                contagem_linhas[codigo] += 1

    for h in handles.values():
        try:
            h.close()
        except Exception:
            pass

    eventos = sorted(arquivos_evento.keys())
    return arquivos_evento, dict(contagem_linhas), eventos


# =========================
# Modo Cloud-safe: incremental (batch + rerun)
# =========================
def spool_init_state() -> Dict[str, Any]:
    """
    Estado serializável para processar em lotes.
    """
    return {
        "inited": False,
        "done": False,
        "is_txt": True,
        "eventos_alvo": [],
        "paths": {},   # codigo -> str(path)
        "counts": {},  # codigo -> int
        "bytes_lidos": 0,
    }


def spool_step(
    state: Dict[str, Any],
    uploaded_file,
    tmp_dir: Path,
    eventos_alvo: Set[str],
    batch_bytes: int = 8_000_000,  # ~8MB por passo (bom no Cloud)
    progress_bar=None,
    status_slot=None,
) -> Dict[str, Any]:
    """
    Processa o upload em lotes por BYTES para não "matar" o healthcheck no Cloud.
    - Para TXT: lê até batch_bytes por chamada.
    - Para XLSX: cai para modo antigo (XLSX já é pesado e não é comum ser gigante).
    """
    if not state:
        state = spool_init_state()

    # init
    if not state.get("inited", False):
        state["inited"] = True
        state["done"] = False
        state["eventos_alvo"] = sorted(list(eventos_alvo))

        is_txt = uploaded_file.name.lower().endswith(".txt")
        state["is_txt"] = is_txt

        # garante início do arquivo
        try:
            uploaded_file.seek(0)
        except Exception:
            pass

        # prepara paths e zera arquivos
        paths = {}
        counts = {}
        for cod in eventos_alvo:
            p = tmp_dir / f"{cod}.txt"
            paths[cod] = str(p)
            counts[cod] = 0
            # cria/zera
            p.write_text("", encoding="utf-8")

        state["paths"] = paths
        state["counts"] = counts
        state["bytes_lidos"] = 0

        if status_slot:
            status_slot.info("Processamento incremental iniciado...")

    # XLSX: usa modo antigo (sem incremental)
    if not state.get("is_txt", True):
        if status_slot:
            status_slot.info("Entrada XLSX detectada — usando modo tradicional (pode ser mais lento).")

        arquivos_evento, contagem_linhas, eventos = spool_por_evento(
            uploaded_file=uploaded_file,
            tmp_dir=tmp_dir,
            eventos_alvo=eventos_alvo,
            progress_bar=progress_bar,
            status_slot=status_slot,
        )
        state["paths"] = {k: str(v) for k, v in arquivos_evento.items()}
        state["counts"] = {k: int(v) for k, v in contagem_linhas.items()}
        state["done"] = True
        return state

    # TXT: processa em lote
    total_bytes = getattr(uploaded_file, "size", None) or 1
    bytes_lidos = int(state.get("bytes_lidos", 0))
    bytes_no_passo = 0

    # abre handles append
    handles = {}
    for cod, p_str in state["paths"].items():
        p = Path(p_str)
        handles[cod] = p.open("a", encoding="utf-8", newline="\n")

    try:
        # posiciona no ponto onde parou
        try:
            uploaded_file.seek(bytes_lidos)
        except Exception:
            # se não conseguir seek, seguimos lendo (pode duplicar em alguns ambientes),
            # mas normalmente o UploadedFile suporta seek.
            pass

        while bytes_no_passo < batch_bytes:
            raw = uploaded_file.read(min(256_000, batch_bytes - bytes_no_passo))
            if not raw:
                # EOF
                state["done"] = True
                break

            bytes_no_passo += len(raw)

            # processa linhas do chunk
            # cuidado: pode cortar linha no meio -> acumulador
            # vamos manter um buffer no state
            buf = state.get("_buf", b"") + raw
            linhas = buf.split(b"\n")
            state["_buf"] = linhas.pop()  # última pode estar incompleta

            for bline in linhas:
                try:
                    linha = bline.decode("latin1", errors="ignore").rstrip("\r")
                    codigo = extrair_codigo_evento(linha)
                    if not codigo or codigo not in eventos_alvo:
                        continue
                    handles[codigo].write(linha + "\n")
                    state["counts"][codigo] = int(state["counts"].get(codigo, 0)) + 1
                except Exception:
                    continue

        bytes_lidos += bytes_no_passo
        state["bytes_lidos"] = bytes_lidos

        if progress_bar:
            progress_bar.progress(min(bytes_lidos / total_bytes, 1.0))
        if status_slot:
            status_slot.text(f"Processando... {bytes_lidos:,}/{total_bytes:,} bytes")

        # se terminou, flush do buffer restante
        if state.get("done"):
            tail = state.get("_buf", b"")
            if tail:
                try:
                    linha = tail.decode("latin1", errors="ignore").rstrip("\r")
                    codigo = extrair_codigo_evento(linha)
                    if codigo and codigo in eventos_alvo:
                        handles[codigo].write(linha + "\n")
                        state["counts"][codigo] = int(state["counts"].get(codigo, 0)) + 1
                except Exception:
                    pass
            state["_buf"] = b""

    finally:
        for h in handles.values():
            try:
                h.close()
            except Exception:
                pass

    return state