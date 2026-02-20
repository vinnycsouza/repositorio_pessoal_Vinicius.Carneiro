from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd

from .layout import CAB_K300, CAB_K150


def _parse_decimal_ptbr(v: str) -> Decimal:
    v = (v or "").strip()
    if not v:
        return Decimal("0")
    v = v.replace(".", "").replace(",", ".")
    try:
        return Decimal(v)
    except InvalidOperation:
        return Decimal("0")


def _ord_dt_comp_mmaaaa(dt_comp: str) -> int:
    """
    DT_COMP no MANAD vem como MMAAAA (ex.: 122024, 012012).
    Para ordenar cronologicamente, usamos uma chave AAAAMM (ex.: 202412, 201201).
    Mantém o DT_COMP original — só cria chave para ordenação.
    """
    s = (str(dt_comp) or "").strip().zfill(6)
    if len(s) == 6 and s.isdigit():
        mm = int(s[:2])
        aaaa = int(s[2:])
        if 1 <= mm <= 12:
            return aaaa * 100 + mm
    return 99999999


def ler_catalogo_k150(path_k150: Path) -> pd.DataFrame:
    """
    Lê K150.txt e retorna DataFrame com:
      COD_RUBRICA, DESC_RUBRICA

    ✅ Ordena por COD_RUBRICA crescente (ordem numérica real quando possível).
    """
    rows = []
    with path_k150.open("r", encoding="utf-8", errors="ignore") as f:
        for linha in f:
            linha = linha.rstrip("\n")
            partes = linha.split("|")

            # normaliza para tamanho do CAB_K150
            partes = partes[: len(CAB_K150)]
            if len(partes) < len(CAB_K150):
                partes += [""] * (len(CAB_K150) - len(partes))

            # índices: 3=COD_RUBRICA, 4=DESC_RUBRICA
            cod = (partes[3] or "").strip()
            desc = (partes[4] or "").strip()

            if cod:
                rows.append((cod, desc))

    df = pd.DataFrame(rows, columns=["COD_RUBRICA", "DESC_RUBRICA"]).drop_duplicates()
    if df.empty:
        return df

    # ✅ Ordenação por código (numérica quando possível; mantém string original)
    df["COD_RUBRICA"] = df["COD_RUBRICA"].astype(str).str.strip()

    # chave numérica para ordenar corretamente 50, 234, 238, 417, 8140...
    df["_COD_NUM"] = pd.to_numeric(df["COD_RUBRICA"], errors="coerce")

    # Se houver códigos não-numéricos (NaN), eles ficam por último, mas mantemos estável
    df = (
        df.sort_values(by=["_COD_NUM", "COD_RUBRICA"], kind="stable", na_position="last")
          .drop(columns=["_COD_NUM"])
          .reset_index(drop=True)
    )
    return df


def alertas_descricoes_repetidas(
    df_rubricas: pd.DataFrame,
    selected_codigos: Set[str],
) -> Optional[pd.DataFrame]:
    """
    Retorna DF com descrições que possuem múltiplos códigos (no universo selecionado).
    """
    if df_rubricas is None or df_rubricas.empty:
        return None

    df = df_rubricas.copy()
    df["COD_RUBRICA"] = df["COD_RUBRICA"].astype(str)

    if selected_codigos:
        df = df[df["COD_RUBRICA"].isin(set(map(str, selected_codigos)))]

    if df.empty:
        return None

    grp = df.groupby("DESC_RUBRICA")["COD_RUBRICA"].nunique().reset_index(name="qtd_codigos")
    grp = grp[grp["qtd_codigos"] > 1].sort_values("qtd_codigos", ascending=False)

    if grp.empty:
        return None

    cods = (
        df.groupby("DESC_RUBRICA")["COD_RUBRICA"]
        .apply(lambda s: ", ".join(sorted(set(s))))
        .reset_index(name="codigos")
    )

    out = grp.merge(cods, on="DESC_RUBRICA", how="left")
    out.columns = ["Descrição", "Qtd códigos", "Códigos"]
    return out


