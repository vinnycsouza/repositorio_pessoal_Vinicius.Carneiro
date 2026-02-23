# core/competencia_extract.py
from __future__ import annotations

import re
from typing import List

MESES = {
    "JAN": "01", "JANEIRO": "01",
    "FEV": "02", "FEVEREIRO": "02",
    "MAR": "03", "MARCO": "03", "MARÇO": "03",
    "ABR": "04", "ABRIL": "04",
    "MAI": "05", "MAIO": "05",
    "JUN": "06", "JUNHO": "06",
    "JUL": "07", "JULHO": "07",
    "AGO": "08", "AGOSTO": "08",
    "SET": "09", "SETEMBRO": "09",
    "OUT": "10", "OUTUBRO": "10",
    "NOV": "11", "NOVEMBRO": "11",
    "DEZ": "12", "DEZEMBRO": "12",
}

EMISSAO_KW = ["EMISSAO", "EMITIDO EM", "DATA:", "HORA:", "PÁGINA", "PAGINA"]


def _linhas_texto(texto: str) -> List[str]:
    t = texto or ""
    return [ln.strip() for ln in t.splitlines() if ln.strip()]


def _linha_tem_emissao(linha: str) -> bool:
    l = (linha or "").upper()
    if any(k in l for k in EMISSAO_KW):
        return True
    if re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", l) and ("EMISSAO" in l or "EMITIDO" in l or "DATA" in l):
        return True
    return False


def extrair_competencia_texto(texto: str) -> str | None:
    """
    Prioridades:
      1) "Mês/Ano: 12/2018"
      2) "Período: ... Dezembro/2012"
      3) "Competência 31/01/2021" -> 01/2021
      4) mm/aaaa, mm.aaaa, jan/21, janeiro 2021 (ignorando linhas de emissão)
    """
    linhas = _linhas_texto(texto)
    linhas_validas = [ln for ln in linhas if not _linha_tem_emissao(ln)]
    joined = "\n".join(linhas_validas)
    low = joined.lower()

    # 1) Mês/Ano: 12/2018
    m = re.search(r"\bm[eê]s\s*/\s*ano\s*:\s*(0?[1-9]|1[0-2])\s*/\s*(20\d{2})\b", low, flags=re.IGNORECASE)
    if m:
        return f"{m.group(1).zfill(2)}/{m.group(2)}"

    # 2) Período: ... Dezembro/2012
    m = re.search(r"\bper[ií]odo\s*:\s*.*?\b([a-zç]{3,9})\s*/\s*(20\d{2})\b", low, flags=re.IGNORECASE)
    if m:
        mes_txt = m.group(1).replace("ç", "c").upper()
        aa = m.group(2)
        if mes_txt in MESES:
            return f"{MESES[mes_txt]}/{aa}"

    # 3) Competência dd/mm/aaaa -> mm/aaaa
    m = re.search(r"\bcompet[eê]ncia\b\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(20\d{2})\b", low, flags=re.IGNORECASE)
    if m:
        mm = int(m.group(2))
        aa = m.group(3)
        if 1 <= mm <= 12:
            return f"{str(mm).zfill(2)}/{aa}"

    # 4.1) mm/aaaa
    m = re.search(r"\b(0?[1-9]|1[0-2])\s*/\s*(20\d{2})\b", low)
    if m:
        return f"{m.group(1).zfill(2)}/{m.group(2)}"

    # 4.2) mm.aaaa ou mm-aaaa
    m = re.search(r"\b(0?[1-9]|1[0-2])\s*[.\-]\s*(20\d{2})\b", low)
    if m:
        return f"{m.group(1).zfill(2)}/{m.group(2)}"

    # 4.3) jan/21
    m = re.search(r"\b([a-zç]{3,9})\s*/\s*(\d{2})\b", low)
    if m:
        mes_txt = m.group(1).replace("ç", "c").upper()
        ano2 = m.group(2)
        if mes_txt in MESES:
            return f"{MESES[mes_txt]}/20{ano2}"

    # 4.4) janeiro 2021
    m = re.search(r"\b([a-zç]{3,9})\s+(20\d{2})\b", low)
    if m:
        mes_txt = m.group(1).replace("ç", "c").upper()
        aa = m.group(2)
        if mes_txt in MESES:
            return f"{MESES[mes_txt]}/{aa}"

    return None
