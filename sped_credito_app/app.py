from __future__ import annotations

from pathlib import Path

import streamlit as st

from calculos import (
    ALIQUOTAS_PADRAO,
    calcular_oportunidades,
    resumo_por_ano,
    resumo_por_cfop,
    resumo_por_empresa,
)
from consolidacao import consolidar_bases
from exportacao import gerar_excel_saida
from parsers.parser_icms_ipi import listar_abas as listar_abas_icms
from parsers.parser_icms_ipi import processar_sped_icms
from parsers.parser_pis_cofins import listar_abas as listar_abas_pis
from parsers.parser_pis_cofins import processar_sped_pis


st.set_page_config(page_title="Oportunidades SPED", layout="wide")
st.title("📊 Apurador de Oportunidades — SPED PIS/COFINS + SPED ICMS/IPI")
st.caption("Leitura de dois arquivos Excel pesados por caminho local.")

st.markdown("""
### Regras consideradas
- **Lucro Real**
  - exclusão do **ICMS ST** da base do PIS/COFINS
  - exclusão do **PIS/COFINS por dentro**
- **Lucro Presumido**
  - exclusão do **ICMS ST**
  - exclusão do **DIFAL**
  - exclusão do **PIS/COFINS por dentro**
""")

c1, c2 = st.columns(2)

with c1:
    caminho_pis = st.text_input(
        "Arquivo SPED PIS/COFINS",
        placeholder=r"C:\SPED\arquivo_pis_cofins.xlsx",
    )

with c2:
    caminho_icms = st.text_input(
        "Arquivo SPED ICMS/IPI",
        placeholder=r"C:\SPED\arquivo_icms_ipi.xlsx",
    )

c3, c4, c5, c6 = st.columns(4)

with c3:
    regime = st.selectbox(
        "Regime tributário",
        options=["real", "presumido"],
        format_func=lambda x: "Lucro Real" if x == "real" else "Lucro Presumido",
    )

with c4:
    aliquota_pis = st.number_input(
        "Alíquota PIS",
        min_value=0.0,
        max_value=1.0,
        value=float(ALIQUOTAS_PADRAO[regime]["pis"]),
        step=0.0001,
        format="%.4f",
    )

with c5:
    aliquota_cofins = st.number_input(
        "Alíquota COFINS",
        min_value=0.0,
        max_value=1.0,
        value=float(ALIQUOTAS_PADRAO[regime]["cofins"]),
        step=0.0001,
        format="%.4f",
    )

with c6:
    skiprows = st.number_input(
        "Linhas iniciais a ignorar",
        min_value=0,
        max_value=20,
        value=0,
        step=1,
    )


def brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def validar_arquivo(caminho: str) -> tuple[bool, str]:
    p = Path(caminho)

    if not caminho.strip():
        return False, "Caminho não informado."

    if not p.exists():
        return False, "Arquivo não encontrado."

    if p.suffix.lower() not in {".xlsx", ".xlsb"}:
        return False, "Formato inválido. Use .xlsx ou .xlsb."

    tamanho_gb = p.stat().st_size / (1024 ** 3)
    return True, f"{tamanho_gb:.2f} GB"


if caminho_pis:
    ok, msg = validar_arquivo(caminho_pis)
    if ok:
        st.success(f"PIS/COFINS válido — {msg}")
    else:
        st.error(f"PIS/COFINS: {msg}")

if caminho_icms:
    ok, msg = validar_arquivo(caminho_icms)
    if ok:
        st.success(f"ICMS/IPI válido — {msg}")
    else:
        st.error(f"ICMS/IPI: {msg}")

e1, e2 = st.columns(2)

with e1:
    if caminho_pis:
        with st.expander("Abas detectadas no PIS/COFINS", expanded=False):
            try:
                st.write(listar_abas_pis(caminho_pis))
            except Exception as e:
                st.error(f"Falha ao listar abas: {e}")

with e2:
    if caminho_icms:
        with st.expander("Abas detectadas no ICMS/IPI", expanded=False):
            try:
                st.write(listar_abas_icms(caminho_icms))
            except Exception as e:
                st.error(f"Falha ao listar abas: {e}")

