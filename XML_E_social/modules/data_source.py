from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


TABELAS_WORKSPACE_OBRIGATORIAS = {
    "meta",
    "dados_empresa",
    "rel_movimentos_cp",
}
CAMPOS_LEVANTAMENTO_OBRIGATORIOS = {
    "cod_rubr",
    "ide_tab_rubr",
    "dsc_rubr",
    "nat_rubr",
    "cod_inc_cp",
    "status_cp",
    "carater_verba",
    "tipo_verba",
    "per_apur",
    "cpf",
    "vr_rubr",
}


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_path: Path
    db_path: Path
    status: str
    origem: str

    @classmethod
    def from_path(
        cls,
        caminho: str | Path,
        *,
        origem: str = "manual",
        exigir_concluido: bool = True,
    ) -> "WorkspaceContext":
        informado = Path(str(caminho).strip().strip('"').strip("'")).expanduser().resolve()
        db_path = (
            informado
            if informado.is_file() or informado.suffix.lower() == ".db"
            else informado / "processamento.db"
        )
        if not db_path.is_file():
            raise FileNotFoundError(
                f"processamento.db não localizado em: {informado}"
            )
        conn = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=30
        )
        try:
            tabelas = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            ausentes = sorted(TABELAS_WORKSPACE_OBRIGATORIAS - tabelas)
            if ausentes:
                raise ValueError(
                    "Workspace incompatível. Tabelas ausentes: " + ", ".join(ausentes)
                )
            colunas = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(rel_movimentos_cp)")
            }
            campos_ausentes = sorted(CAMPOS_LEVANTAMENTO_OBRIGATORIOS - colunas)
            if campos_ausentes:
                raise ValueError(
                    "Workspace incompatível com o Levantamento. Campos ausentes: "
                    + ", ".join(campos_ausentes)
                )
            row = conn.execute(
                "SELECT valor FROM meta WHERE chave='status'"
            ).fetchone()
            status = str(row[0] if row else "interrompido").strip().lower()
        finally:
            conn.close()
        if exigir_concluido and status != "concluido":
            raise ValueError(
                f"O Workspace não está concluído (status: {status or 'desconhecido'})."
            )
        return cls(
            workspace_path=db_path.parent,
            db_path=db_path,
            status=status,
            origem=origem,
        )

    @classmethod
    def from_resultado(
        cls, resultado: Mapping[str, object]
    ) -> "WorkspaceContext":
        db_path = resultado.get("db_path")
        workspace = resultado.get("workspace_temporario")
        caminho = db_path or workspace
        if not caminho:
            raise ValueError("A sessão atual não possui Workspace associado.")
        return cls.from_path(caminho, origem="sessao")


class SQLiteDataSource:
    """Fonte compartilhada baseada no SQLite persistente do Workspace."""

    def __init__(self, contexto: WorkspaceContext):
        self.contexto = contexto

    def conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            f"file:{self.contexto.db_path.as_posix()}?mode=ro",
            uri=True,
            timeout=120,
        )
        conn.execute("PRAGMA busy_timeout = 120000")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -131072")
        return conn

    @property
    def db_path(self) -> Path:
        return self.contexto.db_path

    @property
    def workspace_path(self) -> Path:
        return self.contexto.workspace_path
