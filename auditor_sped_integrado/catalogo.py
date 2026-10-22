"""Regras documentadas. A presença no catálogo não autoriza crédito automático."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Regra:
    codigo: str
    titulo: str
    regimes: str
    tratamento: str
    fonte: str
    url: str


REGRAS = (
    Regra(
        "PISCOFINS_ICMS_69",
        "ICMS próprio na base de PIS/COFINS",
        "Real e presumido; verificar regime da receita",
        "Triagem por item; validação exige nota, apuração e recolhimento",
        "STF Tema 69; parecer PGFN e jurisprudência vinculante RFB",
        "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/legislacao/jurisprudencia-vinculante/pis-cofins",
    ),
    Regra(
        "PISCOFINS_ICMS_ST_1125",
        "ICMS-ST na base de PIS/COFINS do substituído",
        "Real e presumido; confirmar condição de substituído",
        "Triagem; não confundir com restituição estadual do ICMS-ST",
        "STJ Tema 1125; parecer PGFN e jurisprudência vinculante RFB",
        "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/legislacao/jurisprudencia-vinculante/pis-cofins",
    ),
    Regra(
        "PISCOFINS_CREDITOS_ART3",
        "Créditos ordinários de PIS/COFINS não cumulativos",
        "Em regra lucro real, conforme tributação de cada receita",
        "Pendente de motor por natureza de gasto, CST e documento",
        "Leis 10.637/2002 e 10.833/2003, art. 3º; orientações RFB",
        "https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/conformidade-tributaria/Creditos-Indevidos-de-PIS-Pasep-Cofins-Setor-Supermercadista",
    ),
    Regra(
        "ICMS_CREDITOS_LC87",
        "Créditos de ICMS em entradas",
        "Real e presumido; depende da UF e da operação",
        "Pendente de regras estaduais e confronto com apuração",
        "Lei Complementar 87/1996, arts. 20, 21 e 33",
        "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp87.htm",
    ),
    Regra(
        "IPI_CREDITOS",
        "Créditos e saldos de IPI",
        "Real e presumido; depende da operação industrial",
        "Pendente de confronto com entradas, apuração e saldo",
        "Orientações RFB sobre ressarcimento de IPI",
        "https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/creditos/ipi/conceito%20e%20prazos",
    ),
    Regra(
        "IRPJ_CSLL_SALDO",
        "Saldo negativo de IRPJ/CSLL",
        "Real e presumido",
        "Pendente de conciliação ECF, retenções, pagamentos e PER/DCOMP",
        "Orientações RFB sobre saldo negativo",
        "https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/creditos/sneg",
    ),
)


# Cada regra aparece como oportunidade no painel. Apenas os módulos abaixo
# possuem cálculo e relatório implementados; os demais ficam visíveis, sem ação.
MODULOS_IMPLEMENTADOS = frozenset({
    "PISCOFINS_ICMS_ST_1125",
    "PISCOFINS_ICMS_69",
})

