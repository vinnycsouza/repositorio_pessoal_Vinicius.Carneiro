from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Set, Tuple

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


def montar_pivot_dtcomp_por_rubrica(
    path_k300: Path,
    selected_codigos: Set[str],
    allowed_ind_rubr: Set[str],
    allowed_ind_base_ps: Set[str],
    desc_map: Dict[str, str],
) -> pd.DataFrame:
    """
    Retorna um DataFrame com:
      linhas: DT_COMP
      colunas: rubricas selecionadas (cada uma vira uma coluna)
      valores: soma(VLR_RUBR)

    OBS: respeita os filtros (COD_RUBR, IND_RUBR, IND_BASE_PS).
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

            dt_comp = (partes[5] or "").strip()
            cod_rubr = (partes[6] or "").strip()
            vl = (partes[7] or "").strip()
            ind_rubr = (partes[8] or "").strip()
            ind_base_ps = (partes[10] or "").strip()

            if not dt_comp:
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
        # tabela vazia com colunas esperadas
        return pd.DataFrame(columns=["DT_COMP"])

    # construir tabela longa
    rows = []
    for (dt, cod), total in acc.items():
        rows.append({"DT_COMP": dt, "COD_RUBR": cod, "TOTAL": float(total)})

    df_long = pd.DataFrame(rows)

    # pivot: linhas DT_COMP, colunas COD_RUBR
    df_pivot = df_long.pivot_table(
        index="DT_COMP",
        columns="COD_RUBR",
        values="TOTAL",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()

    # ordenar DT_COMP numericamente (ex.: 012012, 022012...)
    df_pivot["_ord"] = pd.to_numeric(df_pivot["DT_COMP"], errors="coerce")
    df_pivot = df_pivot.sort_values("_ord").drop(columns=["_ord"]).reset_index(drop=True)

    # renomear colunas para "COD - DESCRIÇÃO"
    new_cols = ["DT_COMP"]
    for c in df_pivot.columns[1:]:
        cod = str(c)
        desc = (desc_map.get(cod, "") or "").strip()
        if desc:
            new_cols.append(f"{cod} - {desc}"[:250])  # evita cabeçalho gigante
        else:
            new_cols.append(cod)
    df_pivot.columns = new_cols

    return df_pivot