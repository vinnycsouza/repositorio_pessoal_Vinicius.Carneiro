"""Compara, em streaming, os XLSX S-1200 do LaraTex com um Workspace.

Ferramenta somente leitura. Não altera os XLSX nem o processamento.db.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import argparse
import html
import json
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile


TEXTOS = re.compile(br"<(?:x:)?t[^>]*>(.*?)</(?:x:)?t>", re.DOTALL)
VALOR = re.compile(br"<(?:x:)?v[^>]*>(.*?)</(?:x:)?v>", re.DOTALL)
CELULAS = re.compile(br"<(?:x:)?c\b.*?</(?:x:)?c>", re.DOTALL)


def _centavos(valor: str) -> int:
    try:
        return int(
            (Decimal(str(valor).strip()) * 100).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    except (InvalidOperation, ValueError):
        return 0


def _valor_segmento(segmento: bytes, compartilhados: list[str]) -> str:
    texto = TEXTOS.search(segmento)
    if texto is not None:
        return html.unescape(texto.group(1).decode("utf-8", "replace")).strip()
    valor = VALOR.search(segmento)
    if valor is None:
        return ""
    bruto = valor.group(1).decode("utf-8", "replace").strip()
    if re.search(br'\bt="s"', segmento):
        try:
            return compartilhados[int(bruto)]
        except (ValueError, IndexError):
            return ""
    return bruto


def _valores_linha(bloco: bytes, compartilhados: list[str]) -> list[str]:
    return [
        _valor_segmento(celula.group(0), compartilhados)
        for celula in CELULAS.finditer(bloco)
    ]


def _carregar_compartilhados(pacote: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in pacote.namelist():
        return []
    saida: list[str] = []
    with pacote.open("xl/sharedStrings.xml") as origem:
        for _, elemento in ET.iterparse(origem, events=("end",)):
            if elemento.tag.rsplit("}", 1)[-1] == "si":
                saida.append("".join(
                    filho.text or "" for filho in elemento.iter()
                    if filho.tag.rsplit("}", 1)[-1] == "t"
                ))
                elemento.clear()
    return saida


def _blocos_linhas_xlsx(caminho: Path):
    with zipfile.ZipFile(caminho) as pacote:
        compartilhados = _carregar_compartilhados(pacote)
        planilhas = sorted(
            nome for nome in pacote.namelist()
            if nome.startswith("xl/worksheets/") and nome.endswith(".xml")
        )
        for nome in planilhas:
            with pacote.open(nome) as origem:
                pendente = b""
                fim_linha: bytes | None = None
                inicio_linha: bytes | None = None
                while True:
                    trecho = origem.read(4 * 1024 * 1024)
                    if not trecho:
                        break
                    combinado = pendente + trecho
                    if fim_linha is None:
                        if b"</x:row>" in combinado:
                            inicio_linha, fim_linha = b"<x:row", b"</x:row>"
                        elif b"</row>" in combinado:
                            inicio_linha, fim_linha = b"<row", b"</row>"
                        else:
                            pendente = combinado
                            continue
                    partes = combinado.split(fim_linha)
                    pendente = partes.pop()
                    for parte in partes:
                        inicio = parte.rfind(inicio_linha)
                        if inicio >= 0:
                            yield parte[inicio:] + fim_linha, compartilhados


def _valores_indices(
    bloco: bytes, indices: set[int], compartilhados: list[str]
) -> dict[int, str]:
    """Lê somente as primeiras células necessárias, sem dividir as 61 colunas."""
    encontrados: dict[int, str] = {}
    for indice, localizado in enumerate(CELULAS.finditer(bloco)):
        if indice > max(indices):
            break
        if indice in indices:
            encontrados[indice] = _valor_segmento(
                localizado.group(0), compartilhados
            )
    return encontrados


def carregar_laratex(pasta: Path) -> tuple[dict[tuple[str, str, str], list[int]], int]:
    agregado: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    total = 0
    for caminho in sorted(pasta.glob("*.xlsx")):
        linhas = _blocos_linhas_xlsx(caminho)
        primeiro_bloco, compartilhados = next(linhas, (b"", []))
        cabecalho = _valores_linha(primeiro_bloco, compartilhados)
        indices = {nome: posicao for posicao, nome in enumerate(cabecalho)}
        obrigatorios = {
            "periodo_apuracao", "identificador_rubrica", "codigo_rubrica",
            "vlr_total_rubrica",
        }
        faltantes = obrigatorios - set(indices)
        if faltantes:
            raise ValueError(f"{caminho.name}: colunas ausentes: {sorted(faltantes)}")
        processadas = 0
        indices_necessarios = {
            indices["codigo_rubrica"],
            indices["identificador_rubrica"],
            indices["periodo_apuracao"],
            indices["vlr_total_rubrica"],
        }
        for bloco, compartilhados in linhas:
            valores = _valores_indices(
                bloco, indices_necessarios, compartilhados
            )
            chave = (
                valores.get(indices["codigo_rubrica"], ""),
                valores.get(indices["identificador_rubrica"], ""),
                valores.get(indices["periodo_apuracao"], ""),
            )
            if not chave[0]:
                continue
            agregado[chave][0] += 1
            agregado[chave][1] += _centavos(
                valores.get(indices["vlr_total_rubrica"], "")
            )
            processadas += 1
        total += processadas
        print(json.dumps({
            "arquivo": caminho.name,
            "linhas": processadas,
            "chaves_acumuladas": len(agregado),
        }), flush=True)
    return dict(agregado), total


def carregar_workspace(db_path: Path) -> tuple[dict[tuple[str, str, str], list[int]], int]:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        linhas = conn.execute("""
            SELECT COALESCE(cod_rubr,''),COALESCE(ide_tab_rubr,''),COALESCE(per_apur,''),
                   COUNT(*),ROUND(COALESCE(SUM(CAST(vr_rubr AS REAL)),0)*100)
            FROM rel_movimentos_cp
            GROUP BY cod_rubr,ide_tab_rubr,per_apur
        """).fetchall()
    finally:
        conn.close()
    agregado = {
        (str(codigo), str(tabela), str(periodo)): [int(quantidade), int(centavos or 0)]
        for codigo, tabela, periodo, quantidade, centavos in linhas
    }
    return agregado, sum(item[0] for item in agregado.values())


def comparar(laratex, workspace) -> dict[str, object]:
    chaves_lara = set(laratex)
    chaves_ws = set(workspace)
    ausentes = sorted(
        chaves_lara - chaves_ws,
        key=lambda chave: abs(laratex[chave][1]),
        reverse=True,
    )
    divergentes = sorted(
        (
            chave for chave in chaves_lara & chaves_ws
            if laratex[chave] != workspace[chave]
        ),
        key=lambda chave: abs(laratex[chave][1] - workspace[chave][1]),
        reverse=True,
    )
    rubricas_lara = {(c, t) for c, t, _ in chaves_lara}
    rubricas_ws = {(c, t) for c, t, _ in chaves_ws}
    rubricas_ausentes = sorted(rubricas_lara - rubricas_ws)
    ausencias_por_competencia: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for chave in ausentes:
        resumo = ausencias_por_competencia[chave[2]]
        resumo[0] += 1
        resumo[1] += laratex[chave][0]
        resumo[2] += laratex[chave][1]

    rubricas_ausentes_detalhe = []
    for codigo, tabela in rubricas_ausentes:
        chaves = [chave for chave in ausentes if chave[:2] == (codigo, tabela)]
        rubricas_ausentes_detalhe.append({
            "codigo": codigo,
            "tabela": tabela,
            "competencias": len(chaves),
            "linhas_laratex": sum(laratex[chave][0] for chave in chaves),
            "valor_laratex": sum(laratex[chave][1] for chave in chaves) / 100,
            "primeira_competencia": min((chave[2] for chave in chaves), default=""),
            "ultima_competencia": max((chave[2] for chave in chaves), default=""),
        })
    rubricas_ausentes_detalhe.sort(
        key=lambda item: abs(item["valor_laratex"]), reverse=True
    )

    def detalhe(chave, somente_lara=False):
        lara = laratex[chave]
        ws = workspace.get(chave, [0, 0])
        return {
            "codigo": chave[0], "tabela": chave[1], "competencia": chave[2],
            "linhas_laratex": lara[0], "valor_laratex": lara[1] / 100,
            "linhas_workspace": ws[0], "valor_workspace": ws[1] / 100,
            "diferenca": (lara[1] - ws[1]) / 100,
        }

    return {
        "chaves_laratex": len(chaves_lara),
        "chaves_workspace": len(chaves_ws),
        "rubricas_laratex": len(rubricas_lara),
        "rubricas_workspace": len(rubricas_ws),
        "rubricas_totalmente_ausentes": len(rubricas_lara - rubricas_ws),
        "chaves_competencia_ausentes": len(ausentes),
        "chaves_com_contagem_ou_valor_divergente": len(divergentes),
        "ausencias_por_competencia": [
            {
                "competencia": competencia,
                "chaves": valores[0],
                "linhas": valores[1],
                "valor": valores[2] / 100,
            }
            for competencia, valores in sorted(ausencias_por_competencia.items())
        ],
        "rubricas_ausentes": rubricas_ausentes_detalhe,
        "maiores_ausencias": [detalhe(chave, True) for chave in ausentes[:100]],
        "maiores_divergencias": [detalhe(chave) for chave in divergentes[:100]],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pasta_laratex", type=Path)
    parser.add_argument("workspace_ou_db", type=Path)
    args = parser.parse_args()
    db_path = (
        args.workspace_ou_db
        if args.workspace_ou_db.suffix.lower() == ".db"
        else args.workspace_ou_db / "processamento.db"
    )
    laratex, linhas_laratex = carregar_laratex(args.pasta_laratex)
    workspace, linhas_workspace = carregar_workspace(db_path)
    resultado = comparar(laratex, workspace)
    resultado["linhas_laratex"] = linhas_laratex
    resultado["linhas_workspace"] = linhas_workspace
    print("RESULTADO=" + json.dumps(resultado, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
