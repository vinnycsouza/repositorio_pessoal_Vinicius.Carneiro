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


st.set_page_config(layout="wide")
st.title("🧾 Auditor INSS — Lote (60+ PDFs) | Qualidade + Aproximação por Baixo")

arquivos = st.file_uploader("Envie 1 ou mais PDFs de folha", type="pdf", accept_multiple_files=True)

tol_totalizador = st.number_input("Tolerância p/ 'bater totalizador' (R$)", min_value=0.0, value=1.00, step=0.50)
tol_erro_aprox = st.number_input("Tolerância desejada p/ erro da aproximação (R$)", min_value=0.0, value=5.00, step=1.00)

if arquivos:
    linhas_resumo = []
    linhas_devolvidas = []

    for arquivo in arquivos:
        with pdfplumber.open(arquivo) as pdf:
            dados = {}
            comp_atual = None

            for page in pdf.pages:
                # competência usada para anexar eventos (pode usar fallback)
                comp_atual = extrair_competencia_robusta(page, comp_atual)
                if not comp_atual:
                    continue

                dados.setdefault(comp_atual, {"eventos": [], "base_empresa": None, "totais_proventos_pdf": None})

                # ✅ totalizador só é associado quando a competência aparece NA PÁGINA (sem fallback)
                tot = extrair_totais_proventos_page(page)
                if tot:
                    comp_na_pagina = extrair_competencia_sem_fallback(page)  # sem fallback
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
                pass

            base_of = info["base_empresa"]

            prov = df[df["tipo"] == "PROVENTO"].copy()
            tot_extraido = {
                "ativos": float(prov["ativos"].fillna(0).sum()),
                "desligados": float(prov["desligados"].fillna(0).sum()),
                "total": float(prov["total"].fillna(0).sum()),
            }

            tot_pdf_comp = info.get("totais_proventos_pdf")
            totais_usados = tot_pdf_comp if tot_pdf_comp else tot_extraido

            totalizador_encontrado = tot_pdf_comp is not None
            bate_totalizador = None
            if totalizador_encontrado:
                bate_totalizador = (
                    abs(tot_pdf_comp["ativos"] - tot_extraido["ativos"]) <= tol_totalizador and
                    abs(tot_pdf_comp["desligados"] - tot_extraido["desligados"]) <= tol_totalizador and
                    abs(tot_pdf_comp["total"] - tot_extraido["total"]) <= tol_totalizador
                )

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

    df_resumo = pd.DataFrame(linhas_resumo)
    df_devolvidas = pd.DataFrame(linhas_devolvidas)

    st.subheader("Filtro de status (para não 'sumir' mês que ficou ATENCAO)")
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

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_resumo.to_excel(writer, index=False, sheet_name="Resumo_Qualidade")
        df_devolvidas.to_excel(writer, index=False, sheet_name="Rubricas_Devolvidas")

    buffer.seek(0)
    st.download_button(
        "📥 Baixar Excel consolidado (60+ PDFs)",
        data=buffer,
        file_name="AUDITOR_INSS_CONSOLIDADO.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
