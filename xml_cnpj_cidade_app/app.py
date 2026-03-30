import io
import json
import zipfile
import tempfile
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

import pandas as pd
import streamlit as st


# =========================================================
# CONFIGURAÇÃO GERAL
# =========================================================
st.set_page_config(
    page_title="Relatório XML por Emitente e Destinatário",
    layout="wide"
)

st.title("📦 Relatório XML por Emitente, Destinatário, Cidade e Tipo de Nota")
st.caption(
    "Processa pastas com ZIP/XML, acumula os dados entre processamentos "
    "e gera um relatório consolidado final."
)


# =========================================================
# ARQUIVO TEMPORÁRIO DE PERSISTÊNCIA
# =========================================================
APP_TEMP_DIR = Path(tempfile.gettempdir()) / "streamlit_xml_emit_dest"
APP_TEMP_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = APP_TEMP_DIR / "estado_xml_relatorio.json"


# =========================================================
# ESTADO INICIAL
# =========================================================
def estado_padrao():
    return {
        "acumulado": {},
        "pastas_processadas": [],
        "arquivos_processados": [],
        "total_xml_validos": 0,
        "total_erros": 0,
        "total_arquivos_zip": 0,
        "total_arquivos_xml_soltos": 0,
        "log": [],
    }


def inicializar_session_state():
    if "estado_app" not in st.session_state:
        carregado = carregar_estado_disco()
        st.session_state["estado_app"] = carregado if carregado else estado_padrao()


# =========================================================
# PERSISTÊNCIA
# =========================================================
def salvar_estado_disco():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st.session_state["estado_app"], f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"Não foi possível salvar o estado temporário: {e}")


def carregar_estado_disco():
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return None
    return None


def apagar_estado_disco():
    try:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
    except Exception:
        pass


# =========================================================
# XML
# =========================================================
NAMESPACE = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


def texto_tag(parent, tag, ns=NAMESPACE):
    if parent is None:
        return ""
    node = parent.find(f"nfe:{tag}", ns)
    return node.text.strip() if node is not None and node.text else ""


def obter_documento(pai, ns=NAMESPACE):
    if pai is None:
        return ""
    cnpj = texto_tag(pai, "CNPJ", ns)
    if cnpj:
        return cnpj
    cpf = texto_tag(pai, "CPF", ns)
    return cpf


def identificar_tipo_nota(root, ns=NAMESPACE):
    ide = root.find(".//nfe:ide", ns)

    if ide is None:
        return "Não identificado", ""

    mod = texto_tag(ide, "mod", ns)
    tp_nf = texto_tag(ide, "tpNF", ns)

    if mod == "65":
        return "NFC-e", mod

    if mod == "55":
        if tp_nf == "0":
            return "NF-e Entrada", mod
        if tp_nf == "1":
            return "NF-e Saída", mod
        return "NF-e", mod

    return "Não identificado", mod


def extrair_emitente(root, ns=NAMESPACE):
    emit = root.find(".//nfe:emit", ns)
    ender_emit = emit.find("nfe:enderEmit", ns) if emit is not None else None

    return {
        "documento_emitente": obter_documento(emit, ns),
        "nome_emitente": texto_tag(emit, "xNome", ns),
        "cidade_emitente": texto_tag(ender_emit, "xMun", ns),
        "uf_emitente": texto_tag(ender_emit, "UF", ns),
    }


def extrair_destinatario(root, ns=NAMESPACE):
    dest = root.find(".//nfe:dest", ns)

    if dest is None:
        return {
            "documento_destinatario": "",
            "nome_destinatario": "",
            "cidade_destinatario": "",
            "uf_destinatario": "",
        }

    ender_dest = dest.find("nfe:enderDest", ns) if dest is not None else None

    return {
        "documento_destinatario": obter_documento(dest, ns),
        "nome_destinatario": texto_tag(dest, "xNome", ns),
        "cidade_destinatario": texto_tag(ender_dest, "xMun", ns),
        "uf_destinatario": texto_tag(ender_dest, "UF", ns),
    }


def extrair_chave_nota(root, ns=NAMESPACE):
    inf_nfe = root.find(".//nfe:infNFe", ns)
    if inf_nfe is not None:
        chave = inf_nfe.attrib.get("Id", "")
        return chave.replace("NFe", "").strip()
    return ""


