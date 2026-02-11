import io
import re
import pdfplumber
import pandas as pd
import streamlit as st

# Seus módulos (layout analítico)
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

    # fallback: se não detectou colunas de grupos, assume resumo
    return "RESUMO"


# ---------------------------
# Extratores para layout RESUMO (GLOBAL)
# ---------------------------

def extrair_base_inss_global_texto(texto: str) -> float | None:
    """
    Tenta achar o melhor candidato de base INSS empresa em PDF de resumo.
    Aceita variações:
    - BASE INSS (EMPRESA)
    - BASE INSS EMPRESA
    - BASE INSS
    """
    if not texto:
        return None

    txt = texto.replace("\n", " ")
    # prioriza "BASE INSS ... EMPRESA"
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

    # Heurística: em resumo pode aparecer várias bases (diretores/autônomos),
    # mas a maior base costuma ser "empresa/funcionários" no consolidado.
    return float(max(candidatos))


def extrair_eventos_resumo_page(page) -> list[dict]:
    """
    Extrai eventos em RESUMO (GLOBAL) com heurística simples.
    - Se encontrar seções "VENCIMENTOS" e "DESCONTOS": classifica.
    - Se encontrar tabela "EVENTO DESCRICAO ... VALOR": classifica por seção.
    Saída no mesmo formato do analítico, mas com:
      ativos = valor, desligados = 0, total = valor
    """
    txt = page.extract_text() or ""
    if not txt.strip():
        return []

    linhas = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    eventos = []

    secao = None  # PROVENTO / DESCONTO
    for ln in linhas:
        l = ln.lower()

        # troca seção por cabeçalhos comuns
        if "vencimentos" in l or "proventos" in l:
            secao = "PROVENTO"
            continue
        if "descontos" in l:
            secao = "DESCONTO"
            continue

        # ignora linhas de base/cabeçalhos
        if "base inss" in l:
            continue
        if "resumo" in l and "folha" in l:
            continue
        if "total" in l and "geral" in l and ("venc" in l or "desc" in l):
            continue

        # tenta capturar: COD + DESCRICAO + VALOR (último número BR na linha)
        # Ex: "0001 ORDENADO  1.234,56"
        m_cod = re.match(r"^\s*(\d{3,6})\s+(.+)$", ln)
        if not m_cod:
            continue

        codigo = m_cod.group(1)
        resto = m_cod.group(2)

        # pega o último número BR da linha
        nums = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", resto)
        if not nums:
            continue

        valor = normalizar_valor_br(nums[-1])
        if valor is None:
            continue

        # descrição = resto sem o último número (e sem excesso)
        desc = resto
        # remove o último valor encontrado
        desc = re.sub(re.escape(nums[-1]) + r"\s*$", "", desc).strip()
        desc = re.sub(r"\s{2,}", " ", desc)

        # se não tiver seção, tenta inferir:
        # em muitos resumos descontos ficam depois de "DESCONTOS"
        tipo = secao if secao in ("PROVENTO", "DESCONTO") else "PROVENTO"

        rubrica = f"{codigo} {desc}".strip()

        eventos.append({
            "rubrica": rubrica,
            "tipo": tipo,
            "ativos": float(valor),
            "desligados": 0.0,
            "total": float(valor),
        })

    return eventos


def diagnostico_extracao_proventos(df_eventos: pd.DataFrame, tol_inconsistencia: float = 1.00) -> pd.DataFrame:
    """
    Diagnóstico interno baseado no que foi extraído (principalmente analítico).
    """
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

st.set_page_config(layout="wide")
st.title("🧾 Auditor INSS — Híbrido (Analítico + Resumos)")

arquivos = st.file_uploader("Envie 1 ou mais PDFs de folha", type="pdf", accept_multiple_files=True)

st.markdown("### Configurações")
col_cfg1, col_cfg2, col_cfg3, col_cfg4 = st.columns(4)
with col_cfg1:
    tol_totalizador = st.number_input("Tolerância totalizador (R$)", min_value=0.0, value=1.00, step=0.50)
with col_cfg2:
    banda_ok = st.number_input("Banda OK (|erro| ≤)", min_value=0.0, value=10.0, step=1.0)
with col_cfg3:
    banda_aceitavel = st.number_input("Banda ACEITÁVEL (|erro| ≤)", min_value=0.0, value=10000.0, step=100.0)
with col_cfg4:
    modo_auditor_prof = st.checkbox("🕵️ Auditor Profissional", value=True)

indice_incidencia_on = st.checkbox("📈 Índice de Incidência", value=True)
mapa_incidencia_on = st.checkbox("🧭 Mapa de Incidência (impacto %)", value=True)
radar_on = st.checkbox("📡 Radar Estrutural Automático", value=True)

