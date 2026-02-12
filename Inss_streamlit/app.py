import io
import re
import pdfplumber
import pandas as pd
import streamlit as st

# Seus módulos (usados principalmente no layout analítico)
from extrator_pdf import extrair_eventos_page, extrair_base_empresa_page, pagina_eh_de_bases
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

# Aceita códigos 0001 e 00001 (2012 e 2018), mas NÃO aceita 3 dígitos (evita "908" virar código)
COD_RE = r"\b(0\d{3,4})\b"


def normalizar_valor_br(txt: str):
    if txt is None:
        return None
    try:
        s = str(txt).strip()
        s = s.replace("R$", "").replace(" ", "")
        return float(s.replace(".", "").replace(",", "."))
    except Exception:
        return None


def fmt_money(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    try:
        return f"R$ {float(v):,.2f}"
    except Exception:
        return "-"


def extrair_competencia_sem_fallback(page):
    """
    Muito importante para o 2018 anual:
    prioriza 'Mês/Ano: 01/2018' e evita capturar '29/11/2023' (data de emissão).
    """
    txt_raw = page.extract_text() or ""
    txt = txt_raw.lower()

    # 0) PRIORIDADE: "Mês/Ano: 12/2018" (ou "Mes/Ano")
    m = re.search(
        r"\b(m[eê]s\s*/\s*ano|mes\s*/\s*ano)\s*[:\-]?\s*(0?[1-9]|1[0-2])\s*/\s*(20\d{2})\b",
        txt,
        flags=re.IGNORECASE
    )
    if m:
        mm = m.group(2).zfill(2)
        aa = m.group(3)
        return f"{mm}/{aa}"

    # 1) 01/2021 (EVITA capturar 11/2023 dentro de 29/11/2023)
    m = re.search(r"(?<!\d/)\b(0?[1-9]|1[0-2])\s*/\s*(20\d{2})\b", txt)
    if m:
        mm = m.group(1).zfill(2)
        aa = m.group(2)
        return f"{mm}/{aa}"

    # 2) 01.2012 ou 01-2012
    m = re.search(r"(?<!\d[-.])\b(0?[1-9]|1[0-2])\s*[.\-]\s*(20\d{2})\b", txt)
    if m:
        mm = m.group(1).zfill(2)
        aa = m.group(2)
        return f"{mm}/{aa}"

    # 3) jan/21
    m = re.search(r"\b([a-zç]{3,9})\s*/\s*(\d{2})\b", txt)
    if m:
        mes_txt = m.group(1).replace("ç", "c")
        ano2 = m.group(2)
        if mes_txt in MESES:
            return f"{MESES[mes_txt]}/20{ano2}"

    # 4) janeiro 2021
    m = re.search(r"\b([a-zç]{3,9})\s+(20\d{2})\b", txt)
    if m:
        mes_txt = m.group(1).replace("ç", "c")
        aa = m.group(2)
        if mes_txt in MESES:
            return f"{MESES[mes_txt]}/{aa}"

    return None


def extrair_competencia_robusta(page, competencia_atual=None):
    comp = extrair_competencia_sem_fallback(page)
    return comp if comp else competencia_atual


def extrair_totais_proventos_page(page) -> dict | None:
    """
    Extrai TOTAIS PROVENTOS ativos desligados total (layout analítico).
    """
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
# Detector híbrido de layout
# ---------------------------

def detectar_layout_pdf(pages_text: list[str]) -> str:
    """
    Retorna: 'ANALITICO' | 'RESUMO'
    """
    joined = "\n".join([t for t in pages_text if t]).lower()

    # Evidência forte de analítico:
    if ("cod provento" in joined and "cod desconto" in joined and "ativos" in joined and "desligados" in joined):
        return "ANALITICO"
    if ("ativos" in joined and "desligados" in joined and "totais proventos" in joined):
        return "ANALITICO"

    # Evidência de resumo:
    if "resumo da folha" in joined:
        return "RESUMO"
    if "resumo geral" in joined:
        return "RESUMO"
    if ("vencimentos" in joined and "descontos" in joined and "base inss" in joined):
        return "RESUMO"
    if ("evento" in joined and "descr" in joined and "qtd" in joined and "valor" in joined):
        return "RESUMO"
    if ("situação" in joined or "situacao" in joined) and "geral" in joined and ("mês/ano" in joined or "mes/ano" in joined):
        return "RESUMO"

    return "RESUMO"


# ---------------------------
# Reconhecimento de sistema por assinatura estrutural
# ---------------------------

def _score_any(text: str, patterns: list[str]) -> int:
    return sum(1 for p in patterns if p in text)


def reconhecer_sistema_por_assinatura(pages_text: list[str]) -> dict:
    """
    Retorna:
    - familia_layout: 'ANALITICO_ESPELHADO' | 'RESUMO_EVENTO_QTD' | 'RESUMO_VENC_DESC_BASE' | 'DESCONHECIDO'
    - sistema_provavel: string amigável
    - confianca: 0-100
    - evidencias: lista curta
    """
    joined = "\n".join([t for t in pages_text if t]).lower()
    evid = []

    s_analitico = _score_any(joined, [
        "cod provento", "cod desconto", "ativos", "desligados", "totais proventos"
    ])
    s_evento_qtd = _score_any(joined, [
        "evento", "descr", "qtd", "refer", "valor"
    ])
    s_venc_desc = _score_any(joined, [
        "vencimentos", "descontos", "base inss", "base inss empresa", "mês/ano", "mes/ano", "situação", "situacao"
    ])

    scores = {
        "ANALITICO_ESPELHADO": s_analitico,
        "RESUMO_EVENTO_QTD": s_evento_qtd,
        "RESUMO_VENC_DESC_BASE": s_venc_desc,
    }
    familia = max(scores, key=scores.get)
    top = scores[familia]
    if top == 0:
        familia = "DESCONHECIDO"

    # evidências
    if "cod provento" in joined: evid.append("COD PROVENTO")
    if "cod desconto" in joined: evid.append("COD DESCONTO")
    if "ativos" in joined: evid.append("ATIVOS")
    if "desligados" in joined: evid.append("DESLIGADOS")
    if "totais proventos" in joined: evid.append("TOTAIS PROVENTOS")
    if "resumo da folha" in joined: evid.append("RESUMO DA FOLHA")
    if "resumo geral" in joined: evid.append("RESUMO GERAL")
    if "vencimentos" in joined: evid.append("VENCIMENTOS")
    if "descontos" in joined: evid.append("DESCONTOS")
    if "base inss empresa" in joined or "base inss (empresa)" in joined: evid.append("BASE INSS EMPRESA")
    if ("situação" in joined or "situacao" in joined) and "geral" in joined: evid.append("SITUAÇÃO GERAL")
    if "mês/ano" in joined or "mes/ano" in joined: evid.append("MÊS/ANO")

    if familia == "ANALITICO_ESPELHADO":
        sistema = "Domínio/Questor/Mastermaq (família analítica espelhada)"
        confianca = min(95, 60 + top * 10)
    elif familia == "RESUMO_EVENTO_QTD":
        sistema = "Senior/Alterdata/TOTVS (família resumo por evento)"
        confianca = min(90, 55 + top * 10)
    elif familia == "RESUMO_VENC_DESC_BASE":
        sistema = "TOTVS (Protheus/RM)/Senior (família vencimentos/descontos/base)"
        confianca = min(90, 55 + top * 10)
    else:
        sistema = "Não identificado"
        confianca = 10

    return {
        "familia_layout": familia,
        "sistema_provavel": sistema,
        "confianca": int(confianca),
        "evidencias": evid[:10],
        "scores": scores,
    }


# ---------------------------
# Filtros de páginas-alvo
# ---------------------------

def pagina_alvo_resumo_2012(page) -> bool:
    t = (page.extract_text() or "").lower()
    return ("resumo geral" in t and "folha" in t) or ("resumo geral de folha" in t)


def pagina_alvo_situacao_geral_2018(page) -> bool:
    t = (page.extract_text() or "").lower()
    return (("situação" in t) or ("situacao" in t)) and ("geral" in t) and (("mês/ano" in t) or ("mes/ano" in t))


# ---------------------------
# Extratores para layout RESUMO (GLOBAL)
# ---------------------------

def extrair_base_inss_global_texto(texto: str) -> float | None:
    """
    Encontra base INSS 'empresa' em PDFs de resumo.
    Heurística: maior candidato.
    """
    if not texto:
        return None

    txt = texto.replace("\n", " ")
    padroes = [
        r"\bbase\s+inss\s*\(?.{0,15}empresa.{0,15}\)?\s*[:\-]?\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})",
        r"\bbase\s+inss\s+empresa\s*[:\-]?\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})",
        r"\bbase\s+inss\s*[:\-]?\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})",
    ]

    candidatos = []
    for p in padroes:
        for m in re.finditer(p, txt, flags=re.IGNORECASE):
            v = normalizar_valor_br(m.group(1))
            if v is not None:
                candidatos.append(v)

    if not candidatos:
        return None

    return float(max(candidatos))


def extrair_quadros_2018(texto: str) -> dict:
    """
    Extrai (apenas para VISUAL) as bases por quadro na página de Situação: Geral.
    Ex.: Funcionários / Diretores / Autônomos.
    """
    t = (texto or "")
    low = t.lower()

    out = {"funcionarios": None, "diretores": None, "autonomos": None}

    def pick_base(bloco: str):
        m = re.search(
            r"base\s+inss.*?empresa.*?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})",
            bloco,
            flags=re.IGNORECASE
        )
        return normalizar_valor_br(m.group(1)) if m else None

    partes = re.split(r"totalizaç[aã]o\s+da\s+folha", low, flags=re.IGNORECASE)
    for p in partes[1:]:
        tag = "funcionarios"
        if "diretor" in p:
            tag = "diretores"
        elif "aut[oô]nomo" in p or "autonomo" in p:
            tag = "autonomos"
        b = pick_base(p)
        if b is not None:
            out[tag] = float(b)

    return out


def extrair_eventos_resumo_page(page) -> list[dict]:
    """
    Extrai eventos em RESUMO respeitando 2 colunas:
    - 2012: linhas com '|' separando PROVENTOS (esq) e DESCONTOS (dir)
    - 2018: 2 rubricas na mesma linha (sem '|'), com colunas (Referência / Valor)
    Saída:
      ativos = valor, desligados = 0, total = valor
      referencia = (se detectada) senão None
    """
    txt = page.extract_text() or ""
    if not txt.strip():
        return []

    linhas = [ln.rstrip() for ln in txt.splitlines() if ln.strip()]
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

    def primeiro_codigo(s: str):
        m = re.search(COD_RE, s)
        return m.group(1) if m else None

    def limpar_desc(cod: str, chunk: str):
        # remove o código do começo
        x = re.sub(r"^\s*" + re.escape(cod) + r"\s+", "", chunk).strip()
        # remove numéricos finais (ref/valor)
        nums = numeros_br(x)
        if nums:
            # remove o último número (valor)
            x = re.sub(re.escape(nums[-1]) + r"\s*$", "", x).strip()
            # e se ainda sobrar outro no fim (referência), remove também
            nums2 = numeros_br(x)
            if nums2:
                x = re.sub(re.escape(nums2[-1]) + r"\s*$", "", x).strip()
        x = re.sub(r"\s{2,}", " ", x)
        return x

    def add_event(tipo: str, cod: str, desc: str, valor: float, referencia: float | None):
        rubrica = f"{cod} {desc}".strip()
        eventos.append({
            "rubrica": rubrica,
            "tipo": tipo,
            "referencia": float(referencia) if referencia is not None else None,
            "ativos": float(valor),
            "desligados": 0.0,
            "total": float(valor),
        })

    def linha_deve_ignorar(lnlow: str) -> bool:
        # Evita totalizadores/cabeçalhos e blocos de base entrarem como "eventos"
        termos = [
            "resumo", "total geral", "totalização", "totalizacao",
            "base inss", "salario contribuicao", "salário contribuição",
            "situação", "situacao", "mês/ano", "mes/ano",
            "vencimentos", "descontos",
            "informações", "informacoes",
            "contribuições", "contribuicoes",
            "inss", "fgts"
        ]
        # mas NÃO bloqueia tudo com "inss" porque algumas rubricas podem ter "inss" no nome em outros modelos,
        # então usamos esse filtro só no resumo (funciona bem).
        return any(t in lnlow for t in termos)

    for ln in linhas:
        l = ln.lower()

        if "vencimentos" in l or "proventos" in l:
            secao = "PROVENTO"
            continue
        if "descontos" in l:
            secao = "DESCONTO"
            continue

        if linha_deve_ignorar(l):
            continue

        # Modelo com colunas separadas por '|'
        if "|" in ln:
            partes = [p.strip() for p in ln.split("|")]
            blocos = [p for p in partes if p and re.search(COD_RE, p)]
            if len(blocos) >= 2:
                esq, dir = blocos[0], blocos[1]

                cod_esq = primeiro_codigo(esq)
                val_esq = ultimo_numero_br(esq)
                ref_esq = penultimo_numero_br(esq)
                if cod_esq and val_esq is not None:
                    desc_esq = limpar_desc(cod_esq, esq)
                    add_event("PROVENTO", cod_esq, desc_esq, val_esq, ref_esq)

                cod_dir = primeiro_codigo(dir)
                val_dir = ultimo_numero_br(dir)
                ref_dir = penultimo_numero_br(dir)
                if cod_dir and val_dir is not None:
                    desc_dir = limpar_desc(cod_dir, dir)
                    add_event("DESCONTO", cod_dir, desc_dir, val_dir, ref_dir)
                continue
            elif len(blocos) == 1:
                ln = blocos[0]
                l = ln.lower()

        # Modelo “grudado”: 2 códigos na mesma linha
        cod_pos = []
        for m in re.finditer(COD_RE, ln):
            cod = m.group(1)
            cod_pos.append((cod, m.start()))
        cod_pos = sorted(cod_pos, key=lambda x: x[1])

        if len(cod_pos) >= 2:
            (cod1, p1), (cod2, p2) = cod_pos[0], cod_pos[1]
            chunk1 = ln[p1:p2].strip()
            chunk2 = ln[p2:].strip()

            v1 = ultimo_numero_br(chunk1)
            r1 = penultimo_numero_br(chunk1)

            v2 = ultimo_numero_br(chunk2)
            r2 = penultimo_numero_br(chunk2)

            if v1 is not None:
                add_event("PROVENTO", cod1, limpar_desc(cod1, chunk1), v1, r1)
            if v2 is not None:
                add_event("DESCONTO", cod2, limpar_desc(cod2, chunk2), v2, r2)
            continue

        # Linha simples (1 rubrica)
        m_cod = re.match(r"^\s*(0\d{3,4})\s+(.+)$", ln)
        if not m_cod:
            continue

        cod = m_cod.group(1)
        resto = m_cod.group(2)

        val = ultimo_numero_br(resto)
        if val is None:
            continue
        ref = penultimo_numero_br(resto)

        desc = limpar_desc(cod, f"{cod} {resto}")
        tipo = secao if secao in ("PROVENTO", "DESCONTO") else "PROVENTO"
        add_event(tipo, cod, desc, val, ref)

    return eventos


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
        "rubrica", "referencia", "ativos", "desligados", "total",
        "soma_partes", "delta_total_vs_partes",
        "flag_inconsistencia_total", "flag_total_sem_partes", "flag_partes_sem_total",
        "flag_rubrica_curta", "flag_rubrica_somente_num",
        "score_suspeita"
    ]
    cols_out = [c for c in cols_out if c in df.columns]
    return df[cols_out].sort_values(["score_suspeita", "delta_total_vs_partes", "total"], ascending=[False, False, False])


