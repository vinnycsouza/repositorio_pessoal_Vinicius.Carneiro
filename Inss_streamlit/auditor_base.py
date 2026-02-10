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


# ------------------ combinações por valor ------------------

def _sugerir_combinacoes_por_valor(
    candidatos: pd.DataFrame,
    alvo: float,
    tol: float = 0.05,
    top_n: int = 35,
    max_k: int = 6,
):
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
        combos.append({"soma": _from_cents(soma), "erro": _from_cents(diff), "itens": itens})
    return combos


# ------------------ auditoria (agora com exclusão) ------------------

def auditoria_por_grupo(
    df: pd.DataFrame,
    base_calc: dict,
    base_oficial: dict | None,
    totais_proventos_pdf: dict | None = None,
):
    """
    Retorna:
      - resumo (DataFrame)
      - candidatos (dict)
      - combos (dict)
      - descontos_classificados (DataFrame)
      - blocos (dict) com somatórios de FORA/NEUTRA e base_por_exclusao
    """

    # 1) Totais de proventos (se você não passar o total do PDF, usamos o extraído)
    prov = df[df["tipo"] == "PROVENTO"].copy()
    tot_prov_extraido = {
        "ativos": float(prov["ativos"].fillna(0).sum()),
        "desligados": float(prov["desligados"].fillna(0).sum()),
        "total": float(prov["total"].fillna(0).sum()),
    }

    tot_prov = totais_proventos_pdf or tot_prov_extraido

    # 2) Soma de proventos FORA/NEUTRA (isso é o “o que não incide”, na prática)
    prov_fora = df[(df["tipo"] == "PROVENTO") & (df["classificacao"] == "FORA")].copy()
    prov_neutra = df[(df["tipo"] == "PROVENTO") & (df["classificacao"] == "NEUTRA")].copy()

    soma_fora = {
        "ativos": float(prov_fora["ativos"].fillna(0).sum()),
        "desligados": float(prov_fora["desligados"].fillna(0).sum()),
        "total": float(prov_fora["total"].fillna(0).sum()),
    }
    soma_neutra = {
        "ativos": float(prov_neutra["ativos"].fillna(0).sum()),
        "desligados": float(prov_neutra["desligados"].fillna(0).sum()),
        "total": float(prov_neutra["total"].fillna(0).sum()),
    }

    # 3) BASE POR EXCLUSÃO (a nova estrela)
    base_exclusao = {
        "ativos": float(tot_prov["ativos"] - soma_fora["ativos"] - soma_neutra["ativos"]),
        "desligados": float(tot_prov["desligados"] - soma_fora["desligados"] - soma_neutra["desligados"]),
        "total": float(tot_prov["total"] - soma_fora["total"] - soma_neutra["total"]),
    }

    # 4) Descontos classificados (mantemos pra auditoria)
    descontos_classificados = identificar_ajustes_negativos(df)
    aj = descontos_classificados[descontos_classificados["eh_ajuste_negativo"]].copy()

    descontos_reduzem = {
        "ativos": float(aj["ativos"].fillna(0).sum()) if not aj.empty else 0.0,
        "desligados": float(aj["desligados"].fillna(0).sum()) if not aj.empty else 0.0,
        "total": float(aj["total"].fillna(0).sum()) if not aj.empty else 0.0,
    }

    # 5) Monta resumo comparando 2 reconstruções:
    #    - Base por Inclusão (ENTRA - descontos_reduzem)
    #    - Base por Exclusão (TOTAL_PROV - FORA - NEUTRA)
    base_inclusao = {
        "ativos": float(base_calc.get("ativos", 0.0) - descontos_reduzem["ativos"]),
        "desligados": float(base_calc.get("desligados", 0.0) - descontos_reduzem["desligados"]),
        "total": float(base_calc.get("total", 0.0) - descontos_reduzem["total"]),
    }

    linhas = []
    for g in ["ativos", "desligados", "total"]:
        of = None if not base_oficial else float(base_oficial.get(g, 0.0))
        linhas.append({
            "grupo": g.upper(),
            "tot_proventos_pdf_ou_extraido": float(tot_prov[g]),
            "fora_proventos": soma_fora[g],
            "neutra_proventos": soma_neutra[g],
            "base_por_exclusao": base_exclusao[g],
            "base_calc_ENTRA": float(base_calc.get(g, 0.0)),
            "descontos_reduzem_base": descontos_reduzem[g],
            "base_por_inclusao": base_inclusao[g],
            "base_oficial_pdf": of,
            "dif_exclusao_vs_oficial": None if of is None else float(base_exclusao[g] - of),
            "dif_inclusao_vs_oficial": None if of is None else float(base_inclusao[g] - of),
        })

    if base_oficial and "afastados" in base_oficial:
        linhas.append({
            "grupo": "AFASTADOS",
            "tot_proventos_pdf_ou_extraido": None,
            "fora_proventos": None,
            "neutra_proventos": None,
            "base_por_exclusao": None,
            "base_calc_ENTRA": None,
            "descontos_reduzem_base": None,
            "base_por_inclusao": None,
            "base_oficial_pdf": float(base_oficial["afastados"]),
            "dif_exclusao_vs_oficial": None,
            "dif_inclusao_vs_oficial": None,
        })

    resumo = pd.DataFrame(linhas)

    # 6) Candidatos e combos passam a mirar o "gap" da exclusão (quando a exclusão não bater)
    candidatos = {}
    combos = {}

    # se base_exclusao estiver MENOR que oficial, é porque algo classificado como FORA/NEUTRA na verdade entra
    # então candidatos = (FORA/NEUTRA) por valor
    prov_fn = df[(df["tipo"] == "PROVENTO") & (df["classificacao"].isin(["FORA", "NEUTRA"]))].copy()

    for g in ["ativos", "desligados", "total"]:
        linha = resumo[resumo["grupo"] == g.upper()].iloc[0]
        of = linha["base_oficial_pdf"]
        if pd.isna(of):
            candidatos[g] = prov_fn.head(0)
            combos[g] = []
            continue

        gap = float(of - base_exclusao[g])  # quanto falta pra exclusão bater
        cand = prov_fn.copy()
        cand["valor_alvo"] = cand[g].fillna(0.0).astype(float)
        cand = cand[cand["valor_alvo"] > 0].copy()
        cand = cand.sort_values("valor_alvo", ascending=False)
        candidatos[g] = cand[["rubrica", "tipo", "classificacao", "valor_alvo"]].copy()

        if gap > 0:
            combos[g] = _sugerir_combinacoes_por_valor(candidatos[g], gap)
        else:
            combos[g] = []

    blocos = {
        "tot_proventos_usado": tot_prov,
        "tot_proventos_extraido": tot_prov_extraido,
        "soma_fora": soma_fora,
        "soma_neutra": soma_neutra,
        "base_por_exclusao": base_exclusao,
        "base_por_inclusao": base_inclusao,
        "descontos_reduzem": descontos_reduzem,
    }

    return resumo, candidatos, combos, descontos_classificados, blocos

