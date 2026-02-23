# core/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Modelo(str, Enum):
    GERENCIAL_2021_PLUS = "GERENCIAL_2021_PLUS"
    SAGE_RESUMO_FOLHA = "SAGE_RESUMO_FOLHA"
    SAGE_DECIMO_TERCEIRO = "SAGE_DECIMO_TERCEIRO"
    SAGE_HIERARQUIA_EMPRESARIAL = "SAGE_HIERARQUIA_EMPRESARIAL"
    SAGE_PAGAMENTO_MENSAL = "SAGE_PAGAMENTO_MENSAL"
    DESCONHECIDO = "DESCONHECIDO"


class SubtipoResumo(str, Enum):
    TOTALIZACAO_CCUSTO = "TOTALIZACAO_CCUSTO"
    DEPARTAMENTO = "DEPARTAMENTO"
    PARENTESES_ESCOPO = "PARENTESES_ESCOPO"
    HIERARQUIA = "HIERARQUIA"
    OUTRO = "OUTRO"
    NAO_IDENTIFICADO = "NAO_IDENTIFICADO"


class Confianca(str, Enum):
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"


@dataclass(frozen=True)
class ResumoIndexado:
    arquivo: str
    arquivo_id: str

    competencia: str  # "MM/AAAA" (pode estar vazio e ser preenchido depois)
    resumo_id: str

    modelo: Modelo
    subtipo: SubtipoResumo

    resumo_nome: str
    resumo_nome_norm: str

    pag_ini: int
    pag_fim: int

    sinais_detectados: List[str] = field(default_factory=list)
    score_modelo: int = 0
    confianca_modelo: Confianca = Confianca.BAIXA

    # campos opcionais para futuro
    applies_company: Optional[str] = None
    notes: Optional[str] = None


@dataclass(frozen=True)
class BlocoCandidato:
    arquivo: str
    arquivo_id: str
    pag_ini: int
    pag_fim: int

    # texto do cabeçalho (primeiras linhas)
    header_text: str
    # amostra adicional (pode ser a página inteira ou parte)
    sample_text: str