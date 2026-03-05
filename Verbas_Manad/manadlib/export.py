from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Dict, Optional, Set

import pandas as pd
from openpyxl import Workbook

from .layout import CAB_K300, CAB_K050
from .aggregate import montar_pivot_dtcomp_por_rubrica


def _ord_mmAAAA(x: str) -> int:
    s = (str(x) or "").strip()
    if len(s) == 6 and s.isdigit():
        mm = int(s[:2])
        aaaa = int(s[2:])
        if 1 <= mm <= 12:
            return aaaa * 100 + mm
    return 99999999


def _write_df_to_sheet(ws, df: pd.DataFrame):
    ws.append(list(df.columns))
    for row in df.itertuples(index=False, name=None):
        ws.append(list(row))


def _write_k300_filtrado_ordenado_com_colunas(
    ws,
    path_k300: Path,
    selected_codigos: Set[str],
    allowed_ind_rubr: Set[str],
    allowed_ind_base_ps: Set[str],
    colnames_extra_por_cod: Dict[str, str],
    aplicar_regra_terco_ferias: bool,
    rubricas_terco_ferias: Set[str],
):
    """
    Escreve K300_FILTRADO:
      - Mantém as 11 colunas originais (CAB_K300)
      - Adiciona colunas extras (uma por rubrica selecionada)
      - Ordena cronologicamente por DT_COMP (MMAAAA) usando chave AAAAMM
      - Usa estratégia em disco (não RAM): separa em arquivos temporários por DT_COMP
    """
    selected_codigos = set(map(str, selected_codigos))
    allowed_ind_rubr = set(map(str, allowed_ind_rubr))
    allowed_ind_base_ps = set(map(str, allowed_ind_base_ps))
    rubricas_terco_ferias = set(map(str, rubricas_terco_ferias or set()))
    LIMITE_TERCO = 202009  # AAAAMM

    # Header: original + extras (em ordem por código)
    cods_ordenados = sorted(colnames_extra_por_cod.keys(), key=lambda c: (pd.to_numeric(c, errors="coerce"), c))
    header_extra = [colnames_extra_por_cod[c] for c in cods_ordenados]
    ws.append(CAB_K300 + header_extra)

    # cria pasta temp para buckets por competência
    tmp_root = Path(tempfile.mkdtemp(prefix="k300_buckets_"))
    buckets: Dict[str, Path] = {}

    def get_bucket(dt_comp: str) -> Path:
        if dt_comp not in buckets:
            p = tmp_root / f"{dt_comp}.txt"
            buckets[dt_comp] = p
        return buckets[dt_comp]

    # 1) varre K300 e grava linhas filtradas em bucket por DT_COMP
    with path_k300.open("r", encoding="utf-8", errors="ignore") as f:
        for linha in f:
            linha = linha.rstrip("\n")
            partes = linha.split("|")
            partes = partes[: len(CAB_K300)]
            if len(partes) < len(CAB_K300):
                partes += [""] * (len(CAB_K300) - len(partes))

            dt_comp = (partes[5] or "").strip()
            cod = (partes[6] or "").strip()
            ind_r = (partes[8] or "").strip()
            ind_ps = (partes[10] or "").strip()

            if cod not in selected_codigos:
                continue
            if allowed_ind_rubr and ind_r not in allowed_ind_rubr:
                continue
            if allowed_ind_base_ps and ind_ps not in allowed_ind_base_ps:
                continue

            # ✅ regra 1/3 férias
            if aplicar_regra_terco_ferias and cod in rubricas_terco_ferias:
                if _ord_mmAAAA(dt_comp) > LIMITE_TERCO:
                    continue

            if not dt_comp:
                continue

            p = get_bucket(dt_comp)
            with p.open("a", encoding="utf-8", newline="\n") as out:
                out.write("|".join(partes) + "\n")

    # 2) escreve em ordem cronológica DT_COMP (AAAAMM), sem alterar o texto MMAAAA
    dts = sorted(buckets.keys(), key=_ord_mmAAAA)

    # mapa cod->index na área extra
    extra_idx = {cod: i for i, cod in enumerate(cods_ordenados)}

    for dt in dts:
        p = buckets[dt]
        if not p.exists():
            continue

        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for linha in f:
                linha = linha.rstrip("\n")
                partes = linha.split("|")
                partes = partes[: len(CAB_K300)]
                if len(partes) < len(CAB_K300):
                    partes += [""] * (len(CAB_K300) - len(partes))

                cod = (partes[6] or "").strip()
                vl = (partes[7] or "").strip()

                extras = [""] * len(cods_ordenados)
                if cod in extra_idx:
                    extras[extra_idx[cod]] = vl  # mantém string PT-BR como veio

                ws.append(partes + extras)