# ---------------------------
# UI
# ---------------------------

st.set_page_config(layout="wide")
st.title("🧾 Auditor INSS — Híbrido + Assinatura Estrutural (2012/2018 corrigidos)")

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
    modo_auditor_prof = st.checkbox("🕵️ Auditor Profissional", value=True)

indice_incidencia_on = st.checkbox("📈 Índice de Incidência", value=True)
mapa_incidencia_on = st.checkbox("🧭 Mapa de Incidência (impacto %)", value=True)
radar_on = st.checkbox("📡 Radar Estrutural Automático", value=True)
mostrar_referencia = st.checkbox("🔢 Mostrar coluna Referência nas tabelas", value=False)
painel_2018_on = st.checkbox("🏛 Painel estrutural 2018 (Situação: Geral)", value=True)

st.info(
    "✅ Detector Híbrido decide entre **ANALÍTICO** e **RESUMO**.\n"
    "✅ 2012: aceita códigos `0001` e 2018: `00001`.\n"
    "✅ 2018 anual: competência vem de **Mês/Ano**, e pages são filtradas por **Situação: Geral**.\n"
    "✅ 2012: pages são filtradas por **Resumo Geral de Folha**."
)

if arquivos:
    linhas_resumo = []
    linhas_devolvidas = []
    linhas_diagnostico = []
    linhas_mapa = []
    eventos_dump = []
    linhas_quadros_2018 = []

    for arquivo in arquivos:
        with pdfplumber.open(arquivo) as pdf:
            texts = [(p.extract_text() or "") for p in pdf.pages[:2]]
            layout = detectar_layout_pdf(texts)
            assin = reconhecer_sistema_por_assinatura(texts)

            # Heurística de filtro RESUMO por páginas-alvo
            filtro_2012 = any("RESUMO GERAL" in e for e in assin["evidencias"])
            filtro_2018 = any("SITUAÇÃO GERAL" in e for e in assin["evidencias"])

            dados = {}
            comp_atual = None

            for page in pdf.pages:
                # Filtros por assinatura
                if layout == "RESUMO":
                    if filtro_2012 and not pagina_alvo_resumo_2012(page):
                        continue
                    if filtro_2018 and not pagina_alvo_situacao_geral_2018(page):
                        continue

                comp_atual = extrair_competencia_robusta(page, comp_atual)
                if not comp_atual:
                    comp_atual = "SEM_COMP"

                dados.setdefault(comp_atual, {
                    "eventos": [],
                    "base_empresa": None,
                    "totais_proventos_pdf": None,
                    "quadros": None,
                })

                # Base oficial
                if layout == "ANALITICO":
                    if pagina_eh_de_bases(page):
                        base = extrair_base_empresa_page(page)
                        if base and dados[comp_atual]["base_empresa"] is None:
                            dados[comp_atual]["base_empresa"] = base
                else:
                    # RESUMO: tenta extrator padrão e também heurística texto
                    if dados[comp_atual]["base_empresa"] is None:
                        base = None
                        try:
                            base = extrair_base_empresa_page(page)
                        except Exception:
                            base = None

                        if base:
                            dados[comp_atual]["base_empresa"] = base
                        else:
                            b = extrair_base_inss_global_texto(page.extract_text() or "")
                            if b is not None:
                                dados[comp_atual]["base_empresa"] = {"total": float(b)}

                # Totalizador (apenas analítico)
                if layout == "ANALITICO":
                    tot = extrair_totais_proventos_page(page)
                    if tot and dados[comp_atual]["totais_proventos_pdf"] is None:
                        dados[comp_atual]["totais_proventos_pdf"] = tot

                # Painel estrutural 2018 (apenas visual)
                if painel_2018_on and layout == "RESUMO" and filtro_2018 and pagina_alvo_situacao_geral_2018(page):
                    quadros = extrair_quadros_2018(page.extract_text() or "")
                    # só salva se achou algo
                    if any(v is not None for v in quadros.values()):
                        dados[comp_atual]["quadros"] = quadros

                # Eventos
                if layout == "ANALITICO":
                    try:
                        dados[comp_atual]["eventos"].extend(extrair_eventos_page(page))
                    except Exception:
                        dados[comp_atual]["eventos"].extend(extrair_eventos_resumo_page(page))
                else:
                    dados[comp_atual]["eventos"].extend(extrair_eventos_resumo_page(page))

        # Por competência
        for comp, info in dados.items():
            df = pd.DataFrame(info["eventos"])
            if df.empty:
                linhas_resumo.append({
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "layout": layout,
                    "grupo": "",
                    "status": "SEM_EVENTOS",
                    "familia_layout": assin["familia_layout"],
                    "sistema_provavel": assin["sistema_provavel"],
                    "confianca_assinatura": assin["confianca"],
                    "evidencias_assinatura": ", ".join(assin["evidencias"]),
                })
                continue

            # garante colunas
            for c in ["rubrica", "tipo", "referencia", "ativos", "desligados", "total"]:
                if c not in df.columns:
                    df[c] = 0.0 if c in ("ativos", "desligados", "total") else None

            df["rubrica"] = df["rubrica"].astype(str)
            df["tipo"] = df["tipo"].astype(str)

            for col in ["ativos", "desligados", "total"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            # referencia opcional
            if "referencia" in df.columns:
                df["referencia"] = pd.to_numeric(df["referencia"], errors="coerce")

            # remove duplicados
            df = df.drop_duplicates(subset=["rubrica", "tipo", "ativos", "desligados", "total"]).reset_index(drop=True)

            try:
                _, df = calcular_base_por_grupo(df)
            except Exception:
                pass
            df = _safe_classificacao(df)

            base_of = info["base_empresa"]

            prov = df[df["tipo"] == "PROVENTO"].copy()
            tot_extraido = {
                "ativos": float(prov["ativos"].sum()),
                "desligados": float(prov["desligados"].sum()),
                "total": float(prov["total"].sum()),
            }

            if layout != "ANALITICO":
                totais_usados = {"total": float(prov["total"].sum())}
            else:
                tot_pdf = info.get("totais_proventos_pdf")
                totais_usados = tot_pdf if tot_pdf else tot_extraido

            # totalizador (somente analítico)
            totalizador_encontrado = bool(info.get("totais_proventos_pdf")) if layout == "ANALITICO" else False
            bate_totalizador = None
            dif_totalizador_ativos = None
            dif_totalizador_desligados = None
            if layout == "ANALITICO" and totalizador_encontrado:
                tot_pdf = info["totais_proventos_pdf"]
                dif_totalizador_ativos = float(tot_pdf["ativos"] - tot_extraido["ativos"])
                dif_totalizador_desligados = float(tot_pdf["desligados"] - tot_extraido["desligados"])
                bate_totalizador = (
                    abs(dif_totalizador_ativos) <= tol_totalizador and
                    abs(dif_totalizador_desligados) <= tol_totalizador
                )

            # dump eventos
            df_dump = df.copy()
            df_dump.insert(0, "arquivo", arquivo.name)
            df_dump.insert(1, "competencia", comp)
            df_dump["layout"] = layout
            df_dump["familia_layout"] = assin["familia_layout"]
            df_dump["sistema_provavel"] = assin["sistema_provavel"]
            eventos_dump.append(df_dump)

            # Quadros 2018 (visual)
            if painel_2018_on and isinstance(info.get("quadros"), dict):
                q = info["quadros"]
                linhas_quadros_2018.append({
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "funcionarios": q.get("funcionarios"),
                    "diretores": q.get("diretores"),
                    "autonomos": q.get("autonomos"),
                    "layout": layout,
                    "familia_layout": assin["familia_layout"],
                    "sistema_provavel": assin["sistema_provavel"]
                })

            # Mapa
            if mapa_incidencia_on:
                grupos = ["ativos", "desligados"] if layout == "ANALITICO" else ["total"]
                for g in grupos:
                    prov_total_g = float(totais_usados.get(g, 0.0) or 0.0)
                    if prov_total_g <= 0:
                        continue
                    tmp = df[df["tipo"] == "PROVENTO"].copy()
                    agg = (
                        tmp.groupby(["rubrica", "classificacao"], as_index=False)[g]
                        .sum()
                        .rename(columns={g: "valor"})
                    )
                    agg = agg[agg["valor"] != 0].copy()
                    if agg.empty:
                        continue
                    agg["impacto_pct_proventos"] = (agg["valor"] / prov_total_g) * 100.0
                    agg.insert(0, "arquivo", arquivo.name)
                    agg.insert(1, "competencia", comp)
                    agg.insert(2, "grupo", ("ATIVOS" if g == "ativos" else "DESLIGADOS" if g == "desligados" else "GLOBAL"))
                    agg.insert(3, "proventos_grupo", prov_total_g)
                    agg["layout"] = layout
                    agg["familia_layout"] = assin["familia_layout"]
                    agg["sistema_provavel"] = assin["sistema_provavel"]
                    linhas_mapa.extend(agg.to_dict(orient="records"))

            # Auditoria
            grupos_auditar = ["ativos", "desligados"] if layout == "ANALITICO" else ["total"]

            for g in grupos_auditar:
                res = auditoria_por_exclusao_com_aproximacao(
                    df=df,
                    base_oficial=base_of,
                    totais_proventos=totais_usados,
                    grupo=g,
                    top_n_subset=44
                )

                proventos_g = float(totais_usados.get(g, 0.0) or 0.0)

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
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "layout": layout,
                    "grupo": grupo_label,

                    "totalizador_encontrado": totalizador_encontrado,
                    "bate_totalizador": bate_totalizador,
                    "dif_totalizador_ativos": dif_totalizador_ativos,
                    "dif_totalizador_desligados": dif_totalizador_desligados,

                    "proventos_grupo": round(proventos_g, 2),
                    "base_oficial": None if base_of_g is None else round(float(base_of_g), 2),

                    "indice_incidencia": None if indice_incidencia is None else float(indice_incidencia),
                    "gap_bruto_prov_menos_base": None if gap_bruto is None else round(float(gap_bruto), 2),

                    "base_exclusao": res.get("base_exclusao"),
                    "gap": res.get("gap"),
                    "base_aprox_por_baixo": res.get("base_aprox_por_baixo"),
                    "erro_por_baixo": erro,

                    "status": status,

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
                            "valor": float(r.get("valor_alvo", 0.0) or 0.0),
                            "familia_layout": assin["familia_layout"],
                            "sistema_provavel": assin["sistema_provavel"],
                        })

            # Diagnóstico
            if modo_auditor_prof and layout == "ANALITICO" and totalizador_encontrado and bate_totalizador is False:
                diag = diagnostico_extracao_proventos(df, tol_inconsistencia=max(1.0, tol_totalizador))
                if not diag.empty:
                    dtop = diag.head(50).copy()
                    dtop.insert(0, "arquivo", arquivo.name)
                    dtop.insert(1, "competencia", comp)
                    dtop.insert(2, "layout", layout)
                    dtop.insert(3, "familia_layout", assin["familia_layout"])
                    dtop.insert(4, "sistema_provavel", assin["sistema_provavel"])
                    linhas_diagnostico.extend(dtop.to_dict(orient="records"))

    # ---------------- DataFrames finais ----------------
    df_resumo = pd.DataFrame(linhas_resumo)
    df_devolvidas = pd.DataFrame(linhas_devolvidas)
    df_diag = pd.DataFrame(linhas_diagnostico)
    df_mapa = pd.DataFrame(linhas_mapa)
    df_eventos = pd.concat(eventos_dump, ignore_index=True) if eventos_dump else pd.DataFrame()
    df_quadros_2018 = pd.DataFrame(linhas_quadros_2018) if linhas_quadros_2018 else pd.DataFrame()

    # Chaves para filtro cruzado
    if not df_resumo.empty:
        df_resumo["chave"] = df_resumo["arquivo"].astype(str) + "|" + df_resumo["competencia"].astype(str) + "|" + df_resumo["grupo"].astype(str)
    if not df_devolvidas.empty:
        df_devolvidas["chave"] = df_devolvidas["arquivo"].astype(str) + "|" + df_devolvidas["competencia"].astype(str) + "|" + df_devolvidas["grupo"].astype(str)
    if not df_mapa.empty:
        df_mapa["chave"] = df_mapa["arquivo"].astype(str) + "|" + df_mapa["competencia"].astype(str) + "|" + df_mapa["grupo"].astype(str)
    if not df_diag.empty:
        df_diag["chave"] = df_diag["arquivo"].astype(str) + "|" + df_diag["competencia"].astype(str)

    # ---------------- Filtros globais (sidebar) ----------------
    st.sidebar.header("🔎 Filtros (lote)")

    if df_resumo.empty:
        st.warning("Nenhum dado consolidado foi gerado (verifique se as competências foram identificadas).")
        st.stop()

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

    # eventos: filtra por arquivo+competencia
    if not df_eventos.empty:
        pares_ok = set((r["arquivo"], r["competencia"]) for _, r in df_resumo_f[["arquivo", "competencia"]].drop_duplicates().iterrows())
        df_eventos_f = df_eventos[df_eventos.apply(lambda x: (x["arquivo"], x["competencia"]) in pares_ok, axis=1)].copy()
    else:
        df_eventos_f = df_eventos

    # diag: filtra por arquivo+competencia
    if not df_diag.empty:
        pares_ok2 = set((r["arquivo"], r["competencia"]) for _, r in df_resumo_f[["arquivo", "competencia"]].drop_duplicates().iterrows())
        df_diag_f = df_diag[df_diag.apply(lambda x: (x["arquivo"], x["competencia"]) in pares_ok2, axis=1)].copy()
    else:
        df_diag_f = df_diag

    # quadros 2018: filtra por arquivo+competencia
    if not df_quadros_2018.empty:
        pares_ok3 = set((r["arquivo"], r["competencia"]) for _, r in df_resumo_f[["arquivo", "competencia"]].drop_duplicates().iterrows())
        df_quadros_2018_f = df_quadros_2018[df_quadros_2018.apply(lambda x: (x["arquivo"], x["competencia"]) in pares_ok3, axis=1)].copy()
    else:
        df_quadros_2018_f = df_quadros_2018

    # ---------------- RADAR (filtrado) ----------------
    df_radar = pd.DataFrame()
    if radar_on and ((df_devolvidas_f is not None and not df_devolvidas_f.empty) or (df_mapa_f is not None and not df_mapa_f.empty)):
        base_periodos = df_resumo_f[df_resumo_f["grupo"].isin(["ATIVOS", "DESLIGADOS", "GLOBAL"])].copy()
        base_periodos["chave_periodo"] = base_periodos["arquivo"].astype(str) + "|" + base_periodos["competencia"].astype(str) + "|" + base_periodos["grupo"].astype(str)
        tot_periodos = base_periodos.groupby("grupo")["chave_periodo"].nunique().to_dict()

        if df_devolvidas_f is not None and not df_devolvidas_f.empty:
            d = df_devolvidas_f.copy()
            d["chave_periodo"] = d["arquivo"].astype(str) + "|" + d["competencia"].astype(str) + "|" + d["grupo"].astype(str)
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

    # ---------------- Abas ----------------
    tab_resumo, tab_eventos, tab_devolvidas, tab_mapa, tab_radar, tab_diag, tab_quadros = st.tabs(
        ["📌 Resumo", "📋 Eventos", "🧩 Devolvidas", "🧭 Mapa", "📡 Radar", "🕵️ Diagnóstico", "🏛 Estrutura 2018"]
    )

    with tab_resumo:
        st.subheader("📌 Resumo consolidado (já filtrado)")
        st.dataframe(
            df_resumo_f.sort_values(["competencia", "arquivo", "layout", "grupo"]),
            use_container_width=True
        )

        if painel_2018_on and not df_quadros_2018_f.empty:
            st.markdown("### 🏛 Painel Estrutural (2018) — Situação: Geral (visual)")
            st.caption("Isso é apenas VISUAL e não entra no cálculo da auditoria.")
            st.dataframe(df_quadros_2018_f.sort_values(["competencia", "arquivo"]), use_container_width=True)

    with tab_eventos:
        st.subheader("📋 Eventos extraídos (já filtrado por lote)")
        if df_eventos_f.empty:
            st.info("Sem eventos para os filtros selecionados.")
        else:
            cols = df_eventos_f.columns.tolist()
            if not mostrar_referencia and "referencia" in cols:
                cols = [c for c in cols if c != "referencia"]
            st.dataframe(df_eventos_f[cols].head(5000), use_container_width=True)

    with tab_devolvidas:
        st.subheader("🧩 Rubricas devolvidas (já filtrado)")
        if df_devolvidas_f is None or df_devolvidas_f.empty:
            st.info("Nenhuma rubrica devolvida para os filtros selecionados.")
        else:
            st.dataframe(
                df_devolvidas_f.sort_values(["competencia", "arquivo", "grupo", "valor"], ascending=[True, True, True, False]),
                use_container_width=True
            )

    with tab_mapa:
        st.subheader("🧭 Mapa de Incidência (já filtrado)")
        if df_mapa_f is None or df_mapa_f.empty:
            st.info("Mapa vazio para os filtros selecionados.")
        else:
            comps = sorted(df_mapa_f["competencia"].unique().tolist())
            grupos = sorted(df_mapa_f["grupo"].unique().tolist())

            colA, colB, colC = st.columns(3)
            with colA:
                comp_sel = st.selectbox("Competência", comps, index=len(comps) - 1, key="map_comp")
            with colB:
                grupo_sel = st.selectbox("Grupo", grupos, index=0, key="map_grupo")
            with colC:
                topn = st.number_input("Top N", min_value=10, max_value=500, value=50, step=10, key="map_topn")

            class_opts = sorted(df_mapa_f["classificacao"].unique().tolist())
            class_sel = st.multiselect("Classificação", class_opts, default=class_opts, key="map_class")

            view = df_mapa_f[
                (df_mapa_f["competencia"] == comp_sel) &
                (df_mapa_f["grupo"] == grupo_sel) &
                (df_mapa_f["classificacao"].isin(class_sel))
            ].copy()

            view = view.sort_values(["impacto_pct_proventos", "valor"], ascending=[False, False]).head(int(topn))
            st.dataframe(
                view[["rubrica", "classificacao", "valor", "impacto_pct_proventos", "proventos_grupo", "arquivo", "layout"]],
                use_container_width=True
            )

    with tab_radar:
        st.subheader("📡 Radar Estrutural (já filtrado)")
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
                      "classificacao_mais_comum", "classificacao_mapa_mais_comum"]:
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
                colunas_ordem = ["score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"]
                for c in colunas_ordem:
                    if c not in v.columns:
                        v[c] = pd.NA

                v = v.sort_values(
                    colunas_ordem,
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
        st.subheader("🕵️ Diagnóstico (já filtrado)")
        if df_diag_f is None or df_diag_f.empty:
            st.info("Sem diagnósticos para os filtros selecionados.")
        else:
            st.dataframe(df_diag_f, use_container_width=True)

    with tab_quadros:
        st.subheader("🏛 Estrutura 2018 — Situação: Geral (visual)")
        if not painel_2018_on:
            st.info("Ative o Painel estrutural 2018 nas configurações.")
        elif df_quadros_2018_f.empty:
            st.info("Nenhum quadro 2018 detectado para os filtros selecionados.")
        else:
            st.dataframe(df_quadros_2018_f.sort_values(["competencia", "arquivo"]), use_container_width=True)
            st.caption("Dica: normalmente a base que interessa para auditoria do INSS patronal é a do quadro principal (ex.: funcionários).")

    # ---------------- Excel consolidado (já filtrado) ----------------
    buffer = io.BytesIO()

    # Para evitar erro de xlsxwriter em alguns ambientes, usamos openpyxl
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_resumo_f.to_excel(writer, index=False, sheet_name="Resumo_Filtrado")
        df_eventos_f.to_excel(writer, index=False, sheet_name="Eventos_Filtrados")
        (df_devolvidas_f if df_devolvidas_f is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Devolvidas_Filtradas")
        (df_mapa_f if df_mapa_f is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Mapa_Filtrado")
        df_radar.to_excel(writer, index=False, sheet_name="Radar_Filtrado")
        (df_diag_f if df_diag_f is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Diag_Filtrado")
        (df_quadros_2018_f if df_quadros_2018_f is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Quadros_2018")

    buffer.seek(0)
    st.download_button(
        "📥 Baixar Excel (dados filtrados)",
        data=buffer,
        file_name="AUDITOR_INSS_HIBRIDO_FILTRADO.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Envie um ou mais PDFs para iniciar.")
