from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Set, Tuple, Optional

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


def _ord_mmAAAA(x: str) -> int:
    """
    Ordenação cronológica para DT_COMP no padrão MANAD: MMAAAA.
    Retorna chave AAAAMM. NÃO altera o valor original.
    """
    s = (str(x) or "").strip()
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
    aplicar_regra_terco_ferias: bool = False,
    rubricas_terco_ferias: Optional[Set[str]] = None,
) -> pd.DataFrame:
    """
    DT_COMP (MMAAAA) x Rubricas selecionadas (colunas), soma(VLR_RUBR).
    ✅ Agora também aplica modulação do 1/3 de férias até 09/2020 quando ativada.
    """
    selected_codigos = set(map(str, selected_codigos))
    allowed_ind_rubr = set(map(str, allowed_ind_rubr))
    allowed_ind_base_ps = set(map(str, allowed_ind_base_ps))

    rubricas_terco_ferias = set(map(str, rubricas_terco_ferias or set()))
    LIMITE_TERCO = 202009  # AAAAMM (09/2020)

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

            # ✅ regra 1/3 férias
            if aplicar_regra_terco_ferias and cod_rubr in rubricas_terco_ferias:
                if _ord_mmAAAA(dt_comp) > LIMITE_TERCO:
                    continue

            valor = _parse_decimal_ptbr(vl)
            key = (dt_comp, cod_rubr)
            acc[key] = acc.get(key, Decimal("0")) + valor

    if not acc:
        return pd.DataFrame(columns=["DT_COMP"])

    rows = [{"DT_COMP": dt, "COD_RUBR": cod, "TOTAL": float(total)} for (dt, cod), total in acc.items()]
    df_long = pd.DataFrame(rows)

    df_pivot = df_long.pivot_table(
        index="DT_COMP",
        columns="COD_RUBR",
        values="TOTAL",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()

    # ✅ ordena cronologicamente (MMAAAA -> AAAAMM)
    df_pivot["_ord"] = df_pivot["DT_COMP"].apply(_ord_mmAAAA)
    df_pivot = df_pivot.sort_values("_ord").drop(columns=["_ord"]).reset_index(drop=True)

    # renomeia colunas para "COD - DESCRIÇÃO"
    new_cols = ["DT_COMP"]
    for c in df_pivot.columns[1:]:
        cod = str(c)
        desc = (desc_map.get(cod, "") or "").strip()
        new_cols.append((f"{cod} - {desc}" if desc else cod)[:250])
    df_pivot.columns = new_cols

    return df_pivot