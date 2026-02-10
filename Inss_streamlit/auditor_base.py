import pandas as pd
import re
from itertools import combinations


def _to_cents(x: float) -> int:
    return int(round(float(x) * 100))


def _from_cents(c: int) -> float:
    return c / 100.0


def identificar_ajustes_negativos(df: pd.DataFrame) -> pd.DataFrame:
    """
    Heurística: dentro do bloco DESCONTO, tenta separar descontos financeiros (INSS/IRRF/etc.)
    de eventos negativos de remuneração (faltas/atrasos/DSR descontado/ajustes).
    Esses "ajustes negativos" podem reduzir a base (dependendo do ERP).
    """
    if df.empty:
        return df.copy()

    desc = df[df["tipo"] == "DESCONTO"].copy()
    if desc.empty:
        desc["eh_ajuste_negativo"] = False
        return desc

    padroes_ajuste = [
        "falta", "faltas",
        "atraso", "atrasos",
        "dsr desc", "dsr descont",
        "desc dsr",
        "desconto de", "descontos",
        "ajuste", "ajustes",
        "adiant", "adiantamento",
        "saldo", "compens",
        "repos", "reposição", "reposicao",
        "suspens", "suspensão", "suspensao",
        "penalid", "multa",  # (multa pode ser ajuste ou financeiro; fica como candidato)
    ]

    def eh_ajuste(r):
        txt = (r or "").lower()
        return any(p in txt for p in padroes_ajuste)

    desc["eh_ajuste_negativo"] = desc["rubrica"].apply(eh_ajuste)
    return desc


def reconstruir_base(df: pd.DataFrame, base_calc: dict) -> dict:
    """
    Base reconstruída (hipótese):
      base_reconstruida = proventos_ENTRA - ajustes_negativos
    Onde ajustes_negativos são descontos que podem reduzir remuneração.
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
        "base_reconstruida": base_reconstruida
    }


def _sugerir_combinacoes_por_valor(
    candidatos: pd.DataFrame,
    alvo: float,
    tol: float = 0.05,
    top_n: int = 35,
    max_k: int = 6,
):
    """
    Busca combinações de valores que somem aproximadamente o alvo.
    Usada para "explicar" o residual.
    """
    if candidatos.empty:
        return []

    alvo_c = _to_cents(abs(alvo))
    tol_c = _to_cents(tol)

    cand = candidatos.sort_values("valor_alvo", ascending=False).head(top_n).reset_index(drop=True)
    vals = cand["valor_alvo"].tolist()
    vals_c = [_to_cents(v) for v in vals]

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


def auditoria_por_grupo(df: pd.DataFrame, base_calc: dict, base_oficial: dict | None):
    """
    Retorna:
      - resumo (DataFrame): por grupo
      - candidatos (dict): tabelas de candidatos por grupo
      - combos (dict): combinações por grupo
    """
    # total de proventos (bruto) só pra contexto
    prov = df[df["tipo"] == "PROVENTO"].copy()
    tot_prov = {
        "ativos": float(prov["ativos"].fillna(0).sum()),
        "desligados": float(prov["desligados"].fillna(0).sum()),
        "total": float(prov["total"].fillna(0).sum())
    }

    recon = reconstruir_base(df, base_calc)
    ajustes = recon["ajustes_negativos"]
    base_rec = recon["base_reconstruida"]

    linhas = []
    for g in ["ativos", "desligados", "total"]:
        of = None if not base_oficial else float(base_oficial.get(g, 0.0))
        residual = None if of is None else float(of - base_rec[g])

        linhas.append({
            "grupo": g.upper(),
            "proventos_brutos": tot_prov[g],
            "base_calc_ENTRA": base_calc[g],
            "ajustes_negativos_identificados": ajustes[g],
            "base_reconstruida": base_rec[g],
            "base_oficial_pdf": of,
            "residual_nao_explicado": residual
        })

    # afastados (não existe no quadro de eventos desse modelo)
    if base_oficial and "afastados" in base_oficial:
        linhas.append({
            "grupo": "AFASTADOS",
            "proventos_brutos": None,
            "base_calc_ENTRA": None,
            "ajustes_negativos_identificados": None,
            "base_reconstruida": None,
            "base_oficial_pdf": float(base_oficial["afastados"]),
            "residual_nao_explicado": float(base_oficial["afastados"]),
        })

    resumo = pd.DataFrame(linhas)

    # Candidatos para explicar residual:
    # - Se residual > 0: base_oficial maior que reconstruída → pode ter proventos "fora/neutra" que estão compondo a base
    # - Se residual < 0: reconstruída maior → pode haver ENTRA indevido OU ajustes negativos faltando
    candidatos = {}
    combos = {}

    # candidatos baseados em PROVENTO fora/neutra (por grupo)
    prov_fn = df[(df["tipo"] == "PROVENTO") & (df["classificacao"].isin(["FORA", "NEUTRA"]))].copy()

    for g in ["ativos", "desligados", "total"]:
        linha = resumo[resumo["grupo"] == g.upper()].iloc[0]
        residual = linha["residual_nao_explicado"]
        if pd.isna(residual):
            candidatos[g] = prov_fn.head(0)
            combos[g] = []
            continue

        # tabela de candidatos com coluna valor_alvo do grupo
        cand = prov_fn.copy()
        cand["valor_alvo"] = cand[g].fillna(0.0).astype(float)
        cand = cand[cand["valor_alvo"] > 0].copy()
        cand = cand.sort_values("valor_alvo", ascending=False)

        candidatos[g] = cand[["rubrica", "tipo", "classificacao", "valor_alvo"]].copy()

        # combinações só fazem sentido quando residual é positivo (queremos "explicar" o que está dentro da base)
        # mas você pode olhar também quando negativo pra investigar ENTRA indevido (aí seria o inverso).
        if residual > 0:
            combos[g] = _sugerir_combinacoes_por_valor(candidatos[g], residual)
        else:
            combos[g] = []

    return resumo, candidatos, combos
