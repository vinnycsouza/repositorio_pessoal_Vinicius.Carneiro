from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Iterable

import pandas as pd
from pypdf import PdfReader
from modules.comparador import ordenar_competencias


MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_FILES_ZIP = 5_000
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024


@dataclass(frozen=True)
class RegistroEcac:
    arquivo: str
    empresa: str
    cnpj: str
    competencia: str
    salario_familia: float | None
    recibo: str
    transmitido_em: datetime | None
    recibo_retificado: str
    hash_arquivo: str
    situacao: str = "Vigente"


@dataclass(frozen=True)
class OcorrenciaEcac:
    arquivo: str
    nivel: str
    mensagem: str


def _sem_acentos(valor: str) -> str:
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", valor or "")
        if not unicodedata.combining(caractere)
    )


def _texto_busca(valor: str) -> str:
    return re.sub(r"\s+", " ", _sem_acentos(valor).upper()).strip()


def _moeda_brasileira(valor: str) -> float:
    return float(valor.replace(".", "").replace(",", "."))


def _primeiro(padrao: str, texto: str, flags: int = 0) -> str:
    encontrado = re.search(padrao, texto, flags)
    return encontrado.group(1).strip() if encontrado else ""


def extrair_texto_pdf(pdf_bytes: bytes) -> str:
    if not pdf_bytes or len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError("PDF vazio ou acima do limite de 30 MB.")
    leitor = PdfReader(io.BytesIO(pdf_bytes))
    if leitor.is_encrypted:
        raise ValueError("PDF protegido por senha.")
    return "\n".join((pagina.extract_text() or "") for pagina in leitor.pages)


def analisar_texto_dctfweb(
    texto_original: str,
    arquivo: str,
    hash_arquivo: str = "",
) -> RegistroEcac:
    texto = _texto_busca(texto_original)
    if "RELATORIO DA DECLARACAO COMPLETA" not in texto or "DCTFWEB" not in texto:
        raise ValueError("O documento não foi reconhecido como Declaração Completa da DCTFWeb.")

    cnpj = _primeiro(r"CNPJ\s+(\d{2}[.]\d{3}[.]\d{3}/\d{4}-\d{2})", texto)
    competencia = _primeiro(r"PERIODO APURACAO\s+(\d{2}/\d{4})", texto)
    recibo = _primeiro(r"NUMERO DO RECIBO\s+(\d+)", texto)
    recibo_retificado = _primeiro(
        r"NUMERO DO RECIBO DA DECLARACAO RETIFICADA\s+(\d+)", texto
    )
    data_txt = _primeiro(
        r"DATA/HORA DA(?:\s+IDENTIFICACAO DA)?\s*TRANSMISSAO\s+(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})",
        texto,
    )
    if not data_txt:
        data_txt = _primeiro(
            r"DATA/HORA DA TRANSMISSAO\s+(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})",
            texto,
        )
    transmitido_em = (
        datetime.strptime(data_txt, "%d/%m/%Y %H:%M:%S") if data_txt else None
    )

    bloco_nome = _primeiro(r"NOME DO CONTRIBUINTE\s+(.+?)\s+CNPJ\s+", texto)
    empresa = re.sub(r"\s+", " ", bloco_nome).strip(" -")

    valor_txt = _primeiro(
        r"SALARIO\s+FAMILIA\s*:\s*([0-9.]+,[0-9]{2})", texto
    )
    valor = _moeda_brasileira(valor_txt) if valor_txt else None
    if not cnpj or not competencia:
        raise ValueError("CNPJ ou competência não foram localizados no documento.")

    return RegistroEcac(
        arquivo=arquivo,
        empresa=empresa,
        cnpj=cnpj,
        competencia=competencia,
        salario_familia=valor,
        recibo=recibo,
        transmitido_em=transmitido_em,
        recibo_retificado=recibo_retificado,
        hash_arquivo=hash_arquivo,
        situacao="Vigente" if valor is not None else "Salário-família não informado",
    )


