"""Conciliação C170 em lotes, com índice temporário no disco."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory

import pandas as pd
from openpyxl import load_workbook

from projeto_icms_piscofins.core.normalize import normalize_icms_items, normalize_piscofins_items


def _fonte(arquivo: str | Path | bytes):
    return BytesIO(arquivo) if isinstance(arquivo, bytes) else Path(arquivo)


def _numero(valor) -> float:
    numero = pd.to_numeric(valor, errors="coerce")
    return 0.0 if pd.isna(numero) else float(numero)


def _chave_item(chave, item) -> str:
    digitos = re.sub(r"\D", "", str(chave or ""))
    numero = int(_numero(item))
    return f"{digitos}:{numero}" if len(digitos) == 44 and numero > 0 else ""


def _lotes_c170(arquivo, tipo: str, nome_arquivo: str):
    # O normalizador original é aplicado em lotes para preservar aliases e
    # conversões sem manter o livro completo em DataFrames.
    from auditor_sped_integrado.motor import _identificar_linhas

    livro = load_workbook(_fonte(arquivo), read_only=True, data_only=True)
    try:
        nomes = [nome for nome in livro.sheetnames if nome.casefold().startswith("c170")]
        if not nomes:
            raise ValueError(f"Aba C170 não encontrada em {nome_arquivo}.")
        for nome in nomes:
            aba = livro[nome]
            aba.reset_dimensions()
            linhas = aba.iter_rows(values_only=True)
            cabecalho = next(linhas, None)
            if cabecalho is None:
                continue
            lote = []
            inicio = 2
            for numero_linha, valores in enumerate(linhas, 2):
                lote.append(valores)
                if len(lote) < 4000:
                    continue
                bruto = pd.DataFrame(lote, columns=cabecalho)
                normal = normalize_icms_items(bruto) if tipo == "icms" else normalize_piscofins_items(bruto)
                ident = _identificar_linhas(bruto, tipo)
                normal["cnpj_estabelecimento"] = ident["cnpj_estabelecimento"]
                normal["competencia"] = ident["competencia"]
                normal["_aba_origem"] = nome
                normal["_linha_origem"] = range(inicio, numero_linha + 1)
                yield normal
                lote.clear()
                inicio = numero_linha + 1
            if lote:
                bruto = pd.DataFrame(lote, columns=cabecalho)
                normal = normalize_icms_items(bruto) if tipo == "icms" else normalize_piscofins_items(bruto)
                ident = _identificar_linhas(bruto, tipo)
                normal["cnpj_estabelecimento"] = ident["cnpj_estabelecimento"]
                normal["competencia"] = ident["competencia"]
                normal["_aba_origem"] = nome
                normal["_linha_origem"] = range(inicio, inicio + len(lote))
                yield normal
    finally:
        livro.close()


def triagem_c170_streaming(
    caminho_icms, caminho_pis, tolerancia: float, nome_icms: str, nome_pis: str,
    hash_icms: str, hash_pis: str,
) -> pd.DataFrame:
    from auditor_sped_integrado.motor import COLUNAS, _cobertura_icms

    cobertura_icms = _cobertura_icms(caminho_icms)
    with TemporaryDirectory(prefix="auditor_sped_c170_") as pasta:
        conexao = sqlite3.connect(str(Path(pasta) / "triagem.db"))
        try:
            conexao.execute("""CREATE TABLE icms (
                chave_item TEXT, chave TEXT, item INTEGER, cnpj TEXT, competencia TEXT,
                operacao TEXT, situacao_ok INTEGER, cfop TEXT, bc_icms REAL,
                vl_icms REAL, vl_icms_st REAL, aba TEXT, linha INTEGER
            )""")
            conexao.execute("""CREATE TABLE pis (
                chave_item TEXT, chave TEXT, item INTEGER, cnpj TEXT, competencia TEXT,
                cfop TEXT, bc_icms REAL, vl_icms REAL, vl_icms_st REAL,
                bc_pis REAL, bc_cofins REAL, aba TEXT, linha INTEGER
            )""")
            achou_icms = achou_pis = False
            for lote in _lotes_c170(caminho_icms, "icms", nome_icms):
                registros = []
                for linha in lote.itertuples(index=False, name=None):
                    item = dict(zip(lote.columns, linha))
                    chave_item = _chave_item(item["chave"], item["item"])
                    achou_icms |= len(str(item["chave"])) == 44
                    if not chave_item:
                        continue
                    registros.append((
                        chave_item, str(item["chave"]), int(_numero(item["item"])),
                        str(item["cnpj_estabelecimento"]), str(item["competencia"]),
                        str(item["ind_oper_desc"]), int(bool(item["situacao_ok"])),
                        str(item["cfop"]), _numero(item["bc_icms"]),
                        _numero(item["vl_icms"]), _numero(item["vl_icms_st"]),
                        item["_aba_origem"], int(item["_linha_origem"]),
                    ))
                conexao.executemany("INSERT INTO icms VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", registros)
            if not achou_icms:
                raise ValueError("C170 de ICMS/IPI não contém chave de NF-e com 44 dígitos.")
            conexao.execute("CREATE INDEX icms_por_chave_item ON icms (chave_item)")
            for lote in _lotes_c170(caminho_pis, "pis", nome_pis):
                registros = []
                for linha in lote.itertuples(index=False, name=None):
                    item = dict(zip(lote.columns, linha))
                    chave_item = _chave_item(item["chave"], item["item"])
                    achou_pis |= len(str(item["chave"])) == 44
                    if not chave_item or item["ind_oper_desc"] != "Saída" or not item["situacao_ok"]:
                        continue
                    registros.append((
                        chave_item, str(item["chave"]), int(_numero(item["item"])),
                        str(item["cnpj_estabelecimento"]), str(item["competencia"]),
                        str(item["cfop"]), _numero(item["bc_icms"]),
                        _numero(item["vl_icms"]), _numero(item["vl_icms_st"]),
                        _numero(item["bc_pis"]), _numero(item["bc_cofins"]),
                        item["_aba_origem"], int(item["_linha_origem"]),
                    ))
                conexao.executemany("INSERT INTO pis VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", registros)
            if not achou_pis:
                raise ValueError("C170 de PIS/COFINS não contém chave de NF-e com 44 dígitos.")
            conexao.execute("CREATE INDEX pis_por_chave_contexto ON pis (chave_item, cnpj, competencia)")
            colunas_icms = ["chave_item", "chave", "item", "cnpj", "competencia", "operacao", "situacao_ok",
                            "cfop", "bc_icms", "vl_icms", "vl_icms_st", "aba", "linha"]
            colunas_pis = ["chave_item", "chave", "item", "cnpj", "competencia", "cfop", "bc_icms",
                           "vl_icms", "vl_icms_st", "bc_pis", "bc_cofins", "aba", "linha"]
            achados = []
            for valores in conexao.execute("SELECT * FROM pis ORDER BY rowid"):
                pis = dict(zip(colunas_pis, valores))
                pares = [dict(zip(colunas_icms, v)) for v in conexao.execute(
                    "SELECT * FROM icms WHERE chave_item=?", (pis["chave_item"],)
                )]
                if not pares:
                    continue
                referencia = pares[0] if len(pares) == 1 else None
                evidencia = {
                    "regra": "CONCILIACAO_C170", "chave_nfe": pis["chave_item"].split(":")[0],
                    "item": pis["item"], "aba_pis": pis["aba"], "linha_pis": pis["linha"],
                    "aba_icms": referencia["aba"] if referencia else None,
                    "linha_icms": referencia["linha"] if referencia else None,
                    "cnpj_pis": pis["cnpj"], "cnpj_icms": referencia["cnpj"] if referencia else None,
                    "competencia_pis": pis["competencia"],
                    "competencia_icms": referencia["competencia"] if referencia else None,
                    "cfop_pis": pis["cfop"], "cfop_icms": referencia["cfop"] if referencia else None,
                    "arquivo_pis_sha256": hash_pis, "arquivo_icms_sha256": hash_icms,
                }
                cnpj, competencia = pis["cnpj"], pis["competencia"]
                if not cnpj or not competencia or not cobertura_icms:
                    achados.append({**evidencia, "estado": "Cobertura indeterminada",
                                    "motivo": "CNPJ, competência ou registro 0000 insuficiente para verificar a cobertura do ICMS/IPI"})
                    continue
                if (cnpj, competencia) not in cobertura_icms:
                    if referencia and referencia["operacao"] == "Entrada" and referencia["cnpj"] != cnpj:
                        motivo = (f"Saída do estabelecimento {cnpj} em {competencia} sem cobertura no ICMS/IPI fornecido; "
                                  f"mesma chave e item encontrados como entrada no estabelecimento {referencia['cnpj']}")
                    else:
                        motivo = (f"Saída do estabelecimento {cnpj} em {competencia} sem cobertura no ICMS/IPI fornecido; "
                                  "chave e item encontrados em outro contexto")
                    achados.append({**evidencia, "estado": "Estabelecimento sem cobertura", "motivo": motivo})
                    continue
                mesmo = [p for p in pares if p["cnpj"] == cnpj and p["competencia"] == competencia]
                if not mesmo:
                    achados.append({**evidencia, "estado": "Estabelecimento ou competência diferente",
                                    "motivo": "Chave e item encontrados no ICMS/IPI, mas em outro estabelecimento ou competência"})
                    continue
                saidas = [p for p in mesmo if p["operacao"] == "Saída" and p["situacao_ok"]]
                if not saidas:
                    outra = mesmo[0] if len(mesmo) == 1 else None
                    achados.append({**evidencia, "estado": "Operação diferente",
                                    "motivo": "Saída em Contribuições sem saída correspondente no ICMS/IPI do mesmo estabelecimento e competência",
                                    "linha_icms": mesmo[0]["linha"] if outra else None,
                                    "cnpj_icms": outra["cnpj"] if outra else None,
                                    "competencia_icms": outra["competencia"] if outra else None,
                                    "cfop_icms": outra["cfop"] if outra else None})
                    continue
                contagem_pis = conexao.execute(
                    "SELECT COUNT(*) FROM pis WHERE chave_item=? AND cnpj=? AND competencia=?",
                    (pis["chave_item"], cnpj, competencia),
                ).fetchone()[0]
                if len(saidas) != 1 or contagem_pis != 1:
                    achados.append({**evidencia, "estado": "Ambíguo",
                                    "motivo": "Chave da NF-e e item repetidos no mesmo estabelecimento e competência",
                                    "linha_icms": None, "cnpj_icms": None,
                                    "competencia_icms": None, "cfop_icms": None})
                    continue
                outra = saidas[0]
                valor_icms = outra["vl_icms"] or pis["vl_icms"]
                valor_st = outra["vl_icms_st"] or pis["vl_icms_st"]
                base_icms = outra["bc_icms"] or pis["bc_icms"]
                base_pis, base_cofins = pis["bc_pis"], pis["bc_cofins"]
                comum = {
                    "chave_nfe": pis["chave_item"].split(":")[0], "item": pis["item"],
                    "aba_pis": pis["aba"], "linha_pis": pis["linha"],
                    "aba_icms": outra["aba"], "linha_icms": outra["linha"],
                    "cnpj_pis": cnpj, "cnpj_icms": outra["cnpj"],
                    "competencia_pis": competencia, "competencia_icms": outra["competencia"],
                    "cfop_pis": pis["cfop"], "cfop_icms": outra["cfop"],
                    "base_icms": base_icms, "valor_icms": valor_icms, "valor_icms_st": valor_st,
                    "base_pis": base_pis, "base_cofins": base_cofins,
                    "diferenca_pis": base_icms - base_pis, "diferenca_cofins": base_icms - base_cofins,
                    "arquivo_pis_sha256": hash_pis, "arquivo_icms_sha256": hash_icms,
                }
                if valor_icms > 0 and base_icms > 0 and base_pis > 0 and base_cofins > 0:
                    if abs(base_icms - base_pis) <= tolerancia and abs(base_icms - base_cofins) <= tolerancia:
                        achados.append({**comum, "regra": "PISCOFINS_ICMS_69", "estado": "Indício para revisão",
                                        "motivo": "Bases de ICMS, PIS e COFINS iguais; confirmar base de receita e exclusão na apuração"})
                if valor_st > 0 and base_pis > 0 and base_cofins > 0:
                    achados.append({**comum, "regra": "PISCOFINS_ICMS_ST_1125", "estado": "Revisão jurídica",
                                    "motivo": "ICMS-ST presente; confirmar condição de substituído e inclusão nas bases"})
            return pd.DataFrame(achados, columns=COLUNAS)
        finally:
            conexao.close()