st.info(
    "✅ **Detector Híbrido**: identifica automaticamente o layout do PDF.\n\n"
    "- **Analítico**: audita ATIVOS/DESLIGADOS (mais preciso).\n"
    "- **Resumo**: audita **GLOBAL** (base única), mantendo Mapa/Radar."
)

if arquivos:
    linhas_resumo = []
    linhas_devolvidas = []
    linhas_diagnostico = []
    linhas_mapa = []

    # Para export: também guardamos os eventos por competência/arquivo
    eventos_dump = []

    for arquivo in arquivos:
        with pdfplumber.open(arquivo) as pdf:
            # captura textos das 2 primeiras páginas para detectar layout
            texts = []
            for i, p in enumerate(pdf.pages[:2]):
                texts.append(p.extract_text() or "")
            layout = detectar_layout_pdf(texts)

            dados = {}
            comp_atual = None

            for page in pdf.pages:
                comp_atual = extrair_competencia_robusta(page, comp_atual)
                if not comp_atual:
                    # se não achou competência, ainda assim tenta agrupar como "SEM_COMP"
                    comp_atual = "SEM_COMP"

                dados.setdefault(comp_atual, {"eventos": [], "base_empresa": None, "totais_proventos_pdf": None})

                # base oficial:
                # - Analítico: páginas de bases + seu extrator
                # - Resumo: tenta extrator e fallback por texto
                if layout == "ANALITICO":
                    if pagina_eh_de_bases(page):
                        base = extrair_base_empresa_page(page)
                        if base and dados[comp_atual]["base_empresa"] is None:
                            dados[comp_atual]["base_empresa"] = base
                else:
                    # tenta pegar base por extrator (se ele funcionar), senão regex texto
                    if dados[comp_atual]["base_empresa"] is None:
                        try:
                            base = extrair_base_empresa_page(page)
                        except Exception:
                            base = None

                        if base:
                            dados[comp_atual]["base_empresa"] = base
                        else:
                            b = extrair_base_inss_global_texto(page.extract_text() or "")
                            if b is not None:
                                # padroniza como dict com chave "total"
                                dados[comp_atual]["base_empresa"] = {"total": float(b)}

                # totalizador (só faz sentido no analítico)
                if layout == "ANALITICO":
                    tot = extrair_totais_proventos_page(page)
                    if tot and dados[comp_atual]["totais_proventos_pdf"] is None:
                        dados[comp_atual]["totais_proventos_pdf"] = tot

                # eventos
                if layout == "ANALITICO":
                    try:
                        dados[comp_atual]["eventos"].extend(extrair_eventos_page(page))
                    except Exception:
                        # se falhar, tenta pelo resumo como fallback
                        dados[comp_atual]["eventos"].extend(extrair_eventos_resumo_page(page))
                else:
                    dados[comp_atual]["eventos"].extend(extrair_eventos_resumo_page(page))

        # ---------------- por competência ----------------
        for comp, info in dados.items():
            df = pd.DataFrame(info["eventos"])
            if df.empty:
                linhas_resumo.append({
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "layout": layout,
                    "grupo": "",
                    "status": "SEM_EVENTOS",
                })
                continue

            # garante colunas
            for c in ["rubrica", "tipo", "ativos", "desligados", "total"]:
                if c not in df.columns:
                    df[c] = 0.0 if c in ("ativos", "desligados", "total") else ""

            df["rubrica"] = df["rubrica"].astype(str)
            df["tipo"] = df["tipo"].astype(str)

            # normaliza numéricos
            for col in ["ativos", "desligados", "total"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            # remove duplicados
            df = df.drop_duplicates(subset=["rubrica", "tipo", "ativos", "desligados", "total"]).reset_index(drop=True)

            # classifica (ENTRA/NEUTRA/FORA) se possível
            try:
                _, df = calcular_base_por_grupo(df)
            except Exception:
                pass
            df = _safe_classificacao(df)

            # base oficial
            base_of = info["base_empresa"]

            # totais de proventos
            prov = df[df["tipo"] == "PROVENTO"].copy()
            tot_extraido = {
                "ativos": float(prov["ativos"].sum()),
                "desligados": float(prov["desligados"].sum()),
                "total": float(prov["total"].sum()),
            }

            # no resumo, a gente usa sempre "total" (GLOBAL)
            if layout != "ANALITICO":
                totais_usados = {"total": float(prov["total"].sum())}
            else:
                tot_pdf_comp = info.get("totais_proventos_pdf")
                totais_usados = tot_pdf_comp if tot_pdf_comp else tot_extraido

            # valida totalizador (só analítico)
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

            # dump para export
            df_dump = df.copy()
            df_dump.insert(0, "arquivo", arquivo.name)
            df_dump.insert(1, "competencia",i := comp, comp)  # mantém compatível
            df_dump["layout"] = layout
            eventos_dump.append(df_dump)

            # ---------------- Mapa de Incidência ----------------
            if mapa_incidencia_on:
                if layout == "ANALITICO":
                    grupos = ["ativos", "desligados"]
                else:
                    grupos = ["total"]  # GLOBAL

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

                    linhas_mapa.extend(agg.to_dict(orient="records"))

            # ---------------- Auditoria ----------------
            if layout == "ANALITICO":
                grupos_auditar = ["ativos", "desligados"]
            else:
                grupos_auditar = ["total"]  # GLOBAL

            for g in grupos_auditar:
                res = auditoria_por_exclusao_com_aproximacao(
                    df=df,
                    base_oficial=base_of,
                    totais_proventos=totais_usados,
                    grupo=g,
                    top_n_subset=44
                )

                base_exclusao = res.get("base_exclusao")
                gap = res.get("gap")
                base_aprox = res.get("base_aprox_por_baixo")
                erro = res.get("erro_por_baixo")

                proventos_g = float(totais_usados.get(g, 0.0) or 0.0)

                # base oficial por grupo
                if not base_of:
                    base_of_g = None
                else:
                    # analítico: base_of pode ter ativos/desligados/total
                    # resumo: base_of vira {"total": ...}
                    base_of_g = base_of.get(g) if isinstance(base_of, dict) else None
                    if base_of_g is None and isinstance(base_of, dict):
                        # fallback: usa total
                        base_of_g = base_of.get("total")

                indice_incidencia = None
                gap_bruto = None
                if indice_incidencia_on and base_of_g is not None and proventos_g > 0:
                    base_of_gf = float(base_of_g)
                    indice_incidencia = base_of_gf / proventos_g
                    gap_bruto = proventos_g - base_of_gf

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

                    "base_exclusao": base_exclusao,
                    "gap": gap,
                    "base_aprox_por_baixo": base_aprox,
                    "erro_por_baixo": erro,

                    "status": status
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
                            "valor": float(r.get("valor_alvo", 0.0) or 0.0)
                        })

            # Diagnóstico quando falhar totalizador
            if modo_auditor_prof and layout == "ANALITICO" and totalizador_encontrado and bate_totalizador is False:
                diag = diagnostico_extracao_proventos(df, tol_inconsistencia=max(1.0, tol_totalizador))
                if not diag.empty:
                    diag_top = diag.head(50).copy()
                    diag_top.insert(0, "arquivo", arquivo.name)
                    diag_top.insert(1, "competencia", comp)
                    diag_top.insert(2, "layout", layout)
                    diag_top.insert(3, "dif_totalizador_ativos", dif_totalizador_ativos)
                    diag_top.insert(4, "dif_totalizador_desligados", dif_totalizador_desligados)
                    linhas_diagnostico.extend(diag_top.to_dict(orient="records"))

    # ---------------- DataFrames finais ----------------
    df_resumo = pd.DataFrame(linhas_resumo)
    df_devolvidas = pd.DataFrame(linhas_devolvidas)
    df_diag = pd.DataFrame(linhas_diagnostico)
    df_mapa = pd.DataFrame(linhas_mapa)
    df_eventos_dump = pd.concat(eventos_dump, ignore_index=True) if eventos_dump else pd.DataFrame()

    # ---------------- RADAR (ATIVOS/DESLIGADOS/GLOBAL) ----------------
    df_radar = pd.DataFrame()
    if radar_on and (not df_devolvidas.empty or not df_mapa.empty) and not df_resumo.empty:
        base_periodos = df_resumo[df_resumo["grupo"].isin(["ATIVOS", "DESLIGADOS", "GLOBAL"])].copy()
        base_periodos["chave_periodo"] = base_periodos["arquivo"].astype(str) + " | " + base_periodos["competencia"].astype(str) + " | " + base_periodos["grupo"].astype(str)
        tot_periodos = base_periodos.groupby("grupo")["chave_periodo"].nunique().to_dict()

        # Devolvidas: recorrência
        if not df_devolvidas.empty:
            d = df_devolvidas.copy()
            d["chave_periodo"] = d["arquivo"].astype(str) + " | " + d["competencia"].astype(str)

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

        # Mapa: impacto médio
        if not df_mapa.empty:
            m = df_mapa.copy()
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

        # ordenação default robusta
        for c in ["score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"]:
            if c not in df_radar.columns:
                df_radar[c] = pd.NA

        df_radar = df_radar.sort_values(
            ["score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"],
            ascending=[False, False, False, False],
            na_position="last"
        ).reset_index(drop=True)

    # ---------------- Abas ----------------
    tab_resumo, tab_eventos, tab_devolvidas, tab_mapa, tab_radar, tab_diag = st.tabs(
        ["📌 Resumo", "📋 Eventos", "🧩 Devolvidas", "🧭 Mapa", "📡 Radar", "🕵️ Diagnóstico"]
    )

    with tab_resumo:
        st.subheader("📌 Resumo consolidado")
        if df_resumo.empty:
            st.info("Sem dados no resumo.")
        else:
            status_opts = sorted(df_resumo["status"].dropna().unique().tolist())
            status_sel = st.multiselect("Mostrar status:", options=status_opts, default=status_opts, key="status_filter")
            view = df_resumo[df_resumo["status"].isin(status_sel)].copy()
            st.dataframe(view.sort_values(["competencia", "arquivo", "layout", "grupo"]), use_container_width=True)

    with tab_eventos:
        st.subheader("📋 Eventos extraídos (todas as competências)")
        if df_eventos_dump.empty:
            st.info("Sem eventos extraídos.")
        else:
            colA, colB = st.columns(2)
            with colA:
                layouts = sorted(df_eventos_dump["layout"].dropna().unique().tolist())
                lay_sel = st.multiselect("Layout", layouts, default=layouts)
            with colB:
                tipos = sorted(df_eventos_dump["tipo"].dropna().unique().tolist())
                tipo_sel = st.multiselect("Tipo", tipos, default=tipos)
            v = df_eventos_dump[
                (df_eventos_dump["layout"].isin(lay_sel)) &
                (df_eventos_dump["tipo"].isin(tipo_sel))
            ].copy()
            st.dataframe(v.head(5000), use_container_width=True)

    with tab_devolvidas:
        st.subheader("🧩 Rubricas devolvidas")
        if df_devolvidas.empty:
            st.info("Nenhuma rubrica devolvida (ou sem base/GAP positivo).")
        else:
            st.dataframe(df_devolvidas.sort_values(["competencia", "arquivo", "grupo", "valor"], ascending=[True, True, True, False]),
                         use_container_width=True)

    with tab_mapa:
        st.subheader("🧭 Mapa de Incidência — impacto (%)")
        if df_mapa.empty:
            st.info("Mapa vazio.")
        else:
            comps = sorted(df_mapa["competencia"].unique().tolist())
            grupos = sorted(df_mapa["grupo"].unique().tolist())

            colA, colB, colC = st.columns(3)
            with colA:
                comp_sel = st.selectbox("Competência", comps, index=len(comps) - 1, key="map_comp")
            with colB:
                grupo_sel = st.selectbox("Grupo", grupos, index=0, key="map_grupo")
            with colC:
                topn = st.number_input("Top N", min_value=10, max_value=500, value=50, step=10, key="map_topn")

            class_opts = sorted(df_mapa["classificacao"].unique().tolist())
            class_sel = st.multiselect("Classificação", class_opts, default=class_opts, key="map_class")

            view = df_mapa[
                (df_mapa["competencia"] == comp_sel) &
                (df_mapa["grupo"] == grupo_sel) &
                (df_mapa["classificacao"].isin(class_sel))
            ].copy()

            view = view.sort_values(["impacto_pct_proventos", "valor"], ascending=[False, False]).head(int(topn))
            st.dataframe(view[["rubrica", "classificacao", "valor", "impacto_pct_proventos", "proventos_grupo", "arquivo", "layout"]],
                         use_container_width=True)

    with tab_radar:
        st.subheader("📡 Radar Estrutural Automático")
        st.caption("Cruza **recorrência** (devolvidas) + **impacto (%)** (mapa). Não prova erro; prioriza investigação.")

        if df_radar.empty:
            st.info("Radar vazio (precisa de devolvidas e/ou mapa).")
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

            # garante colunas (evita KeyError)
            colunas_criticas = [
                "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido",
                "score_risco", "classificacao_mais_comum", "classificacao_mapa_mais_comum"
            ]
            for c in colunas_criticas:
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
                st.info("Nenhuma rubrica atende aos filtros atuais.")
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
        st.subheader("🕵️ Diagnóstico de Extração (apenas Analítico)")
        if df_diag.empty:
            st.info("Sem diagnósticos (ou sem falhas de totalizador).")
        else:
            st.dataframe(df_diag, use_container_width=True)

    # ---------------- Excel consolidado ----------------
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_resumo.to_excel(writer, index=False, sheet_name="Resumo_Qualidade")
        df_eventos_dump.to_excel(writer, index=False, sheet_name="Eventos_Extraidos")
        df_devolvidas.to_excel(writer, index=False, sheet_name="Rubricas_Devolvidas")
        df_mapa.to_excel(writer, index=False, sheet_name="Mapa_Incidencia")
        df_radar.to_excel(writer, index=False, sheet_name="Radar_Estrutural")
        df_diag.to_excel(writer, index=False, sheet_name="Diagnostico_Extracao")

    buffer.seek(0)
    st.download_button(
        "📥 Baixar Excel consolidado (Híbrido)",
        data=buffer,
        file_name="AUDITOR_INSS_HIBRIDO.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