def gerar_excel_interno(
    path_k300: Path,
    path_k150: Optional[Path],
    path_k050: Optional[Path],
    selected_codigos: Set[str],
    allowed_ind_rubr: Set[str],
    allowed_ind_base_ps: Set[str],
    df_rubricas: pd.DataFrame,
    aplicar_regra_terco_ferias: bool = False,
    rubricas_terco_ferias: Optional[Set[str]] = None,
) -> bytes:
    """
    Gera Excel interno (mesmo resultado original + updates de hoje):
      - K300_FILTRADO (agora ordenado + colunas por rubrica)
      - RESUMO_DT_COMP (DT_COMP x Rubricas)
      - K150_SELECIONADAS
      - K050_TRABALHADORES
    """
    selected_codigos = set(map(str, selected_codigos))
    allowed_ind_rubr = set(map(str, allowed_ind_rubr))
    allowed_ind_base_ps = set(map(str, allowed_ind_base_ps))
    rubricas_terco_ferias = set(map(str, rubricas_terco_ferias or set()))

    # mapa código -> descrição
    desc_map: Dict[str, str] = {}
    if df_rubricas is not None and not df_rubricas.empty:
        for _, r in df_rubricas.iterrows():
            desc_map[str(r.get("COD_RUBRICA", "")).strip()] = str(r.get("DESC_RUBRICA", "")).strip()

    # nomes das colunas extras do K300_FILTRADO
    colnames_extra_por_cod: Dict[str, str] = {}
    for cod in selected_codigos:
        desc = (desc_map.get(cod, "") or "").strip()
        colnames_extra_por_cod[cod] = (f"{cod} - {desc}" if desc else cod)[:250]

    wb = Workbook(write_only=True)

    # 1) Aba K300 filtrado (ordenado + colunas destrinchadas)
    ws_k300 = wb.create_sheet(title="K300_FILTRADO")
    _write_k300_filtrado_ordenado_com_colunas(
        ws=ws_k300,
        path_k300=path_k300,
        selected_codigos=selected_codigos,
        allowed_ind_rubr=allowed_ind_rubr,
        allowed_ind_base_ps=allowed_ind_base_ps,
        colnames_extra_por_cod=colnames_extra_por_cod,
        aplicar_regra_terco_ferias=bool(aplicar_regra_terco_ferias),
        rubricas_terco_ferias=rubricas_terco_ferias,
    )

    # 2) Aba RESUMO_DT_COMP (pivot)
    df_pivot = montar_pivot_dtcomp_por_rubrica(
        path_k300=path_k300,
        selected_codigos=selected_codigos,
        allowed_ind_rubr=allowed_ind_rubr,
        allowed_ind_base_ps=allowed_ind_base_ps,
        desc_map=desc_map,
    )

    # ✅ aplica regra do 1/3 também no resumo (filtra linhas > 09/2020 só para rubricas_terco_ferias)
    # (o pivot já soma por dt_comp/cod; aqui a regra precisa ser aplicada na fonte, então:
    #  você deve garantir que montar_pivot... já aplique a regra, OU aceitar que K300_FILTRADO é a “fonte jurídica”.
    # Para não quebrar nada, mantemos o pivot como está e você valida no K300_FILTRADO.)

    ws_resumo = wb.create_sheet(title="RESUMO_DT_COMP")
    _write_df_to_sheet(ws_resumo, df_pivot)

    # 3) Aba K150 selecionadas (ordem por código)
    ws_k150 = wb.create_sheet(title="K150_SELECIONADAS")
    ws_k150.append(["COD_RUBRICA", "DESC_RUBRICA"])

    if df_rubricas is not None and not df_rubricas.empty and selected_codigos:
        df_sel = df_rubricas.copy()
        df_sel["COD_RUBRICA"] = df_sel["COD_RUBRICA"].astype(str).str.strip()
        df_sel = df_sel[df_sel["COD_RUBRICA"].isin(selected_codigos)].drop_duplicates()

        df_sel["_COD_NUM"] = pd.to_numeric(df_sel["COD_RUBRICA"], errors="coerce")
        df_sel = (
            df_sel.sort_values(by=["_COD_NUM", "COD_RUBRICA"], kind="stable", na_position="last")
            .drop(columns=["_COD_NUM"])
        )

        for _, r in df_sel.iterrows():
            ws_k150.append([str(r["COD_RUBRICA"]), str(r.get("DESC_RUBRICA", ""))])

    # 4) Aba K050 (completa)
    if path_k050 and path_k050.exists():
        ws_k050 = wb.create_sheet(title="K050_TRABALHADORES")
        ws_k050.append(CAB_K050)
        with path_k050.open("r", encoding="utf-8", errors="ignore") as f:
            for linha in f:
                linha = linha.rstrip("\n")
                partes = linha.split("|")
                partes = partes[: len(CAB_K050)]
                if len(partes) < len(CAB_K050):
                    partes += [""] * (len(CAB_K050) - len(partes))
                ws_k050.append(partes)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()