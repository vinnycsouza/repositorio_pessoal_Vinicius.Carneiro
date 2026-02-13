# app.py
# ✅ Auditor INSS — Híbrido (ANALÍTICO + RESUMOS) com Navegação por PERÍODO → RESUMO
# ✅ Agora o usuário pode analisar QUALQUER resumo dentro do PDF (geral, obras, TJ, etc.)
# ✅ Mantém tudo que já existia: mapa, radar, devolvidas, exportação Excel, assinatura, semáforo 🟢🟡🔴
# ✅ Para RESUMO: evita “cobertor curto” ao NÃO misturar blocos (cada resumo vira uma unidade de análise)
# ✅ Foco do app: análise estrutural da base INSS da empresa — você pode filtrar “somente geral” depois se quiser

import io
import re
import zipfile
import pdfplumber
import pandas as pd
import streamlit as st

# Seus módulos (layout analítico)
from extrator_pdf import (
    extrair_eventos_page,
    extrair_base_empresa_page,
    pagina_eh_de_bases,
)
from calculo_base import calcular_base_por_grupo
from auditor_base import auditoria_por_exclusao_com_aproximacao


# ---------------------------
# Utilidades gerais
# ---------------------------

MESES = {
    "jan": "01", "janeiro": "01",
    "fev": "02", "fevereiro": "02",
    "mar": "03", "marco": "03", "março": "03",
    "abr": "04", "abril": "04",
    "mai": "05", "maio": "05",
    "jun": "06", "junho": "06",
    "jul": "07", "julho": "07",
    "ago": "08", "agosto": "08",
    "set": "09", "setembro": "09",
    "out": "10", "outubro": "10",
    "nov": "11", "novembro": "11",
    "dez": "12", "dezembro": "12",
}

VAL_RE = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})"

# Palavras que indicam sub-blocos (não “geral”)
SUBBLOCO_KW = [
    "centro de custo", "centro custo", "ccusto", "c.custo",
    "departamento", "setor", "filial", "unidade", "obra",
    "tomador", "contrato", "projeto",
    "diretor", "diretoria", "autônomo", "autonomo", "pró-labore", "pro-labore",
    "estagi", "terceir", "prestador", "rpa",
    "lotação", "lotacao",
    "rubricas por", "totalização da folha", "totalizacao da folha",
    "resumo por", "analítico por", "analitico por",
]

# Indícios de cabeçalho/rodapé/emitido (não é competência)
EMISSAO_KW = ["emissao", "emitido em", "data:", "hora:", "página", "pagina"]

# Palavras “fortes” que indicam resumo GERAL
KW_GERAL = [
    "resumo geral da folha de pagamento",
    "resumo da folha de pagamento",
    "situação: geral",
    "situacao: geral",
    "resumo da hierarquia empresarial",
    "hierarquia empresarial",
]


def normalizar_valor_br(txt: str):
    if txt is None:
        return None
    try:
        s = str(txt).strip()
        s = s.replace("R$", "").replace(" ", "")
        return float(s.replace(".", "").replace(",", "."))
    except Exception:
        return None


def _linhas_texto(texto: str) -> list[str]:
    t = texto or ""
    return [ln.strip() for ln in t.splitlines() if ln.strip()]


def _linha_tem_subbloco(linha: str) -> bool:
    l = (linha or "").lower()
    return any(k in l for k in SUBBLOCO_KW)


def _linha_tem_emissao(linha: str) -> bool:
    l = (linha or "").lower()
    if any(k in l for k in EMISSAO_KW):
        return True
    if re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", l) and ("emissao" in l or "emitido" in l or "data" in l):
        return True
    return False


def _safe_classificacao(df: pd.DataFrame) -> pd.DataFrame:
    if "classificacao" not in df.columns:
        df["classificacao"] = "SEM_CLASSIFICACAO"
    df["classificacao"] = df["classificacao"].fillna("SEM_CLASSIFICACAO").astype(str)
    return df


def _mode_or_none(series: pd.Series):
    if series is None or series.empty:
        return None
    vc = series.value_counts(dropna=True)
    return vc.index[0] if len(vc) else None


# ---------------------------
# Competência (robusta)
# ---------------------------

