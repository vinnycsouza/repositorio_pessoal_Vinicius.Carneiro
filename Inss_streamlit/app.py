import io
import pdfplumber
import pandas as pd
import streamlit as st

from competencia import extrair_competencia
from extrator_pdf import extrair_eventos_page, extrair_base_empresa_page, pagina_eh_de_bases
from calculo_base import calcular_base_por_grupo

st.set_page_config(layout="wide")
st.title("📊 Conciliação INSS Patronal por Competência (Ativos / Desligados / Afastados)")

arquivo = st.file_uploader("Envie o PDF da folha", type="pdf")

if arquivo:
    dados = {}
    comp_atual = None

    with pdfplumber.open(arquivo) as pdf:
        for page in pdf.pages:
            comp_atual = extrair_competencia(page, comp_atual)
            if not comp_atual:
                continue

            dados.setdefault(comp_atual, {
                "eventos": [],            # lista de dicts
                "base_empresa": None      # dict por grupo
            })

            # Base (somente páginas de bases/resumo)
            if pagina_eh_de_bases(page):
                base = extrair_base_empresa_page(page)
                # pega a primeira encontrada; se repetir igual, tanto faz
                if base and dados[comp_atual]["base_empresa"] is None:
                    dados[comp_atual]["base_empresa"] = base

            # Eventos (somente páginas que não são de bases)
            dados[comp_atual]["eventos"].extend(extrair_eventos_page(page))

    if not dados:
        st.error("Não consegui detectar competência/estruturas nesse PDF.")
        st.stop()

    for comp, info in dados.items():
        st.divider()
        st.subheader(f"📅 Competência {comp}")

        df = pd.DataFrame(info["eventos"])
        if df.empty:
            st.warning("Nenhum evento (rubrica) foi extraído para esta competência.")
            continue

        # dedup para PDFs mesclados / páginas repetidas
        df = df.drop_duplicates(subset=["rubrica", "tipo", "ativos", "desligados", "total"]).reset_index(drop=True)

        # calcula base por grupo usando regras (ENTRA/NEUTRA/FORA)
        base_calc, df = calcular_base_por_grupo(df)

        base_of = info["base_empresa"]

        # totais brutos de proventos/descontos (do quadro de eventos)
        prov = df[df["tipo"] == "PROVENTO"]
        desc = df[df["tipo"] == "DESCONTO"]

        tot_prov = {
            "ativos": float(prov["ativos"].sum()),
            "desligados": float(prov["desligados"].sum()),
            "total": float(prov["total"].sum())
        }
        tot_desc = {
            "ativos": float(desc["ativos"].sum()),
            "desligados": float(desc["desligados"].sum()),
            "total": float(desc["total"].sum())
        }

        # métricas principais
        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Proventos (Ativos)", f"R$ {tot_prov['ativos']:,.2f}")
        c2.metric("Base calculada (Ativos)", f"R$ {base_calc['ativos']:,.2f}")
        if base_of:
            c3.metric("Base oficial (Ativos)", f"R$ {base_of['ativos']:,.2f}")
            c4.metric("Diferença Ativos (calc - oficial)", f"R$ {(base_calc['ativos']-base_of['ativos']):,.2f}")
        else:
            c3.metric("Base oficial (Ativos)", "Não encontrada")
            c4.metric("Diferença Ativos", "-")

        tab1, tab2, tab3 = st.tabs(["📋 Eventos", "🔵 Proventos x 🔴 Descontos", "🧮 Conciliação por grupo"])

        with tab1:
            st.dataframe(df.sort_values(["tipo", "classificacao", "rubrica"]), use_container_width=True)

        with tab2:
            colA, colB = st.columns(2)
            with colA:
                st.markdown("### 🔵 Proventos")
                st.dataframe(prov.sort_values("total", ascending=False), use_container_width=True)
            with colB:
                st.markdown("### 🔴 Descontos")
                st.dataframe(desc.sort_values("total", ascending=False), use_container_width=True)

        with tab3:
            st.markdown("### Comparativo (por grupo)")

            # monta tabela de conciliação
            linhas = []

            # Ativos / Desligados sempre existem no quadro de eventos
            for grupo in ["ativos", "desligados"]:
                linhas.append({
                    "grupo": grupo.upper(),
                    "proventos_brutos": tot_prov[grupo],
                    "base_calculada_ENTRA": base_calc[grupo],
                    "base_oficial": base_of[grupo] if base_of else None,
                    "obs": ""
                })

            # AFASTADOS: existe na base oficial, mas NÃO no quadro de eventos deste modelo
            linhas.append({
                "grupo": "AFASTADOS",
                "proventos_brutos": None,
                "base_calculada_ENTRA": None,
                "base_oficial": base_of["afastados"] if base_of else None,
                "obs": "Consta na BASE oficial, mas não é detalhado no quadro de eventos deste relatório."
            })

            # TOTAL
            linhas.append({
                "grupo": "TOTAL",
                "proventos_brutos": tot_prov["total"],
                "base_calculada_ENTRA": base_calc["total"],
                "base_oficial": base_of["total"] if base_of else None,
                "obs": ""
            })

            conciliacao = pd.DataFrame(linhas)
            st.dataframe(conciliacao, use_container_width=True)

            st.markdown("### Eventos fora da base (soma por grupo)")

            fora = df[df["classificacao"].isin(["FORA", "NEUTRA"]) & (df["tipo"] == "PROVENTO")].copy()
            fora["soma_grupos"] = fora["ativos"].fillna(0) + fora["desligados"].fillna(0)

            colX, colY = st.columns(2)
            with colX:
                st.markdown("**Top eventos PROVENTO que NÃO entram (ou estão NEUTRA)**")
                st.dataframe(
                    fora.sort_values("total", ascending=False).head(30),
                    use_container_width=True
                )
            with colY:
                st.markdown("**Totais fora da base (apenas eventos PROVENTO)**")
                st.write(f"- Ativos: R$ {float(fora['ativos'].sum()):,.2f}")
                st.write(f"- Desligados: R$ {float(fora['desligados'].sum()):,.2f}")
                st.write(f"- Total: R$ {float(fora['total'].sum()):,.2f}")

        # -------- Excel --------
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Eventos")

            if base_of:
                pd.DataFrame([{
                    "ativos": base_of["ativos"],
                    "desligados": base_of["desligados"],
                    "afastados": base_of["afastados"],
                    "total": base_of["total"]
                }]).to_excel(writer, index=False, sheet_name="Base_Oficial")

            conciliacao.to_excel(writer, index=False, sheet_name="Conciliacao")
            prov.to_excel(writer, index=False, sheet_name="Proventos")
            desc.to_excel(writer, index=False, sheet_name="Descontos")

            df[df["classificacao"] == "ENTRA"].to_excel(writer, index=False, sheet_name="ENTRA")
            df[df["classificacao"] == "NEUTRA"].to_excel(writer, index=False, sheet_name="NEUTRA")
            df[df["classificacao"] == "FORA"].to_excel(writer, index=False, sheet_name="FORA")

        buffer.seek(0)

        st.download_button(
            "📥 Baixar Excel (Eventos + Base + Conciliação)",
            data=buffer,
            file_name=f"INSS_Conciliacao_{comp.replace('/','-')}_{arquivo.name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
