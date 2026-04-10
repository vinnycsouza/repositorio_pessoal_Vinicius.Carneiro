import streamlit as st

from modules.auditoria import gerar_auditoria, gerar_excel_saida
from modules.processador_zip import processar_zip_esocial
from utils.helpers import decimal_br


st.set_page_config(
    page_title="Auditoria CPP indevida — eSocial",
    layout="wide",
)

st.title("Auditoria de CPP sobre verbas indenizatórias — eSocial")
st.caption(
    "Aplicativo local em Python + Streamlit para abrir o ZIP original do eSocial, localizar automaticamente os XMLs relevantes e gerar uma triagem inicial de possível tributação indevida."
)


with st.sidebar:
    st.header("Entrada")
    arquivo_zip = st.file_uploader(
        "Selecione o ZIP original do eSocial",
        type=["zip"],
        accept_multiple_files=False,
    )

    st.markdown("---")
    st.subheader("Eventos usados nesta versão")
    st.write("- S-1010 — rubricas")
    st.write("- S-1200 — remuneração")
    st.write("- S-3000 — exclusões")
    st.write("- S-5001 — apoio por trabalhador")
    st.write("- S-5011 — base patronal consolidada")

    st.markdown("---")
    if st.button("Resetar aplicação", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


@st.cache_data(show_spinner=False)
def executar_processamento(zip_bytes: bytes):
    return processar_zip_esocial(zip_bytes)


if not arquivo_zip:
    st.info(
        "Envie o ZIP original do eSocial. O app vai localizar automaticamente os XMLs relevantes dentro do pacote, inclusive se houver subpastas ou ZIP dentro de ZIP."
    )

    st.markdown(
        """
### Como este app trabalha
- abre o ZIP original do eSocial;
- varre arquivos internos automaticamente;
- identifica os XMLs necessários para a auditoria, sem filtro manual;
- remove, na triagem, eventos excluídos por S-3000;
- cruza rubricas do S-1010 com remuneração do S-1200 e base patronal do S-5011;
- mantém o S-5001 como apoio para conferência por trabalhador.

### Observação técnica importante
Esta versão gera uma **triagem inicial de risco**. Ela ajuda a localizar situações em que uma rubrica marcada com `codIncCP = 00` aparece em contexto de base patronal no mesmo período/categoria/lotação. A prova definitiva da incidência indevida pode exigir refinamento adicional conforme o layout real da base e a estratégia da empresa.
        """
    )
    st.stop()

zip_bytes = arquivo_zip.getvalue()

with st.spinner("Processando ZIP original do eSocial..."):
    resultado = executar_processamento(zip_bytes)


df_inventario = resultado["inventario"]
df_rubricas = resultado["rubricas"]
df_exclusoes = resultado["exclusoes"]
df_remun = resultado["remuneracoes"]
df_bases_trab = resultado["bases_trabalhador"]
df_bases_contrib = resultado["bases_contribuicao"]
df_erros = resultado["erros_xml"]
df_layout = resultado["layout_check"]

with st.spinner("Gerando cruzamento de auditoria..."):
    df_auditoria = gerar_auditoria(df_rubricas, df_remun, df_bases_trab, df_bases_contrib)


col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Arquivos inventariados", f"{len(df_inventario):,}".replace(",", "."))
with col2:
    qtd_rel = 0 if df_inventario.empty else int(df_inventario["tipo"].isin(["S-1010", "S-1200", "S-5001", "S-5011", "S-3000"]).sum())
    st.metric("XMLs relevantes localizados", f"{qtd_rel:,}".replace(",", "."))
with col3:
    st.metric("Rubricas S-1010", f"{len(df_rubricas):,}".replace(",", "."))
with col4:
    alto = len(df_auditoria[df_auditoria["grau_risco"] == "ALTO"]) if not df_auditoria.empty else 0
    st.metric("Sinalizações altas", f"{alto:,}".replace(",", "."))


st.markdown("## Resumo da localização automática dos XMLs")
if df_inventario.empty:
    st.warning("Nenhum arquivo foi identificado no ZIP.")
else:
    resumo_tipos = (
        df_inventario.groupby("tipo", as_index=False)
        .agg(qtd_arquivos=("arquivo", "count"))
        .sort_values("qtd_arquivos", ascending=False)
    )
    st.dataframe(resumo_tipos, use_container_width=True, hide_index=True)

st.markdown("## Checagem do layout lido")
if df_layout.empty:
    st.warning("Não foi possível montar a checagem de layout.")
else:
    st.dataframe(df_layout, use_container_width=True, hide_index=True)

st.markdown("## Painel de auditoria inicial")
if df_auditoria.empty:
    st.warning(
        "Nenhuma sinalização foi encontrada no cruzamento inicial. Isso pode significar ausência de rubricas com codIncCP=00 no S-1200, ausência de base patronal compatível no S-5011 ou necessidade de refino adicional no layout analisado."
    )
else:
    total_sinalizado = df_auditoria["valor_sinalizado"].sum()
    total_rubricas_nao_inc = df_auditoria["valor_rubrica"].sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("Total de rubricas não incidentes", f"R$ {decimal_br(total_rubricas_nao_inc)}")
    c2.metric("Total sinalizado", f"R$ {decimal_br(total_sinalizado)}")
    c3.metric("Linhas sinalizadas", str(int((df_auditoria["grau_risco"].isin(["ALTO", "MEDIO"]).sum()))))

    filtro_risco = st.selectbox(
        "Filtrar por grau de risco",
        ["Todos", "ALTO", "MEDIO", "BAIXO"],
        index=0,
    )

    df_view = df_auditoria.copy()
    if filtro_risco != "Todos":
        df_view = df_view[df_view["grau_risco"] == filtro_risco].copy()

    st.dataframe(df_view, use_container_width=True, hide_index=True)


tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "Inventário",
    "Rubricas S-1010",
    "Remuneração S-1200",
    "Bases S-5001",
    "Bases S-5011",
    "Exclusões S-3000",
    "Erros XML",
])

with tab1:
    st.dataframe(df_inventario, use_container_width=True, hide_index=True)

with tab2:
    st.dataframe(df_rubricas, use_container_width=True, hide_index=True)

with tab3:
    st.dataframe(df_remun, use_container_width=True, hide_index=True)

with tab4:
    st.dataframe(df_bases_trab, use_container_width=True, hide_index=True)

with tab5:
    st.dataframe(df_bases_contrib, use_container_width=True, hide_index=True)

with tab6:
    st.dataframe(df_exclusoes, use_container_width=True, hide_index=True)

with tab7:
    st.dataframe(df_erros, use_container_width=True, hide_index=True)


st.markdown("## Exportação")
excel_bytes = gerar_excel_saida(
    df_inventario=df_inventario,
    df_rubricas=df_rubricas,
    df_exclusoes=df_exclusoes,
    df_remun=df_remun,
    df_bases_trabalhador=df_bases_trab,
    df_bases_contribuicao=df_bases_contrib,
    df_auditoria=df_auditoria,
    df_erros=df_erros,
    df_layout=df_layout,
)

st.download_button(
    label="Baixar Excel da auditoria",
    data=excel_bytes,
    file_name="auditoria_cpp_esocial.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

st.markdown(
    """
### Próximo passo recomendado
A próxima evolução natural é ampliar a regra jurídica por rubrica e separar um cálculo estimado da CPP potencialmente indevida por competência, estabelecimento e lotação.
    """
)
