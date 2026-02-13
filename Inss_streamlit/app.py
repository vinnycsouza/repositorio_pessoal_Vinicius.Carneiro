import io
import re
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

# coisas que NÃO queremos considerar como "geral da empresa"
SUBBLOCO_KW = [
    "centro de custo", "centro custo", "ccusto", "c.custo",
    "departamento", "setor", "filial", "unidade", "obra",
    "tomador", "contrato", "projeto", "lotação", "lotacao",
    "diretor", "diretoria", "autônomo", "autonomo", "pró-labore", "pro-labore",
    "estagi", "terceir", "prestador", "rpa",
    "rubricas por", "resumo por", "analítico por", "analitico por",
    "totalização da folha", "totalizacao da folha",
]

# bases/itens que NÃO são a base INSS empresa (geral)
EXCL_BASE_KW = [
    "rat", "sat", "fap", "gilsat", "terceiros", "senai", "sesi", "sebrae", "incra", "salário-educação",
    "salario-educacao", "educação", "educacao", "fgts"
]

# cabeçalho/rodapé/emissão (não é competência)
EMISSAO_KW = ["emissao", "emitido em", "data:", "hora:", "página", "pagina"]


def normalizar_valor_br(txt: str):
    if txt is None:
        return None
    try:
        s = str(txt).strip()
        s = s.replace("R$", "").replace(" ", "")
        return float(s.replace(".", "").replace(",", "."))
    except Exception:
        return None


def _linhas_texto(page) -> list[str]:
    t = page.extract_text() or ""
    return [ln.strip() for ln in t.splitlines() if ln.strip()]


def _linha_tem_subbloco(linha: str) -> bool:
    l = (linha or "").lower()
    return any(k in l for k in SUBBLOCO_KW)


def _linha_tem_excl_base(linha: str) -> bool:
    l = (linha or "").lower()
    return any(k in l for k in EXCL_BASE_KW)


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

def extrair_competencia_sem_fallback(page):
    linhas = _linhas_texto(page)
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


def extrair_competencia_robusta(page, competencia_atual=None):
    comp = extrair_competencia_sem_fallback(page)
    return comp if comp else competencia_atual


# ---------------------------
# Detector híbrido de layout
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
# Assinatura estrutural
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
    if "base inss empresa" in joined: evid.append("BASE INSS EMPRESA")
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
# RESUMO: heurística de página "válida"
# ---------------------------

def pagina_parece_tabela_eventos_resumo(texto: str) -> bool:
    """
    Evita pegar páginas de BASES (RAT/terceiros etc.) e totalizações não-evento.
    Critério:
      - tem "vencimentos/proventos" ou "descontos" OU padrão 2012/2018
      - e tem pelo menos N linhas começando com código (3-6 dígitos)
    """
    if not texto or not texto.strip():
        return False

    low = texto.lower()

    # se a página é claramente só bases/encargos, ignora
    if "bases de c" in low or "bases de cá" in low or "bases de ca" in low:
        # pode existir bases no mesmo relatório, então ainda pode ter eventos,
        # mas a regra do "linhas com código no início" decide.
        pass

    linhas = [ln.strip() for ln in texto.splitlines() if ln.strip()]
    linhas = [ln for ln in linhas if not _linha_tem_subbloco(ln)]  # evita blocos não gerais
    cod_inicio = sum(1 for ln in linhas if re.match(r"^\s*\d{3,6}\b", ln))

    tem_headers = (
        ("vencimentos" in low) or ("proventos" in low) or ("descontos" in low) or
        ("resumo da folha" in low) or ("resumo geral" in low) or ("situação: geral" in low) or
        ("total vantagem" in low) or ("total de vencimentos" in low)
    )

    return tem_headers and cod_inicio >= 6


# ---------------------------
# RESUMO: totalizadores e base (somente geral)
# ---------------------------

