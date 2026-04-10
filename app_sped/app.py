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


# =========================================================
# CONFIG
# =========================================================

# True = mantém .txt e .rec da entrega vencedora
# False = tenta manter só .txt; se não existir, mantém .rec
MANTER_TODOS_FORMATOS = True

EXTENSOES_ACEITAS = {".txt", ".rec"}


# =========================================================
# MODELO
# =========================================================

@dataclass
class ArquivoSped:
    caminho_interno: str
    nome_arquivo: str
    extensao: str
    cnpj: str
    competencia: str        # YYYY-MM
    cod_fin: str            # 0 original / 1 retificadora
    tipo_entrega: str
    dt_ini: str
    dt_fim: str
    modificado_em: datetime
    tamanho: int
    grupo_entrega: str = ""
    manter: bool = False


# =========================================================
# AUXILIARES
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


def ler_linhas_iniciais(data: bytes, limite: int = 300) -> List[str]:
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
    # Estrutura esperada do EFD Contribuições:
    # [1]=0000
    # [3]=COD_FIN
    # [4]=DT_INI
    # [5]=DT_FIN
    # [7]=CNPJ
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


def chave_entrega(cnpj: str, competencia: str, cod_fin: str, modificado_em: datetime) -> str:
    return f"{cnpj}|{competencia}|{cod_fin}|{modificado_em.strftime('%Y%m%d%H%M%S')}"


def escolher_representante_entrega(itens: List[ArquivoSped]) -> ArquivoSped:
    txts = [i for i in itens if i.extensao == ".txt"]
    return txts[0] if txts else itens[0]


def escolher_entrega_vencedora(entregas: List[ArquivoSped]) -> ArquivoSped:
    def peso(item: ArquivoSped):
        prioridade_ret = 1 if item.cod_fin == "1" else 0
        return (
            prioridade_ret,
            item.modificado_em,
            item.nome_arquivo.lower(),
        )

    return sorted(entregas, key=peso, reverse=True)[0]


# =========================================================
# LEITURA DO ZIP
# =========================================================

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

            encontrados.append(
                ArquivoSped(
                    caminho_interno=info.filename,
                    nome_arquivo=Path(info.filename).name,
                    extensao=extensao,
                    cnpj=cnpj,
                    competencia=competencia,
                    cod_fin=cod_fin,
                    tipo_entrega=tipo_entrega,
                    dt_ini=dt_ini,
                    dt_fim=dt_fim,
                    modificado_em=dt_mod,
                    tamanho=info.file_size,
                )
            )

    return encontrados


# =========================================================
# SELEÇÃO
# =========================================================

def selecionar_validos(arquivos: List[ArquivoSped]) -> List[ArquivoSped]:
    grupos: Dict[Tuple[str, str], List[ArquivoSped]] = {}

    for arq in arquivos:
        grupos.setdefault((arq.cnpj, arq.competencia), []).append(arq)

    for (_, _), itens in grupos.items():
        entregas_map: Dict[str, List[ArquivoSped]] = {}

        for item in itens:
            grp = chave_entrega(item.cnpj, item.competencia, item.cod_fin, item.modificado_em)
            item.grupo_entrega = grp
            entregas_map.setdefault(grp, []).append(item)

        representantes = [
            escolher_representante_entrega(lista_entrega)
            for lista_entrega in entregas_map.values()
        ]

        vencedor = escolher_entrega_vencedora(representantes)

        for item in itens:
            item.manter = item.grupo_entrega == vencedor.grupo_entrega

        if not MANTER_TODOS_FORMATOS:
            vencedores = [i for i in itens if i.manter]
            txts = [i for i in vencedores if i.extensao == ".txt"]

            if txts:
                manter_txt = txts[0]
                for i in vencedores:
                    i.manter = i is manter_txt
            else:
                recs = [i for i in vencedores if i.extensao == ".rec"]
                if recs:
                    manter_rec = recs[0]
                    for i in vencedores:
                        i.manter = i is manter_rec

    return arquivos


# =========================================================
# GERAÇÃO DO ZIP FINAL
# =========================================================

def montar_zip_filtrado(upload_bytes: bytes, arquivos: List[ArquivoSped]) -> bytes:
    selecionados = [a for a in arquivos if a.manter]

    entrada = io.BytesIO(upload_bytes)
    saida = io.BytesIO()

    with zipfile.ZipFile(entrada, "r") as zf_in, zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zf_out:
        for arq in selecionados:
            try:
                conteudo = zf_in.read(arq.caminho_interno)
                zf_out.writestr(arq.nome_arquivo, conteudo)
            except Exception:
                continue

    saida.seek(0)
    return saida.getvalue()


# =========================================================
# UI
# =========================================================

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
                total_sel = len(set((a.cnpj, a.competencia) for a in selecionados))

                st.success("Processamento concluído.")

                c1, c2, c3 = st.columns(3)
                c1.metric("Arquivos SPED lidos", len(arquivos))
                c2.metric("Competências encontradas", total_comp)
                c3.metric("Competências filtradas", total_sel)

                resumo = {}
                for a in selecionados:
                    chave = (a.cnpj, a.competencia)
                    resumo.setdefault(chave, []).append(a)

                st.subheader("Itens mantidos")
                for (cnpj, comp), itens in sorted(resumo.items()):
                    tipos = ", ".join(sorted(set(i.tipo_entrega for i in itens)))
                    nomes = ", ".join(i.nome_arquivo for i in itens)
                    st.write(f"**{comp}** | CNPJ: {cnpj} | {tipos}")
                    st.caption(nomes)

                nome_base = Path(uploaded_file.name).stem
                nome_saida = f"{nome_base}_filtrado.zip"

                st.download_button(
                    "Baixar ZIP filtrado",
                    data=zip_filtrado,
                    file_name=nome_saida,
                    mime="application/zip",
                    use_container_width=True,
                )