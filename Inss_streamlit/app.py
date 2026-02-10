import io
import pdfplumber
import pandas as pd
import streamlit as st

from competencia import extrair_competencia
from extrator_pdf import extrair_eventos_page, extrair_base_empresa_page, pagina_eh_de_bases
from calculo_base import calcular_base_por_grupo
from auditor_base import auditoria_por_grupo, identificar_ajustes_negativos

st.set_page_config(layout="wide")
st.title("🧾 Auditor de Base INSS Patronal (por Competência)")

arquivo = st.file_uploader("Envie o PDF da folha", type="pdf")

if arquivo:
    dados = {}
    comp_atual = None

    with pdfplumber.open(arquivo) as pdf:
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

        df = df.drop_duplicates(subset=["rubrica", "tipo", "ativos", "desligados", "total"]).reset_index(drop=True)

        base_calc, df = calcular_base_por_grupo(df)
        base_of = info["base_empresa"]

        prov = df[df["tipo"] == "PROVENTO"].copy()
        desc = df[df["tipo"] == "DESCONTO"].copy()

        tot_prov = {
            "ativos": float(prov["ativos"].sum()),
            "desligados": float(prov["desligados"].sum()),
            "total": float(prov["total"].sum())
        }

        # ---------------- métricas principais ----------------
        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Proventos (Ativos)", f"R$ {tot_prov['ativos']:,.2f}")
        c2.metric("Base calculada ENTRA (Ativos)", f"R$ {base_calc['ativos']:,.2f}")

        if base_of:
            c3.metric("Base oficial (Ativos)", f"R$ {base_of['ativos']:,.2f}")
            c4.metric("Diferença (calc - oficial)", f"R$ {(base_calc['ativos'] - base_of['ativos']):,.2f}")
        else:
            c3.metric("Base oficial (Ativos)", "Não encontrada")
            c4.metric("Diferença", "-")

        # ---------------- abas elegantes ----------------
        tab1, tab2, tab3, tab4 = st.tabs(["📋 Eventos", "🔵 Proventos", "🔴 Descontos", "🧾 Auditoria da Base"])

        with tab1:
            st.dataframe(df.sort_values(["tipo", "classificacao", "rubrica"]), use_container_width=True)

        with tab2:
            st.dataframe(prov.sort_values("total", ascending=False), use_container_width=True)
            st.write(f"**Total Proventos (Ativos):** R$ {float(prov['ativos'].sum()):,.2f}")
            st.write(f"**Total Proventos (Desligados):** R$ {float(prov['desligados'].sum()):,.2f}")

        with tab3:
            st.dataframe(desc.sort_values("total", ascending=False), use_container_width=True)
            st.write(f"**Total Descontos (Ativos):** R$ {float(desc['ativos'].sum()):,.2f}")
            st.write(f"**Total Descontos (Desligados):** R$ {float(desc['desligados'].sum()):,.2f}")

        with tab4:
            st.markdown("### 🔎 Reconstrução e rastreio do que compõe a base")

            resumo, candidatos, combos = auditoria_por_grupo(df, base_calc, base_of)
            st.dataframe(resumo, use_container_width=True)

            st.markdown("### 🧩 Ajustes negativos detectados (descontos que podem reduzir remuneração)")
            desc_aj = identificar_ajustes_negativos(df)
            aj = desc_aj[(desc_aj["tipo"] == "DESCONTO") & (desc_aj["eh_ajuste_negativo"])].copy()
            if aj.empty:
                st.info("Nenhum desconto foi identificado como ajuste negativo pela heurística atual.")
            else:
                st.dataframe(
                    aj.sort_values("total", ascending=False)[["rubrica", "ativos", "desligados", "total"]],
                    use_container_width=True
                )

            st.markdown("### 🧨 Valores potencialmente 'não explicados' pela base reconstruída")
            st.write(
                "O **residual não explicado** é a parte da **base oficial** que não foi justificada por:\n"
                "- proventos classificados como **ENTRA**, e\n"
                "- ajustes negativos detectados (quando aplicável).\n\n"
                "Esse residual é onde normalmente aparecem verbas que **podem estar compondo base indevidamente** "
                "ou rubricas que hoje estão **NEUTRAS/FORA** mas entram na lógica do sistema."
            )

            colA, colB = st.columns(2)
            with colA:
                st.markdown("#### Candidatas por impacto (ATIVOS)")
                cand_a = candidatos["ativos"]
                st.dataframe(cand_a.head(30), use_container_width=True)

            with colB:
                st.markdown("#### Combinações que podem explicar o residual (ATIVOS)")
                linha_a = resumo[resumo["grupo"] == "ATIVOS"].iloc[0]
                residual_a = linha_a["residual_nao_explicado"]
                if pd.isna(residual_a) or residual_a <= 0:
                    st.info("Não há residual positivo em ATIVOS para 'explicar' (ou base oficial não encontrada).")
                else:
                    combs = combos["ativos"]
                    if not combs:
                        st.warning(
                            "Não encontrei combinação exata com as maiores rubricas FORA/NEUTRA. "
                            "Isso pode indicar residual distribuído em muitas rubricas pequenas, "
                            "ou algo não detalhado no quadro."
                        )
                    else:
                        for i, c in enumerate(combs[:6], start=1):
                            st.markdown(f"**#{i}** soma = R$ {c['soma']:,.2f} (erro: R$ {c['erro']:,.2f})")
                            st.dataframe(c["itens"], use_container_width=True)

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

            # Base oficial
            if base_of:
                pd.DataFrame([base_of]).to_excel(writer, index=False, sheet_name="Base_Oficial")

            # Auditoria
            resumo, candidatos, combos = auditoria_por_grupo(df, base_calc, base_of)
            resumo.to_excel(writer, index=False, sheet_name="Auditoria_Resumo")

            candidatos["ativos"].head(200).to_excel(writer, index=False, sheet_name="Candidatas_Ativos")
            candidatos["desligados"].head(200).to_excel(writer, index=False, sheet_name="Candidatas_Desligados")

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

            # Ajustes negativos
            desc_aj = identificar_ajustes_negativos(df)
            desc_aj.to_excel(writer, index=False, sheet_name="Descontos_Ajustes")

        buffer.seek(0)

        st.download_button(
            "📥 Baixar Excel (Auditoria Completa)",
            data=buffer,
            file_name=f"AUDITOR_BASE_INSS_{comp.replace('/','-')}_{arquivo.name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
