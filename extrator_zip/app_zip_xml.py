# app_zip_xml.py
# 📦 Coletor de XML (NF-e / NFC-e) — Multi ZIP ➜ Novo ZIP + Excel de Conferência
# ✅ Lê XML dentro de ZIP (e ZIP dentro de ZIP)
# ✅ Ignora Cancelados / Inutilizados / Denegados (por pasta/nome + por conteúdo)
# ✅ Gera um ZIP final com TODOS os XML em UMA ÚNICA PASTA (XML/)
# ✅ Mantém o nome original e, se repetir, usa:
#    arquivo.xml, arquivo (1).xml, arquivo (2).xml...
# ✅ Identifica Entrada / Saída pelo campo tpNF do XML
# ✅ Gera Excel de conferência com dados principais

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd
import streamlit as st


# =========================================================
# CONFIG UI
# =========================================================
st.set_page_config(page_title="Coletor de XML — Multi ZIP", layout="wide")

st.title("📦 Coletor de XML (NF-e / NFC-e) — Multi ZIP ➜ Novo ZIP")
st.caption(
    "Envie vários arquivos .zip. O app extrai apenas XML válidos, "
    "ignora Cancelados / Inutilizados / Denegados, identifica Entrada / Saída "
    "e gera um ZIP final + Excel de conferência."
)


# =========================================================
# CONSTANTES
# =========================================================
EXCLUDE_PATH_TOKENS = (
    "cancel", "cancelad", "cancelados",
    "inutil", "inutiliz", "inutilizados",
    "deneg", "denegad", "denegados",
)

CANCEL_EVENT_CODE = b"110111"
INUT_MARKERS = (
    b"procInutNFe",
    b"<inutNFe",
    b"</procInutNFe>",
)
DENEG_MARKERS = (
    b"deneg",
    b"denegad",
)

MAX_XML_SIZE_MB = 50


# =========================================================
# FUNÇÕES GERAIS
# =========================================================
def should_exclude_by_path(path_like: str) -> bool:
    p = path_like.replace("\\", "/").lower()
    return any(tok in p for tok in EXCLUDE_PATH_TOKENS)


def normalize_xml_bytes(content: bytes) -> bytes:
    content = content.strip()
    content = re.sub(br"\s+", b" ", content)
    return content.lower()


def should_exclude_by_content(xml_bytes: bytes) -> bool:
    b = normalize_xml_bytes(xml_bytes)

    if any(marker.lower() in b for marker in INUT_MARKERS):
        return True

    if b"proceventonfe" in b and CANCEL_EVENT_CODE in b:
        return True

    if b"cancelamento" in b:
        return True

    if b"inutiliz" in b:
        return True

    if any(marker in b for marker in DENEG_MARKERS):
        return True

    return False


def unique_flat_name(original_name: str, used_names: set[str]) -> str:
    name = Path(original_name).name
    base = Path(name).stem
    ext = Path(name).suffix

    candidate = name
    counter = 1

    while candidate in used_names:
        candidate = f"{base} ({counter}){ext}"
        counter += 1

    used_names.add(candidate)
    return candidate


def init_stats() -> dict:
    return {
        "incluidos": 0,
        "ignorados_path": 0,
        "ignorados_conteudo": 0,
        "xml_erros": 0,
        "zip_erros": 0,
        "zip_depth_limite": 0,
        "arquivos_zip_processados": 0,
        "arquivos_zip_enviados": 0,
        "xml_grandes_ignorados": 0,
    }


def format_size_mb(num_bytes: int) -> str:
    return f"{num_bytes / 1024 / 1024:.1f} MB"


def safe_text(value):
    if value is None:
        return ""
    return str(value).strip()


def only_digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


# =========================================================
# XML / NFE
# =========================================================
def strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def find_first_text_by_localname(root: ET.Element, localname: str) -> str:
    for elem in root.iter():
        if strip_namespace(elem.tag) == localname:
            return safe_text(elem.text)
    return ""


