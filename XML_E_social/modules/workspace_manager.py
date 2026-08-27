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
    versao_engine: str = ""
    versao_parser: str = ""
    versao_consistencia: str = ""


@dataclass(frozen=True)
class WorkspaceCatalogItem:
    nome_empresa: str
    cnpj: str
    nome_workspace: str
    caminho: Path
    db_path: Path
    status: str
    tamanho_sqlite: int
    quantidade_xml: int
    periodo_minimo: str
    periodo_maximo: str
    atualizado_em: float

    @property
    def carregavel(self) -> bool:
        return self.status == "Concluído"

    @property
    def rotulo(self) -> str:
        periodo = (
            f"{self.periodo_minimo} a {self.periodo_maximo}"
            if self.periodo_minimo or self.periodo_maximo
            else "período não identificado"
        )
        return (
            f"{self.nome_empresa} | {self.cnpj} | {periodo} | "
            f"{self.status} | {self.nome_workspace}"
        )


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


def pasta_padrao_workspaces() -> Path:
    configurada = os.environ.get("ESOCIAL_WORKSPACES_DIR", "").strip()
    if configurada:
        return Path(configurada).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return (base / "XML_eSocial" / "workspaces").resolve()
    return (Path.home() / ".xml_esocial" / "workspaces").resolve()


def _catalogar_workspace(caminho: Path) -> WorkspaceCatalogItem | None:
    db_path = caminho / "processamento.db"
    if not caminho.is_dir() or not db_path.is_file():
        return None
    conn = None
    try:
        conn = sqlite3.connect(
            f"file:{db_path.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=2,
        )
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 2000")
        tabelas = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "meta" not in tabelas:
            return None
        metadados = {
            str(chave): str(valor)
            for chave, valor in conn.execute("SELECT chave,valor FROM meta")
        }
        status_bruto = metadados.get("status", "interrompido").strip().lower()
        status = {
            "concluido": "Concluído",
            "processando": "Em processamento",
            "interrompido": "Interrompido",
        }.get(status_bruto, "Interrompido")

        nome_empresa = "Não identificado"
        cnpj = "Não identificado"
        if "dados_empresa" in tabelas:
            colunas_empresa = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(dados_empresa)")
            }
            if {"nome_empresa", "cnpj_empregador"} <= colunas_empresa:
                row = conn.execute(
                    "SELECT nome_empresa,cnpj_empregador FROM dados_empresa "
                    "WHERE TRIM(COALESCE(nome_empresa,''))<>'' LIMIT 1"
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        "SELECT nome_empresa,cnpj_empregador FROM dados_empresa LIMIT 1"
                    ).fetchone()
                if row:
                    nome_empresa = str(row[0] or "").strip() or nome_empresa
                    cnpj = formatar_cnpj(row[1]) or cnpj

        quantidade_xml = 0
        if metadados.get("total_xml_processados", "").isdigit():
            quantidade_xml = int(metadados["total_xml_processados"])
        elif "contagem_eventos" in tabelas:
            quantidade_xml = int(
                conn.execute(
                    "SELECT COALESCE(SUM(quantidade),0) FROM contagem_eventos"
                ).fetchone()[0]
            )
        elif "eventos" in tabelas:
            quantidade_xml = int(
                conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
            )
        periodo_minimo = metadados.get("periodo_minimo", "")
        periodo_maximo = metadados.get("periodo_maximo", "")
        if (
            not (periodo_minimo or periodo_maximo)
            and "rel_movimentos_cp" in tabelas
        ):
            periodo_minimo, periodo_maximo = conn.execute(
                "SELECT COALESCE(MIN(per_apur),''),COALESCE(MAX(per_apur),'') "
                "FROM rel_movimentos_cp"
            ).fetchone()
        atualizado_em = float(
            metadados.get("atualizado_em", str(db_path.stat().st_mtime)) or 0
        )
        return WorkspaceCatalogItem(
            nome_empresa=nome_empresa,
            cnpj=cnpj,
            nome_workspace=caminho.name,
            caminho=caminho.resolve(),
            db_path=db_path.resolve(),
            status=status,
            tamanho_sqlite=int(db_path.stat().st_size),
            quantidade_xml=quantidade_xml,
            periodo_minimo=str(periodo_minimo or ""),
            periodo_maximo=str(periodo_maximo or ""),
            atualizado_em=atualizado_em,
        )
    except (OSError, ValueError, sqlite3.Error):
        return None
    finally:
        if conn is not None:
            conn.close()


def listar_workspaces_disponiveis(
    pasta_base: str | Path | None = None,
) -> list[WorkspaceCatalogItem]:
    base = (
        Path(pasta_base).expanduser().resolve()
        if pasta_base is not None
        else pasta_padrao_workspaces()
    )
    if not base.is_dir():
        return []
    itens = []
    for caminho in base.iterdir():
        item = _catalogar_workspace(caminho)
        if item is not None:
            itens.append(item)
    return sorted(
        itens,
        key=lambda item: (item.atualizado_em, item.nome_empresa.lower()),
        reverse=True,
    )


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
    versao_engine = ""
    versao_parser = ""
    versao_consistencia = ""
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
            if "meta" in tabelas:
                metadados = {
                    str(chave): str(valor)
                    for chave, valor in conn.execute(
                        "SELECT chave,valor FROM meta WHERE chave IN "
                        "('versao_engine','versao_parser','versao_consistencia_recibo_s1200')"
                    )
                }
                versao_engine = metadados.get("versao_engine", "")
                versao_parser = metadados.get("versao_parser", "")
                versao_consistencia = metadados.get(
                    "versao_consistencia_recibo_s1200", ""
                )
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
        versao_engine=versao_engine,
        versao_parser=versao_parser,
        versao_consistencia=versao_consistencia,
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
