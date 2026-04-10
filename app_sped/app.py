import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict

import streamlit as st


# =========================================================
# CONFIGURAÇÃO DA PÁGINA
# =========================================================

st.set_page_config(
    page_title="Filtro simples de SPED por competência",
    layout="centered",
)

st.title("Filtro simples de SPED por competência")
st.caption(
    "Envie um arquivo ZIP para filtrar automaticamente a entrega correta de cada competência."
)


# =========================================================
# TEXTO DE ORIENTAÇÃO
# =========================================================

st.subheader("Padrão de uso")
st.markdown("""
**Como utilizar o programa**

Este sistema foi desenvolvido para trabalhar com **arquivos SPED compactados em formato `.zip`**, realizando a filtragem automática das entregas por competência.

**Regras para uso correto:**
- O arquivo deve ser enviado **sempre em pasta zipada (`.zip`)**.
- O conteúdo do ZIP deve corresponder a **um único ano-calendário**.
- Recomendamos organizar os arquivos por ano antes de compactar.
- O programa analisa os arquivos `.txt` e `.rec` existentes dentro do ZIP.
- O sistema sempre prioriza a **entrega retificadora mais recente**, quando houver.
- Na ausência de retificadora, será considerada a **entrega original**.
- O arquivo `.rec` será incluído no resultado **apenas quando existir e corresponder à entrega vencedora**.
- O arquivo `.txt` é sempre tratado como o arquivo principal da escrituração.

**Importante sobre tamanho dos arquivos**
- Para evitar falhas de processamento, envie os arquivos **separados por ano-calendário**.
- Não é recomendável juntar vários anos no mesmo ZIP.
- Caso a base seja muito grande, o ideal é gerar **um ZIP para cada ano**.

**Exemplo de uso recomendado**
- `SPED 2021.zip`
- `SPED 2022.zip`
- `SPED 2023.zip`

**Resultado gerado pelo sistema**
- O programa irá gerar um **novo arquivo ZIP filtrado**, contendo apenas os arquivos válidos de cada competência encontrada no período enviado.
""")

st.warning("""
**Observações importantes**
- O programa não substitui conferência fiscal.
- O objetivo é organizar e filtrar automaticamente os arquivos da escrituração.
- Se o ZIP não contiver arquivos SPED válidos, o processamento não será concluído.
- Arquivos com estrutura inconsistente, corrompidos ou fora do padrão podem não ser aproveitados.
""")


# =========================================================
# ESTADO / RESET
# =========================================================

if "reset_counter" not in st.session_state:
    st.session_state.reset_counter = 0

if "zip_filtrado_bytes" not in st.session_state:
    st.session_state.zip_filtrado_bytes = None

if "nome_zip_saida" not in st.session_state:
    st.session_state.nome_zip_saida = None

if "selecionados_resumo" not in st.session_state:
    st.session_state.selecionados_resumo = []

if "metricas" not in st.session_state:
    st.session_state.metricas = None

if "erro_processamento" not in st.session_state:
    st.session_state.erro_processamento = None


def resetar_app() -> None:
    st.session_state.reset_counter += 1
    st.session_state.zip_filtrado_bytes = None
    st.session_state.nome_zip_saida = None
    st.session_state.selecionados_resumo = []
    st.session_state.metricas = None
    st.session_state.erro_processamento = None
    st.rerun()


col_upload, col_reset = st.columns([4, 1])

with col_reset:
    st.write("")
    st.write("")
    if st.button("Resetar", use_container_width=True):
        resetar_app()

uploaded_file = col_upload.file_uploader(
    "Envie o arquivo ZIP",
    type=["zip"],
    key=f"upload_zip_{st.session_state.reset_counter}",
)


# =========================================================
# MODELO
# =========================================================

EXTENSOES_ACEITAS = {".txt", ".rec"}


@dataclass
class ArquivoSped:
    caminho_interno: str
    nome_arquivo: str
    nome_base: str
    extensao: str
    cnpj: str
    competencia: str
    cod_fin: str
    tipo_entrega: str
    dt_ini: str
    dt_fim: str
    modificado_em_zip: datetime
    tamanho: int
    timestamp_nome: Optional[datetime] = None
    manter: bool = False


# =========================================================
# FUNÇÕES AUXILIARES
# =========================================================

