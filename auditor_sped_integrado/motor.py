"""Inventário dos Excel Sysconv e triagem conservadora de C170."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import sys
import unicodedata
from zipfile import ZipFile

import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from projeto_icms_piscofins.core.normalize import normalize_icms_items, normalize_piscofins_items


TIPOS = ("EFD ICMS/IPI", "EFD-Contribuições", "ECD", "ECF")
COLUNAS = (
    "regra", "estado", "motivo", "chave_nfe", "item", "aba_pis", "linha_pis", "aba_icms", "linha_icms",
    "cnpj_pis", "cnpj_icms", "competencia_pis", "competencia_icms", "cfop_pis", "cfop_icms",
    "base_icms", "valor_icms", "valor_icms_st", "base_pis", "base_cofins",
    "diferenca_pis", "diferenca_cofins", "arquivo_pis_sha256", "arquivo_icms_sha256",
)
_ROW_START_RE = re.compile(rb"<row(?:\s|>)")
_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


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


def _coluna(quadro: pd.DataFrame, *nomes: str) -> pd.Series:
    for nome in nomes:
        if nome in quadro.columns:
            return quadro[nome].fillna("").astype(str).str.strip()
    return pd.Series("", index=quadro.index, dtype=str)


def _cnpj(valor: object) -> str:
    digitos = re.sub(r"\D", "", str(valor or ""))
    return digitos if len(digitos) == 14 else ""


def _competencia(mes: object, ano: object) -> str:
    nome_mes = unicodedata.normalize("NFKD", str(mes or "")).encode("ascii", "ignore").decode().lower().strip()
    numero_mes = _MESES.get(nome_mes)
    if numero_mes is None and nome_mes.isdigit():
        numero_mes = int(nome_mes)
    ano_texto = str(ano or "").strip().removesuffix(".0")
    if not ano_texto.isdigit() or len(ano_texto) != 4 or not numero_mes or not 1 <= numero_mes <= 12:
        return ""
    return f"{ano_texto}-{numero_mes:02d}"


def _identificar_linhas(quadro: pd.DataFrame, tipo: str) -> pd.DataFrame:
    if tipo == "pis":
        cnpjs = _coluna(quadro, "CNPJ Estabelecimento(C010)", "CNPJ Estabelecimento", "CNPJ")
    else:
        cnpjs = _coluna(quadro, "CNPJ", "CNPJ Estabelecimento")
    meses = _coluna(quadro, "Mês", "Mes")
    anos = _coluna(quadro, "Ano")
    identificadores = pd.DataFrame(index=quadro.index)
    identificadores["cnpj_estabelecimento"] = cnpjs.map(_cnpj)
    identificadores["competencia"] = [_competencia(mes, ano) for mes, ano in zip(meses, anos)]
    return identificadores


def _cobertura_icms(arquivo: str | Path | bytes) -> set[tuple[str, str]]:
    fonte = BytesIO(arquivo) if isinstance(arquivo, bytes) else Path(arquivo)
    with pd.ExcelFile(fonte) as livro:
        if "0000" not in livro.sheet_names:
            return set()
        quadro = pd.read_excel(livro, sheet_name="0000", dtype=str)
    identificadores = _identificar_linhas(quadro, "icms")
    return {
        (cnpj, periodo)
        for cnpj, periodo in zip(identificadores["cnpj_estabelecimento"], identificadores["competencia"])
        if cnpj and periodo
    }


def _ler_c170(arquivo: str | Path | bytes, nome: str) -> pd.DataFrame:
    fonte = BytesIO(arquivo) if isinstance(arquivo, bytes) else Path(arquivo)
    with pd.ExcelFile(fonte) as livro:
        abas = [nome_aba for nome_aba in livro.sheet_names if nome_aba.casefold().startswith("c170")]
        if not abas:
            raise ValueError(f"Aba C170 não encontrada em {nome}.")
        quadros = []
        for aba in abas:
            quadro = pd.read_excel(livro, sheet_name=aba)
            quadro["_aba_origem"] = aba
            quadro["_linha_origem"] = range(2, len(quadro) + 2)
            quadros.append(quadro)
        return pd.concat(quadros, ignore_index=True)


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
    icms_bruto = _ler_c170(caminho_icms, nome_icms)
    pis_bruto = _ler_c170(caminho_pis, nome_pis)
    icms = normalize_icms_items(icms_bruto)
    pis = normalize_piscofins_items(pis_bruto)
    for quadro, bruto, tipo in ((icms, icms_bruto, "icms"), (pis, pis_bruto, "pis")):
        identificadores = _identificar_linhas(bruto, tipo)
        quadro["cnpj_estabelecimento"] = identificadores["cnpj_estabelecimento"]
        quadro["competencia"] = identificadores["competencia"]
    for quadro, nome in ((icms, "ICMS/IPI"), (pis, "PIS/COFINS")):
        if quadro.empty:
            raise ValueError(f"A aba C170 de {nome} está vazia.")
        if not any(quadro["chave"].astype(str).str.len().eq(44)):
            raise ValueError(f"C170 de {nome} não contém chave de NF-e com 44 dígitos.")
    icms["_chave_item"] = icms.apply(_chave_item, axis=1)
    pis["_chave_item"] = pis.apply(_chave_item, axis=1)
    grupos_icms = {chave: grupo for chave, grupo in icms[icms["_chave_item"] != ""].groupby("_chave_item")}
    pis_saida = pis[(pis["ind_oper_desc"] == "Saída") & pis["situacao_ok"] & (pis["_chave_item"] != "")]
    contagem_pis = pis_saida.groupby(["_chave_item", "cnpj_estabelecimento", "competencia"]).size()
    cobertura_icms = _cobertura_icms(caminho_icms)
    hash_pis, hash_icms = hash_arquivo(caminho_pis), hash_arquivo(caminho_icms)
    achados = []
    for indice, linha in pis_saida.iterrows():
        chave_item = linha["_chave_item"]
        grupo = grupos_icms.get(chave_item)
        if grupo is None:
            continue
        cnpj = linha["cnpj_estabelecimento"]
        competencia = linha["competencia"]
        referencia = grupo.iloc[0] if len(grupo) == 1 else None
        evidencias = {
            "regra": "CONCILIACAO_C170", "chave_nfe": chave_item.split(":")[0],
            "item": int(linha["item"]), "aba_pis": pis_bruto.at[indice, "_aba_origem"],
            "linha_pis": int(pis_bruto.at[indice, "_linha_origem"]),
            "aba_icms": icms_bruto.at[grupo.index[0], "_aba_origem"] if referencia is not None else None,
            "linha_icms": int(icms_bruto.at[grupo.index[0], "_linha_origem"]) if referencia is not None else None,
            "cnpj_pis": cnpj,
            "cnpj_icms": referencia["cnpj_estabelecimento"] if referencia is not None else None,
            "competencia_pis": competencia,
            "competencia_icms": referencia["competencia"] if referencia is not None else None,
            "cfop_pis": linha["cfop"],
            "cfop_icms": referencia["cfop"] if referencia is not None else None,
            "arquivo_pis_sha256": hash_pis, "arquivo_icms_sha256": hash_icms,
        }
        if not cnpj or not competencia or not cobertura_icms:
            achados.append({**evidencias, "estado": "Cobertura indeterminada",
                            "motivo": "CNPJ, competência ou registro 0000 insuficiente para verificar a cobertura do ICMS/IPI"})
            continue
        if (cnpj, competencia) not in cobertura_icms:
            if referencia is not None and referencia["ind_oper_desc"] == "Entrada" and referencia["cnpj_estabelecimento"] != cnpj:
                motivo = (f"Saída do estabelecimento {cnpj} em {competencia} sem cobertura no ICMS/IPI fornecido; "
                          f"mesma chave e item encontrados como entrada no estabelecimento {referencia['cnpj_estabelecimento']}")
            else:
                motivo = (f"Saída do estabelecimento {cnpj} em {competencia} sem cobertura no ICMS/IPI fornecido; "
                          "chave e item encontrados em outro contexto")
            achados.append({**evidencias, "estado": "Estabelecimento sem cobertura",
                            "motivo": motivo})
            continue
        grupo_mesmo = grupo[(grupo["cnpj_estabelecimento"] == cnpj) & (grupo["competencia"] == competencia)]
        if grupo_mesmo.empty:
            achados.append({**evidencias, "estado": "Estabelecimento ou competência diferente",
                            "motivo": "Chave e item encontrados no ICMS/IPI, mas em outro estabelecimento ou competência"})
            continue
        grupo_saida = grupo_mesmo[(grupo_mesmo["ind_oper_desc"] == "Saída") & grupo_mesmo["situacao_ok"]]
        if grupo_saida.empty:
            outra = grupo_mesmo.iloc[0] if len(grupo_mesmo) == 1 else None
            achados.append({**evidencias, "estado": "Operação diferente",
                            "motivo": "Saída em Contribuições sem saída correspondente no ICMS/IPI do mesmo estabelecimento e competência",
                            "linha_icms": int(icms_bruto.at[grupo_mesmo.index[0], "_linha_origem"]) if outra is not None else None,
                            "cnpj_icms": outra["cnpj_estabelecimento"] if outra is not None else None,
                            "competencia_icms": outra["competencia"] if outra is not None else None,
                            "cfop_icms": outra["cfop"] if outra is not None else None})
            continue
        if len(grupo_saida) != 1 or int(contagem_pis[(chave_item, cnpj, competencia)]) != 1:
            achados.append({**evidencias, "estado": "Ambíguo", "motivo": "Chave da NF-e e item repetidos no mesmo estabelecimento e competência",
                            "linha_icms": None, "cnpj_icms": None, "competencia_icms": None, "cfop_icms": None})
            continue
        outra = grupo_saida.iloc[0]
        valor_icms = _numero(outra, "vl_icms") or _numero(linha, "vl_icms")
        valor_st = _numero(outra, "vl_icms_st") or _numero(linha, "vl_icms_st")
        base_icms = _numero(outra, "bc_icms") or _numero(linha, "bc_icms")
        base_pis, base_cofins = _numero(linha, "bc_pis"), _numero(linha, "bc_cofins")
        comum = {
            "chave_nfe": chave_item.split(":")[0], "item": int(linha["item"]),
            "aba_pis": pis_bruto.at[indice, "_aba_origem"],
            "linha_pis": int(pis_bruto.at[indice, "_linha_origem"]),
            "aba_icms": icms_bruto.at[grupo_saida.index[0], "_aba_origem"],
            "linha_icms": int(icms_bruto.at[grupo_saida.index[0], "_linha_origem"]),
            "cnpj_pis": cnpj, "cnpj_icms": outra["cnpj_estabelecimento"],
            "competencia_pis": competencia, "competencia_icms": outra["competencia"],
            "cfop_pis": linha["cfop"], "cfop_icms": outra["cfop"],
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

