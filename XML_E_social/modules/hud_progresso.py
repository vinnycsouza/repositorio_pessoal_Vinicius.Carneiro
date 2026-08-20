from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DadosHUDIngestao:
    fonte: str = "—"
    itens_lidos: str = "—"
    itens_restantes: str = "—"
    volume_lido: str = "—"
    xml_catalogados: str = "—"
    ritmo: str = "—"
    eta: str = "calculando"
    fontes_descobertas: str = "—"
    fontes_concluidas: str = "—"
    fontes_em_leitura: str = "—"
    fontes_pendentes: str = "—"
    fontes_com_erro: str = "—"
    volume_restante: str = "—"
    tempo_decorrido: str = "—"


def _capturar(texto: str, padrao: str, valor_padrao: str = "—") -> str:
    achado = re.search(padrao, texto, flags=re.IGNORECASE)
    return achado.group(1).strip() if achado else valor_padrao


def _numero_exibicao(valor: str) -> int | None:
    digitos = re.sub(r"\D", "", valor or "")
    return int(digitos) if digitos else None


def extrair_hud_ingestao(detalhes: str, mensagem: str = "") -> DadosHUDIngestao:
    """Organiza o texto emitido pela Engine sem alterar suas métricas."""
    texto = str(detalhes or mensagem or "")
    itens = re.search(r"itens\s+([\d.,]+)\s*/\s*([\d.,]+)", texto, re.I)
    lidos = itens.group(1) if itens else "—"
    total = itens.group(2) if itens else "—"
    lidos_num = _numero_exibicao(lidos)
    total_num = _numero_exibicao(total)
    restantes = (
        f"{max(total_num - lidos_num, 0):,}".replace(",", ".")
        if lidos_num is not None and total_num is not None else "—"
    )
    volume = _capturar(
        texto,
        r"\|\s*([\d.,]+\s*[KMGT]?B\s*/\s*[\d.,]+\s*[KMGT]?B)\s*\|",
    ).replace("/", " de ")
    return DadosHUDIngestao(
        fonte=_capturar(texto, r"Fonte:\s*([^|]+)"),
        itens_lidos=f"{lidos} de {total}" if itens else "—",
        itens_restantes=restantes,
        volume_lido=volume,
        xml_catalogados=_capturar(texto, r"([\d.,]+)\s+XMLs catalogados"),
        ritmo=_capturar(texto, r"([\d.,]+\s+itens/s)"),
        eta=_capturar(texto, r"ETA da fonte\s+([^|]+?)(?:\s*\||\.$|$)", "calculando"),
        fontes_descobertas=_capturar(texto, r"fontes descobertas\s+([\d.,]+)"),
        fontes_concluidas=_capturar(texto, r"lidas\s+([\d.,]+)"),
        fontes_em_leitura=_capturar(texto, r"em leitura\s+([\d.,]+)"),
        fontes_pendentes=_capturar(texto, r"pendentes\s+([\d.,]+)"),
        fontes_com_erro=_capturar(texto, r"com erro\s+([\d.,]+)"),
        volume_restante=_capturar(texto, r"restante conhecido\s+([^|]+?)(?:\s*\||\.$|$)"),
        tempo_decorrido=_capturar(texto, r"decorrido\s+([^|]+?)(?:\s*\||\.$|$)"),
    )