def limpar_cnpj(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def parse_data_sped(valor: str) -> Optional[datetime]:
    if not valor or len(valor) != 8 or not valor.isdigit():
        return None
    try:
        return datetime.strptime(valor, "%d%m%Y")
    except ValueError:
        return None


def competencia_from_dt_ini(dt_ini: str) -> str:
    dt = parse_data_sped(dt_ini)
    if not dt:
        return "0000-00"
    return dt.strftime("%Y-%m")


def ler_linhas_iniciais(data: bytes, limite: int = 400) -> List[str]:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            texto = data.decode(enc, errors="replace")
            return texto.splitlines()[:limite]
        except Exception:
            continue
    return []


def localizar_registro_0000(linhas: List[str]) -> Optional[List[str]]:
    for linha in linhas:
        linha = linha.strip()
        if linha.startswith("|0000|"):
            return linha.split("|")
    return None


def interpretar_registro_0000(partes: List[str]) -> Tuple[str, str, str, str, str, str]:
    """
    Estrutura esperada do EFD Contribuições:
    [1]=0000
    [3]=COD_FIN
    [4]=DT_INI
    [5]=DT_FIN
    [7]=CNPJ
    """
    cod_fin = partes[3].strip() if len(partes) > 3 else ""
    dt_ini = partes[4].strip() if len(partes) > 4 else ""
    dt_fim = partes[5].strip() if len(partes) > 5 else ""
    cnpj = limpar_cnpj(partes[7].strip()) if len(partes) > 7 else ""
    competencia = competencia_from_dt_ini(dt_ini)

    if cod_fin == "1":
        tipo = "Retificadora"
    elif cod_fin == "0":
        tipo = "Original"
    else:
        tipo = f"Desconhecido({cod_fin or 'vazio'})"

    return cnpj, competencia, cod_fin, tipo, dt_ini, dt_fim


def normalizar_nome_base(nome_arquivo: str) -> str:
    return Path(nome_arquivo).stem.strip().lower()


def extrair_timestamp_do_nome(nome_arquivo: str) -> Optional[datetime]:
    """
    Procura timestamps no nome, priorizando YYYYMMDDHHMMSS.
    Exemplos:
    - PISCOFINS_20210301_20210331_05240070000130_1_20231130153636.txt
    - ALGUM_ARQUIVO_20210131.txt
    """
    base = Path(nome_arquivo).stem

    candidatos_14 = re.findall(r"(?<!\d)(20\d{12})(?!\d)", base)
    for cand in reversed(candidatos_14):
        try:
            return datetime.strptime(cand, "%Y%m%d%H%M%S")
        except ValueError:
            pass

    candidatos_8 = re.findall(r"(?<!\d)(20\d{6})(?!\d)", base)
    for cand in reversed(candidatos_8):
        try:
            return datetime.strptime(cand, "%Y%m%d")
        except ValueError:
            pass

    return None


def nome_base_sem_timestamp(nome_arquivo: str) -> str:
    """
    Remove timestamps para facilitar o vínculo entre .txt e .rec.
    """
    base = normalizar_nome_base(nome_arquivo)
    base = re.sub(r"(?<!\d)20\d{12}(?!\d)", "", base)
    base = re.sub(r"(?<!\d)20\d{6}(?!\d)", "", base)
    base = re.sub(r"__+", "_", base)
    base = base.strip("_- ")
    return base


def ler_zip_sped(upload_bytes: bytes) -> List[ArquivoSped]:
    encontrados: List[ArquivoSped] = []

    with zipfile.ZipFile(io.BytesIO(upload_bytes), "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue

            extensao = Path(info.filename).suffix.lower()
            if extensao not in EXTENSOES_ACEITAS:
                continue

            try:
                bruto = zf.read(info)
            except Exception:
                continue

            linhas = ler_linhas_iniciais(bruto)
            reg_0000 = localizar_registro_0000(linhas)
            if not reg_0000:
                continue

            cnpj, competencia, cod_fin, tipo_entrega, dt_ini, dt_fim = interpretar_registro_0000(reg_0000)
            nome_arquivo = Path(info.filename).name
            dt_mod_zip = datetime(*info.date_time)

            encontrados.append(
                ArquivoSped(
                    caminho_interno=info.filename,
                    nome_arquivo=nome_arquivo,
                    nome_base=normalizar_nome_base(nome_arquivo),
                    extensao=extensao,
                    cnpj=cnpj,
                    competencia=competencia,
                    cod_fin=cod_fin,
                    tipo_entrega=tipo_entrega,
                    dt_ini=dt_ini,
                    dt_fim=dt_fim,
                    modificado_em_zip=dt_mod_zip,
                    tamanho=info.file_size,
                    timestamp_nome=extrair_timestamp_do_nome(nome_arquivo),
                )
            )

    return encontrados


def escolher_txt_vencedor(itens_comp: List[ArquivoSped]) -> Optional[ArquivoSped]:
    """
    Escolhe o .txt vencedor da competência.
    Prioridade:
    1) Retificadora
    2) Timestamp do nome do arquivo
    3) Timestamp do ZIP
    4) Nome do arquivo
    """
    txts = [i for i in itens_comp if i.extensao == ".txt"]
    if not txts:
        return None

    def peso(item: ArquivoSped):
        eh_ret = 1 if item.cod_fin == "1" else 0
        ts_nome = item.timestamp_nome or datetime.min
        return (
            eh_ret,
            ts_nome,
            item.modificado_em_zip,
            item.nome_arquivo.lower(),
        )

    return sorted(txts, key=peso, reverse=True)[0]


def rec_corresponde_ao_txt(rec: ArquivoSped, txt: ArquivoSped) -> bool:
    """
    Vínculo entre .rec e .txt vencedor.
    Regras:
    - mesmo CNPJ
    - mesma competência
    - mesmo COD_FIN
    - nome compatível sem timestamp
    """
    if rec.extensao != ".rec" or txt.extensao != ".txt":
        return False

    if rec.cnpj != txt.cnpj:
        return False
    if rec.competencia != txt.competencia:
        return False
    if rec.cod_fin != txt.cod_fin:
        return False

    base_rec = nome_base_sem_timestamp(rec.nome_arquivo)
    base_txt = nome_base_sem_timestamp(txt.nome_arquivo)

    if base_rec == base_txt:
        return True

    if base_rec and base_txt and (base_rec in base_txt or base_txt in base_rec):
        return True

    return False


def selecionar_validos(arquivos: List[ArquivoSped]) -> List[ArquivoSped]:
    grupos_comp: Dict[Tuple[str, str], List[ArquivoSped]] = {}

    for arq in arquivos:
        grupos_comp.setdefault((arq.cnpj, arq.competencia), []).append(arq)

    for (_, _), itens_comp in grupos_comp.items():
        for item in itens_comp:
            item.manter = False

        txt_vencedor = escolher_txt_vencedor(itens_comp)

        if txt_vencedor is None:
            # Cenário raro: não existe .txt na competência.
            # Mantém o melhor arquivo disponível.
            def peso_sem_txt(item: ArquivoSped):
                eh_ret = 1 if item.cod_fin == "1" else 0
                ts_nome = item.timestamp_nome or datetime.min
                score_ext = 1 if item.extensao == ".rec" else 0
                return (
                    eh_ret,
                    score_ext,
                    ts_nome,
                    item.modificado_em_zip,
                    item.nome_arquivo.lower(),
                )

            vencedor = sorted(itens_comp, key=peso_sem_txt, reverse=True)[0]
            vencedor.manter = True
            continue

        txt_vencedor.manter = True

        for item in itens_comp:
            if item.extensao == ".rec" and rec_corresponde_ao_txt(item, txt_vencedor):
                item.manter = True

    return arquivos


def montar_zip_filtrado(upload_bytes: bytes, arquivos: List[ArquivoSped]) -> bytes:
    selecionados = [a for a in arquivos if a.manter]

    entrada = io.BytesIO(upload_bytes)
    saida = io.BytesIO()

    with zipfile.ZipFile(entrada, "r") as zf_in, zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zf_out:
        nomes_ja_inseridos = set()

        for arq in selecionados:
            try:
                conteudo = zf_in.read(arq.caminho_interno)
                nome_saida = arq.nome_arquivo

                if nome_saida in nomes_ja_inseridos:
                    pasta = re.sub(r"\W+", "_", f"{arq.cnpj}_{arq.competencia}_{arq.cod_fin}")
                    nome_saida = f"{pasta}/{arq.nome_arquivo}"

                zf_out.writestr(nome_saida, conteudo)
                nomes_ja_inseridos.add(nome_saida)
            except Exception:
                continue

    saida.seek(0)
    return saida.getvalue()


def resumir_selecionados(selecionados: List[ArquivoSped]) -> List[Dict[str, str]]:
    resumo = []
    por_comp: Dict[Tuple[str, str], List[ArquivoSped]] = {}

    for item in selecionados:
        por_comp.setdefault((item.cnpj, item.competencia), []).append(item)

    for (cnpj, competencia), itens in sorted(por_comp.items()):
        txts = sorted([i.nome_arquivo for i in itens if i.extensao == ".txt"])
        recs = sorted([i.nome_arquivo for i in itens if i.extensao == ".rec"])
        tipo = itens[0].tipo_entrega if itens else ""

        resumo.append({
            "cnpj": cnpj,
            "competencia": competencia,
            "tipo": tipo,
            "txts": ", ".join(txts) if txts else "",
            "recs": ", ".join(recs) if recs else "",
        })

    return resumo


def processar_zip(upload_bytes: bytes, nome_arquivo_original: str) -> None:
    arquivos = ler_zip_sped(upload_bytes)

    if not arquivos:
        st.session_state.erro_processamento = (
            "Nenhum arquivo SPED válido (.txt/.rec com registro 0000) foi encontrado dentro do ZIP."
        )
        st.session_state.zip_filtrado_bytes = None
        st.session_state.nome_zip_saida = None
        st.session_state.selecionados_resumo = []
        st.session_state.metricas = None
        return

    arquivos = selecionar_validos(arquivos)
    selecionados = [a for a in arquivos if a.manter]
    zip_filtrado = montar_zip_filtrado(upload_bytes, arquivos)

    total_comp = len(set((a.cnpj, a.competencia) for a in arquivos))
    total_mantidos = len(selecionados)

    st.session_state.zip_filtrado_bytes = zip_filtrado
    st.session_state.nome_zip_saida = f"{Path(nome_arquivo_original).stem}_filtrado.zip"
    st.session_state.selecionados_resumo = resumir_selecionados(selecionados)
    st.session_state.metricas = {
        "arquivos_lidos": len(arquivos),
        "competencias": total_comp,
        "arquivos_mantidos": total_mantidos,
    }
    st.session_state.erro_processamento = None


# =========================================================
# AÇÃO PRINCIPAL
# =========================================================

if uploaded_file is not None:
    if st.button("Processar ZIP", use_container_width=True):
        with st.spinner("Lendo e filtrando os arquivos..."):
            try:
                zip_bytes = uploaded_file.read()
                processar_zip(zip_bytes, uploaded_file.name)
            except zipfile.BadZipFile:
                st.session_state.erro_processamento = "O arquivo enviado não é um ZIP válido."
                st.session_state.zip_filtrado_bytes = None
                st.session_state.nome_zip_saida = None
                st.session_state.selecionados_resumo = []
                st.session_state.metricas = None
            except Exception as e:
                st.session_state.erro_processamento = f"Erro ao processar o arquivo: {e}"
                st.session_state.zip_filtrado_bytes = None
                st.session_state.nome_zip_saida = None
                st.session_state.selecionados_resumo = []
                st.session_state.metricas = None


# =========================================================
# EXIBIÇÃO DOS RESULTADOS
# =========================================================

if st.session_state.erro_processamento:
    st.error(st.session_state.erro_processamento)

if st.session_state.metricas:
    st.success("Processamento concluído.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Arquivos SPED lidos", st.session_state.metricas["arquivos_lidos"])
    c2.metric("Competências encontradas", st.session_state.metricas["competencias"])
    c3.metric("Arquivos mantidos", st.session_state.metricas["arquivos_mantidos"])

    st.subheader("Itens mantidos")

    for item in st.session_state.selecionados_resumo:
        st.write(f"**{item['competencia']}** | CNPJ: {item['cnpj']} | {item['tipo']}")
        if item["txts"]:
            st.caption("TXT: " + item["txts"])
        if item["recs"]:
            st.caption("REC: " + item["recs"])

    if st.session_state.zip_filtrado_bytes and st.session_state.nome_zip_saida:
        st.download_button(
            "Baixar ZIP filtrado",
            data=st.session_state.zip_filtrado_bytes,
            file_name=st.session_state.nome_zip_saida,
            mime="application/zip",
            use_container_width=True,
        )