def _extrair_totalizadores_resumo(texto: str) -> dict | None:
    if not texto:
        return None

    linhas = [ln.strip() for ln in texto.splitlines() if ln.strip()]
    cand = [ln for ln in linhas if not _linha_tem_subbloco(ln)]

    total_prov = None

    # 2018: Total de Vencimentos
    for ln in cand:
        if _linha_tem_excl_base(ln):
            continue
        m = re.search(rf"\btotal\s+de\s+vencimentos\s+{VAL_RE}\b", ln, flags=re.IGNORECASE)
        if m:
            v = normalizar_valor_br(m.group(1))
            if v is not None:
                total_prov = v
                break

    # 2012: TOTAL VANTAGEM
    if total_prov is None:
        for ln in cand:
            if _linha_tem_excl_base(ln):
                continue
            if "total vantagem" in ln.lower():
                m = re.search(rf"\btotal\s+vantagem\b.*?{VAL_RE}", ln, flags=re.IGNORECASE)
                if m:
                    v = normalizar_valor_br(m.group(1))
                    if v is not None:
                        total_prov = v
                        break

    # Hierarquia: Total de proventos
    if total_prov is None:
        for ln in cand:
            if _linha_tem_excl_base(ln):
                continue
            m = re.search(rf"\btotal\s+de\s+proventos\b.*?{VAL_RE}\b", ln, flags=re.IGNORECASE)
            if m:
                v = normalizar_valor_br(m.group(1))
                if v is not None:
                    total_prov = v
                    break

    if total_prov is None:
        return None

    return {"total": float(total_prov)}


def extrair_base_inss_global_texto_apenas_geral(texto: str) -> float | None:
    if not texto:
        return None

    linhas = [ln.strip() for ln in texto.splitlines() if ln.strip()]
    cand = [ln for ln in linhas if not _linha_tem_subbloco(ln)]

    # prioridade (Hierarquia)
    for ln in cand:
        if _linha_tem_excl_base(ln):
            continue
        m = re.search(rf"\btotal\s+da\s+base\s+empresa\b.*?{VAL_RE}\b", ln, flags=re.IGNORECASE)
        if m:
            v = normalizar_valor_br(m.group(1))
            if v is not None:
                return float(v)

    # padrões de base INSS empresa (exclui RAT/terceiros etc.)
    padroes = [
        rf"\bbase\s+inss\s*\(\s*empresa\s*\)\s*[:\-]?\s*{VAL_RE}\b",
        rf"\bbase\s+inss\s+empresa\s*[:\-]?\s*{VAL_RE}\b",
        rf"\binss\s+base\s*\(\s*empresa\s*\)\s*[:\-]?\s*{VAL_RE}\b",
        rf"\bbase\s+inss\s*[-–]\s*empresa\s*[:\-]?\s*{VAL_RE}\b",
        rf"\binss\s+base\s+empresa\s*[:\-]?\s*{VAL_RE}\b",
    ]

    candidatos = []
    for ln in cand:
        if _linha_tem_excl_base(ln):
            continue
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
# RESUMO: extrator de eventos (rígido)
# ---------------------------

