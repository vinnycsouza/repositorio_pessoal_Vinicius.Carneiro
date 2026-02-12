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
# Config (SÓ UMA VEZ)
# ---------------------------
st.set_page_config(layout="wide")
st.title("🧾 Auditor INSS — Híbrido + Assinatura Estrutural (com filtros)")


# ---------------------------
# Semáforo de Base (NOVO)
# ---------------------------

def _zona_ord(z: str) -> int:
    # Para ordenar: 🔴 (mais crítico) primeiro, depois 🟡, depois 🟢
    if not z:
        return 99
    if z.startswith("🔴"):
        return 0
    if z.startswith("🟡"):
        return 1
    if z.startswith("🟢"):
        return 2
    return 99


def aplicar_semaforo_base(df: pd.DataFrame, modo: str = "MAPA") -> pd.DataFrame:
    """
    Cria coluna:
      - zona_base: 🔴 / 🟡 / 🟢
      - zona_ord: inteiro para ordenação
    """
    out = df.copy()

    if "classificacao" not in out.columns:
        out["classificacao"] = "SEM_CLASSIFICACAO"
    out["classificacao"] = out["classificacao"].fillna("SEM_CLASSIFICACAO").astype(str)

    modo = (modo or "MAPA").upper()

    if modo == "MAPA":
        if "impacto_pct_proventos" not in out.columns:
            out["impacto_pct_proventos"] = 0.0

        def _zona(row):
            cls = str(row.get("classificacao") or "SEM_CLASSIFICACAO").upper()
            impacto = float(row.get("impacto_pct_proventos") or 0.0)

            # Regras práticas e estáveis:
            # - FORA com pouco impacto -> 🔴
            # - ENTRA com impacto relevante -> 🟢
            # - NEUTRA ou alto impacto -> 🟡
            if cls == "FORA" and impacto < 2.0:
                return "🔴 FORA"
            if cls == "ENTRA" and impacto >= 2.0:
                return "🟢 INCIDE"
            if cls in ("NEUTRA", "SEM_CLASSIFICACAO") and impacto >= 1.0:
                return "🟡 ZONA_CINZA"
            if impacto >= 3.0:
                return "🟡 ZONA_CINZA"
            return "🟢 INCIDE"

        out["zona_base"] = out.apply(_zona, axis=1)
        out["zona_ord"] = out["zona_base"].apply(_zona_ord)
        return out

    # RADAR
    # Radar usa recorrência/impacto/score e também se é "devolvida"
    for c in ["recorrencia_pct", "impacto_medio_pct", "score_risco", "meses_devolvida", "valor_total_devolvido"]:
        if c not in out.columns:
            out[c] = pd.NA

    # devolvida = apareceu em devolvidas alguma vez
    out["devolvida"] = out["meses_devolvida"].fillna(0).astype(float) > 0

    def _zona_radar(row):
        cls_a = str(row.get("classificacao_mais_comum") or "").upper()
        cls_b = str(row.get("classificacao_mapa_mais_comum") or "").upper()
        rec = row.get("recorrencia_pct")
        imp = row.get("impacto_medio_pct")
        score = row.get("score_risco")

        rec = 0.0 if pd.isna(rec) else float(rec)
        imp = 0.0 if pd.isna(imp) else float(imp)
        score = (rec * imp) if pd.isna(score) else float(score)

        devolvida = bool(row.get("devolvida", False))

        # 🔴: tendência FORA e recorrente (e sem devolução forte)
        if ("FORA" in (cls_a, cls_b)) and rec >= 50 and imp < 2 and not devolvida:
            return "🔴 FORA"

        # 🟢: ENTRA/baixo risco
        if ("ENTRA" in (cls_a, cls_b)) and rec < 30 and imp >= 1.5 and not devolvida:
            return "🟢 INCIDE"

        # 🟡: qualquer coisa com sinal de risco/instabilidade
        if devolvida or rec >= 30 or imp >= 3 or score >= 60:
            return "🟡 ZONA_CINZA"

        return "🟢 INCIDE"

    out["zona_base"] = out.apply(_zona_radar, axis=1)
    out["zona_ord"] = out["zona_base"].apply(_zona_ord)
    return out


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

