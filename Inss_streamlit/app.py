import io
import re
import pdfplumber
import pandas as pd
import streamlit as st

from competencia import extrair_competencia
from extrator_pdf import extrair_eventos_page, extrair_base_empresa_page, pagina_eh_de_bases
from calculo_base import calcular_base_por_grupo
from auditor_base import auditoria_por_grupo  # agora retorna 5 valores


def normalizar_valor_br(txt: str):
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except Exception:
        return None


def extrair_totais_proventos_pdf(pdf) -> dict | None:
    """
    Procura no texto do PDF uma linha do tipo:
      TOTAIS PROVENTOS 1.991.989,74 308.209,44 2.300.199,18
    Retorna:
      {"ativos": ..., "desligados": ..., "total": ...}
    ou None se não encontrar.
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
st.title("🧾 Auditor de Base INSS Patronal (por Competência) — Reconstrução por Exclusão")

arquivo = st.file_uploader("Envie o PDF da folha", type="pdf")

if arquivo:
    dados = {}
    comp_atual = None

    with pdfplumber.open(arquivo) as pdf:
        # tenta pegar totais proventos do próprio PDF (global / normalmente único)
        totais_proventos_pdf_global = extrair_totais_proventos_pdf(pdf)

        for page in pdf.pages:
            comp_atual = extrair_competencia(page, comp_atual)
            if not comp_atual:
                continue

            dados.setdefault(comp_atual, {"eventos": [], "base_empresa": None})

            # base oficial (páginas de bases)
            if pagina_eh_de_bases(page):
                base = extrair_base_empresa_page(page)
                if base and dados[comp_atual]["base_empresa"] is None:
                    dados[comp_atual]["base_empresa"] = base

            # eventos (páginas de eventos)
            dados[comp_atual]["eventos"].extend(extrair_eventos_page(page))

    for comp, info in dados.items():
        st.divider()
        st.subheader(f"📅 Competência {comp}")

        df = pd.DataFrame(info["eventos"])
        if df.empty:
            st.warning("Nenhum evento (rubrica) extraído para esta competência.")
            continue

        # evita duplicidade por PDF mesclado/continuação
        df = df.drop_duplicates(subset=["rubrica", "tipo", "ativos", "desligados", "total"]).reset_index(drop=True)

        base_calc, df = calcular_base_por_grupo(df)
        base_of = info["base_empresa"]

        prov = df[df["tipo"] == "PROVENTO"].copy()
        desc = df[df["tipo"] == "DESCONTO"].copy()

        tot_prov_extraido = {
            "ativos": float(prov["ativos"].fillna(0).sum()),
            "desligados": float(prov["desligados"].fillna(0).sum()),
            "total": float(prov["total"].fillna(0).sum())
        }

        # Usa total do PDF se achou; senão usa o extraído
        totais_pdf = totais_proventos_pdf_global if totais_proventos_pdf_global else tot_prov_extraido

        # ---------------- métricas principais ----------------
        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Proventos (Ativos)", f"R$ {totais_pdf['ativos']:,.2f}")
        c2.metric("Proventos (Desligados)", f"R$ {totais_pdf['desligados']:,.2f}")

        if base_of:
            c3.metric("Base oficial (Ativos)", f"R$ {base_of['ativos']:,.2f}")
            c4.metric("Base oficial (Desligados)", f"R$ {base_of['desligados']:,.2f}")
        else:
            c3.metric("Base oficial (Ativos)", "Não encontrada")
            c4.metric("Base oficial (Desligados)", "Não encontrada")

        # ---------------- abas elegantes ----------------
        tab1, tab2, tab3, tab4 = st.tabs(["📋 Eventos", "🔵 Proventos", "🔴 Descontos", "🧾 Auditoria da Base (Exclusão)"])

        with tab1:
            st.dataframe(df.sort_values(["tipo", "classificacao", "rubrica"]), use_container_width=True)

        with tab2:
            st.dataframe(prov.sort_values("total", ascending=False), use_container_width=True)
            st.write(f"**Total Proventos usado na auditoria (ATIVOS):** R$ {totais_pdf['ativos']:,.2f}")
            st.write(f"**Total Proventos usado na auditoria (DESLIGADOS):** R$ {totais_pdf['desligados']:,.2f}")
            if totais_proventos_pdf_global:
                st.caption("Fonte do total: extraído da linha 'TOTAIS PROVENTOS' do PDF.")
            else:
                st.caption("Fonte do total: soma dos proventos extraídos (fallback).")

        with tab3:
            st.dataframe(desc.sort_values("total", ascending=False), use_container_width=True)
            st.write(f"**Total Descontos (Ativos):** R$ {float(desc['ativos'].fillna(0).sum()):,.2f}")
            st.write(f"**Total Descontos (Desligados):** R$ {float(desc['desligados'].fillna(0).sum()):,.2f}")

        with tab4:
            st.markdown("### ✅ Reconstrução por Exclusão (a lógica do ERP na prática)")
            st.write(
                "Nesta visão, a base é reconstruída como:\n\n"
                "**Base por Exclusão = Totais Proventos − Proventos FORA − Proventos NEUTRA**\n\n"
                "Isso costuma refletir melhor relatórios onde o sistema calcula a incidência por exclusão."
            )

            resumo, candidatos, combos, descontos_classificados, blocos = auditoria_por_grupo(
                df=df,
                base_calc=base_calc,
                base_oficial=base_of,
                totais_proventos_pdf=totais_pdf
            )

            st.dataframe(resumo, use_container_width=True)

            # Destaque rápido do quão perto a exclusão chegou da base oficial
            if base_of:
                linha_a = resumo[resumo["grupo"] == "ATIVOS"].iloc[0]
                linha_d = resumo[resumo["grupo"] == "DESLIGADOS"].iloc[0]

                k1, k2, k3 = st.columns(3)
                k1.metric("Dif. Exclusão vs Oficial (Ativos)", f"R$ {float(linha_a['dif_exclusao_vs_oficial']):,.2f}")
                k2.metric("Dif. Exclusão vs Oficial (Desligados)", f"R$ {float(linha_d['dif_exclusao_vs_oficial']):,.2f}")
                k3.metric("Dif. Exclusão vs Oficial (Total)", f"R$ {float(resumo[resumo['grupo']=='TOTAL'].iloc[0]['dif_exclusao_vs_oficial']):,.2f}")

            st.markdown("### 🔎 O que foi EXCLUÍDO para chegar na base (FORA + NEUTRA)")
            colA, colB = st.columns(2)

            with colA:
                st.markdown("#### Top PROVENTOS FORA (ATIVOS)")
                prov_fora = df[(df["tipo"] == "PROVENTO") & (df["classificacao"] == "FORA")].copy()
                prov_fora["valor_alvo"] = prov_fora["ativos"].fillna(0.0)
                st.dataframe(
                    prov_fora.sort_values("valor_alvo", ascending=False)[["rubrica", "ativos", "desligados", "total"]].head(30),
                    use_container_width=True
                )

            with colB:
                st.markdown("#### Top PROVENTOS NEUTRA (ATIVOS)")
                prov_neu = df[(df["tipo"] == "PROVENTO") & (df["classificacao"] == "NEUTRA")].copy()
                prov_neu["valor_alvo"] = prov_neu["ativos"].fillna(0.0)
                st.dataframe(
                    prov_neu.sort_values("valor_alvo", ascending=False)[["rubrica", "ativos", "desligados", "total"]].head(30),
                    use_container_width=True
                )

            st.markdown("### 🧩 Se a Exclusão não bater: candidatas e combinações para explicar o GAP")
            st.write(
                "Se **Base por Exclusão** ficar abaixo da **Base Oficial**, então alguma rubrica marcada como FORA/NEUTRA "
                "provavelmente **entra na incidência** no ERP. As listas abaixo ajudam a encontrar isso."
            )

            colC, colD = st.columns(2)
            with colC:
                st.markdown("#### Candidatas por impacto (ATIVOS)")
                cand_a = candidatos.get("ativos", pd.DataFrame())
                st.dataframe(cand_a.head(30), use_container_width=True)

            with colD:
                st.markdown("#### Combinações que podem explicar o GAP (ATIVOS)")
                if not base_of:
                    st.info("Base oficial não encontrada; não há GAP para conciliar.")
                else:
                    # GAP = base_oficial - base_exclusao (interno ao auditor)
                    combs = combos.get("ativos", [])
                    if not combs:
                        st.warning(
                            "Não encontrei combinação exata com as maiores rubricas FORA/NEUTRA para fechar o GAP. "
                            "Isso pode indicar GAP distribuído em muitas rubricas pequenas, ou rubricas não extraídas."
                        )
                    else:
                        for i, c in enumerate(combs[:6], start=1):
                            st.markdown(f"**#{i}** soma = R$ {c['soma']:,.2f} (erro: R$ {c['erro']:,.2f})")
                            st.dataframe(c["itens"], use_container_width=True)

            st.markdown("### 🧾 Descontos classificados (mantido para auditoria)")
            if descontos_classificados is not None and not descontos_classificados.empty:
                aj = descontos_classificados[descontos_classificados.get("eh_ajuste_negativo", False)].copy()
                fin = descontos_classificados[descontos_classificados.get("eh_financeiro", False)].copy()
                neu = descontos_classificados[descontos_classificados.get("eh_neutro", False)].copy()

                cc1, cc2, cc3 = st.columns(3)
                cc1.metric("🔻 Reduzem base", f"{len(aj)}")
                cc2.metric("💳 Financeiros", f"{len(fin)}")
                cc3.metric("❔ Neutros", f"{len(neu)}")

                if not aj.empty:
                    st.markdown("#### 🔻 Reduzem base (por config) — apenas referência")
                    st.dataframe(
                        aj.sort_values("total", ascending=False)[["rubrica", "ativos", "desligados", "total"]],
                        use_container_width=True
                    )
            else:
                st.info("Não há descontos classificados disponíveis.")

        # ---------------- Excel ----------------
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Eventos")
            prov.to_excel(writer, index=False, sheet_name="Proventos")
            desc.to_excel(writer, index=False, sheet_name="Descontos")

            entra = df[df["classificacao"] == "ENTRA"].copy()
            neutra = df[df["classificacao"] == "NEUTRA"].copy()
            fora = df[df["classificacao"] == "FORA"].copy()

            entra.to_excel(writer, index=False, sheet_name="ENTRA")
            neutra.to_excel(writer, index=False, sheet_name="NEUTRA")
            fora.to_excel(writer, index=False, sheet_name="FORA")

            if base_of:
                pd.DataFrame([base_of]).to_excel(writer, index=False, sheet_name="Base_Oficial")

            # Auditoria (Exclusão)
            resumo, candidatos, combos, descontos_classificados, blocos = auditoria_por_grupo(
                df=df,
                base_calc=base_calc,
                base_oficial=base_of,
                totais_proventos_pdf=totais_pdf
            )
            resumo.to_excel(writer, index=False, sheet_name="Auditoria_Resumo")

            # Exporta blocos auxiliares (muito útil)
            pd.DataFrame([blocos["tot_proventos_usado"]]).to_excel(writer, index=False, sheet_name="Totais_Proventos_Usado")
            pd.DataFrame([blocos["tot_proventos_extraido"]]).to_excel(writer, index=False, sheet_name="Totais_Proventos_Extraido")
            pd.DataFrame([blocos["soma_fora"]]).to_excel(writer, index=False, sheet_name="Soma_FORA")
            pd.DataFrame([blocos["soma_neutra"]]).to_excel(writer, index=False, sheet_name="Soma_NEUTRA")

            candidatos.get("ativos", pd.DataFrame()).head(200).to_excel(writer, index=False, sheet_name="Candidatas_Ativos")
            candidatos.get("desligados", pd.DataFrame()).head(200).to_excel(writer, index=False, sheet_name="Candidatas_Desligados")

            # Combos achatados (Ativos)
            linhas_combo = []
            for n, c in enumerate(combos.get("ativos", []), start=1):
                for _, row in c["itens"].iterrows():
                    linhas_combo.append({
                        "combo": n,
                        "soma_combo": c["soma"],
                        "erro": c["erro"],
                        "rubrica": row["rubrica"],
                        "tipo": row["tipo"],
                        "classificacao": row["classificacao"],
                        "valor": row["valor_alvo"]
                    })
            pd.DataFrame(linhas_combo).to_excel(writer, index=False, sheet_name="Combos_Ativos")

            if descontos_classificados is not None and not descontos_classificados.empty:
                descontos_classificados.to_excel(writer, index=False, sheet_name="Descontos_Classificados")

        buffer.seek(0)

        st.download_button(
            "📥 Baixar Excel (Auditoria Completa)",
            data=buffer,
            file_name=f"AUDITOR_BASE_INSS_{comp.replace('/','-')}_{arquivo.name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