def find_child_text(parent: ET.Element | None, localname: str) -> str:
    if parent is None:
        return ""
    for elem in parent:
        if strip_namespace(elem.tag) == localname:
            return safe_text(elem.text)
    return ""


def find_first_element_by_localname(root: ET.Element, localname: str):
    for elem in root.iter():
        if strip_namespace(elem.tag) == localname:
            return elem
    return None


def detectar_tipo_documento(root: ET.Element) -> str:
    inf_nfe = find_first_element_by_localname(root, "infNFe")
    if inf_nfe is None:
        return ""

    ide = None
    emit = None
    dest = None

    for child in inf_nfe:
        tag = strip_namespace(child.tag)
        if tag == "ide":
            ide = child
        elif tag == "emit":
            emit = child
        elif tag == "dest":
            dest = child

    mod = find_child_text(ide, "mod")
    tp_nf = find_child_text(ide, "tpNF")

    if mod == "65":
        return "NFC-e"

    if mod == "55":
        return "NF-e"

    if tp_nf in {"0", "1"} and emit is not None and dest is not None:
        return "NF-e/NFC-e"

    return ""


def classificar_entrada_saida(tp_nf: str) -> str:
    if tp_nf == "0":
        return "Entrada"
    if tp_nf == "1":
        return "Saída"
    return ""


def extrair_chave_acesso(root: ET.Element) -> str:
    inf_nfe = find_first_element_by_localname(root, "infNFe")
    if inf_nfe is not None:
        inf_id = safe_text(inf_nfe.attrib.get("Id"))
        if inf_id.upper().startswith("NFE") and len(inf_id) >= 47:
            return only_digits(inf_id)
    return find_first_text_by_localname(root, "chNFe")


def extrair_xml_info(xml_bytes: bytes, nome_arquivo_zip_final: str, origem_interna: str) -> dict:
    info = {
        "arquivo_final": nome_arquivo_zip_final,
        "origem_interna_zip": origem_interna,
        "tipo_documento": "",
        "chave_acesso": "",
        "numero_nota": "",
        "serie": "",
        "data_emissao": "",
        "tpNF": "",
        "classificacao": "",
        "cfop": "",
        "natOp": "",
        "emit_cnpj": "",
        "emit_nome": "",
        "dest_cnpj_cpf": "",
        "dest_nome": "",
        "valor_total_nota": "",
        "status_extracao": "OK",
    }

    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        info["status_extracao"] = "ERRO_XML"
        return info

    info["chave_acesso"] = extrair_chave_acesso(root)

    inf_nfe = find_first_element_by_localname(root, "infNFe")
    if inf_nfe is None:
        info["status_extracao"] = "SEM_infNFe"
        return info

    ide = None
    emit = None
    dest = None
    total = None

    for child in inf_nfe:
        tag = strip_namespace(child.tag)
        if tag == "ide":
            ide = child
        elif tag == "emit":
            emit = child
        elif tag == "dest":
            dest = child
        elif tag == "total":
            total = child

    info["tipo_documento"] = detectar_tipo_documento(root)
    info["numero_nota"] = find_child_text(ide, "nNF")
    info["serie"] = find_child_text(ide, "serie")
    info["data_emissao"] = (
        find_child_text(ide, "dhEmi")
        or find_child_text(ide, "dEmi")
    )
    info["tpNF"] = find_child_text(ide, "tpNF")
    info["classificacao"] = classificar_entrada_saida(info["tpNF"])
    info["natOp"] = find_child_text(ide, "natOp")

    info["emit_cnpj"] = find_child_text(emit, "CNPJ")
    info["emit_nome"] = find_child_text(emit, "xNome")

    dest_cnpj = find_child_text(dest, "CNPJ")
    dest_cpf = find_child_text(dest, "CPF")
    info["dest_cnpj_cpf"] = dest_cnpj or dest_cpf
    info["dest_nome"] = find_child_text(dest, "xNome")

    icms_total = None
    if total is not None:
        for child in total:
            if strip_namespace(child.tag) == "ICMSTot":
                icms_total = child
                break

    info["valor_total_nota"] = find_child_text(icms_total, "vNF")

    # Primeiro CFOP encontrado
    for elem in inf_nfe.iter():
        if strip_namespace(elem.tag) == "CFOP":
            info["cfop"] = safe_text(elem.text)
            break

    return info


