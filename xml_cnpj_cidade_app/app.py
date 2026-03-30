import io
import json
import zipfile
import tempfile
import hashlib
from pathlib import Path
from collections import Counter
import xml.etree.ElementTree as ET

import pandas as pd
import streamlit as st


# =========================================================
# CONFIGURAÇÃO GERAL
# =========================================================
st.set_page_config(
    page_title="Relatório XML por CNPJ/Cidade/Tipo",
    layout="wide"
)

st.title("📦 Relatório XML por CNPJ, Cidade e Tipo de Nota")
st.caption(
    "Processa pastas com ZIP/XML, acumula os dados entre processamentos "
    "e gera um relatório consolidado final."
)


# =========================================================
# ARQUIVO TEMPORÁRIO DE PERSISTÊNCIA
# =========================================================
APP_TEMP_DIR = Path(tempfile.gettempdir()) / "streamlit_xml_cnpj_cidade"
APP_TEMP_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = APP_TEMP_DIR / "estado_xml_relatorio.json"


# =========================================================
# ESTADO INICIAL
# =========================================================
def estado_padrao():
    return {
        "acumulado": {},  # dict serializável: chave_str -> quantidade
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
# FUNÇÕES AUXILIARES DE XML
# =========================================================
NAMESPACE = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


def texto_tag(parent, tag, ns=NAMESPACE):
    if parent is None:
        return ""
    node = parent.find(f"nfe:{tag}", ns)
    return node.text.strip() if node is not None and node.text else ""


def documento_emitente(emit, ns=NAMESPACE):
    cnpj = texto_tag(emit, "CNPJ", ns)
    if cnpj:
        return cnpj
    cpf = texto_tag(emit, "CPF", ns)
    return cpf


def identificar_tipo_nota(root, ns=NAMESPACE):
    ide = root.find(".//nfe:ide", ns)

    if ide is None:
        return "Não identificado", ""

    mod = texto_tag(ide, "mod", ns)
    tp_nf = texto_tag(ide, "tpNF", ns)

    # 55 = NF-e
    # 65 = NFC-e
    # tpNF: 0 = Entrada | 1 = Saída
    if mod == "65":
        return "NFC-e", mod

    if mod == "55":
        if tp_nf == "0":
            return "NF-e Entrada", mod
        if tp_nf == "1":
            return "NF-e Saída", mod
        return "NF-e", mod

    return "Não identificado", mod


def extrair_dados_principais(xml_bytes):
    try:
        root = ET.fromstring(xml_bytes)

        emit = root.find(".//nfe:emit", NAMESPACE)
        ender_emit = emit.find("nfe:enderEmit", NAMESPACE) if emit is not None else None

        doc_emitente = documento_emitente(emit, NAMESPACE)
        cidade = texto_tag(ender_emit, "xMun", NAMESPACE)
        uf = texto_tag(ender_emit, "UF", NAMESPACE)
        tipo_nota, modelo = identificar_tipo_nota(root, NAMESPACE)

        return {
            "tipo_nota": tipo_nota,
            "modelo": modelo,
            "documento_emitente": doc_emitente,
            "cidade_emitente": cidade,
            "uf_emitente": uf,
            "erro": False,
        }
    except Exception:
        return {
            "tipo_nota": "",
            "modelo": "",
            "documento_emitente": "",
            "cidade_emitente": "",
            "uf_emitente": "",
            "erro": True,
        }


# =========================================================
# FUNÇÕES DE CONTROLE / CHAVES
# =========================================================
def chave_acumulado(tipo_nota, modelo, documento_emitente, cidade, uf):
    return f"{tipo_nota}|||{modelo}|||{documento_emitente}|||{cidade}|||{uf}"


def split_chave_acumulado(chave):
    partes = chave.split("|||")
    while len(partes) < 5:
        partes.append("")
    return partes[0], partes[1], partes[2], partes[3], partes[4]


def fingerprint_arquivo(path_obj):
    """
    Cria uma identificação simples do arquivo para evitar reprocessamento.
    """
    stat = path_obj.stat()
    base = f"{path_obj.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def adicionar_log(msg):
    st.session_state["estado_app"]["log"].append(msg)
    if len(st.session_state["estado_app"]["log"]) > 200:
        st.session_state["estado_app"]["log"] = st.session_state["estado_app"]["log"][-200:]


# =========================================================
# PROCESSAMENTO
# =========================================================
def processar_xml_bytes(xml_bytes):
    dados = extrair_dados_principais(xml_bytes)

    if dados["erro"]:
        return None

    if (
        dados["documento_emitente"]
        and dados["cidade_emitente"]
        and dados["tipo_nota"]
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
    status = st.empty()

    xml_validos = 0
    erros = 0
    zips_lidos = 0
    xml_soltos_lidos = 0

    arquivos_processados_set = set(estado["arquivos_processados"])

    indice = 0

    # -------------------------
    # XMLs soltos
    # -------------------------
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

    # -------------------------
    # ZIPs
    # -------------------------
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
    status.success("Pasta concluída com sucesso.")

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
# DATAFRAMES E RELATÓRIO
# =========================================================
def gerar_dataframe_consolidado():
    acumulado = st.session_state["estado_app"]["acumulado"]

    linhas = []
    for chave, quantidade in acumulado.items():
        tipo_nota, modelo, documento, cidade, uf = split_chave_acumulado(chave)
        linhas.append({
            "Tipo de Nota": tipo_nota,
            "Modelo": modelo,
            "Documento Emitente": documento,
            "Cidade": cidade,
            "UF": uf,
            "Quantidade XML": quantidade,
        })

    df = pd.DataFrame(linhas)

    if df.empty:
        return df

    df = df.sort_values(
        by=["Tipo de Nota", "Documento Emitente", "Cidade", "UF"],
        ascending=[True, True, True, True]
    ).reset_index(drop=True)

    return df


def gerar_resumos(df):
    if df.empty:
        return {
            "resumo_tipo": pd.DataFrame(),
            "resumo_documento": pd.DataFrame(),
            "resumo_cidade": pd.DataFrame(),
            "estatisticas": pd.DataFrame(),
        }

    resumo_tipo = (
        df.groupby(["Tipo de Nota"], as_index=False)["Quantidade XML"]
        .sum()
        .sort_values("Quantidade XML", ascending=False)
    )

    resumo_documento = (
        df.groupby(["Tipo de Nota", "Documento Emitente"], as_index=False)["Quantidade XML"]
        .sum()
        .sort_values(["Tipo de Nota", "Quantidade XML"], ascending=[True, False])
    )

    resumo_cidade = (
        df.groupby(["Tipo de Nota", "Cidade", "UF"], as_index=False)["Quantidade XML"]
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
        {"Indicador": "Total de documentos emitentes distintos", "Valor": int(df["Documento Emitente"].nunique())},
        {"Indicador": "Total de cidades distintas", "Valor": int(df["Cidade"].nunique())},
    ])

    return {
        "resumo_tipo": resumo_tipo,
        "resumo_documento": resumo_documento,
        "resumo_cidade": resumo_cidade,
        "estatisticas": estatisticas,
    }


def gerar_excel_relatorio(df):
    output = io.BytesIO()
    resumos = gerar_resumos(df)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Consolidado")
        resumos["resumo_tipo"].to_excel(writer, index=False, sheet_name="Resumo por Tipo")
        resumos["resumo_documento"].to_excel(writer, index=False, sheet_name="Resumo por Documento")
        resumos["resumo_cidade"].to_excel(writer, index=False, sheet_name="Resumo por Cidade")
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
            st.rerun()
        else:
            st.info("Nenhum estado salvo encontrado.")

    if st.button("🧹 Resetar aplicação"):
        resetar_app()
        st.success("Aplicação resetada com sucesso.")
        st.rerun()

    st.markdown("---")
    st.write("**Arquivo de persistência temporária:**")
    st.code(str(STATE_FILE))


# =========================================================
# FORMULÁRIO DE PROCESSAMENTO
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
# PAINEL DE INDICADORES
# =========================================================
st.subheader("2) Painel resumido")

col1, col2, col3, col4 = st.columns(4)
col1.metric("XML válidos", estado["total_xml_validos"])
col2.metric("Erros", estado["total_erros"])
col3.metric("ZIPs lidos", estado["total_arquivos_zip"])
col4.metric("Pastas processadas", len(estado["pastas_processadas"]))


# =========================================================
# TABELAS DE RESUMO
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
# PASTAS PROCESSADAS
# =========================================================
with st.expander("Ver pastas processadas"):
    if estado["pastas_processadas"]:
        for pasta in estado["pastas_processadas"]:
            st.write(f"- {pasta}")
    else:
        st.write("Nenhuma pasta processada ainda.")


# =========================================================
# LOG
# =========================================================
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
        file_name="relatorio_xml_cnpj_cidade_tipo.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.caption(
        "Depois de baixar o relatório, você pode usar o botão "
        "'Resetar aplicação' para limpar a sessão e iniciar um novo processamento."
    )