def extrair_dados_principais(xml_bytes):
    try:
        root = ET.fromstring(xml_bytes)

        tipo_nota, modelo = identificar_tipo_nota(root, NAMESPACE)
        emit = extrair_emitente(root, NAMESPACE)
        dest = extrair_destinatario(root, NAMESPACE)
        chave_nota = extrair_chave_nota(root, NAMESPACE)

        return {
            "tipo_nota": tipo_nota,
            "modelo": modelo,
            "chave_nota": chave_nota,
            "documento_emitente": emit["documento_emitente"],
            "nome_emitente": emit["nome_emitente"],
            "cidade_emitente": emit["cidade_emitente"],
            "uf_emitente": emit["uf_emitente"],
            "documento_destinatario": dest["documento_destinatario"],
            "nome_destinatario": dest["nome_destinatario"],
            "cidade_destinatario": dest["cidade_destinatario"],
            "uf_destinatario": dest["uf_destinatario"],
            "erro": False,
        }
    except Exception:
        return {
            "tipo_nota": "",
            "modelo": "",
            "chave_nota": "",
            "documento_emitente": "",
            "nome_emitente": "",
            "cidade_emitente": "",
            "uf_emitente": "",
            "documento_destinatario": "",
            "nome_destinatario": "",
            "cidade_destinatario": "",
            "uf_destinatario": "",
            "erro": True,
        }


# =========================================================
# CHAVES E LOG
# =========================================================
def chave_acumulado(
    tipo_nota,
    modelo,
    documento_emitente,
    cidade_emitente,
    uf_emitente,
    documento_destinatario,
    cidade_destinatario,
    uf_destinatario,
):
    return "|||".join([
        tipo_nota,
        modelo,
        documento_emitente,
        cidade_emitente,
        uf_emitente,
        documento_destinatario,
        cidade_destinatario,
        uf_destinatario,
    ])


def split_chave_acumulado(chave):
    partes = chave.split("|||")
    while len(partes) < 8:
        partes.append("")
    return partes


def fingerprint_arquivo(path_obj):
    stat = path_obj.stat()
    base = f"{path_obj.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def adicionar_log(msg):
    st.session_state["estado_app"]["log"].append(msg)
    if len(st.session_state["estado_app"]["log"]) > 300:
        st.session_state["estado_app"]["log"] = st.session_state["estado_app"]["log"][-300:]


# =========================================================
# PROCESSAMENTO
# =========================================================
def processar_xml_bytes(xml_bytes):
    dados = extrair_dados_principais(xml_bytes)

    if dados["erro"]:
        return None

    if (
        dados["tipo_nota"]
        and dados["documento_emitente"]
        and dados["cidade_emitente"]
    ):
        return dados

    return None


def atualizar_acumulado(dados):
    chave = chave_acumulado(
        dados["tipo_nota"],
        dados["modelo"],
        dados["documento_emitente"],
        dados["cidade_emitente"],
        dados["uf_emitente"],
        dados["documento_destinatario"],
        dados["cidade_destinatario"],
        dados["uf_destinatario"],
    )

    acumulado = st.session_state["estado_app"]["acumulado"]
    acumulado[chave] = acumulado.get(chave, 0) + 1


def listar_arquivos_processaveis(caminho_pasta):
    pasta = Path(caminho_pasta)

    if not pasta.exists():
        raise ValueError("A pasta informada não existe.")

    if not pasta.is_dir():
        raise ValueError("O caminho informado não é uma pasta.")

    arquivos_zip = [p for p in pasta.rglob("*") if p.is_file() and p.suffix.lower() == ".zip"]
    arquivos_xml = [p for p in pasta.rglob("*") if p.is_file() and p.suffix.lower() == ".xml"]

    return arquivos_zip, arquivos_xml