# =========================================================
# ZIP PROCESSING
# =========================================================
def process_zip_bytes(
    zbytes: bytes,
    zout: zipfile.ZipFile,
    depth: int,
    max_depth: int,
    stats: dict,
    used_names: set[str],
    registros_conferencia: list,
):
    try:
        zin = zipfile.ZipFile(io.BytesIO(zbytes), "r")
    except zipfile.BadZipFile:
        stats["zip_erros"] += 1
        return
    except Exception:
        stats["zip_erros"] += 1
        return

    stats["arquivos_zip_processados"] += 1

    for info in zin.infolist():
        if info.is_dir():
            continue

        inner_name = info.filename
        inner_lower = inner_name.lower()

        if should_exclude_by_path(inner_name):
            stats["ignorados_path"] += 1
            continue

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
                registros_conferencia=registros_conferencia,
            )
            continue

        if inner_lower.endswith(".xml"):
            try:
                xml_bytes = zin.read(info)
            except Exception:
                stats["xml_erros"] += 1
                continue

            if len(xml_bytes) > MAX_XML_SIZE_MB * 1024 * 1024:
                stats["xml_grandes_ignorados"] += 1
                continue

            if should_exclude_by_content(xml_bytes):
                stats["ignorados_conteudo"] += 1
                continue

            flat_name = unique_flat_name(inner_name, used_names)
            arcname = f"XML/{flat_name}"

            try:
                zout.writestr(arcname, xml_bytes)
                stats["incluidos"] += 1

                registro = extrair_xml_info(
                    xml_bytes=xml_bytes,
                    nome_arquivo_zip_final=flat_name,
                    origem_interna=inner_name,
                )
                registros_conferencia.append(registro)

            except Exception:
                stats["xml_erros"] += 1


# =========================================================
# EXCEL
# =========================================================
def gerar_excel_conferencia(registros: list[dict]) -> io.BytesIO:
    df = pd.DataFrame(registros)

    colunas_ordem = [
        "arquivo_final",
        "origem_interna_zip",
        "tipo_documento",
        "chave_acesso",
        "numero_nota",
        "serie",
        "data_emissao",
        "tpNF",
        "classificacao",
        "cfop",
        "natOp",
        "emit_cnpj",
        "emit_nome",
        "dest_cnpj_cpf",
        "dest_nome",
        "valor_total_nota",
        "status_extracao",
    ]

    for col in colunas_ordem:
        if col not in df.columns:
            df[col] = ""

    df = df[colunas_ordem]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Conferencia")

        ws = writer.sheets["Conferencia"]

        larguras = {
            "A": 35,
            "B": 45,
            "C": 15,
            "D": 52,
            "E": 12,
            "F": 10,
            "G": 22,
            "H": 8,
            "I": 14,
            "J": 10,
            "K": 25,
            "L": 18,
            "M": 35,
            "N": 18,
            "O": 35,
            "P": 14,
            "Q": 16,
        }

        for col, largura in larguras.items():
            ws.column_dimensions[col].width = largura

        ws.freeze_panes = "A2"

    output.seek(0)
    return output


# =========================================================
# INPUTS
# =========================================================
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
        help="Se existir .zip dentro de .zip, aumente esse nível com cautela.",
    )

with col3:
    limite = st.number_input(
        "Limite de ZIPs (segurança)",
        min_value=1,
        max_value=200,
        value=10,
        step=1,
        help="Evita seleção acidental de arquivos demais no ambiente cloud.",
    )


# =========================================================
# DIAGNÓSTICO INICIAL
# =========================================================
if zips is None:
    st.info("Selecione pelo menos 1 arquivo .zip.")
    st.stop()