def analisar_pdf(pdf_bytes: bytes, arquivo: str) -> RegistroEcac:
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    return analisar_texto_dctfweb(extrair_texto_pdf(pdf_bytes), arquivo, digest)


def iterar_pdfs(nome: str, conteudo: bytes) -> Iterable[tuple[str, bytes]]:
    if nome.lower().endswith(".pdf"):
        yield nome, conteudo
        return
    if not nome.lower().endswith(".zip"):
        raise ValueError("Formato não suportado. Envie PDF ou ZIP.")

    with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
        membros = [item for item in pacote.infolist() if not item.is_dir()]
        if len(membros) > MAX_FILES_ZIP:
            raise ValueError("ZIP acima do limite de 5.000 arquivos.")
        total = sum(max(0, item.file_size) for item in membros)
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise ValueError("ZIP acima do limite descompactado de 500 MB.")
        for item in membros:
            caminho = PurePosixPath(item.filename)
            if caminho.is_absolute() or ".." in caminho.parts:
                continue
            if caminho.suffix.lower() == ".pdf":
                if item.file_size > MAX_PDF_BYTES:
                    continue
                yield f"{nome}::{item.filename}", pacote.read(item)


def processar_arquivos(
    arquivos: Iterable[tuple[str, bytes]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    registros: list[RegistroEcac] = []
    ocorrencias: list[OcorrenciaEcac] = []
    hashes: set[str] = set()

    for nome, conteudo in arquivos:
        try:
            pdfs = list(iterar_pdfs(nome, conteudo))
            if not pdfs:
                ocorrencias.append(OcorrenciaEcac(nome, "Aviso", "Nenhum PDF encontrado."))
            for nome_pdf, pdf_bytes in pdfs:
                digest = hashlib.sha256(pdf_bytes).hexdigest()
                if digest in hashes:
                    ocorrencias.append(
                        OcorrenciaEcac(nome_pdf, "Aviso", "PDF duplicado ignorado.")
                    )
                    continue
                hashes.add(digest)
                try:
                    registros.append(analisar_pdf(pdf_bytes, nome_pdf))
                except Exception as exc:
                    ocorrencias.append(OcorrenciaEcac(nome_pdf, "Erro", str(exc)))
        except Exception as exc:
            ocorrencias.append(OcorrenciaEcac(nome, "Erro", str(exc)))

    if not registros:
        colunas = [campo.name for campo in RegistroEcac.__dataclass_fields__.values()]
        return pd.DataFrame(columns=colunas), pd.DataFrame(), pd.DataFrame(
            [asdict(item) for item in ocorrencias]
        )

    documentos = pd.DataFrame([asdict(item) for item in registros])
    documentos["_ordem_data"] = pd.to_datetime(documentos["transmitido_em"], errors="coerce")
    documentos = documentos.sort_values(
        ["cnpj", "competencia", "_ordem_data", "recibo"],
        na_position="first",
    )
    documentos["situacao"] = "Substituída por declaração posterior"
    indices_vigentes = documentos.groupby(["cnpj", "competencia"], sort=False).tail(1).index
    documentos.loc[indices_vigentes, "situacao"] = documentos.loc[
        indices_vigentes, "salario_familia"
    ].apply(lambda valor: "Vigente" if pd.notna(valor) else "Salário-família não informado")

    vigentes = documentos.loc[indices_vigentes].copy()
    resumo = vigentes[
        ["empresa", "cnpj", "competencia", "salario_familia", "arquivo"]
    ].sort_values(["cnpj", "competencia"])
    resumo = ordenar_competencias(resumo)
    documentos = ordenar_competencias(documentos.drop(columns=["_ordem_data"]))
    return resumo.reset_index(drop=True), documentos.reset_index(drop=True), pd.DataFrame(
        [asdict(item) for item in ocorrencias]
    )