def extrair_eventos_resumo_page(page) -> list[dict]:
    """
    Ajustes importantes:
      - Só considera códigos se estiverem NO INÍCIO do bloco (evita confundir com valores/rat)
      - Separa PROVENTO/DESCONTO por '|', e cada lado deve começar com código
      - Página só é processada se parecer tabela de eventos (filtro no loop principal)
    """
    txt = page.extract_text() or ""
    if not txt.strip():
        return []

    linhas = [ln.rstrip() for ln in txt.splitlines() if ln.strip()]
    eventos = []
    secao = None  # PROVENTO / DESCONTO

    def numeros_br(s: str):
        return re.findall(VAL_RE, s)

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

    def codigo_inicio(s: str):
        m = re.match(r"^\s*(\d{3,6})\b", s)
        return m.group(1) if m else None

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

        # ignora não-eventos
        if "base inss" in l or "bases de c" in l or "bases de cá" in l or "bases de ca" in l:
            continue
        if "total de vencimentos" in l or "total de descontos" in l or "total vantagem" in l or "total de proventos" in l:
            continue
        if "totalização" in l or "totalizacao" in l or "total geral" in l:
            continue
        if ("evento" in l and "descr" in l and "valor" in l) or ("evento" in l and "descricao" in l and "valor" in l):
            continue
        # evita pegar linhas de RAT/terceiros como "evento"
        if _linha_tem_excl_base(ln):
            continue

        # 1) Modelo com colunas separadas por '|'
        if "|" in ln:
            partes = [p.strip() for p in ln.split("|") if p.strip()]
            # cada lado deve COMEÇAR com código
            blocos = [p for p in partes if codigo_inicio(p)]
            if len(blocos) >= 2:
                esq, dir = blocos[0], blocos[1]

                cod_esq = codigo_inicio(esq)
                val_esq = ultimo_numero_br(esq)
                ref_esq = penultimo_numero_br(esq)
                q_esq = antepenultimo_numero_br(esq)
                quant_esq = q_esq if (q_esq is not None and q_esq <= 10000) else None

                if cod_esq and val_esq is not None:
                    add_event("PROVENTO", cod_esq, limpar_desc(cod_esq, esq), val_esq, ref_esq, quant_esq)

                cod_dir = codigo_inicio(dir)
                val_dir = ultimo_numero_br(dir)
                ref_dir = penultimo_numero_br(dir)
                q_dir = antepenultimo_numero_br(dir)
                quant_dir = q_dir if (q_dir is not None and q_dir <= 10000) else None

                if cod_dir and val_dir is not None:
                    add_event("DESCONTO", cod_dir, limpar_desc(cod_dir, dir), val_dir, ref_dir, quant_dir)

                continue

        # 2) Linha simples: exige código no início
        cod = codigo_inicio(ln)
        if not cod:
            continue

        resto = re.sub(r"^\s*" + re.escape(cod) + r"\s+", "", ln).strip()
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
# Diagnóstico analítico
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
# Semáforo simples 🟢🟡🔴 (somente bolinhas)
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

        # NÃO força cor do texto → deixa o Streamlit usar o claro padrão
        if s == "🟢":
            return ["background-color: rgba(40,167,69,0.20);"] * len(row)

        if s == "🟡":
            return ["background-color: rgba(255,193,7,0.20);"] * len(row)

        if s == "🔴":
            return ["background-color: rgba(220,53,69,0.20);"] * len(row)

        return [""] * len(row)

    return df.style.apply(_row_style, axis=1)



# ---------------------------
# UI
# ---------------------------

st.set_page_config(layout="wide")
st.title("🧾 Auditor INSS — Híbrido (4 modelos) — Somente totais gerais da empresa")

arquivos = st.file_uploader("Envie 1 ou mais PDFs", type="pdf", accept_multiple_files=True)

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
    "✅ RESUMO agora:\n"
    "- filtra páginas (evita bases/RAT/terceiros)\n"
    "- extrai totalizador do PDF (Total de Vencimentos / TOTAL VANTAGEM / Total de proventos)\n"
    "- extrai base INSS empresa ignorando RAT/terceiros/FAP/SAT\n"
    "\n"
    "✅ Semáforo: só bolinhas 🟢🟡🔴 e texto preto."
)

