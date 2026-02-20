from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Set, Tuple

import pandas as pd

from .layout import CAB_K300


def _parse_decimal_ptbr(v: str) -> Decimal:
    v = (v or "").strip()
    if not v:
        return Decimal("0")
    v = v.replace(".", "").replace(",", ".")
    try:
        return Decimal(v)
    except InvalidOperation:
        return Decimal("0")


def _norm_dt_comp_mmaaaa(x: str) -> str:
    """
    Normaliza DT_COMP para string MMAAAA com 6 dígitos.
    Ex.: 12012 -> 012012
         ' 122024 ' -> '122024'
    """
    return (str(x) or "").strip().zfill(6)


def _ord_dt_comp_mmaaaa(x: str) -> int:
    """
    DT_COMP vem como MMAAAA (ex.: 122024, 012012).
    Ordenação cronológica via chave AAAAMM (ex.: 202412, 201201).
    NÃO altera o DT_COMP original, só ordena.
    """
    s = _norm_dt_comp_mmaaaa(x)
    if len(s) == 6 and s.isdigit():
        mm = int(s[:2])
        aaaa = int(s[2:])
        if 1 <= mm <= 12:
            return aaaa * 100 + mm
    return 99999999


def montar_pivot_dtcomp_por_rubrica(
    path_k300: Path,
    selected_codigos: Set[str],
    allowed_ind_rubr: Set[str],
    allowed_ind_base_ps: Set[str],
    desc_map: Dict[str, str],
) -> pd.DataFrame:
    """
    Retorna um DataFrame com:
      - linhas: DT_COMP (MMAAAA, exatamente como vem no MANAD — preservado)
      - colunas: rubricas selecionadas (cada uma vira uma coluna)
      - valores: soma(VLR_RUBR)

    Respeita filtros:
      - COD_RUBR
      - IND_RUBR
      - IND_BASE_PS
    """
    selected_codigos = set(map(str, selected_codigos))
    allowed_ind_rubr = set(map(str, allowed_ind_rubr))
    allowed_ind_base_ps = set(map(str, allowed_ind_base_ps))

    # acumula: (dt_comp, cod_rubr) -> Decimal
    acc: Dict[Tuple[str, str], Decimal] = {}

    with path_k300.open("r", encoding="utf-8", errors="ignore") as f:
        for linha in f:
            linha = linha.rstrip("\n")
            partes = linha.split("|")

            partes = partes[: len(CAB_K300)]
            if len(partes) < len(CAB_K300):
                partes += [""] * (len(CAB_K300) - len(partes))

            dt_comp_raw = partes[5]
            dt_comp = _norm_dt_comp_mmaaaa(dt_comp_raw)  # ✅ normaliza aqui
            cod_rubr = (partes[6] or "").strip()
            vl = (partes[7] or "").strip()
            ind_rubr = (partes[8] or "").strip()
            ind_base_ps = (partes[10] or "").strip()

            if not dt_comp.strip():
                continue

            if cod_rubr not in selected_codigos:
                continue
            if allowed_ind_rubr and ind_rubr not in allowed_ind_rubr:
                continue
            if allowed_ind_base_ps and ind_base_ps not in allowed_ind_base_ps:
                continue

            valor = _parse_decimal_ptbr(vl)
            key = (dt_comp, cod_rubr)
            acc[key] = acc.get(key, Decimal("0")) + valor

    if not acc:
        return pd.DataFrame(columns=["DT_COMP"])

    # tabela longa
    rows = [{"DT_COMP": dt, "COD_RUBR": cod, "TOTAL": float(total)} for (dt, cod), total in acc.items()]
    df_long = pd.DataFrame(rows)

    # pivot: linhas DT_COMP, colunas COD_RUBR
    df_pivot = df_long.pivot_table(
        index="DT_COMP",
        columns="COD_RUBR",
        values="TOTAL",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()

    # ✅ normaliza de novo antes de ordenar (garantia extra)
    df_pivot["DT_COMP"] = df_pivot["DT_COMP"].apply(_norm_dt_comp_mmaaaa)

    # ✅ ordenação cronológica
    df_pivot["_ord"] = df_pivot["DT_COMP"].apply(_ord_dt_comp_mmaaaa)
    df_pivot = df_pivot.sort_values("_ord").drop(columns=["_ord"]).reset_index(drop=True)

    # renomear colunas para "COD - DESCRIÇÃO"
    new_cols = ["DT_COMP"]
    for c in df_pivot.columns[1:]:
        cod = str(c)
        desc = (desc_map.get(cod, "") or "").strip()
        if desc:
            new_cols.append(f"{cod} - {desc}"[:250])
        else:
            new_cols.append(cod)
    df_pivot.columns = new_cols

    return df_pivot