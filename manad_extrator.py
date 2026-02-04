import streamlit as st
import pandas as pd
import io



def cabecalho_evento(codigo):
    cabecalhos = {
        "I200": ["REG", "DT_LCTO", "COD_CTA", "COD_CCUS", "COD_CP", "VL_DEB_CRED", "IND_DEB_CRED", "NUM_ARQ", "NUM_LCTO", "IND_LCTO", "HIST_LCTO"],
        "K300": ["REG", "CNPJ/CEI", "IND_FL", "COD_LTC", "COD_REG_TRAB", "DT_COMP", "COD_RUBR", "VLR_RUBR", "IND_RUBR", "IND_BASE_IRRF", "IND_BASE_PS"],
        "K250": ["REG", "CNPJ/CEI", "IND_FL", "COD_LTC", "COD_REG_TRAB", "DT_COMP", "DT_PGTO", "COD_CBO", "COD_OCORR", "DESC_CARGO", "QTD_DEP_IR", "QTD_DEP_SF", "VL_BASE_IRRF", "VL_BASE_PS"],
        "K150": ["REG", "CNPJ/CEI", "DT_INC_ALT", "COD_RUBRICA", "DESC_RUBRICA"],
        "I050": ["REG", "DT_INC_ALT", "IND_NAT", "IND_GRP_CTA", "NIVEL", "COD_GRP_CTA", "COD_GRP_CTA_SUP", "NOME_GRP_CTA"],
    }
    return cabecalhos.get(codigo, ["Campo1", "Campo2", "Campo3", "..."])

def separar_por_evento(linhas):
    eventos = {}
    for registro in linhas:
        registro = str(registro)
        if len(registro) < 4:
            continue
        codigo = registro[:4]
        if codigo not in eventos:
            eventos[codigo] = []
        eventos[codigo].append(registro.split('|'))
    return eventos

st.title("MANAD - Separação por Evento e Geração de Excel")

uploaded_file = st.file_uploader("Selecione o arquivo MANAD (.txt ou .xlsx)", type=["txt", "xlsx"])

if uploaded_file:
    st.success("Arquivo carregado!")
    linhas = []

    if uploaded_file.name.endswith(".txt"):
        # Lê TXT
        linhas = uploaded_file.read().decode("latin1").splitlines()
    else:
        # Lê Excel (primeira coluna de todas as abas)
        xls = pd.ExcelFile(uploaded_file)
        for aba in xls.sheet_names:
            df_aba = pd.read_excel(xls, sheet_name=aba, header=None)
            linhas += df_aba[0].dropna().astype(str).tolist()

    eventos = separar_por_evento(linhas)
    st.write(f"Eventos encontrados: {list(eventos.keys())}")

    if st.button("Gerar arquivo Excel por evento"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if eventos:
                for codigo, registros in eventos.items():
                    cabecalho = cabecalho_evento(codigo)
                    df_evento = pd.DataFrame(registros, columns=cabecalho)
                    # Sheet names must be <= 31 chars and unique
                    sheet_name = codigo[:31]
                    df_evento.to_excel(writer, sheet_name=sheet_name, index=False)
            else:
                # Cria uma aba "Vazio" se não houver eventos
                pd.DataFrame([["Nenhum evento encontrado"]]).to_excel(writer, sheet_name="Vazio", index=False)
        output.seek(0)
        st.download_button(
            label="Baixar Excel com todos os eventos",
            data=output,
            file_name="MANAD_Eventos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )