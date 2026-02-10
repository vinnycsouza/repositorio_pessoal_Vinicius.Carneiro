import io
import re
import pdfplumber
import pandas as pd
import streamlit as st

from competencia import extrair_competencia
from extrator_pdf import extrair_eventos_page, extrair_base_empresa_page, pagina_eh_de_bases
from calculo_base import calcular_base_por_grupo  # pode continuar existindo
from auditor_base import auditoria_por_exclusao_com_aproximacao


def normalizar_valor_br(txt: str):
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except Exception:
        return None


def extrair_totais_proventos_pdf(pdf) -> dict | None:
    """
    Busca em qualquer página a linha:
      TOTAIS PROVENTOS 1.991.989,74 308.209,44 2.300.199,18
    Retorna dict ou None.
    """
    padrao = re.compile(
        r"totais\s+proventos.*?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s+"
        r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\s+"
        r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})",
        re.IGNORECASE
    )
    for page in pdf.pages:
        txt = page.extract_text() or ""
        m = padrao.search(txt)
        if m:
            a = normalizar_valor_br(m.group(1))
            d = normalizar_valor_br(m.group(2))
            t = normalizar_valor_br(m.group(3))
            if a is not None and d is not None and t is not None:
                return {"ativos": a, "desligados": d, "total": t}
    return None


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
            totais_pdf_global = extrair_totais_proventos_pdf(pdf)

            dados = {}
            comp_atual = None

            for page in pdf.pages:
                comp_atual = extrair_competencia(page, comp_atual)
                if not comp_atual:
                    continue

                dados.setdefault(comp_atual, {"eventos": [], "base_empresa": None})

                if pagina_eh_de_bases(page):
                    base = extrair_base_empresa_page(page)
                    if base and dados[comp_atual]["base_empresa"] is None:
                        dados[comp_atual]["base_empresa"] = base

                dados[comp_atual]["eventos"].extend(extrair_eventos_page(page))

        # processa por competência
        for comp, info in dados.items():
            df = pd.DataFrame(info["eventos"])
            if df.empty:
                linhas_resumo.append({
                    "arquivo": arquivo.name,
                    "competencia": comp,
                    "status": "SEM_EVENTOS",
                })
                continue

            df = df.drop_duplicates(subset=["rubrica", "tipo", "ativos", "desligados", "total"]).reset_index(drop=True)

            # mantém seu pipeline de classificação (ENTRA/FORA/NEUTRA) se calcular_base_por_grupo já faz isso
            # (mesmo que a exclusão não use ENTRA diretamente, ela precisa de FORA/NEUTRA bem marcados)
            try:
                _, df = calcular_base_por_grupo(df)
            except Exception:
                # se falhar, pelo menos não quebra lote
                pass

            base_of = info["base_empresa"]

            # Totais proventos usados
            prov = df[df["tipo"] == "PROVENTO"].copy()
            tot_extraido = {
                "ativos": float(prov["ativos"].fillna(0).sum()),
                "desligados": float(prov["desligados"].fillna(0).sum()),
                "total": float(prov["total"].fillna(0).sum()),
            }
            totais_usados = totais_pdf_global if totais_pdf_global else tot_extraido

            totalizador_encontrado = totais_pdf_global is not None
            bate_totalizador = None
            if totalizador_encontrado:
                bate_totalizador = (
                    abs(totais_usados["ativos"] - tot_extraido["ativos"]) <= tol_totalizador and
                    abs(totais_usados["desligados"] - tot_extraido["desligados"]) <= tol_totalizador and
                    abs(totais_usados["total"] - tot_extraido["total"]) <= tol_totalizador
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

                # status de qualidade:
                # - se não tem base oficial: INCOMPLETO_BASE
                # - se totalizador não bate: FALHA_EXTRACAO
                # - se erro_aprox dentro da tol: OK_APROX
                # - senão: ATENCAO
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

                # rubricas devolvidas (as que o algoritmo "incluiu de volta" para fechar por baixo)
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

    st.subheader("📌 Resumo consolidado (Qualidade + Aproximação)")
    st.dataframe(
        df_resumo.sort_values(["competencia", "arquivo", "grupo"], ascending=True),
        use_container_width=True
    )

    st.subheader("🧩 Rubricas devolvidas (prováveis responsáveis por fechar a base por baixo)")
    if df_devolvidas.empty:
        st.info("Nenhuma rubrica foi 'devolvida' (ou não havia base oficial/GAP positivo).")
    else:
        st.dataframe(
            df_devolvidas.sort_values(["competencia", "arquivo", "grupo", "valor"], ascending=[True, True, True, False]),
            use_container_width=True
        )

    # Exporta Excel consolidado
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
