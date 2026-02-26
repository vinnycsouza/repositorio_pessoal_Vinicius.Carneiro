import streamlit as st
import pandas as pd
import io
from datetime import datetime

st.set_page_config(page_title="Unir MANAD (TXT/Excel)", layout="centered")

st.title("🧷 Unir MANAD — TXT único (bruto) ou Excel único")
st.caption(
    "TXT único (bruto) = concatena arquivos sem alterar absolutamente nada.\n"
    "Excel = versão para manipulação/análise."
)

arquivos = st.file_uploader(
    "Envie os TXT do MANAD (selecione na ordem correta)",
    type=["txt"],
    accept_multiple_files=True
)

st.divider()

col1, col2 = st.columns(2)

with col1:
    adicionar_quebra_entre = st.checkbox(
        "Adicionar 1 quebra de linha ENTRE arquivos (⚠ altera 1 byte entre eles)",
        value=False
    )

with col2:
    encoding_excel = st.selectbox(
        "Encoding para gerar o Excel",
        ["latin-1", "utf-8"],
        index=0
    )

incluir_origem_excel = st.checkbox(
    "Excel: incluir ARQ_ORIGEM e N_LINHA",
    value=True
)

def gerar_txt_bruto(files, add_newline_between: bool) -> bytes:
    """
    Concatena os arquivos exatamente como estão (byte a byte).
    Nenhuma modificação é feita no conteúdo.
    """
    out = io.BytesIO()

    for i, f in enumerate(files):
        out.write(f.getvalue())

        if add_newline_between and i < len(files) - 1:
            out.write(b"\n")  # opcional (altera conteúdo)

    return out.getvalue()


def gerar_excel(files, encoding: str, incluir_origem: bool) -> bytes:
    """
    Gera um Excel para análise.
    OBS: Excel exige decodificação (não é byte idêntico ao original).
    """
    rows = []

    for f in files:
        b = f.getvalue()
        texto = b.decode(encoding, errors="replace")
        linhas = texto.splitlines()

        if incluir_origem:
            for idx, ln in enumerate(linhas, start=1):
                rows.append({
                    "ARQ_ORIGEM": f.name,
                    "N_LINHA": idx,
                    "LINHA": ln
                })
        else:
            for ln in linhas:
                rows.append({"LINHA": ln})

    df = pd.DataFrame(rows)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="MANAD_LINHAS")

    return buffer.getvalue()


if not arquivos:
    st.info("Envie os arquivos .txt para habilitar os downloads.")
    st.stop()

st.success(f"{len(arquivos)} arquivo(s) carregado(s).")

agora = datetime.now().strftime("%Y%m%d_%H%M%S")

# ---------------- TXT BRUTO ----------------
txt_bytes = gerar_txt_bruto(arquivos, adicionar_quebra_entre)

st.download_button(
    "⬇️ Baixar TXT único (BRUTO, sem alterar nada)",
    data=txt_bytes,
    file_name=f"manad_unido_bruto_{agora}.txt",
    mime="text/plain"
)

# ---------------- EXCEL ----------------
excel_bytes = gerar_excel(arquivos, encoding_excel, incluir_origem_excel)

st.download_button(
    "⬇️ Baixar Excel único (XLSX)",
    data=excel_bytes,
    file_name=f"manad_unido_{agora}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

with st.expander("Prévia rápida"):
    st.write(f"Tamanho do TXT bruto: **{len(txt_bytes):,} bytes**")
    preview = arquivos[0].getvalue().decode(encoding_excel, errors="replace").splitlines()[:30]
    st.text("\n".join(preview))