def gerar_previa_k300(
    path_k300: Path,
    selected_codigos: Set[str],
    allowed_ind_rubr: Set[str],
    allowed_ind_base_ps: Set[str],
    df_rubricas: pd.DataFrame,
    sample_size: int = 200,
) -> Dict:
    """
    Scan linha a linha no K300.txt, aplica filtros, calcula:
      - totais por rubrica
      - totais por competência
      - amostra de linhas
      - alertas (rubricas sem movimento)
    """
    selected_codigos = set(map(str, selected_codigos))
    allowed_ind_rubr = set(map(str, allowed_ind_rubr))
    allowed_ind_base_ps = set(map(str, allowed_ind_base_ps))

    # mapa código -> descrição
    desc_map = {}
    if df_rubricas is not None and not df_rubricas.empty:
        for _, r in df_rubricas.iterrows():
            desc_map[str(r["COD_RUBRICA"])] = str(r["DESC_RUBRICA"])

    totais_rub: Dict[str, Decimal] = {}
    qtd_rub: Dict[str, int] = {}
    totais_comp: Dict[str, Decimal] = {}
    qtd_comp: Dict[str, int] = {}

    amostra: List[List[str]] = []
    rubricas_sem_mov = set(selected_codigos)

    linhas_filtradas = 0
    comps_distintas = set()

    with path_k300.open("r", encoding="utf-8", errors="ignore") as f:
        for linha in f:
            linha = linha.rstrip("\n")
            partes = linha.split("|")

            # normaliza para CAB_K300 (11 colunas)
            partes = partes[: len(CAB_K300)]
            if len(partes) < len(CAB_K300):
                partes += [""] * (len(CAB_K300) - len(partes))

            # índices K300:
            # 5=DT_COMP, 6=COD_RUBR, 7=VLR_RUBR, 8=IND_RUBR, 10=IND_BASE_PS
            dt_comp = (partes[5] or "").strip()
            cod_rubr = (partes[6] or "").strip()
            vl = (partes[7] or "").strip()
            ind_rubr = (partes[8] or "").strip()
            ind_base_ps = (partes[10] or "").strip()

            # filtros
            if cod_rubr not in selected_codigos:
                continue
            if allowed_ind_rubr and ind_rubr not in allowed_ind_rubr:
                continue
            if allowed_ind_base_ps and ind_base_ps not in allowed_ind_base_ps:
                continue

            valor = _parse_decimal_ptbr(vl)

            totais_rub[cod_rubr] = totais_rub.get(cod_rubr, Decimal("0")) + valor
            qtd_rub[cod_rubr] = qtd_rub.get(cod_rubr, 0) + 1

            if dt_comp:
                dt_comp_norm = str(dt_comp).strip().zfill(6)
                totais_comp[dt_comp_norm] = totais_comp.get(dt_comp_norm, Decimal("0")) + valor
                qtd_comp[dt_comp_norm] = qtd_comp.get(dt_comp_norm, 0) + 1
                comps_distintas.add(dt_comp_norm)

            rubricas_sem_mov.discard(cod_rubr)
            linhas_filtradas += 1

            if len(amostra) < sample_size:
                amostra.append(partes)

    total_geral = sum(totais_rub.values(), Decimal("0"))

    # totais por rubrica
    rows_r = []
    for cod, total in totais_rub.items():
        rows_r.append(
            {
                "COD_RUBR": cod,
                "DESCRIÇÃO": desc_map.get(cod, ""),
                "TOTAL": float(total),
                "QTD LINHAS": int(qtd_rub.get(cod, 0)),
            }
        )
    df_totais_r = pd.DataFrame(rows_r)
    if not df_totais_r.empty:
        df_totais_r["% TOTAL"] = df_totais_r["TOTAL"] / float(total_geral) if total_geral != 0 else 0
        df_totais_r = df_totais_r.sort_values("TOTAL", ascending=False).reset_index(drop=True)

    # totais por competência (✅ ORDENADO CRONOLOGICAMENTE)
    rows_c = []
    for comp, total in totais_comp.items():
        rows_c.append({"DT_COMP": comp, "TOTAL": float(total), "QTD LINHAS": int(qtd_comp.get(comp, 0))})
    df_totais_c = pd.DataFrame(rows_c)
    if not df_totais_c.empty:
        df_totais_c["DT_COMP"] = df_totais_c["DT_COMP"].astype(str).str.strip().str.zfill(6)
        df_totais_c["_ord"] = df_totais_c["DT_COMP"].apply(_ord_dt_comp_mmaaaa)
        df_totais_c = df_totais_c.sort_values("_ord").drop(columns=["_ord"]).reset_index(drop=True)

    # amostra
    df_amostra = pd.DataFrame(amostra, columns=CAB_K300) if amostra else pd.DataFrame(columns=CAB_K300)

    # sem movimento
    sem_mov_rows = [{"COD_RUBR": cod, "DESCRIÇÃO": desc_map.get(cod, "")} for cod in sorted(rubricas_sem_mov)]
    df_sem_mov = pd.DataFrame(sem_mov_rows)

    # format pt-BR simples
    total_fmt = f"R$ {float(total_geral):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    return {
        "rubricas_selecionadas": len(selected_codigos),
        "linhas_filtradas": int(linhas_filtradas),
        "total_geral_formatado": total_fmt,
        "competencias_distintas": len(comps_distintas),
        "df_totais_rubrica": df_totais_r,
        "df_totais_competencia": df_totais_c,
        "df_amostra": df_amostra,
        "rubricas_sem_movimento": list(sorted(rubricas_sem_mov)),
        "df_sem_movimento": df_sem_mov,
    }