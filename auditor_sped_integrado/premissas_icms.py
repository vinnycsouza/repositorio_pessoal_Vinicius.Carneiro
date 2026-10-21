"""Premissas históricas usadas apenas em simulações preliminares."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
import re

import pandas as pd


FONTE_PE = (
    "https://www.sefaz.pe.gov.br/Legislacao/Tributaria/Documents/"
    "Legislacao/Leis_Tributarias/2016/Lei15730_2016.htm"
)
FONTE_MT = (
    "https://app1.sefaz.mt.gov.br/Sistema/legislacao/legislacaotribut.nsf/"
    "c83fc8b160f5810b032567550064fd41/cc9c3b9886404baa0325678b0043a842"
)


@dataclass(frozen=True)
class PremissaICMS:
    uf: str
    codigo_uf: str
    inicio: date
    fim: date
    aliquota_geral: Decimal
    fonte: str
    natureza: str = "Alíquota interna geral; não representa ICMS-ST destacado"


# Piloto. Regras específicas por mercadoria, FCP e ST não são inferidas desta tabela.
PREMISSAS = (
    PremissaICMS("PE", "26", date(2018, 1, 1), date(2023, 12, 31), Decimal("18"), FONTE_PE),
    PremissaICMS("PE", "26", date(2024, 1, 1), date(2026, 12, 31), Decimal("20.5"), FONTE_PE),
    PremissaICMS("MT", "51", date(2018, 1, 1), date(2026, 12, 31), Decimal("17"), FONTE_MT),
)

REGIMES_0110 = {
    "1": "Não cumulativo",
    "2": "Cumulativo",
    "3": "Cumulativo e não cumulativo",
}
REGIMES_DECLARADOS = {
    "Lucro real": "1",
    "Lucro presumido": "2",
    "Misto": "3",
}
ALIQUOTAS_BASICAS = {
    "1": (Decimal("1.65"), Decimal("7.6")),
    "2": (Decimal("0.65"), Decimal("3")),
}

COLUNAS_SIMULACAO = (
    "competencia", "cnpj_estabelecimento", "codigo_uf_nfe", "uf",
    "regime_0110", "regime_declarado", "codigo_regime_calculo",
    "descricao_regime", "fonte_regime",
    "cfop", "cst_pis", "cst_cofins", "aliquota_pis", "aliquota_cofins",
    "registros_c175", "registros_base_conferida", "registros_base_divergente",
    "registros_chave_invalida", "registros_duplicados_entre_abas",
    "base_pis_conferida", "base_cofins_conferida",
    "aliquota_icms_referencia", "parcela_icms_simulada",
    "pis_simulado", "cofins_simulada", "total_simulado",
    "estado_simulacao", "fonte_premissa",
)


@dataclass(frozen=True)
class PeriodoRegime:
    inicio: str
    fim: str
    regime: str


def validar_historico_regime(quadro: pd.DataFrame | None) -> tuple[PeriodoRegime, ...]:
    if quadro is None or quadro.empty:
        return ()
    periodos = []
    for numero, item in enumerate(quadro.to_dict("records"), start=1):
        inicio = str(item.get("inicio") or "").strip()
        fim = str(item.get("fim") or "").strip()
        regime = str(item.get("regime") or "").strip()
        if not inicio and not fim and not regime:
            continue
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", inicio):
            raise ValueError(f"Histórico tributário, linha {numero}: início deve ser AAAA-MM.")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", fim) or fim < inicio:
            raise ValueError(f"Histórico tributário, linha {numero}: fim inválido.")
        if regime not in REGIMES_DECLARADOS:
            raise ValueError(f"Histórico tributário, linha {numero}: regime inválido.")
        periodos.append(PeriodoRegime(inicio, fim, regime))
    periodos.sort(key=lambda x: x.inicio)
    for anterior, atual in zip(periodos, periodos[1:]):
        if anterior.fim >= atual.inicio:
            raise ValueError("Histórico tributário contém períodos sobrepostos.")
    return tuple(periodos)


def buscar_premissa(codigo_uf: str, competencia: str) -> PremissaICMS | None:
    """Só aceita regra que cubra o mês inteiro; mudanças internas exigem data da nota."""
    try:
        ano, mes = map(int, competencia.split("-"))
        inicio = date(ano, mes, 1)
        fim = date(ano, mes, monthrange(ano, mes)[1])
    except (TypeError, ValueError):
        return None
    regras = [
        regra for regra in PREMISSAS
        if regra.codigo_uf == codigo_uf and regra.inicio <= inicio and regra.fim >= fim
    ]
    if len(regras) > 1:
        raise ValueError(f"Premissas de ICMS sobrepostas para UF {codigo_uf} em {competencia}.")
    return regras[0] if regras else None


def tabela_premissas() -> pd.DataFrame:
    return pd.DataFrame([
        {**asdict(regra), "inicio": regra.inicio.isoformat(), "fim": regra.fim.isoformat(),
         "aliquota_geral": float(regra.aliquota_geral)}
        for regra in PREMISSAS
    ])


def _texto(valor: object) -> str:
    return "" if valor is None or pd.isna(valor) else str(valor).strip().removesuffix(".0")


def simular_potencial(
    c175: pd.DataFrame, historico_regime: tuple[PeriodoRegime, ...] = (),
) -> pd.DataFrame:
    """Cenário por alíquota geral da UF, separado do ICMS-ST documental."""
    if c175.empty:
        return pd.DataFrame(columns=COLUNAS_SIMULACAO)
    linhas = []
    for item in c175.to_dict("records"):
        if str(item["cfop"]) != "5405" or str(item["cst_pis"]).zfill(2) != "01" or str(item["cst_cofins"]).zfill(2) != "01":
            continue
        regime = _texto(item.get("regime_0110"))
        declarados = [
            periodo for periodo in historico_regime
            if periodo.inicio <= str(item["competencia"]) <= periodo.fim
        ]
        declarado = declarados[0].regime if declarados else ""
        codigo_declarado = REGIMES_DECLARADOS.get(declarado, "")
        codigo_calculo = regime or codigo_declarado
        fonte_regime = "0110" if regime else ("Histórico informado" if declarado else "Não informado")
        conflito_regime = bool(regime and codigo_declarado and regime != codigo_declarado)
        aliquotas = (Decimal(str(item["aliquota_pis"])), Decimal(str(item["aliquota_cofins"])))
        pares_permitidos = (
            tuple(ALIQUOTAS_BASICAS.values()) if codigo_calculo == "3"
            else (ALIQUOTAS_BASICAS[codigo_calculo],) if codigo_calculo in ALIQUOTAS_BASICAS
            else ()
        )
        aliquotas_compativeis = aliquotas in pares_permitidos
        codigo_uf = _texto(item.get("uf_nfe"))
        regra = buscar_premissa(codigo_uf, str(item["competencia"]))
        conferidos = int(item.get("registros_base_conferida", 0))
        divergentes = int(item.get("registros_base_divergente", 0))
        chaves_invalidas = int(item.get("registros_chave_invalida", 0))
        duplicados = int(item.get("registros_duplicados_entre_abas", 0))
        estado = ""
        if not regra:
            estado = f"Sem premissa histórica verificada para UF {codigo_uf or '?'} / {item['competencia']}"
        elif duplicados:
            estado = "Registros repetidos entre abas; simulação bloqueada"
        elif chaves_invalidas:
            estado = "Chave NF-e inválida ou incompatível; conferir UF"
        elif conflito_regime:
            estado = "Divergência entre 0110 e histórico informado"
        elif codigo_calculo not in REGIMES_0110:
            estado = "Regime por competência não disponível"
        elif not aliquotas_compativeis:
            estado = "Alíquotas C175 incompatíveis com regime básico informado"
        elif conferidos == 0:
            estado = "Bases C175 pendentes de conferência"
        elif divergentes:
            estado = "Simulação parcial; bases divergentes preservadas para revisão"
        else:
            estado = "Simulação preliminar; ICMS-ST documental pendente"
        pode_simular = (
            regra is not None and not duplicados and not chaves_invalidas
            and not conflito_regime and codigo_calculo in REGIMES_0110
            and aliquotas_compativeis and conferidos > 0
        )
        aliquota_uf = regra.aliquota_geral if regra else None
        if pode_simular:
            base_pis = Decimal(str(item["base_pis_conferida"]))
            base_cofins = Decimal(str(item["base_cofins_conferida"]))
            pis = base_pis * aliquota_uf * Decimal(str(item["aliquota_pis"])) / Decimal("10000")
            cofins = base_cofins * aliquota_uf * Decimal(str(item["aliquota_cofins"])) / Decimal("10000")
            pis = min(pis, Decimal(str(item["valor_pis_conferido"])))
            cofins = min(cofins, Decimal(str(item["valor_cofins_conferido"])))
            pis = max(pis, Decimal("0")).quantize(Decimal("0.01"))
            cofins = max(cofins, Decimal("0")).quantize(Decimal("0.01"))
            parcela_icms = (base_pis * aliquota_uf / Decimal("100")).quantize(Decimal("0.01"))
        else:
            pis = cofins = parcela_icms = None
        linhas.append({
            "competencia": item["competencia"],
            "cnpj_estabelecimento": item["cnpj_estabelecimento"],
            "codigo_uf_nfe": codigo_uf,
            "uf": regra.uf if regra else "",
            "regime_0110": regime, "regime_declarado": declarado,
            "codigo_regime_calculo": codigo_calculo,
            "descricao_regime": REGIMES_0110.get(codigo_calculo, "Não informado"),
            "fonte_regime": fonte_regime,
            "cfop": item["cfop"], "cst_pis": item["cst_pis"], "cst_cofins": item["cst_cofins"],
            "aliquota_pis": item["aliquota_pis"], "aliquota_cofins": item["aliquota_cofins"],
            "registros_c175": item["registros_c175"],
            "registros_base_conferida": conferidos, "registros_base_divergente": divergentes,
            "registros_chave_invalida": chaves_invalidas,
            "registros_duplicados_entre_abas": duplicados,
            "base_pis_conferida": item["base_pis_conferida"],
            "base_cofins_conferida": item["base_cofins_conferida"],
            "aliquota_icms_referencia": float(aliquota_uf) if aliquota_uf is not None else None,
            "parcela_icms_simulada": float(parcela_icms) if parcela_icms is not None else None,
            "pis_simulado": float(pis) if pis is not None else None,
            "cofins_simulada": float(cofins) if cofins is not None else None,
            "total_simulado": float(pis + cofins) if pis is not None else None,
            "estado_simulacao": estado, "fonte_premissa": regra.fonte if regra else "",
        })
    return pd.DataFrame(linhas, columns=COLUNAS_SIMULACAO).sort_values(
        ["competencia", "cnpj_estabelecimento", "aliquota_pis", "aliquota_cofins"],
        ignore_index=True,
    ) if linhas else pd.DataFrame(columns=COLUNAS_SIMULACAO)
