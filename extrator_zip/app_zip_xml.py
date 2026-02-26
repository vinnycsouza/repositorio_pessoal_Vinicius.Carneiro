import io
import re
import zipfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Coletor de XML (NF-e) — MultiZIP", layout="wide")
st.title("📦 Coletor de XML (NF-e) — Multi ZIP ➜ Novo ZIP")

EXCLUDE_PATH_TOKENS = (
    "cancel", "cancelad", "cancelados",
    "inutil", "inutiliz", "inutilizados",
    "deneg", "denegad", "denegados",
)

CANCEL_EVENT_CODE = b"110111"  # Evento de cancelamento NF-e (tpEvento)
INUT_MARKERS = (b"procInutNFe", b"<inutNFe", b"</procInutNFe>")

def should_exclude_by_path(path_like: str) -> bool:
    p = path_like.replace("\\", "/").lower()
    return any(tok in p for tok in EXCLUDE_PATH_TOKENS)

def normalize_xml_bytes(b: bytes) -> bytes:
    b = b.strip()
    b = re.sub(br"\s+", b" ", b)
    return b.lower()

def should_exclude_by_content(xml_bytes: bytes) -> bool:
    b = normalize_xml_bytes(xml_bytes)

    # Inutilização
    if any(m.lower() in b for m in INUT_MARKERS):
        return True

    # Cancelamento (procEventoNFe com tpEvento 110111)
    if b"proceventonfe" in b and CANCEL_EVENT_CODE in b:
        return True

    # Fallback por texto (pega casos fora do padrão)
    if b"cancelamento" in b or b"inutiliz" in b or b"deneg" in b:
        return True

    return False

def safe_arcname(*parts: str) -> str:
    clean = []
    for p in parts:
        if not p:
            continue
        p = p.replace("\\", "/").strip("/")
        if p:
            clean.append(p)
    return "/".join(clean)

def process_zip_bytes(zbytes: bytes, zout: zipfile.ZipFile, origin_prefix: str, depth: int, max_depth: int, stats: dict):
    try:
        zin = zipfile.ZipFile(io.BytesIO(zbytes), "r")
    except zipfile.BadZipFile:
        stats["zip_erros"] += 1
        return

    for info in zin.infolist():
        if info.is_dir():
            continue

        inner_name = info.filename
        inner_lower = inner_name.lower()

        if should_exclude_by_path(inner_name):
            stats["ignorados_path"] += 1
            continue

        # ZIP aninhado
        if inner_lower.endswith(".zip"):
            if depth >= max_depth:
                stats["zip_depth_limite"] += 1
                continue
            try:
                nested_bytes = zin.read(info)
            except Exception:
                stats["zip_erros"] += 1
                continue

            nested_prefix = safe_arcname(origin_prefix, f"zip__{Path(inner_name).stem}")
            process_zip_bytes(nested_bytes, zout, nested_prefix, depth + 1, max_depth, stats)
            continue

        # XML
        if inner_lower.endswith(".xml"):
            try:
                xml_bytes = zin.read(info)
            except Exception:
                stats["xml_erros"] += 1
                continue

            if should_exclude_by_content(xml_bytes):
                stats["ignorados_conteudo"] += 1
                continue

            arcname = safe_arcname(origin_prefix, inner_name)
            zout.writestr(arcname, xml_bytes)
            stats["incluidos"] += 1

# -------- UI --------
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    zips = st.file_uploader(
        "Envie seus arquivos .zip (pode selecionar vários de uma vez)",
        type=["zip"],
        accept_multiple_files=True
    )
with col2:
    max_depth = st.number_input("Nível máx. ZIP dentro de ZIP", min_value=1, max_value=10, value=3, step=1)
with col3:
    limite = st.number_input("Limite de ZIPs (segurança)", min_value=1, max_value=200, value=10, step=1)

if zips:
    if len(zips) > int(limite):
        st.error(f"Você selecionou {len(zips)} ZIPs. O limite atual é {limite}. Aumente o limite e tente novamente.")
        st.stop()

    if st.button("🚀 Gerar novo ZIP com XML válidos", type="primary"):
        stats = {
            "incluidos": 0,
            "ignorados_path": 0,
            "ignorados_conteudo": 0,
            "xml_erros": 0,
            "zip_erros": 0,
            "zip_depth_limite": 0,
        }

        out_buffer = io.BytesIO()
        with zipfile.ZipFile(out_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for f in zips:
                try:
                    zbytes = f.read()
                except Exception:
                    stats["zip_erros"] += 1
                    continue

                prefix = safe_arcname("de_zip", Path(f.name).stem)
                process_zip_bytes(
                    zbytes=zbytes,
                    zout=zout,
                    origin_prefix=prefix,
                    depth=1,
                    max_depth=int(max_depth),
                    stats=stats
                )

        out_buffer.seek(0)

        st.success("ZIP gerado com sucesso ✅")
        st.write(stats)

        st.download_button(
            "⬇️ Baixar ZIP com XML válidos",
            data=out_buffer.getvalue(),
            file_name="XML_VALIDOS.zip",
            mime="application/zip"
        )
else:
    st.info("Selecione pelo menos 1 arquivo .zip (você pode selecionar vários).")