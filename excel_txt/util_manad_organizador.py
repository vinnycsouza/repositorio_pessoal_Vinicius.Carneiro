import streamlit as st
import pandas as pd
import io
import zipfile
from datetime import datetime

st.set_page_config(page_title="Organizador MANAD (TXT)", layout="centered")
st.title("🗂️ Organizador MANAD — TXT completos")
st.caption("Gera um ZIP com os arquivos MANAD sem quebrar o padrão do Manual, e opcionalmente um Excel de conferência.")

arquivos = st.file_uploader(
    "Envie os TXT do MANAD (arquivos completos: 0000...9999)",
    type=["txt"],
    accept_multiple_files=True
)

# MANAD: ASCII ISO-8859-1 (Latin-1) :contentReference[oaicite:3]{index=3}
encoding_leitura = st.selectbox("Encoding de leitura (recomendado: latin-1)", ["latin-1", "utf-8"], index=0)

normalizar_quebras = st.checkbox("Normalizar quebras de linha para \\n (recomendado)", value=True)
regravar_latin1 = st.checkbox("Salvar no ZIP em Latin-1 (recomendado p/ padrão)", value=True)

gerar_excel = st.checkbox("Gerar Excel de conferência", value=True)

def ler_txt(uploaded_file) -> str:
    txt = uploaded_file.getvalue().decode(encoding_leitura, errors="ignore")
    if normalizar_quebras:
        txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    # remove linhas vazias no final
    while txt.endswith("\n\n"):
        txt = txt[:-1]
    return txt

def primeiro_registro(txt: str) -> str:
    for ln in txt.splitlines():
        if ln.strip():
            return ln[:4]
    return ""

def ultimo_registro(txt: str) -> str:
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    return lines[-1][:4] if lines else ""

def extrair_qtd_lin_9999(txt: str):
    # 9999|QTD_LIN
    for ln in reversed([l for l in txt.splitlines() if l.strip()]):
        if ln.startswith("9999"):
            parts = ln.split("|")
            # formato: 9999|<qtd>
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except:
                    return None
    return None

def contar_linhas_arquivo(txt: str) -> int:
    # Manual: QTD_LIN considera todas as linhas entre o primeiro 0000 e o 9999, inclusive :contentReference[oaicite:4]{index=4}
    lines = [ln for ln in txt.splitlines() if ln.strip() != ""]
    return len(lines)

if arquivos:
    agora = datetime.now().strftime("%Y%m%d_%H%M%S")

    rel = []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in arquivos:
            txt = ler_txt(f)

            reg_ini = primeiro_registro(txt)
            reg_fim = ultimo_registro(txt)

            qtd_9999 = extrair_qtd_lin_9999(txt)
            qtd_calc = contar_linhas_arquivo(txt)

            # MANAD: cada linha é um registro e o REG são os 4 primeiros caracteres :contentReference[oaicite:5]{index=5}
            ok_ini = (reg_ini == "0000")
            ok_fim = (reg_fim == "9999")

            ok_qtd = (qtd_9999 == qtd_calc) if (qtd_9999 is not None) else False

            rel.append({
                "arquivo": f.name,
                "inicio_REG": reg_ini,
                "fim_REG": reg_fim,
                "tem_0000": ok_ini,
                "tem_9999": ok_fim,
                "QTD_LIN_9999": qtd_9999,
                "QTD_LIN_calculada": qtd_calc,
                "QTD_LIN_bate": ok_qtd
            })

            # grava no zip (preferência: Latin-1) :contentReference[oaicite:6]{index=6}
            if regravar_latin1:
                data = txt.encode("latin-1", errors="replace")
            else:
                data = txt.encode("utf-8", errors="ignore")

            zf.writestr(f.name, data)

    st.success(f"{len(arquivos)} arquivo(s) processado(s).")

    # download do ZIP com os originais “organizados”
    st.download_button(
        "⬇️ Baixar ZIP com os TXT (padrão MANAD)",
        data=zip_buffer.getvalue(),
        file_name=f"manad_txts_{agora}.zip",
        mime="application/zip"
    )

    df_rel = pd.DataFrame(rel).sort_values(["QTD_LIN_bate", "arquivo"], ascending=[True, True])
    st.subheader("Conferência rápida")
    st.dataframe(df_rel, use_container_width=True)

    if gerar_excel:
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            df_rel.to_excel(writer, index=False, sheet_name="CONFERENCIA")
        st.download_button(
            "⬇️ Baixar Excel de conferência",
            data=excel_buffer.getvalue(),
            file_name=f"conferencia_manad_{agora}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    st.info(
        "Observação: este utilitário NÃO concatena arquivos completos em um TXT único, "
        "porque isso geralmente quebra a estrutura (múltiplos 0000/9999) e a contagem do 9999 "
        "(QTD_LIN do primeiro 0000 ao 9999)."
    )
else:
    st.warning("Envie os TXT para começar.")