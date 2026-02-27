i# app_zip_xml.py
# 📦 Coletor de XML (NF-e / NFC-e) — Multi ZIP ➜ Novo ZIP
# ✅ Lê XML dentro de ZIP (e ZIP dentro de ZIP)
# ✅ Ignora Cancelados / Inutilizados / Denegados (por pasta/nome + por conteúdo)
# ✅ Gera um ZIP final com **TODOS os XML em UMA ÚNICA PASTA** (XML/)
# ✅ Mantém o **nome original** e, se repetir, usa padrão: "arquivo.xml", "arquivo (1).xml", "arquivo (2).xml"...

import io
import re
import zipfile
from pathlib import Path

import streamlit as st


# ---------------- UI ----------------
st.set_page_config(page_title="Coletor de XML — MultiZIP", layout="wide")
st.title("📦 Coletor de XML (NF-e / NFC-e) — Multi ZIP ➜ Novo ZIP")

st.caption(
    "• Envie vários .zip (um por vez ou vários) • O app vai extrair apenas XML válidos "
    "(ignorando Cancelados/Inutilizados/Denegados) e gerar um novo ZIP com tudo em uma única pasta."
)

# ---------------- Regras de exclusão ----------------
EXCLUDE_PATH_TOKENS = (
    "cancel", "cancelad", "cancelados",
    "inutil", "inutiliz", "inutilizados",
    "deneg", "denegad", "denegados",
)

# Cancelamento de NF-e costuma aparecer em procEventoNFe com tpEvento 110111
CANCEL_EVENT_CODE = b"110111"
# Inutilização costuma aparecer como procInutNFe / inutNFe
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

    # Cancelamento (procEventoNFe + 110111)
    if b"proceventonfe" in b and CANCEL_EVENT_CODE in b:
        return True

    # Fallback por texto
    if b"cancelamento" in b or b"inutiliz" in b or b"deneg" in b:
        return True

    return False


def unique_flat_name(original_name: str, used_names: set) -> str:
    """
    Mantém o nome original (sem subpastas).
    Se repetir, adiciona:
      arquivo.xml
      arquivo (1).xml
      arquivo (2).xml
    """
    name = Path(original_name).name  # remove subpastas
    base = Path(name).stem
    ext = Path(name).suffix

    candidate = name
    counter = 1
    while candidate in used_names:
        candidate = f"{base} ({counter}){ext}"
        counter += 1

    used_names.add(candidate)
    return candidate


def process_zip_bytes(
    zbytes: bytes,
    zout: zipfile.ZipFile,
    depth: int,
    max_depth: int,
    stats: dict,
    used_names: set,
):
    """Processa um ZIP em memória; extrai XMLs e lida com ZIP aninhado."""
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

        # Excluir por caminho/pasta dentro do zip
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
            process_zip_bytes(
                zbytes=nested_bytes,
                zout=zout,
                depth=depth + 1,
                max_depth=max_depth,
                stats=stats,
                used_names=used_names,
            )
            continue

        # XML
        if inner_lower.endswith(".xml"):
            try:
                xml_bytes = zin.read(info)
            except Exception:
                stats["xml_erros"] += 1
                continue

            # Excluir por conteúdo (cancel/inut/deneg quando misturado)
            if should_exclude_by_content(xml_bytes):
                stats["ignorados_conteudo"] += 1
                continue

            # ✅ ACHAR: tudo numa pasta única, preservando nome original com (1), (2)...
            flat = unique_flat_name(inner_name, used_names)
            arcname = f"XML/{flat}"
            zout.writestr(arcname, xml_bytes)
            stats["incluidos"] += 1


# ---------------- Inputs ----------------
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    zips = st.file_uploader(
        "Envie seus arquivos .zip (pode selecionar vários)",
        type=["zip"],
        accept_multiple_files=True,
    )

with col2:
    max_depth = st.number_input(
        "Nível máx. ZIP dentro de ZIP",
        min_value=1,
        max_value=10,
        value=3,
        step=1,
        help="Se existir .zip dentro de .zip, aumente esse nível (mas evite valores altos).",
    )

with col3:
    limite = st.number_input(
        "Limite de ZIPs (segurança)",
        min_value=1,
        max_value=200,
        value=10,
        step=1,
        help="Use para evitar seleção acidental de muitos arquivos no Cloud.",
    )

# Diagnóstico leve (ajuda na UX quando múltiplos não carregam)
if zips is None:
    st.info("Selecione pelo menos 1 arquivo .zip.")
elif len(zips) == 0:
    st.warning("Nenhum arquivo carregado (lista vazia). Tente selecionar novamente ou arrastar e soltar.")
else:
    st.subheader("📎 Arquivos carregados")
    for f in zips:
        st.write(f"- {f.name} — {f.size/1024/1024:.1f} MB")

    if len(zips) > int(limite):
        st.error(f"Você selecionou {len(zips)} ZIPs. O limite atual é {limite}. Aumente o limite e tente novamente.")
        st.stop()

    if st.button("🚀 Gerar novo ZIP com XML válidos (pasta única)", type="primary"):
        stats = {
            "incluidos": 0,
            "ignorados_path": 0,
            "ignorados_conteudo": 0,
            "xml_erros": 0,
            "zip_erros": 0,
            "zip_depth_limite": 0,
        }

        used_names = set()  # ✅ controla duplicidade no ZIP final com padrão (1), (2)...

        out_buffer = io.BytesIO()
        with zipfile.ZipFile(out_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for f in zips:
                try:
                    zbytes = f.read()
                except Exception:
                    stats["zip_erros"] += 1
                    continue

                # processa o zip (e aninhados)
                process_zip_bytes(
                    zbytes=zbytes,
                    zout=zout,
                    depth=1,
                    max_depth=int(max_depth),
                    stats=stats,
                    used_names=used_names,
                )

        out_buffer.seek(0)

        st.success("ZIP gerado com sucesso ✅")
        st.write(stats)

        # ✅ IMPORTANTE: usar o buffer direto evita duplicar RAM com getvalue()
        st.download_button(
            "⬇️ Baixar ZIP com XML válidos",
            data=out_buffer,
            file_name="XML_VALIDOS.zip",
            mime="application/zip",
        )