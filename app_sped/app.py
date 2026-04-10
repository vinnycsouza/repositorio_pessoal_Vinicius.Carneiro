import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict

import streamlit as st


st.set_page_config(page_title="Filtro SPED ZIP", layout="centered")
st.title("Filtro simples de SPED por competência")
st.caption("Envia um ZIP, o app escolhe a entrega correta por competência e devolve um novo ZIP filtrado.")


EXTENSOES_ACEITAS = {".txt", ".rec"}


@dataclass
class ArquivoSped:
    caminho_interno: str
    nome_arquivo: str
    nome_base: str
    extensao: str
    cnpj: str
    competencia: str          # YYYY-MM
    cod_fin: str              # 0 original / 1 retificadora
    tipo_entrega: str
    dt_ini: str
    dt_fim: str
    modificado_em_zip: datetime
    tamanho: int
    timestamp_nome: Optional[datetime] = None
    grupo_entrega: str = ""
    manter: bool = False


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
    Procura timestamps no nome, priorizando formato YYYYMMDDHHMMSS.
    Ex.: PISCOFINS_20210301_20210331_05240070000130_1_20231130153636.txt
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
    Remove timestamps longos do nome para facilitar o vínculo txt/rec.
    """
    base = normalizar_nome_base(nome_arquivo)
    base = re.sub(r"(?<!\d)20\d{12}(?!\d)", "", base)
    base = re.sub(r"(?<!\d)20\d{6}(?!\d)", "", base)
    base = re.sub(r"__+", "_", base)
    base = base.strip("_- ")
    return base


def score_tipo(item: ArquivoSped) -> int:
    if item.extensao == ".txt":
        return 2
    if item.extensao == ".rec":
        return 1
    return 0


def chave_candidata_para_txt(item: ArquivoSped) -> str:
    """
    Chave mais ampla da entrega, ignorando extensão.
    """
    return f"{item.cnpj}|{item.competencia}|{item.cod_fin}|{nome_base_sem_timestamp(item.nome_arquivo)}"


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
            dt_mod = datetime(*info.date_time)
            nome_arquivo = Path(info.filename).name

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
                    modificado_em_zip=dt_mod,
                    tamanho=info.file_size,
                    timestamp_nome=extrair_timestamp_do_nome(nome_arquivo),
                )
            )

    return encontrados


def escolher_txt_vencedor(itens_comp: List[ArquivoSped]) -> Optional[ArquivoSped]:
    """
    Escolhe a entrega vencedora usando apenas os .txt como base principal.
    Prioridade:
    1) Retificadora
    2) timestamp do nome do arquivo
    3) timestamp do zip
    4) nome
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
    Tenta vincular o .rec ao .txt vencedor.
    A lógica usa:
    - mesmo CNPJ
    - mesma competência
    - mesmo COD_FIN
    - nome sem timestamp compatível
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

    # fallback: um conter o outro
    if base_rec and base_txt and (base_rec in base_txt or base_txt in base_rec):
        return True

    return False


def selecionar_validos(arquivos: List[ArquivoSped]) -> List[ArquivoSped]:
    grupos_comp: Dict[Tuple[str, str], List[ArquivoSped]] = {}

    for arq in arquivos:
        grupos_comp.setdefault((arq.cnpj, arq.competencia), []).append(arq)

    for (_, _), itens_comp in grupos_comp.items():
        txt_vencedor = escolher_txt_vencedor(itens_comp)

        if txt_vencedor is None:
            # Cenário raro: não há txt, então mantém um único arquivo mais forte
            def peso_sem_txt(item: ArquivoSped):
                eh_ret = 1 if item.cod_fin == "1" else 0
                ts_nome = item.timestamp_nome or datetime.min
                return (
                    eh_ret,
                    score_tipo(item),
                    ts_nome,
                    item.modificado_em_zip,
                    item.nome_arquivo.lower(),
                )

            vencedor = sorted(itens_comp, key=peso_sem_txt, reverse=True)[0]
            for item in itens_comp:
                item.manter = item is vencedor
            continue

        for item in itens_comp:
            item.manter = False

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


uploaded_file = st.file_uploader("Envie o arquivo ZIP", type=["zip"])

if uploaded_file is not None:
    if st.button("Processar ZIP", use_container_width=True):
        with st.spinner("Lendo e filtrando os arquivos..."):
            zip_bytes = uploaded_file.read()
            arquivos = ler_zip_sped(zip_bytes)

            if not arquivos:
                st.error("Nenhum arquivo SPED válido (.txt/.rec com registro 0000) foi encontrado dentro do ZIP.")
            else:
                arquivos = selecionar_validos(arquivos)
                zip_filtrado = montar_zip_filtrado(zip_bytes, arquivos)

                selecionados = [a for a in arquivos if a.manter]
                total_comp = len(set((a.cnpj, a.competencia) for a in arquivos))

                st.success("Processamento concluído.")

                c1, c2, c3 = st.columns(3)
                c1.metric("Arquivos SPED lidos", len(arquivos))
                c2.metric("Competências encontradas", total_comp)
                c3.metric("Arquivos mantidos", len(selecionados))

                st.subheader("Itens mantidos")
                por_comp = {}
                for a in selecionados:
                    por_comp.setdefault((a.cnpj, a.competencia), []).append(a)

                for (cnpj, comp), itens in sorted(por_comp.items()):
                    txts = [i.nome_arquivo for i in itens if i.extensao == ".txt"]
                    recs = [i.nome_arquivo for i in itens if i.extensao == ".rec"]
                    tipo = itens[0].tipo_entrega if itens else ""

                    st.write(f"**{comp}** | CNPJ: {cnpj} | {tipo}")
                    if txts:
                        st.caption("TXT: " + ", ".join(txts))
                    if recs:
                        st.caption("REC: " + ", ".join(recs))

                nome_base = Path(uploaded_file.name).stem
                nome_saida = f"{nome_base}_filtrado.zip"

                st.download_button(
                    "Baixar ZIP filtrado",
                    data=zip_filtrado,
                    file_name=nome_saida,
                    mime="application/zip",
                    use_container_width=True,
                )