if st.button("Processar arquivos", type="primary"):
    ok_pis, msg_pis = validar_arquivo(caminho_pis)
    ok_icms, msg_icms = validar_arquivo(caminho_icms)

    if not ok_pis:
        st.error(f"Arquivo PIS/COFINS inválido: {msg_pis}")
        st.stop()

    if not ok_icms:
        st.error(f"Arquivo ICMS/IPI inválido: {msg_icms}")
        st.stop()

    barra = st.progress(0, text="Iniciando...")
    status = st.empty()

    def progresso_geral(valor: float, texto: str):
        barra.progress(min(max(valor, 0.0), 1.0), text=texto)
        status.info(texto)

    try:
        progresso_geral(0.05, "Lendo SPED PIS/COFINS...")
        df_pis, df_resumo_abas_pis = processar_sped_pis(
            caminho_arquivo=caminho_pis,
            skiprows=int(skiprows),
        )

        progresso_geral(0.35, "Lendo SPED ICMS/IPI...")
        df_icms, df_resumo_abas_icms = processar_sped_icms(
            caminho_arquivo=caminho_icms,
            skiprows=int(skiprows),
        )

        progresso_geral(0.60, "Consolidando bases...")
        df_consolidado = consolidar_bases(df_pis, df_icms)

        progresso_geral(0.80, "Calculando oportunidades...")
        df_resultado, resumo = calcular_oportunidades(
            df_consolidado=df_consolidado,
            regime=regime,
            aliquota_pis=aliquota_pis,
            aliquota_cofins=aliquota_cofins,
        )

        progresso_geral(0.92, "Montando resumos...")
        df_resumo_ano = resumo_por_ano(df_resultado)
        df_resumo_empresa = resumo_por_empresa(df_resultado)
        df_resumo_cfop = resumo_por_cfop(df_resultado)

        progresso_geral(1.0, "Concluído.")
        status.success("Processamento concluído com sucesso.")

        st.subheader("Resumo geral")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Base total analisada", brl(resumo["base_total"]))
        m2.metric("ICMS ST excluído", brl(resumo["icms_st"]))
        m3.metric("DIFAL excluído", brl(resumo["difal"]))
        m4.metric("Base ajustada", brl(resumo["base_ajustada"]))

        m5, m6, m7 = st.columns(3)
        m5.metric("PIS recuperável", brl(resumo["pis"]))
        m6.metric("COFINS recuperável", brl(resumo["cofins"]))
        m7.metric("Total recuperável", brl(resumo["total"]))

        t1, t2, t3, t4 = st.tabs([
            "Resumo por Ano",
            "Resumo por Empresa",
            "Resumo por CFOP",
            "Amostra do Resultado",
        ])

        with t1:
            st.dataframe(df_resumo_ano, use_container_width=True)

        with t2:
            st.dataframe(df_resumo_empresa, use_container_width=True)

        with t3:
            st.dataframe(df_resumo_cfop, use_container_width=True)

        with t4:
            st.dataframe(df_resultado.head(1000), use_container_width=True)

        with st.expander("Resumo das abas processadas", expanded=False):
            a1, a2 = st.columns(2)
            with a1:
                st.markdown("**PIS/COFINS**")
                st.dataframe(df_resumo_abas_pis, use_container_width=True)
            with a2:
                st.markdown("**ICMS/IPI**")
                st.dataframe(df_resumo_abas_icms, use_container_width=True)

        excel_saida = gerar_excel_saida(
            df_resumo_ano=df_resumo_ano,
            df_resumo_empresa=df_resumo_empresa,
            df_resumo_cfop=df_resumo_cfop,
            df_resultado_amostra=df_resultado.head(5000),
            df_resumo_abas_pis=df_resumo_abas_pis,
            df_resumo_abas_icms=df_resumo_abas_icms,
        )

        st.download_button(
            label="📥 Baixar resumo em Excel",
            data=excel_saida,
            file_name="resumo_oportunidades_sped.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        if regime == "presumido" and float(resumo["difal"]) == 0:
            st.warning("No lucro presumido, o DIFAL está zerado no resultado. Verifique se o arquivo ICMS/IPI possui coluna/aba com DIFAL identificável.")

    except Exception as e:
        st.error(f"Erro ao processar os arquivos: {e}")