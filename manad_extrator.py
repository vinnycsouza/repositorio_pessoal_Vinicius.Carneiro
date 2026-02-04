import streamlit as st
import pandas as pd
import io

# =========================
# Cabeçalho por evento MANAD
# =========================
def cabecalho_evento(codigo):
    cabecalhos = {
        "I200": ["REG", "DT_LCTO", "COD_CTA", "COD_CCUS", "COD_CP", "VL_DEB_CRED",
                 "IND_DEB_CRED", "NUM_ARQ", "NUM_LCTO", "IND_LCTO", "HIST_LCTO"],
        "K300": ["REG", "CNPJ/CEI", "IND_FL", "COD_LTC", "COD_REG_TRAB", "DT_COMP",
                 "COD_RUBR", "VLR_RUBR", "IND_RUBR", "IND_BASE_IRRF", "IND_BASE_PS"],
        "K250": ["REG", "CNPJ/CEI", "IND_FL", "COD_LTC", "COD_REG_TRAB", "DT_COMP",
                 "DT_PGTO", "COD_CBO", "COD_OCORR", "DESC_CARGO", "QTD_DEP_IR",
                 "QTD_DEP_SF", "VL_BASE_IRRF", "VL_BASE_PS"],
        "K150": ["REG", "CNPJ/CEI", "DT_INC_ALT", "COD_RUBRICA", "DESC_RUBRICA"],
        "I050": ["REG", "DT_INC_ALT", "IND_NAT", "IND_GRP_CTA", "NIVEL",
                 "COD_GRP_CTA", "COD_GRP_CTA_SUP", "NOME_GRP_CTA"],
    }
    return cabecalhos.get(codigo)


# =========================
# Separação por evento
# =========================
def separar_por_evento(linhas):
    eventos = {}
    for registro in linhas:
        registro = str(registro).strip()
        if len(registro) < 4:
            continue
        codigo = registro[:4]
        eventos.setdefault(codigo, []).append(registro.split('|'))
    return eventos


# =========================
# Streamlit UI
# =========================
st.set_page_config(page_title="MANAD Extrator", layout="wide")
st.title("📂 MANAD - Separação por Evento e Geração de Excel")

uploaded_file = st.file_uploader(
    "Selecione o arquivo MANAD (.txt ou .xlsx)",
    type=["txt", "xlsx"],
    key="upload_manad"
)

# =========================
# Estado da sessão
# =========================
if "excel_bytes" not in st.session_state:
    st.session_state.excel_bytes = None

if "estatisticas" not in st.session_state:
    st.session_state.estatisticas = {}

# =========================
# Leitura do arquivo
# =========================
if uploaded_file:
    st.success("Arquivo carregado com sucesso!")

    linhas = []

    # TXT
    if uploaded_file.name.lower().endswith(".txt"):
        linhas = uploaded_file.read().decode("latin1").splitlines()

    # Excel
    else:
        xls = pd.ExcelFile(uploaded_file)
        for aba in xls.sheet_names:
            df_aba = pd.read_excel(xls, sheet_name=aba, header=None)
            linhas.extend(df_aba[0].dropna().astype(str).tolist())

    eventos = separar_por_evento(linhas)
    st.info(f"Eventos encontrados: {', '.join(eventos.keys())}")

    # =========================
    # Geração do Excel
    # =========================
    if st.button("⚙️ Gerar arquivo Excel por evento", key="gerar_excel"):
        output = io.BytesIO()

        MAX_ROWS_EXCEL = 1_048_576
        MAX_DADOS_POR_ABA = MAX_ROWS_EXCEL - 1

        progresso = st.progress(0.0)
        status = st.empty()

        total_eventos = len(eventos)
        eventos_processados = 0
        estatisticas = {}

        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            for codigo, registros in eventos.items():
                eventos_processados += 1
                progresso.progress(eventos_processados / total_eventos)
                status.text(f"Processando evento {codigo} ({eventos_processados}/{total_eventos})")

                cabecalho = cabecalho_evento(codigo)
                if not cabecalho or not registros:
                    continue

                df_evento = pd.DataFrame(registros)
                df_evento = df_evento.iloc[:, :len(cabecalho)]
                df_evento.columns = cabecalho[:df_evento.shape[1]]

                if df_evento.empty:
                    continue

                total_linhas = len(df_evento)
                total_abas = (
                    total_linhas // MAX_DADOS_POR_ABA
                    + (1 if total_linhas % MAX_DADOS_POR_ABA else 0)
                )

                estatisticas[codigo] = {
                    "Total de linhas": total_linhas,
                    "Total de abas": total_abas
                }

                for i in range(total_abas):
                    inicio = i * MAX_DADOS_POR_ABA
                    fim = inicio + MAX_DADOS_POR_ABA
                    nome_aba = codigo if total_abas == 1 else f"{codigo}_{i + 1}"

                    df_evento.iloc[inicio:fim].to_excel(
                        writer,
                        sheet_name=nome_aba[:31],
                        index=False
                    )

        progresso.empty()
        status.success("✅ Excel gerado com sucesso!")

        output.seek(0)
        st.session_state.excel_bytes = output
        st.session_state.estatisticas = estatisticas

    # =========================
    # Download
    # =========================
    if st.session_state.excel_bytes:
        st.download_button(
            label="📥 Baixar Excel com todos os eventos",
            data=st.session_state.excel_bytes,
            file_name="MANAD_Eventos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_excel_manad"
        )

    # =========================
    # Estatísticas
    # =========================
    if st.session_state.estatisticas:
        st.subheader("📊 Estatísticas por evento")
        df_stats = pd.DataFrame.from_dict(
            st.session_state.estatisticas,
            orient="index"
        ).reset_index()
        df_stats.columns = ["Evento", "Total de linhas", "Total de abas"]
        st.dataframe(df_stats, use_container_width=True)
