"""Inventário dos Excel Sysconv e triagem conservadora de C170."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import sys
from zipfile import ZipFile

import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from projeto_icms_piscofins.core.normalize import normalize_icms_items, normalize_piscofins_items


TIPOS = ("EFD ICMS/IPI", "EFD-Contribuições", "ECD", "ECF")
COLUNAS = (
    "regra", "estado", "motivo", "chave_nfe", "item", "linha_pis", "linha_icms",
    "base_icms", "valor_icms", "valor_icms_st", "base_pis", "base_cofins",
    "diferenca_pis", "diferenca_cofins", "arquivo_pis_sha256", "arquivo_icms_sha256",
)
_ROW_START_RE = re.compile(rb"<row(?:\s|>)")


def _contar_linhas_aba(pacote: ZipFile, caminho_aba: str) -> int:
    """Conta elementos de linha no XML, sem confiar na dimensão declarada da aba."""
    total = 0
    pendente = b""
    with pacote.open(caminho_aba) as xml:
        for bloco in iter(lambda: xml.read(4 * 1024 * 1024), b""):
            dados = pendente + bloco
            limite = max(len(dados) - 4, 0)
            total += sum(1 for ocorrencia in _ROW_START_RE.finditer(dados) if ocorrencia.start() < limite)
            pendente = dados[limite:]
    total += sum(1 for _ in _ROW_START_RE.finditer(pendente))
    return max(total - 1, 0)  # Primeira linha: cabeçalho.


def inventariar_excel(arquivo: str | Path | bytes, tipo: str, nome_arquivo: str | None = None) -> dict:
    """Conta linhas de dados por aba do Excel convertido e registra seu hash."""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de escrituração inválido: {tipo}")
    nome = nome_arquivo or ("arquivo.xlsx" if isinstance(arquivo, bytes) else Path(arquivo).name)
    if Path(nome).suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError(f"Formato Excel não aceito: {nome}. Use .xlsx ou .xlsm.")
    if isinstance(arquivo, bytes):
        if not arquivo:
            raise ValueError(f"O arquivo {nome} está vazio.")
        fonte = BytesIO(arquivo)
    else:
        fonte = Path(arquivo)
        if not fonte.is_file():
            raise FileNotFoundError(f"Arquivo Excel não encontrado: {fonte}")
    livro = load_workbook(fonte, read_only=True, data_only=True)
    try:
        planilhas = [(aba.title, aba._worksheet_path) for aba in livro.worksheets]
    finally:
        livro.close()
    abas = {}
    with ZipFile(BytesIO(arquivo) if isinstance(arquivo, bytes) else fonte) as pacote:
        for titulo, caminho_aba in planilhas:
            abas[titulo] = _contar_linhas_aba(pacote, caminho_aba)
    return {
        "tipo": tipo,
        "arquivo": nome,
        "sha256": hash_arquivo(arquivo),
        "linhas": sum(abas.values()),
        "abas": abas,
    }


def hash_arquivo(caminho: str | Path | bytes) -> str:
    if isinstance(caminho, bytes):
        return sha256(caminho).hexdigest()
    digest = sha256()
    with Path(caminho).open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _chave_item(linha: pd.Series) -> str:
    chave = re.sub(r"\D", "", str(linha.get("chave") or ""))
    item = int(linha.get("item") or 0)
    if len(chave) != 44 or item <= 0:
        return ""
    return f"{chave}:{item}"


def _numero(linha: pd.Series, campo: str) -> float:
    valor = pd.to_numeric(linha.get(campo), errors="coerce")
    return 0.0 if pd.isna(valor) else float(valor)


def _ler_c170(arquivo: str | Path | bytes, nome: str) -> pd.DataFrame:
    fonte = BytesIO(arquivo) if isinstance(arquivo, bytes) else Path(arquivo)
    with pd.ExcelFile(fonte) as livro:
        aba = next((nome_aba for nome_aba in livro.sheet_names if "c170" in nome_aba.casefold()), None)
        if not aba:
            raise ValueError(f"Aba C170 não encontrada em {nome}.")
        return pd.read_excel(livro, sheet_name=aba)


def triagem_c170(
    caminho_icms: str | Path | bytes,
    caminho_pis: str | Path | bytes,
    tolerancia: float = 0.01,
    nome_icms: str | None = None,
    nome_pis: str | None = None,
) -> pd.DataFrame:
    """Produz indícios documentados; nenhum valor é declarado recuperável."""
    if tolerancia < 0:
        raise ValueError("A tolerância não pode ser negativa.")
    nome_icms = nome_icms or ("ICMS/IPI.xlsx" if isinstance(caminho_icms, bytes) else Path(caminho_icms).name)
    nome_pis = nome_pis or ("Contribuições.xlsx" if isinstance(caminho_pis, bytes) else Path(caminho_pis).name)
    icms = normalize_icms_items(_ler_c170(caminho_icms, nome_icms))
    pis = normalize_piscofins_items(_ler_c170(caminho_pis, nome_pis))
    for quadro, nome in ((icms, "ICMS/IPI"), (pis, "PIS/COFINS")):
        if quadro.empty:
            raise ValueError(f"A aba C170 de {nome} está vazia.")
        if not any(quadro["chave"].astype(str).str.len().eq(44)):
            raise ValueError(f"C170 de {nome} não contém chave de NF-e com 44 dígitos.")
    icms["_chave_item"] = icms.apply(_chave_item, axis=1)
    pis["_chave_item"] = pis.apply(_chave_item, axis=1)
    grupos_icms = {chave: grupo for chave, grupo in icms[icms["_chave_item"] != ""].groupby("_chave_item")}
    contagem_pis = pis[pis["_chave_item"] != ""]["_chave_item"].value_counts()
    hash_pis, hash_icms = hash_arquivo(caminho_pis), hash_arquivo(caminho_icms)
    achados = []
    for indice, linha in pis.iterrows():
        if linha.get("ind_oper_desc") != "Saída" or not bool(linha.get("situacao_ok")):
            continue
        chave_item = linha["_chave_item"]
        if not chave_item:
            continue
        grupo = grupos_icms.get(chave_item)
        if grupo is None:
            continue
        if len(grupo) != 1 or int(contagem_pis[chave_item]) != 1:
            achados.append({
                "regra": "CONCILIACAO_C170", "estado": "Ambíguo", "motivo": "Chave da NF-e e item repetidos em uma das bases",
                "chave_nfe": chave_item.split(":")[0], "item": int(linha["item"]), "linha_pis": int(indice) + 2,
                "linha_icms": None, "arquivo_pis_sha256": hash_pis, "arquivo_icms_sha256": hash_icms,
            })
            continue
        outra = grupo.iloc[0]
        valor_icms = _numero(outra, "vl_icms") or _numero(linha, "vl_icms")
        valor_st = _numero(outra, "vl_icms_st") or _numero(linha, "vl_icms_st")
        base_icms = _numero(outra, "bc_icms") or _numero(linha, "bc_icms")
        base_pis, base_cofins = _numero(linha, "bc_pis"), _numero(linha, "bc_cofins")
        comum = {
            "chave_nfe": chave_item.split(":")[0], "item": int(linha["item"]),
            "linha_pis": int(indice) + 2, "linha_icms": int(grupo.index[0]) + 2,
            "base_icms": base_icms, "valor_icms": valor_icms, "valor_icms_st": valor_st,
            "base_pis": base_pis, "base_cofins": base_cofins,
            "diferenca_pis": base_icms - base_pis, "diferenca_cofins": base_icms - base_cofins,
            "arquivo_pis_sha256": hash_pis, "arquivo_icms_sha256": hash_icms,
        }
        if valor_icms > 0 and base_icms > 0 and base_pis > 0 and base_cofins > 0:
            if abs(base_icms - base_pis) <= tolerancia and abs(base_icms - base_cofins) <= tolerancia:
                achados.append({**comum, "regra": "PISCOFINS_ICMS_69", "estado": "Indício para revisão", "motivo": "Bases de ICMS, PIS e COFINS iguais; confirmar base de receita e exclusão na apuração"})
        if valor_st > 0 and base_pis > 0 and base_cofins > 0:
            achados.append({**comum, "regra": "PISCOFINS_ICMS_ST_1125", "estado": "Revisão jurídica", "motivo": "ICMS-ST presente; confirmar condição de substituído e inclusão nas bases"})
    return pd.DataFrame(achados, columns=COLUNAS)

