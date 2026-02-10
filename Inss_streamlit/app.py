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
    Gera uma tabela de 'suspeitas' de extração com base no que foi extraído.
    Não adivinha rubrica faltante (isso não dá), mas aponta inconsistências internas.
    """
    df = df_eventos.copy()
    if df.empty:
        return df

    # garante numéricos
    for col in ["ativos", "desligados", "total"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # foca em proventos (onde fica o totalizador)
    df = df[df["tipo"] == "PROVENTO"].copy()
    if df.empty:
        return df

    df["soma_partes"] = df["ativos"] + df["desligados"]
    df["delta_total_vs_partes"] = (df["total"] - df["soma_partes"]).abs()

    # flags típicas de PDF “grudado”
    df["flag_inconsistencia_total"] = df["delta_total_vs_partes"] > tol_inconsistencia
    df["flag_total_sem_partes"] = (df["total"] > 0) & (df["ativos"] == 0) & (df["desligados"] == 0)
    df["flag_partes_sem_total"] = ((df["ativos"] > 0) | (df["desligados"] > 0)) & (df["total"] == 0)

    # rubrica “estranha”
    rub = df["rubrica"].fillna("").astype(str)
    df["flag_rubrica_curta"] = rub.str.len() <= 6
    df["flag_rubrica_somente_num"] = rub.str.match(r"^\s*\d+\s*$")

    # score de suspeita
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
    df = df[cols_out].sort_values(["score_suspeita", "delta_total_vs_partes", "total"], ascending=[False, False, False])
    return df


# ---------------- UI ----------------

st.set_page_config(layout="wide")
st.title("🧾 Auditor INSS — Lote (60+ PDFs) | Qualidade + Aproximação por Baixo")

arquivos = st.file_uploader("Envie 1 ou mais PDFs de folha", type="pdf", accept_multiple_files=True)

st.markdown("### Configurações")
col_cfg1, col_cfg2, col_cfg3 = st.columns(3)
with col_cfg1:
    tol_totalizador = st.number_input("Tolerância p/ 'bater totalizador' (R$)", min_value=0.0, value=1.00, step=0.50)
with col_cfg2:
    tol_erro_aprox = st.number_input("Tolerância desejada p/ erro da aproximação (R$)", min_value=0.0, value=5.00, step=1.00)
with col_cfg3:
    modo_auditor_prof = st.checkbox("🕵️ Modo Auditor Profissional", value=True)

if arquivos:
    linhas_resumo = []
    linhas_devolvidas = []
    linhas_diagnostico = []  # consolidado

    for arquivo in arquivos:
        with pdfplumber.open(arquivo) as pdf:
            dados = {}
            comp_atual = None

            for page in pdf.pages:
                # competência p/ anexar eventos (pode usar fallback)
                comp_atual = extrair_competencia_robusta(page, comp_atual)
                if not comp_atual:
                    continue

                dados.setdefault(comp_atual, {"eventos": [], "base_empresa": None, "totais_proventos_pdf": None})

                # ✅ totalizador só se competência aparece NA PÁGINA (sem fallback)
                tot = extrair_totais_proventos_page(page)
                if tot:
                    comp_na_pagina = extrair_competencia_sem_fallback(page)
                    if comp_na_pagina:
                        dados.setdefault(comp_na_pagina, {"eventos": [], "base_empresa": None, "totais_proventos_pdf": None})
                        if dados[comp_na_pagina]["totais_proventos_pdf"] is None:
                            dados[comp_na_pagina]["totais_proventos_pdf"] = tot

                # base oficial (páginas de bases)
                if pagina_eh_de_bases(page):
                    base = extrair_base_empresa_page(page)
                    if base and dados[comp_atual]["base_empresa"] is None:
                        dados[comp_atual]["base_empresa"] = base

                # eventos (páginas de eventos)
                dados[comp_atual]["eventos"].extend(extrair_eventos_page(page))

        # processa por competência
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

            # classifica rubricas (FORA/NEUTRA/ENTRA)
            try:
                _, df = calcular_base_por_grupo(df)
            except Exception:
                # sem quebrar o lote
                pass

            base_of = info["base_empresa"]

            prov = df[df["tipo"] == "PROVENTO"].copy()
            tot_extraido = {
                "ativos": float(pd.to_numeric(prov["ativos"], errors="coerce").fillna(0).sum()),
                "desligados": float(pd.to_numeric(prov["desligados"], errors="coerce").fillna(0).sum()),
                "total": float(pd.to_numeric(prov["total"], errors="coerce").fillna(0).sum()),
            }

            tot_pdf_comp = info.get("totais_proventos_pdf")
            totais_usados = tot_pdf_comp if tot_pdf_comp else tot_extraido

            totalizador_encontrado = tot_pdf_comp is not None
            bate_totalizador = None
            dif_totalizador_ativos = None
            dif_totalizador_desligados = None
            dif_totalizador_total = None

            if totalizador_encontrado:
                dif_totalizador_ativos = float(tot_pdf_comp["ativos"] - tot_extraido["ativos"])
                dif_totalizador_desligados = float(tot_pdf_comp["desligados"] - tot_extraido["desligados"])
                dif_totalizador_total = float(tot_pdf_comp["total"] - tot_extraido["total"])

                bate_totalizador = (
                    abs(dif_totalizador_ativos) <= tol_totalizador and
                    abs(dif_totalizador_desligados) <= tol_totalizador and
                    abs(dif_totalizador_total) <= tol_totalizador
                )

            # Auditoria por grupo + aproximação
            for grupo in ["ativos", "desligados", "total"]:
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

                if not base_of:
                    status = "INCOMPLETO_BASE"
                elif totalizador_encontrado and bate_totalizador is False:
                    status = "FALHA_EXTRACAO_TOTALIZADOR"
                else:
                    if erro is not None and erro >= 0 and erro <= tol_erro_aprox:
                        status = "OK_APROX"
                    else:
                        status = "ATENCAO"

                linhas_resumo.append({
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "grupo": grupo.upper(),
                    "totalizador_encontrado": totalizador_encontrado,
                    "bate_totalizador": bate_totalizador,
                    "dif_totalizador_ativos": dif_totalizador_ativos,
                    "dif_totalizador_desligados": dif_totalizador_desligados,
                    "dif_totalizador_total": dif_totalizador_total,
                    "tot_proventos_usado": totais_usados.get(grupo),
                    "tot_proventos_extraido": tot_extraido.get(grupo),
                    "base_oficial": None if not base_of else base_of.get(grupo),
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
                            "rubrica": r["rubrica"],
                            "classificacao_origem": r["classificacao"],
                            "valor": float(r["valor_alvo"])
                        })

            # ---------------- Modo Auditor Profissional (por competência) ----------------
            if modo_auditor_prof and totalizador_encontrado and bate_totalizador is False:
                diag = diagnostico_extracao_proventos(df, tol_inconsistencia=max(1.0, tol_totalizador))
                # salva consolidado (top 50)
                if not diag.empty:
                    diag_top = diag.head(50).copy()
                    diag_top.insert(0, "arquivo", arquivo.name)
                    diag_top.insert(1, "competencia", comp)
                    diag_top.insert(2, "dif_totalizador_total", dif_totalizador_total)
                    linhas_diagnostico.extend(diag_top.to_dict(orient="records"))

    df_resumo = pd.DataFrame(linhas_resumo)
    df_devolvidas = pd.DataFrame(linhas_devolvidas)
    df_diag = pd.DataFrame(linhas_diagnostico)

    # ---------------- filtros e tabelas ----------------
    st.subheader("Filtro de status (para não 'sumir' competência)")
    status_opts = sorted(df_resumo["status"].dropna().unique().tolist())
    status_sel = st.multiselect("Mostrar status:", options=status_opts, default=status_opts)

    df_view = df_resumo[df_resumo["status"].isin(status_sel)].copy()

    st.subheader("📌 Resumo consolidado (Qualidade + Aproximação)")
    st.dataframe(
        df_view.sort_values(["competencia", "arquivo", "grupo"], ascending=True),
        use_container_width=True
    )

    st.subheader("🧩 Rubricas devolvidas (para fechar a base por baixo)")
    if df_devolvidas.empty:
        st.info("Nenhuma rubrica foi 'devolvida' (ou não havia base oficial/GAP positivo).")
    else:
        st.dataframe(
            df_devolvidas.sort_values(["competencia", "arquivo", "grupo", "valor"], ascending=[True, True, True, False]),
            use_container_width=True
        )

    # ---------------- Auditor Profissional: painel ----------------
    if modo_auditor_prof:
        st.subheader("🕵️ Auditor Profissional — Diagnóstico de Extração (quando totalizador não bate)")

        falhas = df_resumo[(df_resumo["status"] == "FALHA_EXTRACAO_TOTALIZADOR") & (df_resumo["grupo"] == "TOTAL")].copy()
        if falhas.empty:
            st.success("Nenhuma competência com FALHA_EXTRACAO_TOTALIZADOR (para o grupo TOTAL).")
        else:
            st.markdown(
                "Quando aparece **FALHA_EXTRACAO_TOTALIZADOR**, significa que o **TOTAIS PROVENTOS do PDF** "
                "não bateu com a soma dos proventos extraídos.\n\n"
                "A tabela abaixo mostra as diferenças e, se existir, lista as **linhas suspeitas** dentro do que foi extraído."
            )
            st.dataframe(
                falhas.sort_values(["competencia", "arquivo"], ascending=True)[
                    ["arquivo", "competencia", "dif_totalizador_ativos", "dif_totalizador_desligados", "dif_totalizador_total",
                     "tot_proventos_extraido", "tot_proventos_usado"]
                ],
                use_container_width=True
            )

            if df_diag.empty:
                st.info("Não encontrei linhas suspeitas internas (pode ser rubrica faltando que não foi extraída).")
            else:
                st.markdown("#### Linhas suspeitas (Top 50 por competência)")
                st.dataframe(df_diag, use_container_width=True)

    # ---------------- Excel consolidado ----------------
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_resumo.to_excel(writer, index=False, sheet_name="Resumo_Qualidade")
        df_devolvidas.to_excel(writer, index=False, sheet_name="Rubricas_Devolvidas")
        if modo_auditor_prof:
            df_diag.to_excel(writer, index=False, sheet_name="Diagnostico_Extracao")

    buffer.seek(0)
    st.download_button(
        "📥 Baixar Excel consolidado (60+ PDFs)",
        data=buffer,
        file_name="AUDITOR_INSS_CONSOLIDADO.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
