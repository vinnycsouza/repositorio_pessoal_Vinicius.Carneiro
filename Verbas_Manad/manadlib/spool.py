from __future__ import annotations

import pandas as pd
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple

from .layout import extrair_codigo_evento


def spool_por_evento(
    uploaded_file,
    tmp_dir: Path,
    eventos_alvo: Set[str],
    progress_bar=None,
    status_slot=None,
) -> Tuple[Dict[str, Path], Dict[str, int], list[str]]:
    """
    Separa o arquivo em TXT temporários por evento (somente eventos_alvo).
    Retorna:
      - arquivos_evento: codigo -> Path do arquivo temporário
      - contagem_linhas: codigo -> quantidade
      - eventos: lista ordenada dos eventos encontrados
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
        # XLSX: lê aba a aba e grava linhas (coluna 0) nos arquivos do evento
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