def processar_pasta(caminho_pasta):
    estado = st.session_state["estado_app"]
    pasta = Path(caminho_pasta)

    if str(pasta.resolve()) in estado["pastas_processadas"]:
        raise ValueError("Essa pasta já foi processada nesta sessão.")

    arquivos_zip, arquivos_xml = listar_arquivos_processaveis(caminho_pasta)

    total_itens = len(arquivos_zip) + len(arquivos_xml)

    if total_itens == 0:
        raise ValueError("Nenhum arquivo ZIP ou XML foi encontrado na pasta.")

    progresso = st.progress(0, text="Iniciando processamento...")

    xml_validos = 0
    erros = 0
    zips_lidos = 0
    xml_soltos_lidos = 0

    arquivos_processados_set = set(estado["arquivos_processados"])

    indice = 0

    for xml_file in arquivos_xml:
        indice += 1
        progresso.progress(
            indice / total_itens,
            text=f"Processando XML solto {indice}/{total_itens}: {xml_file.name}"
        )

        try:
            fp = fingerprint_arquivo(xml_file)
            if fp in arquivos_processados_set:
                adicionar_log(f"XML ignorado (já processado): {xml_file}")
                continue

            xml_bytes = xml_file.read_bytes()
            dados = processar_xml_bytes(xml_bytes)

            if dados:
                atualizar_acumulado(dados)
                xml_validos += 1
            else:
                erros += 1

            arquivos_processados_set.add(fp)
            xml_soltos_lidos += 1

        except Exception as e:
            erros += 1
            adicionar_log(f"Erro XML solto {xml_file}: {e}")

    for zip_file in arquivos_zip:
        indice += 1
        progresso.progress(
            indice / total_itens,
            text=f"Processando ZIP {indice}/{total_itens}: {zip_file.name}"
        )

        try:
            fp_zip = fingerprint_arquivo(zip_file)
            if fp_zip in arquivos_processados_set:
                adicionar_log(f"ZIP ignorado (já processado): {zip_file}")
                continue

            with zipfile.ZipFile(zip_file, "r") as z:
                nomes_xml = [n for n in z.namelist() if n.lower().endswith(".xml")]

                for nome_xml in nomes_xml:
                    try:
                        xml_bytes = z.read(nome_xml)
                        dados = processar_xml_bytes(xml_bytes)

                        if dados:
                            atualizar_acumulado(dados)
                            xml_validos += 1
                        else:
                            erros += 1

                    except Exception as e:
                        erros += 1
                        adicionar_log(f"Erro no XML {nome_xml} dentro de {zip_file.name}: {e}")

            arquivos_processados_set.add(fp_zip)
            zips_lidos += 1

        except Exception as e:
            erros += 1
            adicionar_log(f"Erro ZIP {zip_file}: {e}")

    progresso.progress(1.0, text="Processamento concluído.")

    estado["pastas_processadas"].append(str(pasta.resolve()))
    estado["arquivos_processados"] = list(arquivos_processados_set)
    estado["total_xml_validos"] += xml_validos
    estado["total_erros"] += erros
    estado["total_arquivos_zip"] += zips_lidos
    estado["total_arquivos_xml_soltos"] += xml_soltos_lidos

    adicionar_log(
        f"Pasta processada: {pasta.resolve()} | "
        f"ZIPs lidos: {zips_lidos} | XML soltos lidos: {xml_soltos_lidos} | "
        f"XML válidos: {xml_validos} | Erros: {erros}"
    )

    salvar_estado_disco()

    return {
        "xml_validos": xml_validos,
        "erros": erros,
        "zips_lidos": zips_lidos,
        "xml_soltos_lidos": xml_soltos_lidos,
    }


# =========================================================
# DATAFRAMES E EXCEL
# =========================================================
def gerar_dataframe_consolidado():
    acumulado = st.session_state["estado_app"]["acumulado"]

    linhas = []
    for chave, quantidade in acumulado.items():
        (
            tipo_nota,
            modelo,
            documento_emitente,
            cidade_emitente,
            uf_emitente,
            documento_destinatario,
            cidade_destinatario,
            uf_destinatario,
        ) = split_chave_acumulado(chave)

        linhas.append({
            "Tipo de Nota": tipo_nota,
            "Modelo": modelo,
            "Documento Emitente": documento_emitente,
            "Cidade Emitente": cidade_emitente,
            "UF Emitente": uf_emitente,
            "Documento Destinatário": documento_destinatario,
            "Cidade Destinatário": cidade_destinatario,
            "UF Destinatário": uf_destinatario,
            "Quantidade XML": quantidade,
        })

    df = pd.DataFrame(linhas)

    if df.empty:
        return df

    df = df.sort_values(
        by=[
            "Tipo de Nota",
            "Documento Emitente",
            "Cidade Emitente",
            "Documento Destinatário",
            "Cidade Destinatário",
        ],
        ascending=[True, True, True, True, True]
    ).reset_index(drop=True)

    return df