def extrair_competencia_sem_fallback_texto(texto: str):
    """
    Prioridades:
      1) "Mês/Ano: 12/2018" (Situação: Geral 2018)
      2) "Período: ... Dezembro/2012" (Hierarquia/2012)
      3) "Competência 31/01/2021" -> 01/2021 (analítico; reforço)
      4) padrões mm/aaaa, mm.aaaa, jan/21, janeiro 2021 (ignorando linhas de emissão)
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
        mes_txt = m.group(1).replace("ç", "c")
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
        mes_txt = m.group(1).replace("ç", "c")
        ano2 = m.group(2)
        if mes_txt in MESES:
            return f"{MESES[mes_txt]}/20{ano2}"

    # 4.4) janeiro 2021
    m = re.search(r"\b([a-zç]{3,9})\s+(20\d{2})\b", low)
    if m:
        mes_txt = m.group(1).replace("ç", "c")
        aa = m.group(2)
        if mes_txt in MESES:
            return f"{MESES[mes_txt]}/{aa}"

    return None


# ---------------------------
# Detector de layout (ANALITICO vs RESUMO)
# ---------------------------

def detectar_layout_pdf(pages_text: list[str]) -> str:
    joined = "\n".join([t for t in pages_text if t]).lower()
    if ("cod provento" in joined and "cod desconto" in joined and "ativos" in joined and "desligados" in joined):
        return "ANALITICO"
    if ("ativos" in joined and "desligados" in joined and "totais proventos" in joined):
        return "ANALITICO"
    if ("resumo gerencial analitico" in joined and "totais proventos" in joined):
        return "ANALITICO"
    return "RESUMO"


# ---------------------------
# Assinatura estrutural (família/sistema provável)
# ---------------------------

def _score_any(text: str, patterns: list[str]) -> int:
    return sum(1 for p in patterns if p in text)

def reconhecer_sistema_por_assinatura(pages_text: list[str]) -> dict:
    joined = "\n".join([t for t in pages_text if t]).lower()
    evid = []

    s_hierarquia = _score_any(joined, ["resumo da hierarquia empresarial", "previdência social", "total da base empresa"])
    s_analitico = _score_any(joined, ["cod provento", "cod desconto", "ativos", "desligados", "totais proventos", "resumo gerencial analitico"])
    s_situacao_geral = _score_any(joined, ["situação: geral", "mês/ano", "bases de cálculo", "base inss empresa", "total de vencimentos"])
    s_resumo_folha = _score_any(joined, ["resumo geral da folha de pagamento", "resumo da folha de pagamento", "total vantagem", "total descontos"])

    scores = {
        "ANALITICO_ESPELHADO": s_analitico,
        "RESUMO_SITUACAO_GERAL_2018": s_situacao_geral,
        "RESUMO_FOLHA_2012": s_resumo_folha,
        "RESUMO_HIERARQUIA_EMPRESARIAL": s_hierarquia,
    }
    familia = max(scores, key=scores.get)
    top = scores[familia]
    if top == 0:
        familia = "DESCONHECIDO"

    if "resumo da hierarquia empresarial" in joined: evid.append("RESUMO DA HIERARQUIA EMPRESARIAL")
    if "total da base empresa" in joined: evid.append("TOTAL DA BASE EMPRESA")
    if "situação: geral" in joined: evid.append("SITUAÇÃO: GERAL")
    if "mês/ano" in joined or "mes/ano" in joined: evid.append("MÊS/ANO")
    if "bases de cálculo" in joined or "bases de calculo" in joined: evid.append("BASES DE CÁLCULO")
    if "base inss empresa" in joined or "base inss (empresa)" in joined: evid.append("BASE INSS EMPRESA")
    if "total de vencimentos" in joined: evid.append("TOTAL DE VENCIMENTOS")
    if "resumo geral da folha de pagamento" in joined or "resumo da folha de pagamento" in joined:
        evid.append("RESUMO DA FOLHA DE PAGAMENTO")
    if "total vantagem" in joined: evid.append("TOTAL VANTAGEM")
    if "cod provento" in joined: evid.append("COD PROVENTO")
    if "cod desconto" in joined: evid.append("COD DESCONTO")
    if "totais proventos" in joined: evid.append("TOTAIS PROVENTOS")
    if "resumo gerencial analitico" in joined: evid.append("RESUMO GERENCIAL ANALÍTICO")

    if familia == "ANALITICO_ESPELHADO":
        sistema = "Domínio/Questor/Mastermaq (família analítica espelhada)"
        confianca = min(95, 60 + top * 10)
    elif familia == "RESUMO_SITUACAO_GERAL_2018":
        sistema = "Relatório 'Situação: Geral' (família 2018) — provável: Senior/TOTVS (heurística)"
        confianca = min(90, 55 + top * 10)
    elif familia == "RESUMO_FOLHA_2012":
        sistema = "Relatório 'Resumo Geral da Folha' (família 2012) — provável: legado"
        confianca = min(90, 55 + top * 10)
    elif familia == "RESUMO_HIERARQUIA_EMPRESARIAL":
        sistema = "Relatório consolidado 'Hierarquia Empresarial' — vendor não identificado"
        confianca = min(85, 50 + top * 10)
    else:
        sistema = "Não identificado"
        confianca = 10

    return {
        "familia_layout": familia,
        "sistema_provavel": sistema,
        "confianca": int(confianca),
        "evidencias": evid[:14],
        "scores": scores,
    }


# ---------------------------
# Totalizador ANALÍTICO
# ---------------------------

def extrair_totais_proventos_page(page) -> dict | None:
    padrao = re.compile(
        r"totais\s+proventos.*?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s+"
        r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s+"
        r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})",
        re.IGNORECASE
    )
    txt = page.extract_text() or ""
    m = padrao.search(txt)
    if not m:
        return None

    a = normalizar_valor_br(m.group(1))
    d = normalizar_valor_br(m.group(2))
    t = normalizar_valor_br(m.group(3))
    if a is None or d is None or t is None:
        return None
    return {"ativos": a, "desligados": d, "total": t}


# ---------------------------
# RESUMO: totalizador e base (por texto da página)
# ---------------------------

def _extrair_totalizadores_resumo(texto: str) -> dict | None:
    if not texto:
        return None

    linhas = [ln.strip() for ln in (texto or "").splitlines() if ln.strip()]
    cand = [ln for ln in linhas if not _linha_tem_subbloco(ln)]

    total_prov = None
    total_desc = None

    # 2018: Total de Vencimentos
    for ln in cand:
        l = ln.lower()
        m = re.search(rf"\btotal\s+de\s+vencimentos\s+{VAL_RE}\b", l, flags=re.IGNORECASE)
        if m:
            v = normalizar_valor_br(m.group(1))
            if v is not None:
                total_prov = v
                break

    # 2012: TOTAL VANTAGEM
    if total_prov is None:
        for ln in cand:
            l = ln.lower()
            if "total vantagem" in l:
                m = re.search(rf"\btotal\s+vantagem\b.*?{VAL_RE}", l, flags=re.IGNORECASE)
                if m:
                    v = normalizar_valor_br(m.group(1))
                    if v is not None:
                        total_prov = v
                md = re.search(rf"\btotal\s+descontos\b.*?{VAL_RE}", l, flags=re.IGNORECASE)
                if md:
                    vd = normalizar_valor_br(md.group(1))
                    if vd is not None:
                        total_desc = vd
                if total_prov is not None:
                    break

    # Hierarquia: Total de proventos / descontos
    if total_prov is None:
        for ln in cand:
            l = ln.lower()
            m = re.search(rf"\btotal\s+de\s+proventos\b.*?{VAL_RE}\b", l, flags=re.IGNORECASE)
            if m:
                v = normalizar_valor_br(m.group(1))
                if v is not None:
                    total_prov = v
            md = re.search(rf"\btotal\s+de\s+descontos\b.*?{VAL_RE}\b", l, flags=re.IGNORECASE)
            if md:
                vd = normalizar_valor_br(md.group(1))
                if vd is not None:
                    total_desc = vd
            if total_prov is not None:
                break

    if total_prov is None and total_desc is None:
        return None

    out = {"total": float(total_prov) if total_prov is not None else None}
    if total_desc is not None:
        out["descontos_total"] = float(total_desc)
    return out


def extrair_base_inss_global_texto(texto: str) -> float | None:
    """
    Base INSS empresa (geral) — sem tentar adivinhar sub-blocos. Como agora analisamos "um resumo por vez",
    essa função fica mais confiável, porque o resumo selecionado já é o contexto certo.
    """
    if not texto:
        return None

    linhas = [ln.strip() for ln in (texto or "").splitlines() if ln.strip()]
    # ainda assim ignora linhas “sub-bloco” como proteção
    cand = [ln for ln in linhas if not _linha_tem_subbloco(ln)]

    # prioridade (Hierarquia)
    for ln in cand:
        l = ln.lower()
        m = re.search(rf"\btotal\s+da\s+base\s+empresa\b.*?{VAL_RE}\b", l, flags=re.IGNORECASE)
        if m:
            v = normalizar_valor_br(m.group(1))
            if v is not None:
                return float(v)

    padroes = [
        rf"\bbase\s+inss\s*\(\s*empresa\s*\)\s*[:\-]?\s*{VAL_RE}\b",
        rf"\bbase\s+inss\s+empresa\s*[:\-]?\s*{VAL_RE}\b",
        rf"\binss\s+base\s*\(\s*empresa\s*\)\s*[:\-]?\s*{VAL_RE}\b",
        rf"\bbase\s+inss\s*[-–]\s*empresa\s*[:\-]?\s*{VAL_RE}\b",
        rf"\bbase\s+empresa\s*[:\-]?\s*{VAL_RE}\b",
        rf"\binss\s+base\s+empresa\s*[:\-]?\s*{VAL_RE}\b",
        rf"\binss\s+base\b.*?\bempresa\b.*?{VAL_RE}\b",
    ]

    candidatos = []
    for ln in cand:
        l = ln.lower()
        for p in padroes:
            m = re.search(p, l, flags=re.IGNORECASE)
            if m:
                v = normalizar_valor_br(m.group(1))
                if v is not None:
                    candidatos.append(float(v))

    if not candidatos:
        return None
    return float(max(candidatos))


# ---------------------------
# RESUMO: extrator de eventos robusto (evita 1.959,80 virar código 959)
# ---------------------------

def _find_codigos_resumo(linha: str) -> list[tuple[str, int]]:
    cod_pos = []
    for m in re.finditer(r"\b(\d{3,6})\b", linha):
        start, end = m.start(1), m.end(1)
        prev = linha[start - 1] if start - 1 >= 0 else " "
        nxt = linha[end] if end < len(linha) else " "
        if prev in ".,":  # 1.959,80 -> ignora 959
            continue
        if nxt in ".,":   # proteção extra
            continue
        cod_pos.append((m.group(1), start))
    return sorted(cod_pos, key=lambda x: x[1])


def extrair_eventos_resumo_texto(texto: str) -> list[dict]:
    if not texto or not texto.strip():
        return []

    linhas = [ln.rstrip() for ln in texto.splitlines() if ln.strip()]
    eventos = []
    secao = None  # PROVENTO / DESCONTO

    def numeros_br(s: str):
        return re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", s)

    def ultimo_numero_br(s: str):
        nums = numeros_br(s)
        if not nums:
            return None
        return normalizar_valor_br(nums[-1])

    def penultimo_numero_br(s: str):
        nums = numeros_br(s)
        if len(nums) < 2:
            return None
        return normalizar_valor_br(nums[-2])

    def antepenultimo_numero_br(s: str):
        nums = numeros_br(s)
        if len(nums) < 3:
            return None
        return normalizar_valor_br(nums[-3])

    def primeiro_codigo(s: str):
        cods = _find_codigos_resumo(s)
        return cods[0][0] if cods else None

    def limpar_desc(cod: str, chunk: str):
        x = re.sub(r"^\s*" + re.escape(cod) + r"\s+", "", chunk).strip()
        nums = numeros_br(x)
        if nums:
            x = re.sub(re.escape(nums[-1]) + r"\s*$", "", x).strip()
        x = re.sub(r"\s{2,}", " ", x)
        return x

    def add_event(tipo: str, cod: str, desc: str, valor: float, referencia: float | None, quantidade: float | None):
        rubrica = f"{cod} {desc}".strip()
        eventos.append({
            "rubrica": rubrica,
            "tipo": tipo,
            "quantidade": float(quantidade) if quantidade is not None else None,
            "referencia": float(referencia) if referencia is not None else None,
            "ativos": float(valor),
            "desligados": 0.0,
            "total": float(valor),
        })

    for ln in linhas:
        l = ln.lower()

        # detecta seções
        if "vencimentos" in l or "proventos" in l:
            secao = "PROVENTO"
            continue
        if "descontos" in l:
            secao = "DESCONTO"
            continue

        # ignora áreas que não são eventos
        if "base inss" in l or "bases de c" in l or "bases de cá" in l or "bases de ca" in l:
            continue
        if "resumo" in l and "folha" in l:
            continue
        if "total geral" in l:
            continue
        if "totalização" in l or "totalizacao" in l:
            continue
        if "total de vencimentos" in l or "total de descontos" in l:
            continue
        if "total vantagem" in l or "total de proventos" in l:
            continue
        if ("evento" in l and "descr" in l and "valor" in l) or ("evento" in l and "descricao" in l and "valor" in l):
            continue

        # 1) duas colunas com |
        if "|" in ln:
            partes = [p.strip() for p in ln.split("|")]
            blocos = [p for p in partes if p and primeiro_codigo(p)]
            if len(blocos) >= 2:
                esq, dir = blocos[0], blocos[1]

                cod_esq = primeiro_codigo(esq)
                val_esq = ultimo_numero_br(esq)
                ref_esq = penultimo_numero_br(esq)
                q_esq = antepenultimo_numero_br(esq)
                quant_esq = q_esq if (q_esq is not None and q_esq <= 10000) else None

                if cod_esq and val_esq is not None:
                    add_event("PROVENTO", cod_esq, limpar_desc(cod_esq, esq), val_esq, ref_esq, quant_esq)

                cod_dir = primeiro_codigo(dir)
                val_dir = ultimo_numero_br(dir)
                ref_dir = penultimo_numero_br(dir)
                q_dir = antepenultimo_numero_br(dir)
                quant_dir = q_dir if (q_dir is not None and q_dir <= 10000) else None

                if cod_dir and val_dir is not None:
                    add_event("DESCONTO", cod_dir, limpar_desc(cod_dir, dir), val_dir, ref_dir, quant_dir)

                continue
            elif len(blocos) == 1:
                ln = blocos[0]

        # 2) “grudado”: dois códigos
        cod_pos = _find_codigos_resumo(ln)
        if len(cod_pos) >= 2:
            (cod1, p1), (cod2, p2) = cod_pos[0], cod_pos[1]
            chunk1 = ln[p1:p2].strip()
            chunk2 = ln[p2:].strip()

            v1 = ultimo_numero_br(chunk1)
            r1 = penultimo_numero_br(chunk1)
            q1 = antepenultimo_numero_br(chunk1)
            quant1 = q1 if (q1 is not None and q1 <= 10000) else None

            v2 = ultimo_numero_br(chunk2)
            r2 = penultimo_numero_br(chunk2)
            q2 = antepenultimo_numero_br(chunk2)
            quant2 = q2 if (q2 is not None and q2 <= 10000) else None

            if v1 is not None:
                add_event("PROVENTO", cod1, limpar_desc(cod1, chunk1), v1, r1, quant1)
            if v2 is not None:
                add_event("DESCONTO", cod2, limpar_desc(cod2, chunk2), v2, r2, quant2)
            continue

        # 3) linha simples
        m_cod = re.match(r"^\s*(\d{3,6})\s+(.+)$", ln)
        if not m_cod:
            continue

        cod = m_cod.group(1)
        resto = m_cod.group(2)

        val = ultimo_numero_br(resto)
        if val is None:
            continue

        ref = penultimo_numero_br(resto)
        q = antepenultimo_numero_br(resto)
        quant = q if (q is not None and q <= 10000) else None

        desc = limpar_desc(cod, f"{cod} {resto}")
        tipo = secao if secao in ("PROVENTO", "DESCONTO") else "PROVENTO"
        add_event(tipo, cod, desc, val, ref, quant)

    return eventos


# ---------------------------
# Diagnóstico (analítico)
# ---------------------------

def diagnostico_extracao_proventos(df_eventos: pd.DataFrame, tol_inconsistencia: float = 1.00) -> pd.DataFrame:
    df = df_eventos.copy()
    if df.empty:
        return df

    for col in ["ativos", "desligados", "total"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df = df[df["tipo"] == "PROVENTO"].copy()
    if df.empty:
        return df

    df["soma_partes"] = df["ativos"] + df["desligados"]
    df["delta_total_vs_partes"] = (df["total"] - df["soma_partes"]).abs()

    df["flag_inconsistencia_total"] = df["delta_total_vs_partes"] > tol_inconsistencia
    df["flag_total_sem_partes"] = (df["total"] > 0) & (df["ativos"] == 0) & (df["desligados"] == 0)
    df["flag_partes_sem_total"] = ((df["ativos"] > 0) | (df["desligados"] > 0)) & (df["total"] == 0)

    rub = df["rubrica"].fillna("").astype(str)
    df["flag_rubrica_curta"] = rub.str.len() <= 6
    df["flag_rubrica_somente_num"] = rub.str.match(r"^\s*\d+\s*$")

    df["score_suspeita"] = (
        df["flag_inconsistencia_total"].astype(int) * 3 +
        df["flag_total_sem_partes"].astype(int) * 2 +
        df["flag_partes_sem_total"].astype(int) * 2 +
        df["flag_rubrica_curta"].astype(int) * 1 +
        df["flag_rubrica_somente_num"].astype(int) * 1
    )

    cols_out = [
        "rubrica", "ativos", "desligados", "total",
        "soma_partes", "delta_total_vs_partes",
        "flag_inconsistencia_total", "flag_total_sem_partes", "flag_partes_sem_total",
        "flag_rubrica_curta", "flag_rubrica_somente_num",
        "score_suspeita"
    ]
    cols_out = [c for c in cols_out if c in df.columns]
    return df[cols_out].sort_values(["score_suspeita", "delta_total_vs_partes", "total"], ascending=[False, False, False])


# ---------------------------
# Semáforo simples 🟢🟡🔴
# ---------------------------

def semaforo(status: str) -> str:
    s = (status or "").upper()
    if s == "OK":
        return "🟢"
    if s in ("ACEITAVEL", "INCOMPLETO_BASE", "SEM_EVENTOS", "SEM_ERRO", "SEM_COMP"):
        return "🟡"
    if s in ("RUIM", "FALHA_EXTRACAO_TOTALIZADOR"):
        return "🔴"
    return "🟡"


def _styler_semaforo(df: pd.DataFrame):
    if df is None or df.empty or "semaforo" not in df.columns:
        return df

    def _row_style(row):
        s = row.get("semaforo", "")
        if s == "🟢":
            return ["background-color: rgba(40,167,69,0.20);"] * len(row)
        if s == "🟡":
            return ["background-color: rgba(255,193,7,0.20);"] * len(row)
        if s == "🔴":
            return ["background-color: rgba(220,53,69,0.20);"] * len(row)
        return [""] * len(row)

    return df.style.apply(_row_style, axis=1)


# ---------------------------
# NOVO: Detector de “Resumo/Bloco” por página (para navegação)
# ---------------------------

def detectar_nome_resumo_por_pagina(texto: str) -> str:
    """
    Retorna um “nome” humano do resumo (bloco) com base em palavras-chave.
    O objetivo é indexar os resumos dentro do PDF para o usuário escolher.
    """
    low = (texto or "").lower()

    if "resumo da hierarquia empresarial" in low:
        return "HIERARQUIA_EMPRESARIAL"

    if "situação: geral" in low or "situacao: geral" in low:
        return "SITUACAO_GERAL"

    if "resumo geral da folha de pagamento" in low:
        return "RESUMO_GERAL_FOLHA"

    if "resumo da folha de pagamento" in low:
        return "RESUMO_FOLHA"

    # “setoriais” comuns (apenas nomeação — o usuário escolhe)
    # pega o primeiro “rótulo” que aparecer nas primeiras linhas
    linhas = _linhas_texto(texto)[:12]
    joined = " | ".join(linhas).lower()

    # mapeamentos típicos (ajuste livre conforme seus PDFs)
    rotulos = [
        ("obras", "OBRAS"),
        ("tj", "TJ"),
        ("escritorio", "ESCRITORIO"),
        ("escritório", "ESCRITORIO"),
        ("unidade", "UNIDADE"),
        ("sede", "SEDE"),
        ("gre", "GRE"),
        ("rpa", "RPA"),
        ("saude", "SAUDE"),
        ("saúde", "SAUDE"),
        ("pcr", "PCR"),
        ("rn", "RN"),
        ("mc", "MC"),
    ]
    for k, lab in rotulos:
        if k in joined:
            return lab

    return "NAO_IDENTIFICADO"


def _agrupar_paginas_em_blocos(pags: list[dict]) -> dict:
    """
    Entrada: lista de dicts por página:
      {page_idx, page_number, texto, competencia, nome_resumo}
    Saída:
      estrutura[competencia][resumo_id] = {"nome":..., "paginas":[idxs], "pagina_range": "..."}
    """
    estrutura = {}

    # agrupa por competência e nome_resumo, mas mantendo sequência (para gerar IDs estáveis)
    # estratégia: dentro de cada competência, varre páginas em ordem e “corta” quando nome muda.
    by_comp = {}
    for p in pags:
        comp = p.get("competencia") or "SEM_COMP"
        by_comp.setdefault(comp, []).append(p)

    for comp, lst in by_comp.items():
        lst = sorted(lst, key=lambda x: x["page_idx"])
        estrutura.setdefault(comp, {})

        current_name = None
        current_pages = []

        def _flush():
            nonlocal current_name, current_pages
            if not current_pages:
                return
            page_numbers = [pp["page_number"] for pp in current_pages]
            start, end = min(page_numbers), max(page_numbers)
            pagina_range = f"p{start}-{end}" if start != end else f"p{start}"
            resumo_nome = current_name or "NAO_IDENTIFICADO"
            resumo_id = f"{resumo_nome}|{pagina_range}"
            estrutura[comp][resumo_id] = {
                "nome": resumo_nome,
                "paginas_idx": [pp["page_idx"] for pp in current_pages],
                "paginas_num": page_numbers,
                "pagina_range": pagina_range,
            }
            current_name = None
            current_pages = []

        for p in lst:
            nm = p.get("nome_resumo") or "NAO_IDENTIFICADO"
            if current_name is None:
                current_name = nm
                current_pages = [p]
                continue
            if nm == current_name:
                current_pages.append(p)
            else:
                _flush()
                current_name = nm
                current_pages = [p]

        _flush()

    return estrutura


def _round_cols(df_in: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    if df_in is None or df_in.empty:
        return df_in
    df_out = df_in.copy()
    for c in cols:
        if c in df_out.columns:
            df_out[c] = pd.to_numeric(df_out[c], errors="coerce")
            df_out[c] = df_out[c].round(2)
    return df_out


# ---------------------------
# Leitura de uploads: PDF ou ZIP com PDFs
# ---------------------------

def _load_uploaded_files(uploaded_files: list) -> list[dict]:
    """
    Retorna lista de “arquivos PDF” em memória:
      [{"name": "...pdf", "bytes": b"..."}]
    Suporta ZIP contendo PDFs.
    """
    out = []
    for uf in uploaded_files:
        name = uf.name
        data = uf.getvalue()

        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data), "r") as z:
                    for info in z.infolist():
                        if info.filename.lower().endswith(".pdf") and not info.is_dir():
                            pdf_bytes = z.read(info.filename)
                            base = info.filename.split("/")[-1].split("\\")[-1]
                            out.append({"name": base, "bytes": pdf_bytes})
            except Exception:
                # se zip der erro, ignora silenciosamente (não derruba o app)
                continue
        elif name.lower().endswith(".pdf"):
            out.append({"name": name, "bytes": data})

    # remove duplicados por nome (se existir), mantendo o último
    dedup = {}
    for item in out:
        dedup[item["name"]] = item
    return list(dedup.values())


# ---------------------------
# UI
# ---------------------------

st.set_page_config(layout="wide")
st.title("🧾 Auditor INSS — Navegação por Período → Resumo (ANALÍTICO + RESUMOS)")

uploads = st.file_uploader(
    "Envie 1 ou mais PDFs (ou ZIP com PDFs)",
    type=["pdf", "zip"],
    accept_multiple_files=True
)

st.markdown("### Configurações")
c1, c2, c3, c4 = st.columns(4)
with c1:
    tol_totalizador = st.number_input("Tolerância totalizador (R$)", min_value=0.0, value=1.00, step=0.50)
with c2:
    banda_ok = st.number_input("Banda OK (|erro| ≤)", min_value=0.0, value=10.0, step=1.0)
with c3:
    banda_aceitavel = st.number_input("Banda ACEITÁVEL (|erro| ≤)", min_value=0.0, value=10000.0, step=100.0)
with c4:
    modo_auditor_prof = st.checkbox("🕵️ Auditor Profissional (diagnóstico extração)", value=True)

indice_incidencia_on = st.checkbox("📈 Índice de Incidência", value=True)
mapa_incidencia_on = st.checkbox("🧭 Mapa de Incidência (impacto %)", value=True)
radar_on = st.checkbox("📡 Radar Estrutural Automático", value=True)

st.info(
    "✅ Novo fluxo: o app **indexa** o PDF em **Períodos → Resumos** e você escolhe o bloco que quer analisar.\n"
    "✅ Isso evita misturar subtotal/setor com consolidado.\n"
    "✅ O ANALÍTICO continua intacto.\n"
    "✅ Semáforo simples: 🟢🟡🔴"
)

if not uploads:
    st.info("Envie PDFs (ou um ZIP com PDFs) para iniciar.")
    st.stop()

pdf_files = _load_uploaded_files(uploads)
if not pdf_files:
    st.warning("Não encontrei PDFs válidos nos arquivos enviados.")
    st.stop()

# ---------------------------
# 1) INDEXAÇÃO (scan) — não calcula nada, só monta o navegador
# ---------------------------

st.sidebar.header("🧭 Navegação (Período → Resumo)")
st.sidebar.caption("O app cria um índice interno do(s) PDF(s) para você escolher o bloco a analisar.")

index = {}  # index[arquivo]["layout"] + ["assinatura"] + ["estrutura"]
scan_errors = []

for item in pdf_files:
    nome_arquivo = item["name"]
    b = item["bytes"]

    try:
        with pdfplumber.open(io.BytesIO(b)) as pdf:
            # pega 2 primeiras páginas para assinatura/layout
            texts_head = [(p.extract_text() or "") for p in pdf.pages[:2]]
            layout = detectar_layout_pdf(texts_head)
            assin = reconhecer_sistema_por_assinatura(texts_head)

            pags = []
            comp_atual = None

            for i, page in enumerate(pdf.pages):
                texto = page.extract_text() or ""
                comp = extrair_competencia_sem_fallback_texto(texto) or comp_atual
                if not comp:
                    comp = "SEM_COMP"
                comp_atual = comp

                nome_resumo = detectar_nome_resumo_por_pagina(texto)

                pags.append({
                    "page_idx": i,
                    "page_number": page.page_number,
                    "texto": texto,
                    "competencia": comp,
                    "nome_resumo": nome_resumo,
                })

            estrutura = _agrupar_paginas_em_blocos(pags)

            index[nome_arquivo] = {
                "bytes": b,
                "layout": layout,
                "assinatura": assin,
                "pags": pags,          # mantém textos por página para processamento depois
                "estrutura": estrutura # {comp: {resumo_id: {...}}}
            }
    except Exception as e:
        scan_errors.append({"arquivo": nome_arquivo, "erro": f"{type(e).__name__}: {e}"})
        continue

if scan_errors:
    st.sidebar.warning("⚠️ Alguns PDFs falharam no scan (não derruba o app).")
    with st.expander("Ver detalhes do scan"):
        st.dataframe(pd.DataFrame(scan_errors), use_container_width=True)

if not index:
    st.warning("Nenhum PDF pôde ser indexado.")
    st.stop()

# Seletores
arquivos_disp = sorted(index.keys())
arq_sel = st.sidebar.selectbox("Arquivo", arquivos_disp, index=0)

estrutura = index[arq_sel]["estrutura"]
comps_disp = sorted(estrutura.keys())
comp_sel = st.sidebar.selectbox("Período (competência)", comps_disp, index=max(0, len(comps_disp) - 1))

resumos_dict = estrutura.get(comp_sel, {})
resumos_disp = sorted(resumos_dict.keys())

# opção “todos”
resumos_disp2 = ["(TODOS OS RESUMOS DO PERÍODO)"] + resumos_disp
resumo_sel = st.sidebar.selectbox("Resumo (bloco)", resumos_disp2, index=0)

st.sidebar.divider()
st.sidebar.caption("Dica: PDFs anuais geralmente têm vários blocos — escolha o que quiser auditar.")

# ---------------------------
# 2) PROCESSAMENTO: roda o pipeline somente no(s) bloco(s) selecionado(s)
# ---------------------------

linhas_resumo = []
linhas_devolvidas = []
linhas_diagnostico = []
linhas_mapa = []
eventos_dump = []
linhas_erros = []

assin = index[arq_sel]["assinatura"]
layout = index[arq_sel]["layout"]
pags = index[arq_sel]["pags"]

def _processar_um_resumo(resumo_id: str, paginas_idx: list[int]):
    """
    Executa o pipeline para um único “resumo/bloco” (lista de páginas) dentro de uma competência.
    """
    # estrutura por “competência do bloco” (já veio do seletor comp_sel)
    dados = {comp_sel: {"eventos": [], "base_empresa": None, "totais_proventos_pdf": None}}

    # lê somente páginas do bloco
    for idx in paginas_idx:
        page_info = pags[idx]
        texto_pagina = page_info["texto"]

        # ---------- Base oficial ----------
        if layout == "ANALITICO":
            # analítico: usa base em páginas específicas detectadas pelo extrator
            try:
                # reabrir página como pdfplumber Page para usar extrator original
                # (mantém compatibilidade total com seu pipeline atual)
                with pdfplumber.open(io.BytesIO(index[arq_sel]["bytes"])) as pdf2:
                    page_obj = pdf2.pages[idx]
                    if pagina_eh_de_bases(page_obj):
                        base = extrair_base_empresa_page(page_obj)
                        if base and dados[comp_sel]["base_empresa"] is None:
                            dados[comp_sel]["base_empresa"] = base
            except Exception as e:
                linhas_erros.append({
                    "arquivo": arq_sel, "competencia": comp_sel, "pagina": page_info["page_number"],
                    "etapa": "BASE_ANALITICO", "resumo_id": resumo_id,
                    "erro": f"{type(e).__name__}: {e}"
                })
        else:
            # resumo: base pelo texto (agora no contexto do bloco escolhido)
            try:
                b = extrair_base_inss_global_texto(texto_pagina)
                if b is not None and dados[comp_sel]["base_empresa"] is None:
                    dados[comp_sel]["base_empresa"] = {"total": float(b)}
            except Exception as e:
                linhas_erros.append({
                    "arquivo": arq_sel, "competencia": comp_sel, "pagina": page_info["page_number"],
                    "etapa": "BASE_RESUMO", "resumo_id": resumo_id,
                    "erro": f"{type(e).__name__}: {e}"
                })

        # ---------- Totalizador ----------
        if layout == "ANALITICO":
            try:
                with pdfplumber.open(io.BytesIO(index[arq_sel]["bytes"])) as pdf2:
                    page_obj = pdf2.pages[idx]
                    tot = extrair_totais_proventos_page(page_obj)
                    if tot and dados[comp_sel]["totais_proventos_pdf"] is None:
                        dados[comp_sel]["totais_proventos_pdf"] = tot
            except Exception as e:
                linhas_erros.append({
                    "arquivo": arq_sel, "competencia": comp_sel, "pagina": page_info["page_number"],
                    "etapa": "TOTALIZADOR_ANALITICO", "resumo_id": resumo_id,
                    "erro": f"{type(e).__name__}: {e}"
                })
        else:
            try:
                t = _extrair_totalizadores_resumo(texto_pagina)
                if t and t.get("total") is not None:
                    # aqui: como o contexto já é do bloco selecionado,
                    # manter o primeiro total do bloco é OK (não é mais “pdf inteiro”)
                    if dados[comp_sel]["totais_proventos_pdf"] is None:
                        dados[comp_sel]["totais_proventos_pdf"] = {"total": float(t["total"])}
            except Exception as e:
                linhas_erros.append({
                    "arquivo": arq_sel, "competencia": comp_sel, "pagina": page_info["page_number"],
                    "etapa": "TOTALIZADOR_RESUMO", "resumo_id": resumo_id,
                    "erro": f"{type(e).__name__}: {e}"
                })

        # ---------- Eventos ----------
        if layout == "ANALITICO":
            try:
                with pdfplumber.open(io.BytesIO(index[arq_sel]["bytes"])) as pdf2:
                    page_obj = pdf2.pages[idx]
                    if pagina_eh_de_bases(page_obj):
                        continue
                    dados[comp_sel]["eventos"].extend(extrair_eventos_page(page_obj))
            except Exception as e:
                linhas_erros.append({
                    "arquivo": arq_sel, "competencia": comp_sel, "pagina": page_info["page_number"],
                    "etapa": "EVENTOS_ANALITICO", "resumo_id": resumo_id,
                    "erro": f"{type(e).__name__}: {e}"
                })
        else:
            try:
                ev = extrair_eventos_resumo_texto(texto_pagina)
                if ev:
                    dados[comp_sel]["eventos"].extend(ev)
            except Exception as e:
                linhas_erros.append({
                    "arquivo": arq_sel, "competencia": comp_sel, "pagina": page_info["page_number"],
                    "etapa": "EVENTOS_RESUMO", "resumo_id": resumo_id,
                    "erro": f"{type(e).__name__}: {e}"
                })

    # ---------- Por competência (do bloco) ----------
    for comp, info in dados.items():
        df = pd.DataFrame(info["eventos"])
        if df.empty:
            linhas_resumo.append({
                "arquivo": arq_sel,
                "competencia": comp,
                "resumo_id": resumo_id,
                "layout": layout,
                "grupo": "",
                "status": "SEM_EVENTOS",
                "semaforo": "🟡",
                "familia_layout": assin["familia_layout"],
                "sistema_provavel": assin["sistema_provavel"],
                "confianca_assinatura": assin["confianca"],
                "evidencias_assinatura": ", ".join(assin["evidencias"]),
            })
            return

        # garante colunas
        for c in ["rubrica", "tipo", "quantidade", "referencia", "ativos", "desligados", "total"]:
            if c not in df.columns:
                df[c] = 0.0 if c in ("ativos", "desligados", "total") else None

        df["rubrica"] = df["rubrica"].astype(str)
        df["tipo"] = df["tipo"].astype(str)

        for col in ["ativos", "desligados", "total"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        if "quantidade" in df.columns:
            df["quantidade"] = pd.to_numeric(df["quantidade"], errors="coerce")
        if "referencia" in df.columns:
            df["referencia"] = pd.to_numeric(df["referencia"], errors="coerce")

        df = df.drop_duplicates(subset=["rubrica", "tipo", "ativos", "desligados", "total"]).reset_index(drop=True)

        try:
            _, df = calcular_base_por_grupo(df)
        except Exception:
            pass
        df = _safe_classificacao(df)

        base_of = info.get("base_empresa")

        # PROVENTOS
        prov = df[df["tipo"] == "PROVENTO"].copy()
        tot_extraido = {
            "ativos": float(prov["ativos"].sum()),
            "desligados": float(prov["desligados"].sum()),
            "total": float(prov["total"].sum()),
        }

        # totalizador usado
        if layout != "ANALITICO":
            tot_pdf = info.get("totais_proventos_pdf")
            totais_usados = tot_pdf if (isinstance(tot_pdf, dict) and tot_pdf.get("total") is not None) else {"total": float(prov["total"].sum())}
        else:
            tot_pdf = info.get("totais_proventos_pdf")
            totais_usados = tot_pdf if tot_pdf else tot_extraido

        totalizador_encontrado = bool(info.get("totais_proventos_pdf"))
        bate_totalizador = None
        dif_totalizador_ativos = None
        dif_totalizador_desligados = None
        dif_totalizador_total = None

        if layout == "ANALITICO" and isinstance(info.get("totais_proventos_pdf"), dict):
            tot_pdf = info["totais_proventos_pdf"]
            dif_totalizador_ativos = float(tot_pdf.get("ativos", 0.0) - tot_extraido["ativos"])
            dif_totalizador_desligados = float(tot_pdf.get("desligados", 0.0) - tot_extraido["desligados"])
            bate_totalizador = (
                abs(dif_totalizador_ativos) <= tol_totalizador and
                abs(dif_totalizador_desligados) <= tol_totalizador
            )
        elif layout != "ANALITICO" and isinstance(info.get("totais_proventos_pdf"), dict):
            dif_totalizador_total = float(info["totais_proventos_pdf"].get("total", 0.0) - tot_extraido["total"])

        # dump eventos
        df_dump = df.copy()
        df_dump.insert(0, "arquivo", arq_sel)
        df_dump.insert(1, "competencia", comp)
        df_dump.insert(2, "resumo_id", resumo_id)
        df_dump["layout"] = layout
        df_dump["familia_layout"] = assin["familia_layout"]
        df_dump["sistema_provavel"] = assin["sistema_provavel"]
        eventos_dump.append(df_dump)

        # mapa
        if mapa_incidencia_on:
            grupos = ["ativos", "desligados"] if layout == "ANALITICO" else ["total"]
            for g in grupos:
                prov_total_g = float(totais_usados.get(g, 0.0) or 0.0)
                if prov_total_g <= 0:
                    continue
                prov_total_g = round(prov_total_g, 2)

                tmp = df[df["tipo"] == "PROVENTO"].copy()
                if g not in tmp.columns:
                    continue

                agg = (
                    tmp.groupby(["rubrica", "classificacao"], as_index=False)[g]
                    .sum()
                    .rename(columns={g: "valor"})
                )
                agg = agg[agg["valor"] != 0].copy()
                if agg.empty:
                    continue

                agg["valor"] = pd.to_numeric(agg["valor"], errors="coerce").fillna(0.0).round(2)
                agg["impacto_pct_proventos"] = (agg["valor"] / prov_total_g) * 100.0
                agg["impacto_pct_proventos"] = agg["impacto_pct_proventos"].round(6)

                agg.insert(0, "arquivo", arq_sel)
                agg.insert(1, "competencia", comp)
                agg.insert(2, "resumo_id", resumo_id)
                agg.insert(3, "grupo", ("ATIVOS" if g == "ativos" else "DESLIGADOS" if g == "desligados" else "GLOBAL"))
                agg.insert(4, "proventos_grupo", prov_total_g)
                agg["layout"] = layout
                agg["familia_layout"] = assin["familia_layout"]
                agg["sistema_provavel"] = assin["sistema_provavel"]

                linhas_mapa.extend(agg.to_dict(orient="records"))

        # auditoria
        grupos_auditar = ["ativos", "desligados"] if layout == "ANALITICO" else ["total"]
        for g in grupos_auditar:
            try:
                res = auditoria_por_exclusao_com_aproximacao(
                    df=df,
                    base_oficial=base_of,
                    totais_proventos=totais_usados,
                    grupo=g,
                    top_n_subset=44
                )
            except Exception as e:
                linhas_erros.append({
                    "arquivo": arq_sel, "competencia": comp, "pagina": None,
                    "etapa": f"AUDITORIA_{g}", "resumo_id": resumo_id,
                    "erro": f"{type(e).__name__}: {e}"
                })
                continue

            proventos_g = float(totais_usados.get(g, 0.0) or 0.0)
            proventos_g = round(proventos_g, 2)

            # base oficial por grupo
            if not base_of:
                base_of_g = None
            else:
                base_of_g = base_of.get(g) if isinstance(base_of, dict) else None
                if base_of_g is None and isinstance(base_of, dict):
                    base_of_g = base_of.get("total")

            indice_incidencia = None
            gap_bruto = None
            if indice_incidencia_on and base_of_g is not None and proventos_g > 0:
                base_of_gf = float(base_of_g)
                indice_incidencia = base_of_gf / proventos_g
                gap_bruto = proventos_g - base_of_gf

            erro = res.get("erro_por_baixo")
            erro_abs = None if erro is None else abs(float(erro))

            if not base_of:
                status = "INCOMPLETO_BASE"
            elif layout == "ANALITICO" and totalizador_encontrado and bate_totalizador is False:
                status = "FALHA_EXTRACAO_TOTALIZADOR"
            elif erro_abs is None:
                status = "SEM_ERRO"
            elif erro_abs <= banda_ok:
                status = "OK"
            elif erro_abs <= banda_aceitavel:
                status = "ACEITAVEL"
            else:
                status = "RUIM"

            grupo_label = ("ATIVOS" if g == "ativos" else "DESLIGADOS" if g == "desligados" else "GLOBAL")

            linhas_resumo.append({
                "arquivo": arq_sel,
                "competencia": comp,
                "resumo_id": resumo_id,
                "layout": layout,
                "grupo": grupo_label,

                "totalizador_encontrado": totalizador_encontrado,
                "bate_totalizador": bate_totalizador,
                "dif_totalizador_ativos": dif_totalizador_ativos,
                "dif_totalizador_desligados": dif_totalizador_desligados,
                "dif_totalizador_total": dif_totalizador_total,

                "proventos_grupo": proventos_g,
                "base_oficial": (round(float(base_of_g), 2) if base_of_g is not None else None),

                "indice_incidencia": indice_incidencia,
                "gap_bruto_prov_menos_base": gap_bruto,

                "base_exclusao": res.get("base_exclusao"),
                "gap": res.get("gap"),
                "base_aprox_por_baixo": res.get("base_aprox_por_baixo"),
                "erro_por_baixo": erro,

                "status": status,
                "semaforo": semaforo(status),

                "familia_layout": assin["familia_layout"],
                "sistema_provavel": assin["sistema_provavel"],
                "confianca_assinatura": assin["confianca"],
                "evidencias_assinatura": ", ".join(assin["evidencias"]),
            })

            devolvidas = res.get("rubricas_devolvidas")
            if devolvidas is not None and isinstance(devolvidas, pd.DataFrame) and not devolvidas.empty:
                for _, r in devolvidas.iterrows():
                    linhas_devolvidas.append({
                        "arquivo": arq_sel,
                        "competencia": comp,
                        "resumo_id": resumo_id,
                        "layout": layout,
                        "grupo": grupo_label,
                        "rubrica": r.get("rubrica"),
                        "classificacao_origem": r.get("classificacao"),
                        "valor": round(float(r.get("valor_alvo", 0.0) or 0.0), 2),
                        "familia_layout": assin["familia_layout"],
                        "sistema_provavel": assin["sistema_provavel"],
                    })

        # diagnóstico (somente analítico)
        if modo_auditor_prof and layout == "ANALITICO" and totalizador_encontrado and bate_totalizador is False:
            diag = diagnostico_extracao_proventos(df, tol_inconsistencia=max(1.0, tol_totalizador))
            if not diag.empty:
                dtop = diag.head(80).copy()
                dtop.insert(0, "arquivo", arq_sel)
                dtop.insert(1, "competencia", comp)
                dtop.insert(2, "resumo_id", resumo_id)
                dtop.insert(3, "layout", layout)
                dtop.insert(4, "familia_layout", assin["familia_layout"])
                dtop.insert(5, "sistema_provavel", assin["sistema_provavel"])
                linhas_diagnostico.extend(dtop.to_dict(orient="records"))

# Decide quais resumos processar
if resumo_sel == "(TODOS OS RESUMOS DO PERÍODO)":
    # Processa todos os blocos daquele período
    for rid, meta in resumos_dict.items():
        _processar_um_resumo(rid, meta["paginas_idx"])
else:
    meta = resumos_dict.get(resumo_sel)
    if not meta:
        st.warning("Resumo selecionado não encontrado no índice.")
        st.stop()
    _processar_um_resumo(resumo_sel, meta["paginas_idx"])

# ---------------------------
# DataFrames finais
# ---------------------------

df_resumo = pd.DataFrame(linhas_resumo)
df_devolvidas = pd.DataFrame(linhas_devolvidas)
df_diag = pd.DataFrame(linhas_diagnostico)
df_mapa = pd.DataFrame(linhas_mapa)
df_erros = pd.DataFrame(linhas_erros)
df_eventos = pd.concat(eventos_dump, ignore_index=True) if eventos_dump else pd.DataFrame()

if df_resumo.empty:
    st.warning("Nenhum dado consolidado foi gerado (verifique se a competência/resumo têm eventos).")
    st.stop()

# chaves p/ filtro
df_resumo["chave"] = df_resumo["arquivo"].astype(str) + "|" + df_resumo["competencia"].astype(str) + "|" + df_resumo["resumo_id"].astype(str) + "|" + df_resumo["grupo"].astype(str)
if not df_devolvidas.empty:
    df_devolvidas["chave"] = df_devolvidas["arquivo"].astype(str) + "|" + df_devolvidas["competencia"].astype(str) + "|" + df_devolvidas["resumo_id"].astype(str) + "|" + df_devolvidas["grupo"].astype(str)
if not df_mapa.empty:
    df_mapa["chave"] = df_mapa["arquivo"].astype(str) + "|" + df_mapa["competencia"].astype(str) + "|" + df_mapa["resumo_id"].astype(str) + "|" + df_mapa["grupo"].astype(str)
if not df_diag.empty:
    df_diag["chave_comp"] = df_diag["arquivo"].astype(str) + "|" + df_diag["competencia"].astype(str) + "|" + df_diag["resumo_id"].astype(str)

# ---------------------------
# Filtros globais (sidebar)
# ---------------------------

st.sidebar.divider()
st.sidebar.header("🔎 Filtros (resultado)")

familias = sorted(df_resumo["familia_layout"].dropna().unique().tolist())
sistemas = sorted(df_resumo["sistema_provavel"].dropna().unique().tolist())
layouts = sorted(df_resumo["layout"].dropna().unique().tolist())
status_opts = sorted(df_resumo["status"].dropna().unique().tolist())

fam_sel = st.sidebar.multiselect("Família (assinatura)", familias, default=familias)
sis_sel = st.sidebar.multiselect("Sistema provável", sistemas, default=sistemas)
lay_sel = st.sidebar.multiselect("Layout (detector)", layouts, default=layouts)
sta_sel = st.sidebar.multiselect("Status (auditoria)", status_opts, default=status_opts)

df_resumo_f = df_resumo[
    df_resumo["familia_layout"].isin(fam_sel) &
    df_resumo["sistema_provavel"].isin(sis_sel) &
    df_resumo["layout"].isin(lay_sel) &
    df_resumo["status"].isin(sta_sel)
].copy()

chaves_ok = set(df_resumo_f["chave"].dropna().tolist())

def _filtrar_por_chaves(df_any: pd.DataFrame) -> pd.DataFrame:
    if df_any is None or df_any.empty:
        return df_any
    if "chave" not in df_any.columns:
        return df_any
    return df_any[df_any["chave"].isin(chaves_ok)].copy()

df_devolvidas_f = _filtrar_por_chaves(df_devolvidas)
df_mapa_f = _filtrar_por_chaves(df_mapa)

# eventos: filtra por arquivo+competencia+resumo_id
if not df_eventos.empty:
    pares_ok = set(
        (r["arquivo"], r["competencia"], r["resumo_id"])
        for _, r in df_resumo_f[["arquivo", "competencia", "resumo_id"]].drop_duplicates().iterrows()
    )
    df_eventos_f = df_eventos[df_eventos.apply(lambda x: (x["arquivo"], x["competencia"], x["resumo_id"]) in pares_ok, axis=1)].copy()
else:
    df_eventos_f = df_eventos

# diag: filtra por arquivo+competencia+resumo_id
if not df_diag.empty:
    pares_ok2 = set(
        (r["arquivo"], r["competencia"], r["resumo_id"])
        for _, r in df_resumo_f[["arquivo", "competencia", "resumo_id"]].drop_duplicates().iterrows()
    )
    df_diag_f = df_diag[df_diag.apply(lambda x: (x["arquivo"], x["competencia"], x["resumo_id"]) in pares_ok2, axis=1)].copy()
else:
    df_diag_f = df_diag

# ---------------------------
# RADAR (filtrado)
# ---------------------------

df_radar = pd.DataFrame()
if radar_on and ((df_devolvidas_f is not None and not df_devolvidas_f.empty) or (df_mapa_f is not None and not df_mapa_f.empty)):
    base_periodos = df_resumo_f[df_resumo_f["grupo"].isin(["ATIVOS", "DESLIGADOS", "GLOBAL"])].copy()
    base_periodos["chave_periodo"] = (
        base_periodos["arquivo"].astype(str) + "|" +
        base_periodos["competencia"].astype(str) + "|" +
        base_periodos["resumo_id"].astype(str) + "|" +
        base_periodos["grupo"].astype(str)
    )
    tot_periodos = base_periodos.groupby("grupo")["chave_periodo"].nunique().to_dict()

    if df_devolvidas_f is not None and not df_devolvidas_f.empty:
        d = df_devolvidas_f.copy()
        d["chave_periodo"] = (
            d["arquivo"].astype(str) + "|" +
            d["competencia"].astype(str) + "|" +
            d["resumo_id"].astype(str) + "|" +
            d["grupo"].astype(str)
        )
        agg_dev = (
            d.groupby(["grupo", "rubrica"], as_index=False)
            .agg(
                meses_devolvida=("chave_periodo", "nunique"),
                valor_total_devolvido=("valor", "sum"),
                valor_medio_devolvido=("valor", "mean"),
                classificacao_mais_comum=("classificacao_origem", _mode_or_none),
            )
        )
        agg_dev["total_periodos_no_lote"] = agg_dev["grupo"].map(tot_periodos).fillna(0).astype(int)
        agg_dev["recorrencia_pct"] = agg_dev.apply(
            lambda r: (r["meses_devolvida"] / r["total_periodos_no_lote"] * 100.0) if r["total_periodos_no_lote"] > 0 else pd.NA,
            axis=1
        )
    else:
        agg_dev = pd.DataFrame(columns=[
            "grupo", "rubrica", "meses_devolvida", "valor_total_devolvido",
            "valor_medio_devolvido", "classificacao_mais_comum",
            "total_periodos_no_lote", "recorrencia_pct"
        ])

    if df_mapa_f is not None and not df_mapa_f.empty:
        m = df_mapa_f.copy()
        agg_mapa = (
            m.groupby(["grupo", "rubrica"], as_index=False)
            .agg(
                impacto_medio_pct=("impacto_pct_proventos", "mean"),
                impacto_max_pct=("impacto_pct_proventos", "max"),
                valor_medio=("valor", "mean"),
                classificacao_mapa_mais_comum=("classificacao", _mode_or_none),
            )
        )
    else:
        agg_mapa = pd.DataFrame(columns=[
            "grupo", "rubrica", "impacto_medio_pct", "impacto_max_pct",
            "valor_medio", "classificacao_mapa_mais_comum"
        ])

    df_radar = pd.merge(agg_dev, agg_mapa, on=["grupo", "rubrica"], how="outer")

    def _score(row):
        rec = row.get("recorrencia_pct")
        imp = row.get("impacto_medio_pct")
        if pd.isna(rec) or pd.isna(imp):
            return pd.NA
        return float(rec) * float(imp)

    df_radar["score_risco"] = df_radar.apply(_score, axis=1)

    for c in ["score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"]:
        if c not in df_radar.columns:
            df_radar[c] = pd.NA

    df_radar = df_radar.sort_values(
        ["score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"],
        ascending=[False, False, False, False],
        na_position="last"
    ).reset_index(drop=True)

# ---------------------------
# Abas
# ---------------------------

tab_resumo, tab_eventos, tab_devolvidas, tab_mapa, tab_radar, tab_diag, tab_erros = st.tabs(
    ["📌 Resumo", "📋 Eventos", "🧩 Devolvidas", "🧭 Mapa", "📡 Radar", "🕵️ Diagnóstico", "⚠️ Erros"]
)

with tab_resumo:
    st.subheader("📌 Resumo consolidado (filtrado) — Semáforo 🟢🟡🔴")
    df_show = df_resumo_f.sort_values(["competencia", "resumo_id", "arquivo", "layout", "grupo"]).copy()
    cols_front = ["semaforo", "status", "competencia", "resumo_id", "arquivo", "layout", "grupo", "proventos_grupo", "base_oficial", "erro_por_baixo"]
    cols_front = [c for c in cols_front if c in df_show.columns]
    df_show = df_show[cols_front + [c for c in df_show.columns if c not in cols_front]]
    st.dataframe(_styler_semaforo(df_show), use_container_width=True)

with tab_eventos:
    st.subheader("📋 Eventos extraídos (filtrado)")
    if df_eventos_f.empty:
        st.info("Sem eventos para os filtros selecionados.")
    else:
        st.dataframe(df_eventos_f.head(7000), use_container_width=True)

with tab_devolvidas:
    st.subheader("🧩 Rubricas devolvidas (filtrado)")
    if df_devolvidas_f is None or df_devolvidas_f.empty:
        st.info("Nenhuma rubrica devolvida para os filtros selecionados.")
    else:
        st.dataframe(
            df_devolvidas_f.sort_values(["competencia", "resumo_id", "arquivo", "grupo", "valor"], ascending=[True, True, True, True, False]),
            use_container_width=True
        )

with tab_mapa:
    st.subheader("🧭 Mapa de Incidência (filtrado)")
    if df_mapa_f is None or df_mapa_f.empty:
        st.info("Mapa vazio para os filtros selecionados.")
    else:
        comps = sorted(df_mapa_f["competencia"].unique().tolist())
        resumos = sorted(df_mapa_f["resumo_id"].unique().tolist())
        grupos = sorted(df_mapa_f["grupo"].unique().tolist())

        colA, colB, colC, colD = st.columns(4)
        with colA:
            comp_pick = st.selectbox("Competência", comps, index=max(0, len(comps) - 1), key="map_comp")
        with colB:
            resumo_pick = st.selectbox("Resumo", resumos, index=0, key="map_resumo")
        with colC:
            grupo_pick = st.selectbox("Grupo", grupos, index=0, key="map_grupo")
        with colD:
            topn = st.number_input("Top N", min_value=10, max_value=500, value=50, step=10, key="map_topn")

        class_opts = sorted(df_mapa_f["classificacao"].unique().tolist())
        class_sel = st.multiselect("Classificação", class_opts, default=class_opts, key="map_class")

        view = df_mapa_f[
            (df_mapa_f["competencia"] == comp_pick) &
            (df_mapa_f["resumo_id"] == resumo_pick) &
            (df_mapa_f["grupo"] == grupo_pick) &
            (df_mapa_f["classificacao"].isin(class_sel))
        ].copy()

        view = view.sort_values(["impacto_pct_proventos", "valor"], ascending=[False, False]).head(int(topn))
        st.dataframe(
            view[["rubrica", "classificacao", "valor", "impacto_pct_proventos", "proventos_grupo", "arquivo", "layout", "resumo_id"]],
            use_container_width=True
        )

with tab_radar:
    st.subheader("📡 Radar Estrutural (filtrado)")
    if df_radar.empty:
        st.info("Radar vazio para os filtros selecionados (precisa de devolvidas e/ou mapa).")
    else:
        grupos = sorted(df_radar["grupo"].dropna().unique().tolist())
        colA, colB, colC = st.columns(3)
        with colA:
            g_sel = st.selectbox("Grupo", grupos, index=0, key="rad_grupo")
        with colB:
            min_rec = st.slider("Recorrência mínima (%)", min_value=0, max_value=100, value=30, step=5, key="rad_minrec")
        with colC:
            topn = st.number_input("Top N (Radar)", min_value=10, max_value=500, value=50, step=10, key="rad_topn")

        v = df_radar[df_radar["grupo"] == g_sel].copy()
        for c in ["recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido", "score_risco",
                  "classificacao_mais_comum", "classificacao_mapa_mais_comum",
                  "meses_devolvida", "total_periodos_no_lote", "impacto_max_pct", "valor_medio_devolvido"]:
            if c not in v.columns:
                v[c] = pd.NA

        v = v[v["recorrencia_pct"].fillna(0) >= float(min_rec)]

        foco = st.multiselect(
            "Foco por classificação (origem devolvida / mapa)",
            options=["FORA", "NEUTRA", "ENTRA", "SEM_CLASSIFICACAO"],
            default=["FORA", "NEUTRA"],
            key="rad_foco"
        )

        def _match_foco(row):
            a = str(row.get("classificacao_mais_comum") or "")
            b = str(row.get("classificacao_mapa_mais_comum") or "")
            return (a in foco) or (b in foco)

        v = v[v.apply(_match_foco, axis=1)].copy()

        if v.empty:
            st.info("Nenhuma rubrica atende aos filtros do Radar.")
        else:
            v = v.sort_values(
                ["score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"],
                ascending=[False, False, False, False],
                na_position="last"
            ).head(int(topn))

            st.dataframe(
                v[[
                    "rubrica",
                    "classificacao_mais_comum",
                    "classificacao_mapa_mais_comum",
                    "meses_devolvida",
                    "total_periodos_no_lote",
                    "recorrencia_pct",
                    "impacto_medio_pct",
                    "impacto_max_pct",
                    "valor_total_devolvido",
                    "valor_medio_devolvido",
                    "score_risco",
                ]],
                use_container_width=True
            )

with tab_diag:
    st.subheader("🕵️ Diagnóstico (filtrado)")
    if df_diag_f is None or df_diag_f.empty:
        st.info("Sem diagnósticos para os filtros selecionados.")
    else:
        st.dataframe(df_diag_f, use_container_width=True)

with tab_erros:
    st.subheader("⚠️ Erros capturados (não derrubam o app)")
    if df_erros.empty:
        st.info("Nenhum erro foi capturado.")
    else:
        st.dataframe(df_erros, use_container_width=True)

# ---------------------------
# Excel consolidado (filtrado)
# ---------------------------

df_resumo_x = _round_cols(df_resumo_f, ["proventos_grupo", "base_oficial", "erro_por_baixo", "gap", "base_aprox_por_baixo"])
df_mapa_x = _round_cols(df_mapa_f, ["proventos_grupo", "valor"])
if df_mapa_x is not None and not df_mapa_x.empty and "impacto_pct_proventos" in df_mapa_x.columns:
    df_mapa_x["impacto_pct_proventos"] = pd.to_numeric(df_mapa_x["impacto_pct_proventos"], errors="coerce").round(6)

buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
    df_resumo_x.to_excel(writer, index=False, sheet_name="Resumo_Filtrado")
    df_eventos_f.to_excel(writer, index=False, sheet_name="Eventos_Filtrados")
    (df_devolvidas_f if df_devolvidas_f is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Devolvidas_Filtradas")
    (df_mapa_x if df_mapa_x is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Mapa_Filtrado")
    df_radar.to_excel(writer, index=False, sheet_name="Radar_Filtrado")
    (df_diag_f if df_diag_f is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Diag_Filtrado")
    df_erros.to_excel(writer, index=False, sheet_name="Erros")

buffer.seek(0)
st.download_button(
    "📥 Baixar Excel (dados filtrados)",
    data=buffer,
    file_name="AUDITOR_INSS_HIBRIDO_FILTRADO.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