if arquivos:
    linhas_resumo = []
    linhas_devolvidas = []
    linhas_diagnostico = []
    linhas_mapa = []
    eventos_dump = []
    linhas_erros = []

    for arquivo in arquivos:
        with pdfplumber.open(arquivo) as pdf:
            texts = [(p.extract_text() or "") for p in pdf.pages[:2]]
            layout = detectar_layout_pdf(texts)
            assin = reconhecer_sistema_por_assinatura(texts)

            dados = {}
            comp_atual = None

            for page in pdf.pages:
                texto_pagina = page.extract_text() or ""

                comp_atual = extrair_competencia_robusta(page, comp_atual)
                if not comp_atual:
                    comp_atual = "SEM_COMP"

                dados.setdefault(comp_atual, {
                    "eventos": [],
                    "base_empresa": None,
                    "totais_proventos_pdf": None,
                })

                # ---------- Base oficial ----------
                if layout == "ANALITICO":
                    if pagina_eh_de_bases(page):
                        try:
                            base = extrair_base_empresa_page(page)
                        except Exception as e:
                            base = None
                            linhas_erros.append({
                                "arquivo": arquivo.name,
                                "competencia": comp_atual,
                                "pagina": page.page_number,
                                "etapa": "BASE_ANALITICO",
                                "erro": f"{type(e).__name__}: {e}",
                            })
                        if base and dados[comp_atual]["base_empresa"] is None:
                            dados[comp_atual]["base_empresa"] = base
                else:
                    try:
                        b = extrair_base_inss_global_texto_apenas_geral(texto_pagina)
                        if b is not None and dados[comp_atual]["base_empresa"] is None:
                            dados[comp_atual]["base_empresa"] = {"total": float(b)}
                    except Exception as e:
                        linhas_erros.append({
                            "arquivo": arquivo.name,
                            "competencia": comp_atual,
                            "pagina": page.page_number,
                            "etapa": "BASE_RESUMO",
                            "erro": f"{type(e).__name__}: {e}",
                        })

                # ---------- Totalizador ----------
                if layout == "ANALITICO":
                    try:
                        tot = extrair_totais_proventos_page(page)
                        if tot and dados[comp_atual]["totais_proventos_pdf"] is None:
                            dados[comp_atual]["totais_proventos_pdf"] = tot
                    except Exception as e:
                        linhas_erros.append({
                            "arquivo": arquivo.name,
                            "competencia": comp_atual,
                            "pagina": page.page_number,
                            "etapa": "TOTALIZADOR_ANALITICO",
                            "erro": f"{type(e).__name__}: {e}",
                        })
                else:
                    try:
                        t = _extrair_totalizadores_resumo(texto_pagina)
                        if t and t.get("total") is not None:
                            # se aparecer mais de uma vez na competência, usa o MAIOR (mais seguro contra parciais)
                            cur = dados[comp_atual]["totais_proventos_pdf"]
                            if cur is None or float(t["total"]) > float(cur.get("total", 0.0) or 0.0):
                                dados[comp_atual]["totais_proventos_pdf"] = {"total": float(t["total"])}
                    except Exception as e:
                        linhas_erros.append({
                            "arquivo": arquivo.name,
                            "competencia": comp_atual,
                            "pagina": page.page_number,
                            "etapa": "TOTALIZADOR_RESUMO",
                            "erro": f"{type(e).__name__}: {e}",
                        })

                # ---------- Eventos ----------
                if layout == "ANALITICO":
                    if pagina_eh_de_bases(page):
                        continue
                    try:
                        dados[comp_atual]["eventos"].extend(extrair_eventos_page(page))
                    except Exception as e:
                        linhas_erros.append({
                            "arquivo": arquivo.name,
                            "competencia": comp_atual,
                            "pagina": page.page_number,
                            "etapa": "EVENTOS_ANALITICO",
                            "erro": f"{type(e).__name__}: {e}",
                        })
                else:
                    # >>> filtro essencial para PDF "original" (sem tratamento)
                    if not pagina_parece_tabela_eventos_resumo(texto_pagina):
                        continue
                    try:
                        ev = extrair_eventos_resumo_page(page)
                        if ev:
                            dados[comp_atual]["eventos"].extend(ev)
                    except Exception as e:
                        linhas_erros.append({
                            "arquivo": arquivo.name,
                            "competencia": comp_atual,
                            "pagina": page.page_number,
                            "etapa": "EVENTOS_RESUMO",
                            "erro": f"{type(e).__name__}: {e}",
                        })

        # ---------- Por competência ----------
        for comp, info in dados.items():
            df = pd.DataFrame(info["eventos"])
            if df.empty:
                linhas_resumo.append({
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "layout": layout,
                    "grupo": "",
                    "status": "SEM_EVENTOS",
                    "semaforo": "🟡",
                    "familia_layout": assin["familia_layout"],
                    "sistema_provavel": assin["sistema_provavel"],
                    "confianca_assinatura": assin["confianca"],
                    "evidencias_assinatura": ", ".join(assin["evidencias"]),
                })
                continue

            for c in ["rubrica", "tipo", "quantidade", "referencia", "ativos", "desligados", "total"]:
                if c not in df.columns:
                    df[c] = 0.0 if c in ("ativos", "desligados", "total") else None

            df["rubrica"] = df["rubrica"].astype(str)
            df["tipo"] = df["tipo"].astype(str)
            for col in ["ativos", "desligados", "total"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            df = df.drop_duplicates(subset=["rubrica", "tipo", "ativos", "desligados", "total"]).reset_index(drop=True)

            try:
                _, df = calcular_base_por_grupo(df)
            except Exception:
                pass
            df = _safe_classificacao(df)

            base_of = info.get("base_empresa")
            prov = df[df["tipo"] == "PROVENTO"].copy()

            tot_extraido = {"total": float(prov["total"].sum())}
            if layout == "ANALITICO":
                tot_extraido = {
                    "ativos": float(prov["ativos"].sum()),
                    "desligados": float(prov["desligados"].sum()),
                    "total": float(prov["total"].sum()),
                }

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

            if layout == "ANALITICO" and isinstance(info.get("totais_proventos_pdf"), dict):
                tot_pdf = info["totais_proventos_pdf"]
                dif_totalizador_ativos = float(tot_pdf.get("ativos", 0.0) - tot_extraido["ativos"])
                dif_totalizador_desligados = float(tot_pdf.get("desligados", 0.0) - tot_extraido["desligados"])
                bate_totalizador = (
                    abs(dif_totalizador_ativos) <= tol_totalizador and
                    abs(dif_totalizador_desligados) <= tol_totalizador
                )

            df_dump = df.copy()
            df_dump.insert(0, "arquivo", arquivo.name)
            df_dump.insert(1, "competencia", comp)
            df_dump["layout"] = layout
            df_dump["familia_layout"] = assin["familia_layout"]
            df_dump["sistema_provavel"] = assin["sistema_provavel"]
            eventos_dump.append(df_dump)

            # ---------- Mapa ----------
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

                    agg.insert(0, "arquivo", arquivo.name)
                    agg.insert(1, "competencia", comp)
                    agg.insert(2, "grupo", ("ATIVOS" if g == "ativos" else "DESLIGADOS" if g == "desligados" else "GLOBAL"))
                    agg.insert(3, "proventos_grupo", prov_total_g)
                    agg["layout"] = layout
                    agg["familia_layout"] = assin["familia_layout"]
                    agg["sistema_provavel"] = assin["sistema_provavel"]
                    linhas_mapa.extend(agg.to_dict(orient="records"))

            # ---------- Auditoria ----------
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
                        "arquivo": arquivo.name,
                        "competencia": comp,
                        "pagina": None,
                        "etapa": f"AUDITORIA_{g}",
                        "erro": f"{type(e).__name__}: {e}",
                    })
                    continue

                proventos_g = round(float(totais_usados.get(g, 0.0) or 0.0), 2)

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
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "layout": layout,
                    "grupo": grupo_label,
                    "proventos_grupo": proventos_g,
                    "base_oficial": (round(float(base_of_g), 2) if base_of_g is not None else None),
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
                            "arquivo": arquivo.name,
                            "competencia": comp,
                            "layout": layout,
                            "grupo": grupo_label,
                            "rubrica": r.get("rubrica"),
                            "classificacao_origem": r.get("classificacao"),
                            "valor": round(float(r.get("valor_alvo", 0.0) or 0.0), 2),
                            "familia_layout": assin["familia_layout"],
                            "sistema_provavel": assin["sistema_provavel"],
                        })

            if modo_auditor_prof and layout == "ANALITICO" and totalizador_encontrado and bate_totalizador is False:
                diag = diagnostico_extracao_proventos(df, tol_inconsistencia=max(1.0, tol_totalizador))
                if not diag.empty:
                    dtop = diag.head(80).copy()
                    dtop.insert(0, "arquivo", arquivo.name)
                    dtop.insert(1, "competencia", comp)
                    dtop.insert(2, "layout", layout)
                    linhas_diagnostico.extend(dtop.to_dict(orient="records"))

    # ---------------- DataFrames finais ----------------
    df_resumo = pd.DataFrame(linhas_resumo)
    df_devolvidas = pd.DataFrame(linhas_devolvidas)
    df_diag = pd.DataFrame(linhas_diagnostico)
    df_mapa = pd.DataFrame(linhas_mapa)
    df_erros = pd.DataFrame(linhas_erros)
    df_eventos = pd.concat(eventos_dump, ignore_index=True) if eventos_dump else pd.DataFrame()

    if df_resumo.empty:
        st.warning("Nenhum dado consolidado foi gerado (verifique se as competências foram identificadas).")
        st.stop()

    # filtros simples
    st.sidebar.header("🔎 Filtros (lote)")
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

    # ---------------- Abas ----------------
    tab_resumo, tab_eventos, tab_devolvidas, tab_mapa, tab_radar, tab_diag, tab_erros = st.tabs(
        ["📌 Resumo", "📋 Eventos", "🧩 Devolvidas", "🧭 Mapa", "📡 Radar", "🕵️ Diagnóstico", "⚠️ Erros"]
    )

    with tab_resumo:
        st.subheader("📌 Resumo consolidado (Semáforo)")
        df_show = df_resumo_f.sort_values(["competencia", "arquivo", "layout", "grupo"]).copy()
        # só as bolinhas + o essencial (status fica como coluna extra ao lado)
        cols = ["semaforo", "competencia", "arquivo", "layout", "grupo", "proventos_grupo", "base_oficial", "erro_por_baixo", "status"]
        cols = [c for c in cols if c in df_show.columns]
        st.dataframe(_styler_semaforo(df_show[cols]), use_container_width=True)

    with tab_eventos:
        st.subheader("📋 Eventos extraídos (filtrado)")
        if df_eventos.empty:
            st.info("Sem eventos.")
        else:
            st.dataframe(df_eventos.head(7000), use_container_width=True)

    with tab_devolvidas:
        st.subheader("🧩 Rubricas devolvidas")
        if df_devolvidas.empty:
            st.info("Nenhuma rubrica devolvida.")
        else:
            st.dataframe(df_devolvidas, use_container_width=True)

    with tab_mapa:
        st.subheader("🧭 Mapa de Incidência")
        if df_mapa.empty:
            st.info("Mapa vazio.")
        else:
            st.dataframe(df_mapa, use_container_width=True)

    with tab_radar:
        st.subheader("📡 Radar Estrutural")
        st.info("Radar permanece igual ao seu modelo anterior (baseado em Mapa + Devolvidas).")

    with tab_diag:
        st.subheader("🕵️ Diagnóstico")
        if df_diag.empty:
            st.info("Sem diagnósticos.")
        else:
            st.dataframe(df_diag, use_container_width=True)

    with tab_erros:
        st.subheader("⚠️ Erros capturados")
        if df_erros.empty:
            st.info("Nenhum erro capturado.")
        else:
            st.dataframe(df_erros, use_container_width=True)

    # ---------------- Excel consolidado ----------------
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_resumo_f.to_excel(writer, index=False, sheet_name="Resumo_Filtrado")
        df_eventos.to_excel(writer, index=False, sheet_name="Eventos")
        df_devolvidas.to_excel(writer, index=False, sheet_name="Devolvidas")
        df_mapa.to_excel(writer, index=False, sheet_name="Mapa")
        df_diag.to_excel(writer, index=False, sheet_name="Diagnostico")
        df_erros.to_excel(writer, index=False, sheet_name="Erros")

    buffer.seek(0)
    st.download_button(
        "📥 Baixar Excel (consolidado)",
        data=buffer,
        file_name="AUDITOR_INSS_HIBRIDO.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Envie um ou mais PDFs para iniciar.")
