# core/detector.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from core.models import Modelo, Confianca
from core.normalize import normalize_text


@dataclass(frozen=True)
class DetectionResult:
    modelo: Modelo
    score: int
    sinais: List[str]
    confianca: Confianca


def detect_model_from_text(text: str) -> DetectionResult:
    """
    Detecta submodelo com base em assinaturas fortes (fingerprints).
    Usa score para ser auditável.
    """
    t = normalize_text(text)
    sinais: List[str] = []

    scores = {m: 0 for m in Modelo}

    def add(modelo: Modelo, pts: int, sinal: str):
        scores[modelo] += pts
        sinais.append(sinal)

    # GERENCIAL 2021+
    if "RESUMO GERENCIAL" in t and ("ANALITICO" in t or "ANALÍTICO" in t):
        add(Modelo.GERENCIAL_2021_PLUS, 120, "RESUMO GERENCIAL + ANALITICO")
    if "TOTAL DA EMPRESA" in t:
        add(Modelo.GERENCIAL_2021_PLUS, 60, "TOTAL DA EMPRESA")
    if "TODAS EMPRESAS SELECIONADAS" in t:
        add(Modelo.GERENCIAL_2021_PLUS, 20, "TODAS EMPRESAS SELECIONADAS")

    # SAGE HIERARQUIA
    if "RESUMO DA HIERARQUIA EMPRESARIAL" in t:
        add(Modelo.SAGE_HIERARQUIA_EMPRESARIAL, 150, "RESUMO DA HIERARQUIA EMPRESARIAL")

    # 13º / parcelas
    if re.search(r"\b13[ºO]?\b", t) and ("PARCELA" in t or "DECIMO TERCEIRO" in t or "13 SALARIO" in t):
        add(Modelo.SAGE_DECIMO_TERCEIRO, 130, "13O/PARCELA/DECIMO TERCEIRO")
    if "RELACAO DA 2" in t and "PARCELA" in t:
        add(Modelo.SAGE_DECIMO_TERCEIRO, 80, "RELACAO 2A PARCELA")

    # SAGE RESUMO FOLHA (clássico)
    if "RESUMO DA FOLHA DE PAGAMENTO" in t:
        add(Modelo.SAGE_RESUMO_FOLHA, 140, "RESUMO DA FOLHA DE PAGAMENTO")
    if "VENCIMENTOS" in t and "DESCONTOS" in t:
        add(Modelo.SAGE_RESUMO_FOLHA, 40, "VENCIMENTOS + DESCONTOS")
    if "TOTALIZACAO DA FOLHA" in t:
        add(Modelo.SAGE_RESUMO_FOLHA, 30, "TOTALIZACAO DA FOLHA")

    # Pagamento mensal (se existir)
    if "RESUMO DO PAGAMENTO MENSAL" in t:
        add(Modelo.SAGE_PAGAMENTO_MENSAL, 140, "RESUMO DO PAGAMENTO MENSAL")

    # Escolhe o maior score
    modelo_vencedor = max(scores, key=lambda m: scores[m])
    score = scores[modelo_vencedor]

    # Remove sinais que não pertencem ao vencedor (opcional; mantém tudo por simplicidade)
    if score <= 0:
        return DetectionResult(Modelo.DESCONHECIDO, 0, [], Confianca.BAIXA)

    confianca = Confianca.ALTA if score >= 140 else Confianca.MEDIA if score >= 80 else Confianca.BAIXA
    return DetectionResult(modelo_vencedor, score, sinais, confianca)