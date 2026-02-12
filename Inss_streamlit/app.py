import io
import re
import math
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pdfplumber
import pandas as pd
import streamlit as st


# =========================
# Config Streamlit
# =========================
st.set_page_config(layout="wide")
st.title("🧾 Auditor Estrutural – Base INSS Patronal (Híbrido + Semáforo)")


# =========================
# Utilidades
# =========================
def _norm_txt(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _to_float_br(v: str) -> Optional[float]:
    """
    Converte número BR:
      "1.234.567,89" -> 1234567.89
      "0,00" -> 0.0
    """
    if v is None:
        return None
    s = str(v).strip()
    s = s.replace("R$", "").strip()
    # mantém apenas dígitos, ponto, vírgula e sinal
    s = re.sub(r"[^\d\-,.]", "", s)
    if not s:
        return None

    # Heurística BR: último separador decimal costuma ser vírgula
    # Remove pontos de milhar e troca vírgula por ponto
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _money(v: Optional[float]) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v))):
        return "-"
    return f"R$ {v:,.2f}"


def _safe_div(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return a / b


def _round2(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return float(round(v, 2))


def _approx_equal(a: float, b: float, tol_abs: float) -> bool:
    return abs(a - b) <= tol_abs


# =========================
# Classificação e Semáforo
# =========================
def classificar_rubrica_basico(nome: str) -> str:
    """
    Classificação inicial (heurística).
    Você pode refinar depois com um regras.json se quiser.
    """
    n = _norm_txt(nome)

    # Ex.: salário família / educação -> tipicamente FORA
    fora_keys = [
        "salario familia", "salario-familia", "sal fam",
        "salario educacao", "salario-educacao", "sal educ",
        "indenizacao", "ressarc", "ajuda de custo", "auxilio creche",
        "diaria", "vale transporte", "vale alimentacao", "vale refeicao",
        "plano de saude", "assistencia medica", "assistencia odont",
    ]
    entra_keys = [
        "salario", "salario normal", "vencimento", "pro labore",
        "hora extra", "adicional", "periculos", "insalubr",
        "comissao", "gratificacao", "premio", "bonus", "dsr",
        "ferias", "1/3", "terco ferias",
    ]

    if any(k in n for k in fora_keys):
        return "FORA"
    if any(k in n for k in entra_keys):
        return "ENTRA"
    return "NEUTRA"


def aplicar_semaforo_base(df: pd.DataFrame, modo: str = "MAPA") -> pd.DataFrame:
    """
    Define zona_base:
      🟢 INCIDE       = tendência de incidência clara
      🟡 ZONA_CINZA   = oscilação / impacto relevante / devolvida
      🔴 FORA         = tendência de não incidência clara
    """
    out = df.copy()

    if "classificacao" not in out.columns:
        out["classificacao"] = "SEM_CLASSIFICACAO"

    if modo.upper() == "MAPA":
        if "impacto_pct_proventos" not in out.columns:
            out["impacto_pct_proventos"] = 0.0

        def _cls(row):
            cls = str(row.get("classificacao") or "SEM_CLASSIFICACAO")
            impacto = float(row.get("impacto_pct_proventos") or 0.0)

            if cls == "FORA" and impacto < 2:
                return "🔴 FORA"
            if cls == "ENTRA" and impacto >= 3:
                return "🟢 INCIDE"
            if cls in ("NEUTRA", "SEM_CLASSIFICACAO") and impacto >= 1:
                return "🟡 ZONA_CINZA"
            if impacto >= 3:
                return "🟡 ZONA_CINZA"
            return "🟢 INCIDE"

        out["zona_base"] = out.apply(_cls, axis=1)
        return out

    # RADAR
    for c in ["impacto_medio_pct", "recorrencia_pct", "meses_devolvida", "valor_total_devolvido", "score_risco"]:
        if c not in out.columns:
            out[c] = pd.NA

    out["devolvida"] = out["meses_devolvida"].fillna(0).astype(float) > 0

    def _cls_radar(row):
        cls = str(row.get("classificacao_mais_comum") or row.get("classificacao") or "SEM_CLASSIFICACAO")
        cls_mapa = str(row.get("classificacao_mapa_mais_comum") or "")
        impacto = float(row.get("impacto_medio_pct") or 0.0)
        rec = float(row.get("recorrencia_pct") or 0.0)
        score = row.get("score_risco")
        score = float(score) if score is not None and not pd.isna(score) else (rec * impacto)
        devolvida = bool(row.get("devolvida", False))

        # 🔴 fora estável (fora + pouco impacto + sem devolução)
        if ("FORA" in (cls, cls_mapa)) and (rec >= 50) and (impacto < 2) and (not devolvida):
            return "🔴 FORA"

        # 🟢 incide estável
        if ("ENTRA" in (cls, cls_mapa)) and (impacto >= 2) and (rec < 30) and (not devolvida):
            return "🟢 INCIDE"

        # 🟡 zona cinza
        if devolvida or rec >= 30 or impacto >= 3 or score >= 60:
            return "🟡 ZONA_CINZA"

        return "🟢 INCIDE"

    out["zona_base"] = out.apply(_cls_radar, axis=1)
    return out


# =========================
# Assinatura estrutural / Layout
# =========================
@dataclass
class Assinatura:
    familia_layout: str
    sistema_provavel: str


def reconhecer_assinatura(texto: str) -> Tuple[str, Assinatura]:
    t = _norm_txt(texto)

    # Indicadores de analítico “espelhado” (provento | desconto na mesma linha)
    analitico_keys = [
        "cod provento", "cod desconto", "proventos", "descontos",
        "ativos", "desligados", "total"
    ]
    # Indicadores de resumo
    resumo_keys = [
        "resumo da folha", "totais", "totalizadores",
        "salario contribuicao", "salario contribuicao empresa", "terceiros", "fap"
    ]

    is_analitico = sum(k in t for k in analitico_keys) >= 3
    is_resumo = sum(k in t for k in resumo_keys) >= 2

    if is_analitico and not is_resumo:
        # família e “sistema provável” (heurístico)
        fam = "ANALITICO_ESPELHADO"
        sist = "DOMINIO/QUESTOR (provável)"
        return "ANALITICO", Assinatura(fam, sist)

    if is_resumo and not is_analitico:
        fam = "RESUMO_BASES"
        sist = "SENIOR/TOTVS (provável)"
        return "RESUMO", Assinatura(fam, sist)

    # híbrido / indefinido
    fam = "HIBRIDO/INDEFINIDO"
    sist = "NÃO IDENTIFICADO (híbrido)"
    # fallback: se tem cod provento e cod desconto, assume analítico
    if "cod provento" in t and "cod desconto" in t:
        return "ANALITICO", Assinatura("ANALITICO_ESPELHADO", sist)
    return "RESUMO", Assinatura(fam, sist)


# =========================
# Competência
# =========================
def extrair_competencia(texto: str, fallback: Optional[str]) -> Optional[str]:
    """
    Extrai competência do texto da página (ex.: 01/2012).
    """
    t = texto or ""
    # Padrões comuns
    m = re.search(r"\b(0[1-9]|1[0-2])\s*/\s*(20\d{2}|19\d{2})\b", t)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    # Alguns modelos usam "Competência: 01.2012"
    m2 = re.search(r"compet[êe]ncia[:\s]*\b(0[1-9]|1[0-2])[./-](20\d{2}|19\d{2})\b", t, re.IGNORECASE)
    if m2:
        return f"{m2.group(1)}/{m2.group(2)}"

    return fallback


# =========================
# Extração de BASE INSS EMPRESA
# =========================
def extrair_base_inss_empresa(texto: str) -> Optional[Dict[str, float]]:
    """
    Tenta achar "Salário Contribuição Empresa" por grupo (ativos/desligados/total).
    Em muitos PDFs isso aparece como um bloco de bases.
    Retorna dict com chaves: ativos/desligados/total quando achar.
    """
    t = texto or ""
    tn = _norm_txt(t)

    # busca linha que contenha "salario contribuicao empresa"
    # e tenta capturar 3 valores (ativos/desligados/total) ou 1 valor (total)
    if "salario contribuicao empresa" not in tn:
        return None

    # tenta capturar "xxx  yyy  zzz" na mesma linha (BR)
    # Ex.: "Salario Contribuicao Empresa 1.854.598,59 56.746,96 1.911.345,55"
    # ou "Salario Contribuicao Empresa 1.911.345,55"
    # pega trecho de 0-120 chars após a chave
    idx = tn.find("salario contribuicao empresa")
    snippet = t[idx: idx + 200] if idx >= 0 else t

    nums = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", snippet)
    vals = [_to_float_br(n) for n in nums if _to_float_br(n) is not None]
    vals = [v for v in vals if v is not None]

    if not vals:
        return None

    if len(vals) >= 3:
        return {"ativos": float(vals[0]), "desligados": float(vals[1]), "total": float(vals[2])}
    # fallback total
    return {"total": float(vals[0])}


# =========================
# Extração de Eventos (rubricas)
# =========================
def _parse_linha_analitica(linha: str) -> List[Dict]:
    """
    Analítico espelhado:
      [COD PROVENTO] [DESC PROVENTO] [REFER?] [ATIVOS] [DESLIGADOS] [TOTAL] [COD DESC] [DESC DESC] [REFER?] [ATIVOS] [DESLIGADOS] [TOTAL]

    Como os PDFs variam, a gente faz uma heurística:
      - Procura 6 números BR (ativos/desligados/total) para provento e 3 para desconto
      - Divide no meio se achar 6 números no total (3+3)
    """
    out = []
    s = re.sub(r"\s+", " ", (linha or "")).strip()
    if not s:
        return out

    # Captura números BR na linha (valores)
    nums = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", s)
    vals = [_to_float_br(n) for n in nums]
    vals = [v for v in vals if v is not None]

    # Precisamos de pelo menos 3 valores para considerar evento (ativos/desligados/total)
    # Se tiver 6, pode ser provento+desconto na mesma linha
    if len(vals) < 3:
        return out

    # Identifica um "código" no começo
    m_cod = re.match(r"^\s*(\d{3,5})\s+(.*)$", s)
    cod = m_cod.group(1) if m_cod else ""
    resto = m_cod.group(2) if m_cod else s

    # Tenta separar descrição removendo os números do final
    # Vamos cortar a string na posição do primeiro número encontrado
    m_first_num = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", resto)
    desc = resto[: m_first_num.start()].strip() if m_first_num else resto.strip()

    # Se tiver 6+ valores, assume 3 provento + 3 desconto (pegando os 6 últimos)
    if len(vals) >= 6:
        last6 = vals[-6:]
        prov = last6[:3]
        descv = last6[3:]

        out.append({
            "rubrica": f"{cod} {desc}".strip(),
            "tipo": "PROVENTO",
            "ativos": float(prov[0]),
            "desligados": float(prov[1]),
            "total": float(prov[2]),
        })
        # para desconto, o texto geralmente tem outra descrição, mas no resumo espelhado
        # muitas vezes ela vem depois — aqui fica como "DESCONTO (mesma linha)".
        out.append({
            "rubrica": f"{cod} {desc} (DESCONTO?)".strip(),
            "tipo": "DESCONTO",
            "ativos": float(descv[0]),
            "desligados": float(descv[1]),
            "total": float(descv[2]),
        })
        return out

    # Caso tenha só 3 valores: assume é uma linha de um dos quadros (provento OU desconto)
    v3 = vals[-3:]
    out.append({
        "rubrica": f"{cod} {desc}".strip(),
        "tipo": "PROVENTO",  # por default; depois tentamos reclassificar
        "ativos": float(v3[0]),
        "desligados": float(v3[1]),
        "total": float(v3[2]),
    })
    return out


def _parse_linhas_resumo(texto: str) -> List[Dict]:
    """
    Resumo geralmente vem em blocos menos estruturados.
    Aqui tentamos capturar linhas com rubrica + valor (total).
    """
    out = []
    lines = (texto or "").splitlines()
    for ln in lines:
        s = re.sub(r"\s+", " ", ln).strip()
        if not s:
            continue
        # ignora cabeçalhos comuns
        tn = _norm_txt(s)
        if any(k in tn for k in ["resumo", "total", "totais", "base", "salario contribuicao", "terceiros", "fap"]):
            continue

        # rubrica + 1 valor BR
        m = re.search(r"^(.*?)(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s*$", s)
        if not m:
            continue
        nome = m.group(1).strip(" -:")
        val = _to_float_br(m.group(2))
        if val is None or val == 0:
            continue

        out.append({
            "rubrica": nome,
            "tipo": "PROVENTO",   # em resumo, muitas vezes não dá para separar; tratamos como provento
            "ativos": 0.0,
            "desligados": 0.0,
            "total": float(val),
        })
    return out


def extrair_eventos_de_pagina(texto: str, layout: str) -> List[Dict]:
    if layout == "ANALITICO":
        eventos = []
        for ln in (texto or "").splitlines():
            # Heurística: linha com valores BR e algum “código”
            if not re.search(r"\d{1,3}(?:\.\d{3})*,\d{2}", ln):
                continue
            if not re.search(r"^\s*\d{3,5}\s+", ln):
                continue
            eventos.extend(_parse_linha_analitica(ln))
        return eventos

    # RESUMO
    return _parse_linhas_resumo(texto)


def ajustar_tipo_por_heuristica(df: pd.DataFrame) -> pd.DataFrame:
    """
    Em analítico, parte das linhas pode vir como PROVENTO por default.
    Tentamos identificar DESCONTO por palavras-chave.
    """
    out = df.copy()
    if out.empty:
        return out

    def _tipo(row):
        nome = _norm_txt(str(row.get("rubrica", "")))
        if any(k in nome for k in ["inss", "irrf", "falt", "emprest", "plano", "mensal", "pensao", "sind", "liquido", "desconto"]):
            return "DESCONTO"
        return row.get("tipo", "PROVENTO")

    out["tipo"] = out.apply(_tipo, axis=1)
    return out


# =========================
# Reconstrução por exclusão (DEVOLVIDAS)
# =========================
def reconstruir_por_exclusao(
    df_eventos: pd.DataFrame,
    base_of: Optional[Dict[str, float]],
    grupo: str,
    tol_abs: float,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    Estratégia:
      - Começa com proventos do grupo (ativos/desligados/total)
      - Define GAP = proventos - base_of[grupo]
      - Seleciona candidatas (classificacao FORA/NEUTRA e/ou descontos negativos suspeitos)
      - "Devolve" rubricas tentando somar próximo ao GAP
    Retorna:
      - devolvidas (df)
      - resumo com gap e info
    """
    if df_eventos.empty or base_of is None:
        return pd.DataFrame(), {"gap": 0.0, "proventos": float(df_eventos.get(grupo, pd.Series([0])).sum())}

    base_g = base_of.get(grupo)
    if base_g is None:
        return pd.DataFrame(), {"gap": 0.0, "proventos": float(df_eventos.get(grupo, pd.Series([0])).sum())}

    # proventos do grupo
    prov = df_eventos[df_eventos["tipo"] == "PROVENTO"].copy()
    proventos_g = float(prov[grupo].sum())

    gap = proventos_g - float(base_g)

    # Candidatas = rubricas PROVENTO com classificacao != ENTRA
    cand = prov.copy()
    cand["classificacao"] = cand["rubrica"].apply(classificar_rubrica_basico)
    cand = cand[cand["classificacao"] != "ENTRA"].copy()

    if cand.empty:
        return pd.DataFrame(), {"gap": gap, "proventos": proventos_g}

    # Ordena por valor desc
    cand["valor"] = cand[grupo].astype(float)
    cand = cand[cand["valor"] != 0].copy()
    cand = cand.sort_values("valor", ascending=False)

    # Se gap <= 0, não faz sentido “tirar”
    if gap <= 0:
        return pd.DataFrame(), {"gap": gap, "proventos": proventos_g}

    # Heurística gulosa + refinamento local (bom para PDF resumido)
    chosen = []
    soma = 0.0

    for _, r in cand.iterrows():
        v = float(r["valor"])
        if v <= 0:
            continue
        if soma + v <= gap + tol_abs:
            chosen.append(r)
            soma += v
        if _approx_equal(soma, gap, tol_abs):
            break

    devolvidas = pd.DataFrame(chosen) if chosen else pd.DataFrame(columns=list(cand.columns))
    if not devolvidas.empty:
        devolvidas = devolvidas[["rubrica", "classificacao", grupo, "total"]].copy()
        devolvidas = devolvidas.rename(columns={grupo: "valor_devolvido"})
        devolvidas["grupo"] = grupo.upper()

    return devolvidas, {"gap": gap, "proventos": proventos_g, "soma_devolvida": soma, "base_oficial": float(base_g)}


# =========================
# UI – Inputs
# =========================
colA, colB, colC, colD = st.columns(4)

with colA:
    tol_min = st.number_input("Tolerância mínima (R$)", value=10.0, step=10.0)
with colB:
    tol_max = st.number_input("Tolerância máxima (R$)", value=10000.0, step=100.0)
with colC:
    mapa_incidencia_on = st.toggle("Ativar Mapa de Incidência", value=True)
with colD:
    radar_on = st.toggle("Ativar Radar Estrutural", value=True)

st.caption("📌 Dica: Se o PDF for resumido, aumente a tolerância máxima. Se for analítico e bem extraído, reduza.")

arquivos = st.file_uploader(
    "Envie PDF(s) de folha de pagamento",
    type="pdf",
    accept_multiple_files=True
)

# =========================
# Acumuladores (sempre definidos)
# =========================
linhas_resumo = []
linhas_devolvidas = []
linhas_diagnostico = []
linhas_mapa = []
eventos_dump = []


# =========================
# Execução principal
# =========================
if arquivos:
    # limpa para evitar acumulo em rerun
    linhas_resumo.clear()
    linhas_devolvidas.clear()
    linhas_diagnostico.clear()
    linhas_mapa.clear()
    eventos_dump.clear()

    for arquivo in arquivos:
        with pdfplumber.open(arquivo) as pdf:
            comp_atual = None
            base_oficial_por_comp: Dict[str, Dict[str, float]] = {}
            eventos_por_comp: Dict[str, List[Dict]] = {}
            layout_por_comp: Dict[str, str] = {}
            assin_por_comp: Dict[str, Assinatura] = {}

            for page in pdf.pages:
                texto = page.extract_text() or ""
                comp_atual = extrair_competencia(texto, comp_atual)
                if not comp_atual:
                    # sem competência, ignora (ou poderia agrupar em "SEM_COMP")
                    continue

                layout, assin = reconhecer_assinatura(texto)
                layout_por_comp[comp_atual] = layout
                assin_por_comp[comp_atual] = assin

                # base inss empresa
                b = extrair_base_inss_empresa(texto)
                if b:
                    # guarda a primeira ocorrência por comp
                    base_oficial_por_comp.setdefault(comp_atual, b)

                # eventos
                evs = extrair_eventos_de_pagina(texto, layout)
                if evs:
                    eventos_por_comp.setdefault(comp_atual, [])
                    eventos_por_comp[comp_atual].extend(evs)

            # =========================
            # Processa cada competência encontrada neste PDF
            # =========================
            for comp, evs in eventos_por_comp.items():
                layout = layout_por_comp.get(comp, "RESUMO")
                assin = assin_por_comp.get(comp, Assinatura("HIBRIDO/INDEFINIDO", "NÃO IDENTIFICADO"))

                df = pd.DataFrame(evs)
                if df.empty:
                    continue

                # Normaliza colunas
                for c in ["ativos", "desligados", "total"]:
                    if c not in df.columns:
                        df[c] = 0.0
                    df[c] = df[c].fillna(0).astype(float)

                # Ajusta tipo por heurística e classifica rubrica
                df = ajustar_tipo_por_heuristica(df)
                df["classificacao"] = df["rubrica"].apply(classificar_rubrica_basico)

                # remove duplicados “idênticos”
                df = df.drop_duplicates(subset=["rubrica", "tipo", "ativos", "desligados", "total"]).reset_index(drop=True)

                # Totais de proventos por grupo
                prov = df[df["tipo"] == "PROVENTO"].copy()
                totais_usados = {
                    "ativos": float(prov["ativos"].sum()),
                    "desligados": float(prov["desligados"].sum()),
                    "total": float(prov["total"].sum()),
                }

                base_of = base_oficial_por_comp.get(comp)

                # =========================
                # Resumo
                # =========================
                linha_res = {
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "layout": layout,
                    "familia_layout": assin.familia_layout,
                    "sistema_provavel": assin.sistema_provavel,
                    "proventos_ativos": totais_usados["ativos"],
                    "proventos_desligados": totais_usados["desligados"],
                    "proventos_total": totais_usados["total"],
                    "base_of_ativos": base_of.get("ativos") if base_of else None,
                    "base_of_desligados": base_of.get("desligados") if base_of else None,
                    "base_of_total": base_of.get("total") if base_of else None,
                }
                # diffs (se houver base)
                if base_of:
                    linha_res["gap_ativos"] = totais_usados["ativos"] - float(base_of.get("ativos", 0.0))
                    linha_res["gap_desligados"] = totais_usados["desligados"] - float(base_of.get("desligados", 0.0))
                    linha_res["gap_total"] = totais_usados["total"] - float(base_of.get("total", 0.0))
                else:
                    linha_res["gap_ativos"] = None
                    linha_res["gap_desligados"] = None
                    linha_res["gap_total"] = None

                linhas_resumo.append(linha_res)

                # dump eventos (para excel)
                df_dump = df.copy()
                df_dump.insert(0, "arquivo", arquivo.name)
                df_dump.insert(1, "competencia", comp)
                df_dump["layout"] = layout
                df_dump["familia_layout"] = assin.familia_layout
                df_dump["sistema_provavel"] = assin.sistema_provavel
                eventos_dump.append(df_dump)

                # =========================
                # Devolvidas (reconstrução por exclusão)
                # =========================
                if base_of:
                    grupos = ["ativos", "desligados"] if layout == "ANALITICO" else ["total"]
                    for g in grupos:
                        devol, meta = reconstruir_por_exclusao(
                            df_eventos=df,
                            base_of=base_of,
                            grupo=g,
                            tol_abs=float(tol_max),
                        )
                        if not devol.empty:
                            devol = devol.copy()
                            devol.insert(0, "arquivo", arquivo.name)
                            devol.insert(1, "competencia", comp)
                            devol["layout"] = layout
                            devol["familia_layout"] = assin.familia_layout
                            devol["sistema_provavel"] = assin.sistema_provavel
                            devol["gap_grupo"] = meta.get("gap")
                            devol["base_oficial_grupo"] = meta.get("base_oficial")
                            devol["proventos_grupo"] = meta.get("proventos")
                            linhas_devolvidas.extend(devol.to_dict(orient="records"))

                # =========================
                # Mapa (por grupo)
                # =========================
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

                        # ✅ semáforo no mapa
                        agg = aplicar_semaforo_base(agg, modo="MAPA")

                        agg.insert(0, "arquivo", arquivo.name)
                        agg.insert(1, "competencia", comp)
                        agg.insert(2, "grupo", ("ATIVOS" if g == "ativos" else "DESLIGADOS" if g == "desligados" else "GLOBAL"))
                        agg.insert(3, "proventos_grupo", prov_total_g)
                        agg["layout"] = layout
                        agg["familia_layout"] = assin.familia_layout
                        agg["sistema_provavel"] = assin.sistema_provavel

                        linhas_mapa.extend(agg.to_dict(orient="records"))

    # =========================
    # Consolida DataFrames
    # =========================
    df_resumo = pd.DataFrame(linhas_resumo)
    df_devolvidas = pd.DataFrame(linhas_devolvidas)
    df_mapa = pd.DataFrame(linhas_mapa)
    df_eventos = pd.concat(eventos_dump, ignore_index=True) if eventos_dump else pd.DataFrame()

    # =========================
    # Radar estrutural (agregação)
    # =========================
    df_radar = pd.DataFrame()
    if radar_on and (not df_mapa.empty) and (not df_devolvidas.empty):
        # Agrega devolvidas por rubrica/grupo (meses/valor)
        d = df_devolvidas.copy()
        d["meses_devolvida"] = 1

        agg_dev = (
            d.groupby(["rubrica", "grupo"], as_index=False)
            .agg(
                meses_devolvida=("meses_devolvida", "sum"),
                valor_total_devolvido=("valor_devolvido", "sum"),
                valor_medio_devolvido=("valor_devolvido", "mean"),
            )
        )

        # Agrega mapa por rubrica/grupo (impacto e classificação mais comum)
        m = df_mapa.copy()
        m["total_periodos_no_lote"] = 1

        # classificação mais comum no mapa
        def _mode(series: pd.Series) -> str:
            if series.empty:
                return "SEM_CLASSIFICACAO"
            return series.value_counts().index[0]

        agg_mapa = (
            m.groupby(["rubrica", "grupo"], as_index=False)
            .agg(
                total_periodos_no_lote=("total_periodos_no_lote", "sum"),
                impacto_medio_pct=("impacto_pct_proventos", "mean"),
                impacto_max_pct=("impacto_pct_proventos", "max"),
                classificacao_mapa_mais_comum=("classificacao", _mode),
            )
        )

        # merge
        df_radar = agg_mapa.merge(agg_dev, on=["rubrica", "grupo"], how="left")
        df_radar["meses_devolvida"] = df_radar["meses_devolvida"].fillna(0).astype(int)
        df_radar["valor_total_devolvido"] = df_radar["valor_total_devolvido"].fillna(0.0)
        df_radar["valor_medio_devolvido"] = df_radar["valor_medio_devolvido"].fillna(0.0)

        # recorrência de “devolvida”
        df_radar["recorrencia_pct"] = df_radar.apply(
            lambda r: 100.0 * _safe_div(float(r["meses_devolvida"]), float(r["total_periodos_no_lote"])),
            axis=1,
        )

        # score risco simples (você pode ajustar)
        df_radar["score_risco"] = (df_radar["impacto_medio_pct"].fillna(0) * 1.2) + (df_radar["recorrencia_pct"].fillna(0) * 0.8)

        # classificação geral “mais comum” (fallback: do mapa)
        df_radar["classificacao_mais_comum"] = df_radar["classificacao_mapa_mais_comum"]

        # ✅ semáforo no radar
        df_radar = aplicar_semaforo_base(df_radar, modo="RADAR")

    # =========================
    # Interface – Tabs
    # =========================
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["📌 Resumo", "📋 Eventos", "🧩 Devolvidas", "🧭 Mapa de Incidência", "📡 Radar Estrutural"]
    )

    with tab1:
        st.subheader("📌 Resumo por Competência")
        if df_resumo.empty:
            st.warning("Não foi possível extrair resumo (sem competências/eventos).")
        else:
            st.dataframe(df_resumo.sort_values(["arquivo", "competencia"]), use_container_width=True)

    with tab2:
        st.subheader("📋 Eventos extraídos")
        if df_eventos.empty:
            st.warning("Nenhum evento extraído.")
        else:
            st.dataframe(df_eventos.sort_values(["arquivo", "competencia", "tipo", "total"], ascending=[True, True, True, False]),
                         use_container_width=True)

    with tab3:
        st.subheader("🧩 Rubricas devolvidas (reconstrução por exclusão)")
        if df_devolvidas.empty:
            st.info("Nenhuma devolvida detectada (ou base oficial não encontrada no PDF).")
        else:
            st.dataframe(
                df_devolvidas.sort_values(["arquivo", "competencia", "grupo", "valor_devolvido"],
                                          ascending=[True, True, True, False]),
                use_container_width=True
            )

    with tab4:
        st.subheader("🧭 Mapa de Incidência (peso dentro dos proventos)")
        if df_mapa.empty:
            st.info("Mapa vazio. Talvez não tenha proventos ou extração falhou.")
        else:
            colf1, colf2, colf3 = st.columns(3)
            with colf1:
                f_arquivo = st.selectbox("Arquivo", ["(todos)"] + sorted(df_mapa["arquivo"].unique().tolist()))
            with colf2:
                f_comp = st.selectbox("Competência", ["(todas)"] + sorted(df_mapa["competencia"].unique().tolist()))
            with colf3:
                f_grupo = st.selectbox("Grupo", ["(todos)"] + sorted(df_mapa["grupo"].unique().tolist()))

            view = df_mapa.copy()
            if f_arquivo != "(todos)":
                view = view[view["arquivo"] == f_arquivo]
            if f_comp != "(todas)":
                view = view[view["competencia"] == f_comp]
            if f_grupo != "(todos)":
                view = view[view["grupo"] == f_grupo]

            view = view.sort_values(["impacto_pct_proventos", "valor"], ascending=[False, False])

            st.dataframe(
                view[["zona_base", "rubrica", "classificacao", "valor", "impacto_pct_proventos",
                      "grupo", "competencia", "arquivo", "layout", "sistema_provavel"]],
                use_container_width=True
            )

    with tab5:
        st.subheader("📡 Radar Estrutural (priorização por recorrência + impacto + devolução)")
        if df_radar.empty:
            st.info("Radar indisponível (precisa de Mapa + Devolvidas).")
        else:
            colr1, colr2 = st.columns(2)
            with colr1:
                g_sel = st.selectbox("Grupo (Radar)", sorted(df_radar["grupo"].unique().tolist()))
            with colr2:
                topn = st.slider("Top N", min_value=10, max_value=200, value=50, step=10)

            v = df_radar[df_radar["grupo"] == g_sel].copy()

            # ordenação blindada (evita KeyError)
            for c in ["zona_base", "score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"]:
                if c not in v.columns:
                    v[c] = pd.NA

            v = v.sort_values(
                ["zona_base", "score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"],
                ascending=[True, False, False, False, False],
                na_position="last",
            ).head(int(topn))

            st.dataframe(
                v[["zona_base", "rubrica", "classificacao_mais_comum", "classificacao_mapa_mais_comum",
                   "meses_devolvida", "total_periodos_no_lote", "recorrencia_pct",
                   "impacto_medio_pct", "impacto_max_pct", "valor_total_devolvido", "score_risco"]],
                use_container_width=True
            )

    # =========================
    # Export Excel (openpyxl)
    # =========================
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_resumo.to_excel(writer, index=False, sheet_name="Resumo")
        df_eventos.to_excel(writer, index=False, sheet_name="Eventos")
        if not df_devolvidas.empty:
            df_devolvidas.to_excel(writer, index=False, sheet_name="Devolvidas")
        if not df_mapa.empty:
            df_mapa.to_excel(writer, index=False, sheet_name="Mapa")
        if not df_radar.empty:
            df_radar.to_excel(writer, index=False, sheet_name="Radar")

    buffer.seek(0)

    st.download_button(
        "📥 Baixar Excel – Auditoria Completa",
        data=buffer,
        file_name="AUDITORIA_BASE_INSS_COMPLETA.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

else:
    st.info("Envie um ou mais PDFs para iniciar.")
