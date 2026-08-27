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
import zipfile


FIM_LINHA = b"</x:row>"
TEXTOS = re.compile(br"<x:t[^>]*>(.*?)</x:t>", re.DOTALL)


def _centavos(valor: str) -> int:
    try:
        return int(
            (Decimal(str(valor).strip()) * 100).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    except (InvalidOperation, ValueError):
        return 0


def _valores_linha(bloco: bytes) -> list[str]:
    return [
        html.unescape(valor.decode("utf-8", "replace"))
        for valor in TEXTOS.findall(bloco)
    ]


def _blocos_linhas_xlsx(caminho: Path):
    with zipfile.ZipFile(caminho) as pacote:
        planilhas = sorted(
            nome for nome in pacote.namelist()
            if nome.startswith("xl/worksheets/") and nome.endswith(".xml")
        )
        for nome in planilhas:
            with pacote.open(nome) as origem:
                pendente = b""
                while True:
                    trecho = origem.read(4 * 1024 * 1024)
                    if not trecho:
                        break
                    partes = (pendente + trecho).split(FIM_LINHA)
                    pendente = partes.pop()
                    for parte in partes:
                        inicio = parte.rfind(b"<x:row")
                        if inicio >= 0:
                            yield parte[inicio:] + FIM_LINHA
                inicio = pendente.rfind(b"<x:row")
                if inicio >= 0 and FIM_LINHA in pendente[inicio:]:
                    yield pendente[inicio:]


def _valores_indices(bloco: bytes, indices: set[int]) -> dict[int, str]:
    """Lê somente as primeiras células necessárias, sem dividir as 61 colunas."""
    encontrados: dict[int, str] = {}
    inicio = 0
    for indice in range(max(indices) + 1):
        fim = bloco.find(b"</x:c>", inicio)
        if fim < 0:
            break
        if indice in indices:
            localizado = TEXTOS.search(bloco, inicio, fim)
            encontrados[indice] = (
                html.unescape(localizado.group(1).decode("utf-8", "replace")).strip()
                if localizado is not None else ""
            )
        inicio = fim + len(b"</x:c>")
    return encontrados


def carregar_laratex(pasta: Path) -> tuple[dict[tuple[str, str, str], list[int]], int]:
    agregado: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    total = 0
    for caminho in sorted(pasta.glob("*.xlsx")):
        linhas = _blocos_linhas_xlsx(caminho)
        cabecalho = _valores_linha(next(linhas, b""))
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
        for bloco in linhas:
            valores = _valores_indices(bloco, indices_necessarios)
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
            FROM dados_remuneracoes
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