if len(zips) == 0:
    st.warning("Nenhum arquivo carregado. Tente selecionar novamente.")
    st.stop()

st.subheader("📎 Arquivos carregados")

total_size = 0
for f in zips:
    total_size += f.size
    st.write(f"- {f.name} — {format_size_mb(f.size)}")

st.write(f"**Total enviado:** {len(zips)} arquivo(s) — {format_size_mb(total_size)}")

if len(zips) > int(limite):
    st.error(
        f"Você selecionou {len(zips)} ZIPs, mas o limite atual é {limite}. "
        f"Aumente o limite e tente novamente."
    )
    st.stop()


# =========================================================
# PROCESSAMENTO
# =========================================================
if st.button("🚀 Gerar ZIP + Excel de conferência", type="primary"):
    stats = init_stats()
    stats["arquivos_zip_enviados"] = len(zips)

    used_names = set()
    registros_conferencia = []

    progress = st.progress(0, text="Iniciando processamento...")
    status = st.empty()

    out_buffer_zip = io.BytesIO()

    with zipfile.ZipFile(out_buffer_zip, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        total = len(zips)

        for i, f in enumerate(zips, start=1):
            status.write(f"Processando: **{f.name}** ({i}/{total})")

            try:
                zbytes = f.getvalue()
            except Exception:
                stats["zip_erros"] += 1
                progress.progress(i / total, text=f"Erro ao ler {f.name}")
                continue

            process_zip_bytes(
                zbytes=zbytes,
                zout=zout,
                depth=1,
                max_depth=int(max_depth),
                stats=stats,
                used_names=used_names,
                registros_conferencia=registros_conferencia,
            )

            progress.progress(
                i / total,
                text=f"Processados {i}/{total} arquivo(s)..."
            )

    out_buffer_zip.seek(0)

    excel_buffer = gerar_excel_conferencia(registros_conferencia)

    st.success("Processamento concluído com sucesso ✅")

    c1, c2, c3 = st.columns(3)
    c1.metric("XML incluídos", stats["incluidos"])
    c2.metric("Ignorados por pasta/nome", stats["ignorados_path"])
    c3.metric("Ignorados por conteúdo", stats["ignorados_conteudo"])

    c4, c5, c6 = st.columns(3)
    c4.metric("Erros de XML", stats["xml_erros"])
    c5.metric("Erros de ZIP", stats["zip_erros"])
    c6.metric("Limite de profundidade", stats["zip_depth_limite"])

    if stats["xml_grandes_ignorados"] > 0:
        st.warning(
            f"{stats['xml_grandes_ignorados']} XML(s) foram ignorados por excederem "
            f"{MAX_XML_SIZE_MB} MB."
        )

    with st.expander("Ver estatísticas detalhadas"):
        st.json(stats)

    if registros_conferencia:
        df_preview = pd.DataFrame(registros_conferencia)

        st.subheader("📋 Prévia da conferência")
        st.dataframe(
            df_preview[
                [
                    "arquivo_final",
                    "tipo_documento",
                    "chave_acesso",
                    "numero_nota",
                    "tpNF",
                    "classificacao",
                    "emit_nome",
                    "dest_nome",
                    "valor_total_nota",
                ]
            ],
            use_container_width=True,
        )

    nome_zip_saida = f"XML_VALIDOS_{stats['incluidos']}_arquivos.zip"
    nome_excel_saida = f"CONFERENCIA_XML_{stats['incluidos']}_arquivos.xlsx"

    col_dl1, col_dl2 = st.columns(2)

    with col_dl1:
        st.download_button(
            "⬇️ Baixar ZIP com XML válidos",
            data=out_buffer_zip,
            file_name=nome_zip_saida,
            mime="application/zip",
        )

    with col_dl2:
        st.download_button(
            "⬇️ Baixar Excel de conferência",
            data=excel_buffer,
            file_name=nome_excel_saida,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )