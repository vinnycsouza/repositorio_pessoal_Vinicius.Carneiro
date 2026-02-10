from __future__ import annotations

import json
import pandas as pd
from itertools import combinations


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
    """
    Lê auditor_config.json.
    Se não existir, volta com listas vazias (não quebra o app).
    """
    try:
        with open("auditor_config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
            cfg.setdefault("DESCONTOS_REDUZEM_BASE", [])
            cfg.setdefault("DESCONTOS_FINANCEIROS", [])
            return cfg
    except Exception:
        return {"DESCONTOS_REDUZEM_BASE": [], "DESCONTOS_FINANCEIROS": []}


# ------------------ descontos: classificador ------------------

def identificar_ajustes_negativos(df: pd.DataFrame) -> pd.DataFrame:
    """
    Retorna DataFrame de descontos com:
      - eh_ajuste_negativo: True se deve reduzir base (conforme config)
      - eh_financeiro: True se for desconto financeiro (conforme config)
      - eh_neutro: True se não bateu em nenhum dos dois
    """
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

        # prioridade: financeiro
        if any(t in txt for t in termos_financeiros):
            return False, True

        # depois: reduz base
        if any(t in txt for t in termos_reduzem):
            return True, False

        return False, False

    res = desc["rubrica"].apply(classificar)
    desc["eh_ajuste_negativo"] = res.apply(lambda x: x[0])
    desc["eh_financeiro"] = res.apply(lambda x: x[1])
    desc["eh_neutro"] = (~desc["eh_ajuste_negativo"]) & (~desc["eh_financeiro"])

    return desc


# ------------------ reconstrução de base ------------------

def reconstruir_base(df: pd.DataFrame, base_calc: dict) -> dict:
    """
    Reconstrói uma base mais próxima da lógica de alguns ERPs:

      base_reconstruida = base_calc_ENTRA - descontos_reduzem_base

    Onde:
      - base_calc_ENTRA vem do calculo_base.py (somatório de proventos ENTRA)
      - descontos_reduzem_base é uma soma de eventos negativos listados em auditor_config.json
    """
    desc = identificar_ajustes_negativos(df)
    aj = desc[desc["eh_ajuste_negativo"]].copy()

    ajustes = {
        "ativos": float(aj["ativos"].fillna(0).sum()) if not aj.empty else 0.0,
        "desligados": float(aj["desligados"].fillna(0).sum()) if not aj.empty else 0.0,
        "total": float(aj["total"].fillna(0).sum()) if not aj.empty else 0.0,
    }

    base_reconstruida = {
        "ativos": float(base_calc.get("ativos", 0.0) - ajustes["ativos"]),
        "desligados": float(base_calc.get("desligados", 0.0) - ajustes["desligados"]),
        "total": float(base_calc.get("total", 0.0) - ajustes["total"]),
    }

    return {
        "ajustes_negativos": ajustes,
        "base_reconstruida": base_reconstruida,
        "descontos_classificados": desc
    }


# ------------------ combinações por valor ------------------

def _sugerir_combinacoes_por_valor(
    candidatos: pd.DataFrame,
    alvo: float,
    tol: float = 0.05,
    top_n: int = 35,
    max_k: int = 6,
):
    """
    Busca combinações de valores (valor_alvo) que somem aproximadamente o alvo.
    Use com cuidado: combinações explodem; por isso limitamos top_n e max_k.
    """
    if candidatos.empty:
        return []

    alvo_c = _to_cents(abs(alvo))
    tol_c = _to_cents(tol)

    cand = candidatos.sort_values("valor_alvo", ascending=False).head(top_n).reset_index(drop=True)
    vals_c = [_to_cents(v) for v in cand["valor_alvo"].tolist()]

    melhores = []
    for k in range(1, max_k + 1):
        for idxs in combinations(range(len(vals_c)), k):
            soma = sum(vals_c[i] for i in idxs)
            diff = abs(soma - alvo_c)
            if diff <= tol_c:
                melhores.append((diff, soma, idxs))

    melhores.sort(key=lambda x: x[0])

    combos = []
    for diff, soma, idxs in melhores[:20]:
        itens = cand.loc[list(idxs), ["rubrica", "tipo", "classificacao", "valor_alvo"]].copy()
        combos.append({
            "soma": _from_cents(soma),
            "erro": _from_cents(diff),
            "itens": itens
        })
    return combos


# ------------------ auditoria ------------------

def auditoria_por_grupo(df: pd.DataFrame, base_calc: dict, base_oficial: dict | None):
    """
    Retorna:
      - resumo (DataFrame)
      - candidatos (dict): por grupo
      - combos (dict): por grupo
      - descontos_classificados (DataFrame): descontos com flags
    """

    # totais brutos de proventos (contexto)
    prov = df[df["tipo"] == "PROVENTO"].copy()
    tot_prov = {
        "ativos": float(prov["ativos"].fillna(0).sum()),
        "desligados": float(prov["desligados"].fillna(0).sum()),
        "total": float(prov["total"].fillna(0).sum())
    }

    recon = reconstruir_base(df, base_calc)
    ajustes = recon["ajustes_negativos"]
    base_rec = recon["base_reconstruida"]
    descontos_classificados = recon["descontos_classificados"]

    linhas = []
    for g in ["ativos", "desligados", "total"]:
        of = None if not base_oficial else float(base_oficial.get(g, 0.0))
        residual = None if of is None else float(of - base_rec[g])

        linhas.append({
            "grupo": g.upper(),
            "proventos_brutos": tot_prov[g],
            "base_calc_ENTRA": float(base_calc.get(g, 0.0)),
            "descontos_reduzem_base": ajustes[g],
            "base_reconstruida": base_rec[g],
            "base_oficial_pdf": of,
            "residual_nao_explicado": residual
        })

    # AFASTADOS: existe na base oficial, mas não no quadro de eventos desse modelo
    if base_oficial and "afastados" in base_oficial:
        linhas.append({
            "grupo": "AFASTADOS",
            "proventos_brutos": None,
            "base_calc_ENTRA": None,
            "descontos_reduzem_base": None,
            "base_reconstruida": None,
            "base_oficial_pdf": float(base_oficial["afastados"]),
            "residual_nao_explicado": float(base_oficial["afastados"]),
        })

    resumo = pd.DataFrame(linhas)

    # candidatos para explicar residual positivo:
    # proventos que estão FORA/NEUTRA podem estar sendo considerados pela folha como base
    prov_fn = df[(df["tipo"] == "PROVENTO") & (df["classificacao"].isin(["FORA", "NEUTRA"]))].copy()

    candidatos = {}
    combos = {}

    for g in ["ativos", "desligados", "total"]:
        linha = resumo[resumo["grupo"] == g.upper()].iloc[0]
        residual = linha["residual_nao_explicado"]

        cand = prov_fn.copy()
        cand["valor_alvo"] = cand[g].fillna(0.0).astype(float)
        cand = cand[cand["valor_alvo"] > 0].copy()
        cand = cand.sort_values("valor_alvo", ascending=False)

        candidatos[g] = cand[["rubrica", "tipo", "classificacao", "valor_alvo"]].copy()

        if pd.isna(residual) or residual <= 0:
            combos[g] = []
        else:
            combos[g] = _sugerir_combinacoes_por_valor(candidatos[g], residual)

    return resumo, candidatos, combos, descontos_classificados
