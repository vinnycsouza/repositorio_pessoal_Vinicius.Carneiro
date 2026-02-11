import io
import re
import pdfplumber
import pandas as pd
import streamlit as st

from extrator_pdf import extrair_eventos_page, extrair_base_empresa_page, pagina_eh_de_bases
from calculo_base import calcular_base_por_grupo
from auditor_base import auditoria_por_exclusao_com_aproximacao


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


# ----------------- util -----------------

def normalizar_valor_br(txt: str):
    try:
        return float(txt.replace(".", "").replace(",", "."))
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

    # 2) jan/21
    m = re.search(r"\b([a-zç]{3,9})\s*/\s*(\d{2})\b", txt)
    if m:
        mes_txt = m.group(1).replace("ç", "c")
        ano2 = m.group(2)
        if mes_txt in MESES:
            return f"{MESES[mes_txt]}/20{ano2}"

    # 3) janeiro 2021
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
    Extrai: TOTAIS PROVENTOS ativos desligados total (valores BR)
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


def diagnostico_extracao_proventos(df_eventos: pd.DataFrame, tol_inconsistencia: float = 1.00) -> pd.DataFrame:
    """
    Diagnóstico interno baseado no que foi extraído.
    Aponta inconsistências típicas de coluna grudada/quebra de linha.
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


def _safe_classificacao(df: pd.DataFrame) -> pd.DataFrame:
    if "classificacao" not in df.columns:
        df["classificacao"] = "SEM_CLASSIFICACAO"
    df["classificacao"] = df["classificacao"].fillna("SEM_CLASSIFICACAO").astype(str)
    return df


def _mode_or_none(series: pd.Series):
    if series is None or series.empty:
        return None
    vc = series.value_counts()
    return vc.index[0] if len(vc) else None


# ---------------- UI ----------------

st.set_page_config(layout="wide")
st.title("🧾 Auditor INSS — Auditor Estrutural (ATIVOS + DESLIGADOS) | 60+ PDFs")

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

indice_incidencia_on = st.checkbox("📈 Índice de Incidência Estrutural", value=True)
mapa_incidencia_on = st.checkbox("🧭 Mapa de Incidência (impacto %)", value=True)
radar_on = st.checkbox("📡 Radar Estrutural Automático (recorrência + impacto)", value=True)

st.info(
    "🧠 **Auditor Estrutural:** auditoria por **ATIVOS** e **DESLIGADOS** (Salário Contribuição Empresa). "
    "O **TOTAL** é só referência (pode incluir AFASTADOS/ajustes internos)."
)

if arquivos:
    linhas_resumo = []
    linhas_devolvidas = []
    linhas_diagnostico = []
    linhas_mapa = []

    for arquivo in arquivos:
        with pdfplumber.open(arquivo) as pdf:
            dados = {}
            comp_atual = None

            for page in pdf.pages:
                comp_atual = extrair_competencia_robusta(page, comp_atual)
                if not comp_atual:
                    continue

                dados.setdefault(comp_atual, {"eventos": [], "base_empresa": None, "totais_proventos_pdf": None})

                # totalizador só com competência explícita na página
                tot = extrair_totais_proventos_page(page)
                if tot:
                    comp_na_pagina = extrair_competencia_sem_fallback(page)
                    if comp_na_pagina:
                        dados.setdefault(comp_na_pagina, {"eventos": [], "base_empresa": None, "totais_proventos_pdf": None})
                        if dados[comp_na_pagina]["totais_proventos_pdf"] is None:
                            dados[comp_na_pagina]["totais_proventos_pdf"] = tot

                # base oficial
                if pagina_eh_de_bases(page):
                    base = extrair_base_empresa_page(page)
                    if base and dados[comp_atual]["base_empresa"] is None:
                        dados[comp_atual]["base_empresa"] = base

                # eventos
                dados[comp_atual]["eventos"].extend(extrair_eventos_page(page))

        # por competência
        for comp, info in dados.items():
            df = pd.DataFrame(info["eventos"])
            if df.empty:
                linhas_resumo.append({
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "grupo": "",
                    "status": "SEM_EVENTOS",
                })
                continue

            df = df.drop_duplicates(subset=["rubrica", "tipo", "ativos", "desligados", "total"]).reset_index(drop=True)

            # classifica rubricas (ENTRA/NEUTRA/FORA) — se disponível
            try:
                _, df = calcular_base_por_grupo(df)
            except Exception:
                pass

            df = _safe_classificacao(df)

            # numéricos
            for col in ["ativos", "desligados", "total"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            base_of = info["base_empresa"]

            prov = df[df["tipo"] == "PROVENTO"].copy()
            tot_extraido = {
                "ativos": float(prov["ativos"].sum()),
                "desligados": float(prov["desligados"].sum()),
                "total": float(prov["total"].sum()),
            }

            tot_pdf_comp = info.get("totais_proventos_pdf")
            totais_usados = tot_pdf_comp if tot_pdf_comp else tot_extraido

            totalizador_encontrado = tot_pdf_comp is not None
            bate_totalizador = None
            dif_totalizador_ativos = None
            dif_totalizador_desligados = None

            # Auditor Estrutural: valida totalizador só por ATIVOS/DESLIGADOS
            if totalizador_encontrado:
                dif_totalizador_ativos = float(tot_pdf_comp["ativos"] - tot_extraido["ativos"])
                dif_totalizador_desligados = float(tot_pdf_comp["desligados"] - tot_extraido["desligados"])
                bate_totalizador = (
                    abs(dif_totalizador_ativos) <= tol_totalizador and
                    abs(dif_totalizador_desligados) <= tol_totalizador
                )

            # ---------------- Mapa de Incidência ----------------
            if mapa_incidencia_on:
                for grupo in ["ativos", "desligados"]:
                    prov_total_grupo = float(totais_usados.get(grupo, 0.0) or 0.0)
                    if prov_total_grupo <= 0:
                        continue

                    tmp = df[df["tipo"] == "PROVENTO"].copy()
                    agg = (
                        tmp.groupby(["rubrica", "classificacao"], as_index=False)[grupo]
                        .sum()
                        .rename(columns={grupo: "valor"})
                    )
                    agg = agg[agg["valor"] != 0].copy()
                    if agg.empty:
                        continue

                    agg["impacto_pct_proventos"] = (agg["valor"] / prov_total_grupo) * 100.0
                    agg.insert(0, "arquivo", arquivo.name)
                    agg.insert(1, "competencia", comp)
                    agg.insert(2, "grupo", grupo.upper())
                    agg.insert(3, "proventos_grupo", prov_total_grupo)

                    linhas_mapa.extend(agg.to_dict(orient="records"))

            # ---------------- Auditoria SOMENTE ATIVOS/DESLIGADOS ----------------
            for grupo in ["ativos", "desligados"]:
                res = auditoria_por_exclusao_com_aproximacao(
                    df=df,
                    base_oficial=base_of,
                    totais_proventos=totais_usados,
                    grupo=grupo,
                    top_n_subset=44
                )

                base_exclusao = res["base_exclusao"]
                gap = res["gap"]
                base_aprox = res["base_aprox_por_baixo"]
                erro = res["erro_por_baixo"]

                # ---- Índice de incidência estrutural ----
                proventos_grupo = float(totais_usados.get(grupo, 0.0) or 0.0)
                base_of_grupo = None if not base_of else base_of.get(grupo)

                indice_incidencia = None
                gap_bruto_prov_menos_base = None

                if indice_incidencia_on and base_of_grupo is not None and proventos_grupo > 0:
                    base_of_grupo_f = float(base_of_grupo)
                    indice_incidencia = base_of_grupo_f / proventos_grupo
                    gap_bruto_prov_menos_base = proventos_grupo - base_of_grupo_f

                # ---- Status por bandas ----
                erro_abs = None if erro is None else abs(float(erro))

                if not base_of:
                    status = "INCOMPLETO_BASE"
                elif totalizador_encontrado and bate_totalizador is False:
                    status = "FALHA_EXTRACAO_TOTALIZADOR"
                elif erro_abs is None:
                    status = "SEM_ERRO"
                elif erro_abs <= banda_ok:
                    status = "OK"
                elif erro_abs <= banda_aceitavel:
                    status = "ACEITAVEL"
                else:
                    status = "RUIM"

                linhas_resumo.append({
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "grupo": grupo.upper(),

                    "totalizador_encontrado": totalizador_encontrado,
                    "bate_totalizador": bate_totalizador,
                    "dif_totalizador_ativos": dif_totalizador_ativos,
                    "dif_totalizador_desligados": dif_totalizador_desligados,

                    "proventos_grupo": proventos_grupo,
                    "base_oficial": None if not base_of else base_of.get(grupo),

                    "indice_incidencia": indice_incidencia,
                    "gap_bruto_prov_menos_base": gap_bruto_prov_menos_base,

                    "base_exclusao": base_exclusao,
                    "gap": gap,
                    "base_aprox_por_baixo": base_aprox,
                    "erro_por_baixo": erro,

                    "status": status
                })

                devolvidas = res["rubricas_devolvidas"]
                if devolvidas is not None and not devolvidas.empty:
                    for _, r in devolvidas.iterrows():
                        linhas_devolvidas.append({
                            "arquivo": arquivo.name,
                            "competencia": comp,
                            "grupo": grupo.upper(),
                            "rubrica": r.get("rubrica"),
                            "classificacao_origem": r.get("classificacao"),
                            "valor": float(r.get("valor_alvo", 0.0) or 0.0)
                        })

            # TOTAL apenas referência (não audita)
            linhas_resumo.append({
                "arquivo": arquivo.name,
                "competencia": comp,
                "grupo": "TOTAL_REF",

                "totalizador_encontrado": totalizador_encontrado,
                "bate_totalizador": bate_totalizador,
                "dif_totalizador_ativos": dif_totalizador_ativos,
                "dif_totalizador_desligados": dif_totalizador_desligados,

                "proventos_grupo": float(totais_usados.get("total", 0.0) or 0.0),
                "base_oficial": None if not base_of else base_of.get("total"),

                "indice_incidencia": None,
                "gap_bruto_prov_menos_base": None,

                "base_exclusao": None,
                "gap": None,
                "base_aprox_por_baixo": None,
                "erro_por_baixo": None,

                "status": "REFERENCIA"
            })

            # Diagnóstico quando falhar totalizador (por competência)
            if modo_auditor_prof and totalizador_encontrado and bate_totalizador is False:
                diag = diagnostico_extracao_proventos(df, tol_inconsistencia=max(1.0, tol_totalizador))
                if not diag.empty:
                    diag_top = diag.head(50).copy()
                    diag_top.insert(0, "arquivo", arquivo.name)
                    diag_top.insert(1, "competencia", comp)
                    diag_top.insert(2, "dif_totalizador_ativos", dif_totalizador_ativos)
                    diag_top.insert(3, "dif_totalizador_desligados", dif_totalizador_desligados)
                    linhas_diagnostico.extend(diag_top.to_dict(orient="records"))

    # ---------------- saída consolidada ----------------
    df_resumo = pd.DataFrame(linhas_resumo)
    df_devolvidas = pd.DataFrame(linhas_devolvidas)
    df_diag = pd.DataFrame(linhas_diagnostico)
    df_mapa = pd.DataFrame(linhas_mapa)

    # ---------------- RADAR ESTRUTURAL AUTOMÁTICO ----------------
    df_radar = pd.DataFrame()
    if radar_on and (not df_devolvidas.empty or not df_mapa.empty) and not df_resumo.empty:
        # Denominador: quantas competências por grupo (ATIVOS/DESLIGADOS) existem no lote
        base_periodos = df_resumo[df_resumo["grupo"].isin(["ATIVOS", "DESLIGADOS"])].copy()
        base_periodos["chave_periodo"] = base_periodos["arquivo"].astype(str) + " | " + base_periodos["competencia"].astype(str)
        tot_periodos = base_periodos.groupby("grupo")["chave_periodo"].nunique().to_dict()

        # Devolvidas: recorrência por rubrica
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
                lambda r: (r["meses_devolvida"] / r["total_periodos_no_lote"] * 100.0) if r["total_periodos_no_lote"] > 0 else None,
                axis=1
            )
        else:
            agg_dev = pd.DataFrame(columns=[
                "grupo", "rubrica", "meses_devolvida", "valor_total_devolvido",
                "valor_medio_devolvido", "classificacao_mais_comum",
                "total_periodos_no_lote", "recorrencia_pct"
            ])

        # Mapa: impacto médio e classificação mais comum (ENTRA/NEUTRA/FORA)
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

        # Merge
        df_radar = pd.merge(agg_dev, agg_mapa, on=["grupo", "rubrica"], how="outer")

        # Score de risco estrutural (heurística):
        # recorrência (%) * impacto_médio(%) => quanto é recorrente e relevante
        def _score(row):
            rec = row.get("recorrencia_pct")
            imp = row.get("impacto_medio_pct")
            if pd.isna(rec) or pd.isna(imp):
                return None
            return float(rec) * float(imp)

        df_radar["score_risco"] = df_radar.apply(_score, axis=1)

        # ordenação default
        df_radar = df_radar.sort_values(
            ["score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"],
            ascending=[False, False, False, False]
        ).reset_index(drop=True)

    # ---------------- Abas do app ----------------
    tab_resumo, tab_devolvidas, tab_mapa, tab_radar, tab_diag = st.tabs(
        ["📌 Resumo", "🧩 Devolvidas", "🧭 Mapa", "📡 Radar", "🕵️ Diagnóstico"]
    )

    with tab_resumo:
        st.subheader("Filtro de status")
        status_opts = sorted(df_resumo["status"].dropna().unique().tolist())
        status_sel = st.multiselect("Mostrar status:", options=status_opts, default=status_opts, key="status_filter")

        df_view = df_resumo[df_resumo["status"].isin(status_sel)].copy()
        st.subheader("📌 Resumo consolidado (ATIVOS/DESLIGADOS auditáveis + TOTAL_REF)")
        st.dataframe(
            df_view.sort_values(["competencia", "arquivo", "grupo"], ascending=True),
            use_container_width=True
        )

    with tab_devolvidas:
        st.subheader("🧩 Rubricas devolvidas (NEUTRA/FORA que o algoritmo usou para reduzir o GAP)")
        if df_devolvidas.empty:
            st.info("Nenhuma rubrica foi devolvida (ou não havia base oficial/GAP positivo).")
        else:
            st.dataframe(
                df_devolvidas.sort_values(["competencia", "arquivo", "grupo", "valor"], ascending=[True, True, True, False]),
                use_container_width=True
            )

    with tab_mapa:
        st.subheader("🧭 Mapa de Incidência — impacto das rubricas nos Proventos")
        st.caption(
            "Mostra o **peso (%)** das rubricas nos proventos por competência e grupo (ATIVOS/DESLIGADOS), "
            "usando a classificação ENTRA/NEUTRA/FORA."
        )
        if df_mapa.empty:
            st.info("Mapa vazio (sem dados de proventos).")
        else:
            comps = sorted(df_mapa["competencia"].unique().tolist())
            grupos = ["ATIVOS", "DESLIGADOS"]

            colA, colB, colC = st.columns(3)
            with colA:
                comp_sel = st.selectbox("Competência", comps, index=len(comps) - 1, key="map_comp")
            with colB:
                grupo_sel = st.selectbox("Grupo", grupos, index=0, key="map_grupo")
            with colC:
                topn = st.number_input("Top N rubricas", min_value=10, max_value=500, value=50, step=10, key="map_topn")

            class_opts = sorted(df_mapa["classificacao"].unique().tolist())
            class_sel = st.multiselect("Classificação", class_opts, default=class_opts, key="map_class")

            view = df_mapa[
                (df_mapa["competencia"] == comp_sel) &
                (df_mapa["grupo"] == grupo_sel) &
                (df_mapa["classificacao"].isin(class_sel))
            ].copy()

            view = view.sort_values(["impacto_pct_proventos", "valor"], ascending=[False, False]).head(int(topn))

            st.dataframe(
                view[["rubrica", "classificacao", "valor", "impacto_pct_proventos", "proventos_grupo", "arquivo"]],
                use_container_width=True
            )

            st.markdown("#### Totais por classificação")
            resumo_cls = (
                df_mapa[(df_mapa["competencia"] == comp_sel) & (df_mapa["grupo"] == grupo_sel)]
                .groupby("classificacao", as_index=False)[["valor", "impacto_pct_proventos"]]
                .sum()
                .sort_values("impacto_pct_proventos", ascending=False)
            )
            st.dataframe(resumo_cls, use_container_width=True)

    with tab_radar:
        st.subheader("📡 Radar Estrutural Automático")
        st.caption(
            "O Radar cruza **recorrência das devolvidas** (quantos meses a rubrica aparece como 'necessária' para fechar base) "
            "com **impacto (%)** do Mapa. Isso NÃO prova erro: ele prioriza onde investigar primeiro."
        )

        if df_radar.empty:
            st.info("Radar vazio (precisa de devolvidas e/ou mapa).")
        else:
            grupos = ["ATIVOS", "DESLIGADOS"]
            colA, colB, colC = st.columns(3)
            with colA:
                g_sel = st.selectbox("Grupo", grupos, index=0, key="rad_grupo")
            with colB:
                min_rec = st.slider("Recorrência mínima (%)", min_value=0, max_value=100, value=30, step=5, key="rad_minrec")
            with colC:
                topn = st.number_input("Top N (Radar)", min_value=10, max_value=500, value=50, step=10, key="rad_topn")

            v = df_radar[df_radar["grupo"] == g_sel].copy()
            v = v[v["recorrencia_pct"].fillna(0) >= float(min_rec)]

            # foco em rubricas FORA/NEUTRA (onde costuma existir crédito)
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

            v = v.sort_values(
                ["score_risco", "recorrencia_pct", "impacto_medio_pct", "valor_total_devolvido"],
                ascending=[False, False, False, False]
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

            st.markdown("#### Interpretação rápida")
            st.write(
                "- **Recorrência alta + Impacto alto** → melhor candidato para revisão (potencial crédito recorrente).\n"
                "- **Recorrência alta + Impacto baixo** → pode ser ruído distribuído (muitas rubricas pequenas).\n"
                "- **Impacto alto + Recorrência baixa** → evento pontual (rescisão, férias coletivas etc.)."
            )

    with tab_diag:
        st.subheader("🕵️ Diagnóstico de Extração")
        st.caption("Aqui aparecem **linhas suspeitas de extração** (coluna quebrada/total inconsistente). Não é base.")

        if not modo_auditor_prof:
            st.info("Ative 'Auditor Profissional' nas configurações.")
        else:
            falhas = df_resumo[
                (df_resumo["status"] == "FALHA_EXTRACAO_TOTALIZADOR") &
                (df_resumo["grupo"].isin(["ATIVOS", "DESLIGADOS"]))
            ].copy()

            if falhas.empty:
                st.success("Nenhuma competência com FALHA_EXTRACAO_TOTALIZADOR (ATIVOS/DESLIGADOS).")
            else:
                st.dataframe(
                    falhas.sort_values(["competencia", "arquivo", "grupo"], ascending=True)[
                        ["arquivo", "competencia", "grupo", "dif_totalizador_ativos", "dif_totalizador_desligados",
                         "proventos_grupo", "base_oficial"]
                    ],
                    use_container_width=True
                )

            if df_diag.empty:
                st.info("Sem linhas suspeitas internas (pode ser rubrica faltando não extraída).")
            else:
                st.markdown("#### Linhas suspeitas (Top 50 por competência)")
                st.dataframe(df_diag, use_container_width=True)

    # ---------------- Excel consolidado ----------------
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_resumo.to_excel(writer, index=False, sheet_name="Resumo_Qualidade")
        df_devolvidas.to_excel(writer, index=False, sheet_name="Rubricas_Devolvidas")
        if mapa_incidencia_on:
            df_mapa.to_excel(writer, index=False, sheet_name="Mapa_Incidencia")
        if radar_on:
            df_radar.to_excel(writer, index=False, sheet_name="Radar_Estrutural")
        if modo_auditor_prof:
            df_diag.to_excel(writer, index=False, sheet_name="Diagnostico_Extracao")

    buffer.seek(0)
    st.download_button(
        "📥 Baixar Excel consolidado (Auditor + Mapa + Radar)",
        data=buffer,
        file_name="AUDITOR_INSS_ESTRUTURAL_RADAR.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
