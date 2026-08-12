from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


ProgressCallback = Callable[..., None]


ETAPAS = {
    "preparacao": ("Preparação", 0.00, 0.02),
    "ingestao": ("Ingestão SQLite", 0.02, 0.40),
    "segunda_passagem": ("Segunda passagem", 0.40, 0.65),
    "materializacao": ("Materialização analítica", 0.65, 0.85),
    "consolidacao": ("Consolidação dos relatórios", 0.85, 0.95),
    "integridade": ("Controles de integridade", 0.95, 0.98),
    "finalizacao": ("Finalização", 0.98, 1.00),
}


@dataclass(frozen=True)
class ProgressoDetalhado:
    etapa: str
    titulo_etapa: str
    percentual_etapa: float
    percentual_geral: float
    mensagem: str
    detalhes: str = ""


def criar_progresso(
    etapa: str,
    percentual_etapa: float,
    mensagem: str,
    detalhes: str = "",
) -> ProgressoDetalhado:
    if etapa not in ETAPAS:
        raise ValueError(f"Etapa de progresso desconhecida: {etapa}")
    titulo, inicio, fim = ETAPAS[etapa]
    local = max(0.0, min(1.0, float(percentual_etapa)))
    geral = inicio + (fim - inicio) * local
    return ProgressoDetalhado(etapa, titulo, local, geral, mensagem, detalhes)


def emitir_progresso(
    callback: ProgressCallback | None,
    etapa: str,
    percentual_etapa: float,
    mensagem: str,
    detalhes: str = "",
) -> None:
    if callback is None:
        return
    info = criar_progresso(etapa, percentual_etapa, mensagem, detalhes)
    if getattr(callback, "_suporta_progresso_detalhado", False):
        callback(info.percentual_geral, mensagem, info)
    else:
        callback(info.percentual_geral, mensagem)
