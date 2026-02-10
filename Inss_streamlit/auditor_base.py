from __future__ import annotations

import json
import bisect
import pandas as pd


# ------------------ util ------------------

def _to_cents(x: float) -> int:
    return int(round(float(x) * 100))


def _from_cents(c: int) -> float:
    return c / 100.0


def _norm_txt(s: str) -> str:
    s = (s or "").lower()
    return (
        s.replace("á", "a").replace("à", "a").replace("ã", "a").replace("â", "a")
         .replace("é", "e").replace("ê", "e")
         .replace("í", "i")
         .replace("ó", "o").replace("ô", "o").replace("õ", "o")
         .replace("ú", "u")
         .replace("ç", "c")
    )


def carregar_config_auditor():
    try:
        with open("auditor_config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
            cfg.setdefault("DESCONTOS_REDUZEM_BASE", [])
            cfg.setdefault("DESCONTOS_FINANCEIROS", [])
            return cfg
    except Exception:
        return {"DESCONTOS_REDUZEM_BASE": [], "DESCONTOS_FINANCEIROS": []}


# ------------------ descontos: classificador (mantido) ------------------

def identificar_ajustes_negativos(df: pd.DataFrame) -> pd.DataFrame:
    config = carregar_config_auditor()
    termos_reduzem = [_norm_txt(t) for t in config["DESCONTOS_REDUZEM_BASE"]]
    termos_financeiros = [_norm_txt(t) for t in config["DESCONTOS_FINANCEIROS"]]

    desc = df[df["tipo"] == "DESCONTO"].copy()

    if desc.empty:
        desc["eh_ajuste_negativo"] = False
        desc["eh_financeiro"] = False
        desc["eh_neutro"] = False
        return desc

    def classificar(rubrica):
        txt = _norm_txt(rubrica)
        if any(t in txt for t in termos_financeiros):
            return False, True
        if any(t in txt for t in termos_reduzem):
            return True, False
        return False, False

    res = desc["rubrica"].apply(classificar)
    desc["eh_ajuste_negativo"] = res.apply(lambda x: x[0])
    desc["eh_financeiro"] = res.apply(lambda x: x[1])
    desc["eh_neutro"] = (~desc["eh_ajuste_negativo"]) & (~desc["eh_financeiro"])
    return desc


# ------------------ Aproximação do GAP "por baixo" ------------------

def _all_subset_sums(values_cents):
    """
    Retorna lista de (soma, mask) para metade de valores.
    mask é bitmask relativo a essa metade.
    """
    sums = [(0, 0)]
    for i, v in enumerate(values_cents):
        cur = sums[:]  # snapshot
        bit = 1 << i
        for s, m in cur:
            sums.append((s + v, m | bit))
    return sums


def melhor_subset_por_baixo(valores: list[float], alvo: float, top_n: int = 44):
    """
    Encontra subconjunto cuja soma <= alvo e maximiza a soma (chega o mais perto por baixo).
    Usa meet-in-the-middle com no máximo top_n itens (mais relevantes).
    Retorna: (soma_escolhida, indices_escolhidos)
    """
    alvo_c = _to_cents(alvo)
    if alvo_c <= 0 or not valores:
        return 0.0, []

    # pega os top_n maiores valores (melhora performance e qualidade)
    idx_sorted = sorted(range(len(valores)), key=lambda i: valores[i], reverse=True)[:top_n]
    vals = [valores[i] for i in idx_sorted]
    vals_c = [_to_cents(v) for v in vals]

    mid = len(vals_c) // 2
    left = vals_c[:mid]
    right = vals_c[mid:]

    L = _all_subset_sums(left)
    R = _all_subset_sums(right)

    # ordenar R por soma para binary search
    R.sort(key=lambda x: x[0])
    R_sums = [x[0] for x in R]

    best_sum = 0
    best_mask_L = 0
    best_mask_R = 0

    for sL, mL in L:
        if sL > alvo_c:
            continue
        rest = alvo_c - sL
        pos = bisect.bisect_right(R_sums, rest) - 1
        if pos >= 0:
            sR, mR = R[pos]
            total = sL + sR
            if total > best_sum:
                best_sum = total
                best_mask_L = mL
                best_mask_R = mR

    # decodifica máscaras para índices originais
    chosen_local = []
    for i in range(mid):
        if best_mask_L & (1 << i):
            chosen_local.append(i)
    for i in range(len(right)):
        if best_mask_R & (1 << i):
            chosen_local.append(mid + i)

    chosen_original = [idx_sorted[i] for i in chosen_local]
    return _from_cents(best_sum), chosen_original


# ------------------ Auditoria por Exclusão + Qualidade ------------------

def auditoria_por_exclusao_com_aproximacao(
    df: pd.DataFrame,
    base_oficial: dict | None,
    totais_proventos: dict,
    grupo: str = "ativos",
    top_n_subset: int = 44,
):
    """
    Para 1 grupo (ativos/desligados/total):
      base_exclusao = total_proventos - fora - neutra
      gap = base_oficial - base_exclusao
      se gap>0: escolhe subconjunto de FORA/NEUTRA para "devolver" (entrar) por baixo
    """
    prov = df[df["tipo"] == "PROVENTO"].copy()
    prov_fora = df[(df["tipo"] == "PROVENTO") & (df["classificacao"] == "FORA")].copy()
    prov_neu = df[(df["tipo"] == "PROVENTO") & (df["classificacao"] == "NEUTRA")].copy()
    prov_fn = df[(df["tipo"] == "PROVENTO") & (df["classificacao"].isin(["FORA", "NEUTRA"]))].copy()

    total = float(totais_proventos.get(grupo, 0.0))
    soma_fora = float(prov_fora[grupo].fillna(0).sum())
    soma_neu = float(prov_neu[grupo].fillna(0).sum())
    base_exclusao = float(total - soma_fora - soma_neu)

    of = None if not base_oficial else float(base_oficial.get(grupo, 0.0))
    if of is None:
        return {
            "base_exclusao": base_exclusao,
            "gap": None,
            "base_aprox_por_baixo": None,
            "erro_por_baixo": None,
            "rubricas_devolvidas": pd.DataFrame()
        }

    gap = float(of - base_exclusao)

    if gap <= 0:
        # já está igual/maior; por baixo é a própria base_exclusao (não precisa devolver nada)
        return {
            "base_exclusao": base_exclusao,
            "gap": gap,
            "base_aprox_por_baixo": base_exclusao,
            "erro_por_baixo": float(of - base_exclusao),  # pode ser <=0
            "rubricas_devolvidas": pd.DataFrame()
        }

    # candidatos: FORA/NEUTRA com valor positivo
    cand = prov_fn.copy()
    cand["valor_alvo"] = cand[grupo].fillna(0.0).astype(float)
    cand = cand[cand["valor_alvo"] > 0].copy()
    cand = cand.sort_values("valor_alvo", ascending=False).reset_index(drop=True)

    valores = cand["valor_alvo"].tolist()
    soma_escolhida, idxs = melhor_subset_por_baixo(valores, gap, top_n=top_n_subset)

    devolvidas = cand.loc[idxs, ["rubrica", "classificacao", "valor_alvo"]].copy() if idxs else pd.DataFrame()
    base_aprox = float(base_exclusao + soma_escolhida)
    erro = float(of - base_aprox)  # >=0 por construção (por baixo)

    return {
        "base_exclusao": base_exclusao,
        "gap": gap,
        "base_aprox_por_baixo": base_aprox,
        "erro_por_baixo": erro,
        "rubricas_devolvidas": devolvidas.sort_values("valor_alvo", ascending=False) if not devolvidas.empty else devolvidas
    }