def normalizar_valor_br(txt: str):
    if txt is None:
        return None
    try:
        s = str(txt).strip()
        s = s.replace("R$", "").replace(" ", "")
        return float(s.replace(".", "").replace(",", "."))
    except Exception:
        return None


def extrair_competencia_sem_fallback(page):
    txt = (page.extract_text() or "").lower()

    # 1) 01/2021
    m = re.search(r"\b(0?[1-9]|1[0-2])\s*/\s*(20\d{2})\b", txt)
    if m:
        mm = m.group(1).zfill(2)
        aa = m.group(2)
        return f"{mm}/{aa}"

    # 2) 01.2012 ou 01-2012
    m = re.search(r"\b(0?[1-9]|1[0-2])\s*[.\-]\s*(20\d{2})\b", txt)
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
    (Resumo cobre: "Resumo Geral", "Resumo da Folha", layouts sem ATIVOS/DESLIGADOS monetário)
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
    - sistema_provavel: string amigável (palpite por família)
    - confianca: 0-100
    - evidencias: lista curta
    - scores: debug
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
        "vencimentos", "descontos", "base inss", "base inss empresa"
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
    if "evento" in joined and "qtd" in joined: evid.append("EVENTO/QTD")

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
# Extratores para layout RESUMO (GLOBAL)
# ---------------------------

