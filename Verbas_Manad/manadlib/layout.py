from __future__ import annotations

from typing import Optional


# Cabeçalhos (mantendo sua lógica)
CAB_K300 = [
    "REG", "CNPJ/CEI", "IND_FL", "COD_LTC", "COD_REG_TRAB", "DT_COMP",
    "COD_RUBR", "VLR_RUBR", "IND_RUBR", "IND_BASE_IRRF", "IND_BASE_PS",
]

CAB_K150 = ["REG", "CNPJ/CEI", "DT_INC_ALT", "COD_RUBRICA", "DESC_RUBRICA"]

# K050 (Cadastro de trabalhadores) — campos conforme manual (15 campos)
CAB_K050 = [
    "REG", "CNPJ/CEI", "DT_INC_ALT", "COD_REG_TRAB", "CPF", "NIT", "COD_CATEG",
    "NOME_TRAB", "DT_NASC", "DT_ADMISSAO", "DT_DEMISSAO", "IND_VINC",
    "TIPO_ATO_NOM", "NM_ATO_NOM", "DT_ATO_NOM",
]


def cabecalho_evento(codigo: str):
    cabecalhos = {
        "K300": CAB_K300,
        "K150": CAB_K150,
        "K050": CAB_K050,
    }
    return cabecalhos.get(codigo)


def extrair_codigo_evento(linha: str) -> Optional[str]:
    linha = (linha or "").strip()
    if len(linha) < 4:
        return None
    return linha[:4]