def gerar_resumos(df):
    if df.empty:
        return {
            "resumo_tipo": pd.DataFrame(),
            "resumo_emitente": pd.DataFrame(),
            "resumo_destinatario": pd.DataFrame(),
            "resumo_cidade_emitente": pd.DataFrame(),
            "resumo_cidade_destinatario": pd.DataFrame(),
            "estatisticas": pd.DataFrame(),
        }

    resumo_tipo = (
        df.groupby(["Tipo de Nota"], as_index=False)["Quantidade XML"]
        .sum()
        .sort_values("Quantidade XML", ascending=False)
    )

    resumo_emitente = (
        df.groupby(["Tipo de Nota", "Documento Emitente"], as_index=False)["Quantidade XML"]
        .sum()
        .sort_values(["Tipo de Nota", "Quantidade XML"], ascending=[True, False])
    )

    resumo_destinatario = (
        df.groupby(["Tipo de Nota", "Documento Destinatário"], as_index=False)["Quantidade XML"]
        .sum()
        .sort_values(["Tipo de Nota", "Quantidade XML"], ascending=[True, False])
    )

    resumo_cidade_emitente = (
        df.groupby(["Tipo de Nota", "Cidade Emitente", "UF Emitente"], as_index=False)["Quantidade XML"]
        .sum()
        .sort_values(["Tipo de Nota", "Quantidade XML"], ascending=[True, False])
    )

    resumo_cidade_destinatario = (
        df.groupby(["Tipo de Nota", "Cidade Destinatário", "UF Destinatário"], as_index=False)["Quantidade XML"]
        .sum()
        .sort_values(["Tipo de Nota", "Quantidade XML"], ascending=[True, False])
    )

    estado = st.session_state["estado_app"]

    estatisticas = pd.DataFrame([
        {"Indicador": "Total de combinações consolidadas", "Valor": len(df)},
        {"Indicador": "Total de XML válidos processados", "Valor": int(estado["total_xml_validos"])},
        {"Indicador": "Total de erros", "Valor": int(estado["total_erros"])},
        {"Indicador": "Total de ZIPs lidos", "Valor": int(estado["total_arquivos_zip"])},
        {"Indicador": "Total de XML soltos lidos", "Valor": int(estado["total_arquivos_xml_soltos"])},
        {"Indicador": "Total de emitentes distintos", "Valor": int(df["Documento Emitente"].replace("", pd.NA).dropna().nunique())},
        {"Indicador": "Total de destinatários distintos", "Valor": int(df["Documento Destinatário"].replace("", pd.NA).dropna().nunique())},
        {"Indicador": "Total de cidades de emitente distintas", "Valor": int(df["Cidade Emitente"].replace("", pd.NA).dropna().nunique())},
        {"Indicador": "Total de cidades de destinatário distintas", "Valor": int(df["Cidade Destinatário"].replace("", pd.NA).dropna().nunique())},
    ])

    return {
        "resumo_tipo": resumo_tipo,
        "resumo_emitente": resumo_emitente,
        "resumo_destinatario": resumo_destinatario,
        "resumo_cidade_emitente": resumo_cidade_emitente,
        "resumo_cidade_destinatario": resumo_cidade_destinatario,
        "estatisticas": estatisticas,
    }


def gerar_excel_relatorio(df):
    output = io.BytesIO()
    resumos = gerar_resumos(df)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Consolidado")
        resumos["resumo_tipo"].to_excel(writer, index=False, sheet_name="Resumo por Tipo")
        resumos["resumo_emitente"].to_excel(writer, index=False, sheet_name="Resumo Emitente")
        resumos["resumo_destinatario"].to_excel(writer, index=False, sheet_name="Resumo Destinatário")
        resumos["resumo_cidade_emitente"].to_excel(writer, index=False, sheet_name="Cidade Emitente")
        resumos["resumo_cidade_destinatario"].to_excel(writer, index=False, sheet_name="Cidade Destinatário")
        resumos["estatisticas"].to_excel(writer, index=False, sheet_name="Estatísticas")

    output.seek(0)
    return output