def extrair_base_inss_global_texto(texto: str) -> float | None:
    """
    Encontra a melhor base INSS 'empresa' em PDFs de resumo.
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


def extrair_eventos_resumo_page(page) -> list[dict]:
    """
    Extrai eventos em RESUMO (GLOBAL) respeitando 2 colunas:
    - 2012: linhas com '|' separando PROVENTOS (esq) e DESCONTOS (dir)
    - 2018: 2 rubricas na mesma linha (sem '|')
    Saída:
      ativos = valor, desligados = 0, total = valor
    """
    txt = page.extract_text() or ""
    if not txt.strip():
        return []

    linhas = [ln.rstrip() for ln in txt.splitlines() if ln.strip()]
    eventos = []

    secao = None  # PROVENTO / DESCONTO

    def ultimo_numero_br(s: str):
        nums = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", s)
        if not nums:
            return None
        return normalizar_valor_br(nums[-1])

    def primeiro_codigo(s: str):
        m = re.search(r"\b(\d{3,6})\b", s)
        return m.group(1) if m else None

    def limpar_desc(cod: str, chunk: str):
        x = re.sub(r"^\s*" + re.escape(cod) + r"\s+", "", chunk).strip()
        nums = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", x)
        if nums:
            x = re.sub(re.escape(nums[-1]) + r"\s*$", "", x).strip()
        x = re.sub(r"\s{2,}", " ", x)
        return x

    def add_event(tipo: str, cod: str, desc: str, valor: float):
        rubricas = f"{cod} {desc}".strip()
        eventos.append({
            "rubrica": rubricas,
            "tipo": tipo,
            "ativos": float(valor),
            "desligados": 0.0,
            "total": float(valor),
        })

    for ln in linhas:
        l = ln.lower()

        if "vencimentos" in l or "proventos" in l:
            secao = "PROVENTO"
            continue
        if "descontos" in l:
            secao = "DESCONTO"
            continue

        if "base inss" in l:
            continue
        if "resumo" in l and "folha" in l:
            continue
        if "total geral" in l:
            continue
        if "evento" in l and "descricao" in l and "valor" in l:
            continue

        # Modelo com colunas separadas por '|'
        if "|" in ln:
            partes = [p.strip() for p in ln.split("|")]
            blocos = [p for p in partes if p and re.search(r"\b\d{3,6}\b", p)]
            if len(blocos) >= 2:
                esq, dir = blocos[0], blocos[1]

                cod_esq = primeiro_codigo(esq)
                val_esq = ultimo_numero_br(esq)
                if cod_esq and val_esq is not None:
                    desc_esq = limpar_desc(cod_esq, esq)
                    add_event("PROVENTO", cod_esq, desc_esq, val_esq)

                cod_dir = primeiro_codigo(dir)
                val_dir = ultimo_numero_br(dir)
                if cod_dir and val_dir is not None:
                    desc_dir = limpar_desc(cod_dir, dir)
                    add_event("DESCONTO", cod_dir, desc_dir, val_dir)
                continue
            elif len(blocos) == 1:
                ln = blocos[0]

        # Modelo “grudado”: 2 códigos na mesma linha
        cod_pos = []
        for m in re.finditer(r"\b(\d{3,6})\b", ln):
            cod = m.group(1)
            after = ln[m.end():m.end()+2]
            if after.strip() == "":
                continue
            cod_pos.append((cod, m.start()))
        cod_pos = sorted(cod_pos, key=lambda x: x[1])

        if len(cod_pos) >= 2:
            (cod1, p1), (cod2, p2) = cod_pos[0], cod_pos[1]
            chunk1 = ln[p1:p2].strip()
            chunk2 = ln[p2:].strip()

            v1 = ultimo_numero_br(chunk1)
            v2 = ultimo_numero_br(chunk2)

            if v1 is not None:
                add_event("PROVENTO", cod1, limpar_desc(cod1, chunk1), v1)
            if v2 is not None:
                add_event("DESCONTO", cod2, limpar_desc(cod2, chunk2), v2)
            continue

        # Linha simples (1 rubrica)
        m_cod = re.match(r"^\s*(\d{3,6})\s+(.+)$", ln)
        if not m_cod:
            continue

        cod = m_cod.group(1)
        resto = m_cod.group(2)
        val = ultimo_numero_br(resto)
        if val is None:
            continue

        desc = limpar_desc(cod, f"{cod} {resto}")
        tipo = secao if secao in ("PROVENTO", "DESCONTO") else "PROVENTO"
        add_event(tipo, cod, desc, val)

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
        "rubrica", "ativos", "desligados", "total",
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

st.info(
    "✅ Detector Híbrido decide entre **ANALÍTICO** (ATIVOS/DESLIGADOS) e **RESUMO** (GLOBAL).\n"
    "✅ Assinatura estrutural sugere a **família** e um **sistema provável** (heurística).\n"
    "✅ Filtros permitem analisar lotes misturados com mais controle."
)

if arquivos:
    linhas_resumo = []
    linhas_devolvidas = []
    linhas_diagnostico = []
    linhas_mapa = []
    eventos_dump = []

    for arquivo in arquivos:
        with pdfplumber.open(arquivo) as pdf:
            texts = [(p.extract_text() or "") for p in pdf.pages[:2]]
            layout = detectar_layout_pdf(texts)
            assin = reconhecer_sistema_por_assinatura(texts)

            dados = {}
            comp_atual = None

            for page in pdf.pages:
                comp_atual = extrair_competencia_robusta(page, comp_atual)
                if not comp_atual:
                    comp_atual = "SEM_COMP"

                dados.setdefault(comp_atual, {"eventos": [], "base_empresa": None, "totais_proventos_pdf": None})

                # Base oficial
                if layout == "ANALITICO":
                    if pagina_eh_de_bases(page):
                        base = extrair_base_empresa_page(page)
                        if base and dados[comp_atual]["base_empresa"] is None:
                            dados[comp_atual]["base_empresa"] = base
                else:
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

            for c in ["rubrica", "tipo", "ativos", "desligados", "total"]:
                if c not in df.columns:
                    df[c] = 0.0 if c in ("ativos", "desligados", "total") else ""

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

                    # (PONTO 2) semáforo no Mapa
                    agg = aplicar_semaforo_base(agg, modo="MAPA")

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

                    "proventos_grupo": proventos_g,
                    "base_oficial": base_of_g,

                    "indice_incidencia": indice_incidencia,
                    "gap_bruto_prov_menos_base": gap_bruto,

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

    # eventos: filtra por arquivo+competencia (mais flexível)
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

        # (PONTO 3) aplica semáforo no Radar
        df_radar = aplicar_semaforo_base(df_radar, modo="RADAR")

        # (PONTO 3/4) blindagem + ordenação com zona_base
        for c in ["zona_ord", "score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"]:
            if c not in df_radar.columns:
                df_radar[c] = pd.NA

        df_radar = df_radar.sort_values(
            ["zona_ord", "score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"],
            ascending=[True, False, False, False, False],
            na_position="last"
        ).reset_index(drop=True)

    # ---------------- Abas ----------------
    tab_resumo, tab_eventos, tab_devolvidas, tab_mapa, tab_radar, tab_diag = st.tabs(
        ["📌 Resumo", "📋 Eventos", "🧩 Devolvidas", "🧭 Mapa", "📡 Radar", "🕵️ Diagnóstico"]
    )

    with tab_resumo:
        st.subheader("📌 Resumo consolidado (já filtrado)")
        st.dataframe(
            df_resumo_f.sort_values(["competencia", "arquivo", "layout", "grupo"]),
            use_container_width=True
        )

    with tab_eventos:
        st.subheader("📋 Eventos extraídos (já filtrado por lote)")
        if df_eventos_f.empty:
            st.info("Sem eventos para os filtros selecionados.")
        else:
            st.dataframe(df_eventos_f.head(5000), use_container_width=True)

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

            # (PONTO 4) ordenação com semáforo visível
            # garante colunas
            for c in ["zona_ord", "impacto_pct_proventos", "valor"]:
                if c not in view.columns:
                    view[c] = pd.NA

            view = view.sort_values(["zona_ord", "impacto_pct_proventos", "valor"], ascending=[True, False, False]).head(int(topn))

            st.dataframe(
                view[["zona_base", "rubrica", "classificacao", "valor", "impacto_pct_proventos", "proventos_grupo", "arquivo", "layout"]],
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

            # garante colunas antes de filtro/ordem
            for c in ["zona_ord", "zona_base", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido", "score_risco",
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
                # ordena por semáforo primeiro, depois risco
                colunas_ordem = ["zona_ord", "score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"]
                for c in colunas_ordem:
                    if c not in v.columns:
                        v[c] = pd.NA

                v = v.sort_values(
                    colunas_ordem,
                    ascending=[True, False, False, False, False],
                    na_position="last"
                ).head(int(topn))

                st.dataframe(
                    v[[
                        "zona_base",
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

    # ---------------- Excel consolidado (já filtrado) ----------------
    buffer = io.BytesIO()

    # Troca para openpyxl (evita ModuleNotFoundError xlsxwriter)
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_resumo_f.to_excel(writer, index=False, sheet_name="Resumo_Filtrado")
        df_eventos_f.to_excel(writer, index=False, sheet_name="Eventos_Filtrados")
        (df_devolvidas_f if df_devolvidas_f is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Devolvidas_Filtradas")
        (df_mapa_f if df_mapa_f is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Mapa_Filtrado")
        df_radar.to_excel(writer, index=False, sheet_name="Radar_Filtrado")
        (df_diag_f if df_diag_f is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Diag_Filtrado")

    buffer.seek(0)
    st.download_button(
        "📥 Baixar Excel (dados filtrados)",
        data=buffer,
        file_name="AUDITOR_INSS_HIBRIDO_FILTRADO.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.info("Envie um ou mais PDFs para iniciar.")
