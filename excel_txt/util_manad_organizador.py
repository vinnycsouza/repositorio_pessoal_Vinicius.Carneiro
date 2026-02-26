import streamlit as st
import pandas as pd
import io
from datetime import datetime

st.set_page_config(page_title="Unir MANAD (TXT/Excel)", layout="centered")
st.title("🧷 Unir MANAD — TXT único (bruto) ou Excel único")
st.caption(
    "TXT único (bruto) = concatena bytes sem alterar nada. "
    "Excel = representação para manipular (precisa decode)."
)

arquivos = st.file_uploader(
    "Envie os TXT do MANAD (selecione na ordem correta)",
    type=["txt"],
    accept_multiple_files=True
)

st.divider()

col1, col2 = st.columns(2)

# Opções (afetando SOMENTE o TXT bruto)
with col1:
    adicionar_quebra_entre = st.checkbox(
        "Adicionar 1 quebra de linha ENTRE arquivos (altera 1 byte entre eles)",
        value=False
    )

# Opções (afetando SOMENTE o Excel)
with col2:
    encoding_excel = st.selectbox(
        "Encoding para gerar o Excel (mais comum no MANAD: latin-1)",
        ["latin-1", "utf-8"],
        index=0
    )

incluir_origem_excel = st.checkbox("Excel: incluir ARQ_ORIGEM e N_LINHA", value=True)

def gerar_txt_bruto(files, add_newline_between: bool) -> bytes:
    """Concatena os arquivos em bytes, sem alterar conteúdo."""
    out = io.BytesIO()
    for i, f in enumerate(files):
        out.write(f.getvalue())  # bytes brutos
        if add_newline_between and i < len(files) - 1:
            out.write(b"\n")  # altera o resultado (opcional)
    return out.getvalue()

def gerar_excel(files, encoding: str, incluir_origem: bool) -> bytes:
    """
    Gera Excel com 1 linha por linha do TXT.
    Observação: Excel exige decode -> isso é para análise/manipulação.
    """
    rows = []

    for f in files:
        b = f.getvalue()
        texto = b.decode(encoding, errors="replace")  # representação
        linhas = texto.splitlines()

        if incluir_origem:
            for idx, ln in enumerate(linhas, start=1):
                rows.append({"ARQ_ORIGEM": f.name, "N_LINHA": idx, "LINHA": ln})
        else:
            for ln in linhas:
                rows.append({"LINHA": ln})

    df = pd.DataFrame(rows)

    buff = io.BytesIO()
    with pd.ExcelWriter(buff, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="MANAD_LINHAS")
    return buff.getvalue()

if not arquivos:
    st.info("Envie os arquivos .txt para habilitar os downloads.")
    st.stop()

st.success(f"{len(arquivos)} arquivo(s) carregado(s).")

agora = datetime.now().strftime("%Y%m%d_%H%M%S")

# ---------- BOTÃO 1: TXT único (bruto) ----------
txt_bytes = gerar_txt_bruto(arquivos, adicionar_quebra_entre)

st.download_button(
    "⬇️ Baixar TXT único (BRUTO, sem alterar nada)",
    data=txt_bytes,
    file_name=f"manad_unido_bruto_{agora}.txt",
    mime="text/plain"
)

# ---------- BOTÃO 2: Excel único ----------
excel_bytes = gerar_excel(arquivos, encoding_excel, incluir_origem_excel)

st.download_button(
    "⬇️ Baixar Excel único (XLSX)",
    data=excel_bytes,
    file_name=f"manad_unido_{agora}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

with st.expander("Prévia rápida"):
    st.write(f"Tamanho do TXT bruto: **{len(txt_bytes):,} bytes**")
    st.write("Primeiras 30 linhas (do Excel gerado):")
    # mostra preview do excel (a partir do mesmo dataframe seria mais caro; aqui simplificamos)
    # então mostramos prévia do primeiro arquivo decodificado:
    prev = arquivos[0].getvalue().decode(encoding_excel, errors="replace").splitlines()[:30]
    st.text("\n".join(prev))