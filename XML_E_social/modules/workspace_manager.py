from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from send2trash import send2trash


@dataclass(frozen=True)
class WorkspaceInfo:
    nome_empresa: str
    cnpj: str
    nome_workspace: str
    caminho: Path
    status: str
    tamanho_total: int
    tamanho_sqlite: int | None
    quantidade_xml: int = 0
    periodo_minimo: str = ""
    periodo_maximo: str = ""


def formatar_cnpj(valor: object) -> str:
    digitos = "".join(c for c in str(valor or "") if c.isdigit())
    if len(digitos) == 14:
        return (
            f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/"
            f"{digitos[8:12]}-{digitos[12:]}"
        )
    return digitos


def formatar_tamanho(bytes_total: int | None) -> str:
    if bytes_total is None:
        return "Não disponível"
    valor = float(max(bytes_total, 0))
    unidades = ["B", "KB", "MB", "GB", "TB"]
    for unidade in unidades:
        if valor < 1024 or unidade == unidades[-1]:
            casas = 0 if unidade == "B" else 1
            return f"{valor:.{casas}f} {unidade}".replace(".", ",")
        valor /= 1024
    return f"{valor:.1f} TB".replace(".", ",")


def calcular_tamanho_workspace(caminho: str | Path) -> int:
    raiz = Path(caminho).expanduser().resolve()
    total = 0
    for pasta_atual, _, arquivos in os.walk(raiz, followlinks=False):
        for nome in arquivos:
            arquivo = Path(pasta_atual) / nome
            try:
                if not arquivo.is_symlink():
                    total += arquivo.stat().st_size
            except OSError:
                continue
    return total


def _ler_status_sqlite(db_path: Path) -> str:
    if not db_path.is_file():
        return "Interrompido"
    conn = None
    try:
        conn = sqlite3.connect(
            f"file:{db_path.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=5,
        )
        row = conn.execute(
            "SELECT valor FROM meta WHERE chave='status'"
        ).fetchone()
        valor = str(row[0] if row else "interrompido").strip().lower()
    except (OSError, sqlite3.Error):
        return "Em processamento" if db_path.with_name(f"{db_path.name}-wal").exists() else "Interrompido"
    finally:
        if conn is not None:
            conn.close()
    return {
        "concluido": "Concluído",
        "processando": "Em processamento",
        "interrompido": "Interrompido",
    }.get(valor, "Interrompido")


def _empresa_do_resultado(resultado: Mapping[str, object]) -> tuple[str, str]:
    empresa = resultado.get("empresa")
    registros: list[dict] = []
    if hasattr(empresa, "to_dict"):
        try:
            registros = empresa.to_dict("records")
        except (TypeError, ValueError):
            registros = []
    elif isinstance(empresa, list):
        registros = [dict(item) for item in empresa if isinstance(item, Mapping)]
    if not registros:
        return "Não identificado", "Não identificado"
    registro = next(
        (
            item
            for item in registros
            if str(item.get("nome_empresa", "") or "").strip()
        ),
        registros[0],
    )
    nome = str(registro.get("nome_empresa", "") or "").strip()
    cnpj = formatar_cnpj(registro.get("cnpj_empregador", ""))
    return nome or "Não identificado", cnpj or "Não identificado"


def obter_info_workspace(resultado: Mapping[str, object]) -> WorkspaceInfo:
    caminho_informado = resultado.get("workspace_temporario", "")
    if not caminho_informado:
        raise ValueError("O resultado atual não possui um Workspace associado.")
    caminho = Path(str(caminho_informado)).expanduser().resolve()
    if not caminho.is_dir():
        raise FileNotFoundError(f"Workspace não localizado: {caminho}")
    db_path = caminho / "processamento.db"
    nome_empresa, cnpj = _empresa_do_resultado(resultado)
    quantidade_xml = 0
    periodo_minimo = ""
    periodo_maximo = ""
    if db_path.is_file():
        conn = sqlite3.connect(str(db_path), timeout=5)
        try:
            tabelas = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "eventos" in tabelas:
                quantidade_xml = int(
                    conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
                )
            if "rel_movimentos_cp" in tabelas:
                periodo_minimo, periodo_maximo = conn.execute(
                    "SELECT COALESCE(MIN(per_apur),''),COALESCE(MAX(per_apur),'') "
                    "FROM rel_movimentos_cp"
                ).fetchone()
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return WorkspaceInfo(
        nome_empresa=nome_empresa,
        cnpj=cnpj,
        nome_workspace=caminho.name,
        caminho=caminho,
        status=_ler_status_sqlite(db_path),
        tamanho_total=calcular_tamanho_workspace(caminho),
        tamanho_sqlite=db_path.stat().st_size if db_path.is_file() else None,
        quantidade_xml=quantidade_xml,
        periodo_minimo=str(periodo_minimo or ""),
        periodo_maximo=str(periodo_maximo or ""),
    )


def abrir_workspace(caminho: str | Path) -> None:
    pasta = Path(caminho).expanduser().resolve()
    if not pasta.is_dir():
        raise FileNotFoundError(f"Workspace não localizado: {pasta}")
    if os.name == "nt":
        os.startfile(str(pasta))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(pasta)])
    else:
        subprocess.Popen(["xdg-open", str(pasta)])


def enviar_workspace_para_lixeira(caminho: str | Path) -> None:
    pasta = Path(caminho).expanduser().resolve()
    if not pasta.is_dir():
        raise FileNotFoundError(f"Workspace não localizado: {pasta}")
    if pasta == Path(pasta.anchor) or pasta == Path.home().resolve():
        raise ValueError("O caminho informado não é um Workspace seguro.")
    if not (pasta / "processamento.db").is_file():
        raise ValueError("O Workspace não contém processamento.db.")
    send2trash(str(pasta))