# =========================================================
# RESET
# =========================================================
def resetar_app():
    st.session_state["estado_app"] = estado_padrao()
    apagar_estado_disco()


# =========================================================
# INICIALIZAÇÃO
# =========================================================
inicializar_session_state()
estado = st.session_state["estado_app"]


# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.subheader("Ações")

    if st.button("🔄 Recarregar estado salvo"):
        carregado = carregar_estado_disco()
        if carregado:
            st.session_state["estado_app"] = carregado
            st.success("Estado temporário recarregado.")
            
        else:
            st.info("Nenhum estado salvo encontrado.")

    if st.button("🧹 Resetar aplicação"):
        resetar_app()
        st.success("Aplicação resetada com sucesso.")
        

    st.markdown("---")
    st.write("**Arquivo de persistência temporária:**")
    st.code(str(STATE_FILE))


# =========================================================
# PROCESSAR PASTA
# =========================================================
st.subheader("1) Processar uma pasta")

with st.form("form_processar_pasta"):
    caminho_pasta = st.text_input(
        "Informe o caminho da pasta",
        placeholder=r"Ex.: D:\XML\2024\01"
    )
    enviar = st.form_submit_button("Processar pasta")

if enviar:
    caminho_pasta = caminho_pasta.strip()

    if not caminho_pasta:
        st.warning("Informe o caminho de uma pasta.")
    else:
        try:
            resumo = processar_pasta(caminho_pasta)
            st.success(
                "Pasta processada com sucesso. "
                f"ZIPs lidos: {resumo['zips_lidos']} | "
                f"XML soltos lidos: {resumo['xml_soltos_lidos']} | "
                f"XML válidos: {resumo['xml_validos']} | "
                f"Erros: {resumo['erros']}"
            )
        except Exception as e:
            st.error(f"Erro ao processar a pasta: {e}")


# =========================================================
# PAINEL
# =========================================================
st.subheader("2) Painel resumido")

col1, col2, col3, col4 = st.columns(4)
col1.metric("XML válidos", estado["total_xml_validos"])
col2.metric("Erros", estado["total_erros"])
col3.metric("ZIPs lidos", estado["total_arquivos_zip"])
col4.metric("Pastas processadas", len(estado["pastas_processadas"]))


# =========================================================
# TABELAS
# =========================================================
df_consolidado = gerar_dataframe_consolidado()
resumos = gerar_resumos(df_consolidado)

st.subheader("3) Resumo por tipo de nota")
if resumos["resumo_tipo"].empty:
    st.info("Nenhum dado processado até o momento.")
else:
    st.dataframe(resumos["resumo_tipo"], use_container_width=True, height=220)

st.subheader("4) Consolidado detalhado")
if df_consolidado.empty:
    st.info("Nenhum consolidado disponível.")
else:
    st.dataframe(df_consolidado, use_container_width=True, height=420)


# =========================================================
# EXPANDERS
# =========================================================
with st.expander("Ver pastas processadas"):
    if estado["pastas_processadas"]:
        for pasta in estado["pastas_processadas"]:
            st.write(f"- {pasta}")
    else:
        st.write("Nenhuma pasta processada ainda.")

with st.expander("Ver log da sessão"):
    if estado["log"]:
        for linha in estado["log"][-100:]:
            st.write(f"- {linha}")
    else:
        st.write("Sem log disponível.")


# =========================================================
# DOWNLOAD
# =========================================================
st.subheader("5) Gerar relatório final")

if df_consolidado.empty:
    st.info("Processe ao menos uma pasta para liberar o relatório.")
else:
    excel_buffer = gerar_excel_relatorio(df_consolidado)
    st.download_button(
        label="📥 Baixar relatório Excel",
        data=excel_buffer,
        file_name="relatorio_xml_emitente_destinatario.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.caption(
        "Depois de baixar o relatório, você pode usar o botão "
        "'Resetar aplicação' para limpar a sessão e iniciar um novo processamento."
    )