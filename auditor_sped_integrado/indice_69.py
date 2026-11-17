"""Índice temporário em disco para a conciliação do Tema 69."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory


class Indice69:
    def __init__(self) -> None:
        self._diretorio = TemporaryDirectory(prefix="auditor_sped_69_")
        self._conexao = sqlite3.connect(str(Path(self._diretorio.name) / "indice.db"))
        self._conexao.execute("""CREATE TABLE itens (
            periodo TEXT, cnpj TEXT, chave TEXT, item TEXT,
            valor TEXT, aba TEXT, linha INTEGER
        )""")
        self._conexao.execute("""CREATE TABLE c190 (
            periodo TEXT, cnpj TEXT, chave TEXT, cfop TEXT,
            assinatura TEXT UNIQUE, valor TEXT, aba TEXT, linha INTEGER
        )""")
        self._conexao.execute("""CREATE TABLE c190_duplicados (
            periodo TEXT, cnpj TEXT, chave TEXT, cfop TEXT,
            PRIMARY KEY (periodo, cnpj, chave, cfop)
        )""")
        self._pendentes: list[tuple] = []

    def adicionar_item(self, identidade: tuple[str, str, str, str], valor: Decimal,
                       aba: str, linha: int) -> None:
        self._pendentes.append((*identidade, str(valor), aba, linha))
        if len(self._pendentes) >= 5000:
            self._gravar_itens()

    def _gravar_itens(self) -> None:
        if self._pendentes:
            self._conexao.executemany("INSERT INTO itens VALUES (?,?,?,?,?,?,?)", self._pendentes)
            self._pendentes.clear()

    def preparar_busca_itens(self) -> None:
        self._gravar_itens()
        self._conexao.execute("CREATE INDEX itens_por_identidade ON itens (periodo, cnpj, chave, item)")

    def itens(self, identidade: tuple[str, str, str, str]) -> list[tuple[Decimal, str, int]]:
        return [
            (Decimal(valor), aba, linha)
            for valor, aba, linha in self._conexao.execute(
                "SELECT valor, aba, linha FROM itens WHERE periodo=? AND cnpj=? AND chave=? AND item=?",
                identidade,
            )
        ]

    def adicionar_c190(self, grupo: tuple[str, str, str, str], assinatura: tuple,
                       valor: Decimal, aba: str, linha: int) -> None:
        # A assinatura representa a mesma combinação de campos já usada pelo módulo.
        chave_assinatura = repr(assinatura)
        cursor = self._conexao.execute(
            "INSERT OR IGNORE INTO c190 VALUES (?,?,?,?,?,?,?,?)",
            (*grupo, chave_assinatura, str(valor), aba, linha),
        )
        if cursor.rowcount == 0:
            self._conexao.execute(
                "INSERT OR IGNORE INTO c190_duplicados VALUES (?,?,?,?)", grupo,
            )

    def preparar_busca_c190(self) -> None:
        self._conexao.execute("CREATE INDEX c190_por_grupo ON c190 (periodo, cnpj, chave, cfop)")

    def grupo_c190(self, grupo: tuple[str, str, str, str]) -> dict | None:
        linhas = self._conexao.execute(
            "SELECT valor, aba, linha FROM c190 WHERE periodo=? AND cnpj=? AND chave=? AND cfop=? ORDER BY rowid",
            grupo,
        ).fetchall()
        if not linhas:
            return None
        duplicado = self._conexao.execute(
            "SELECT 1 FROM c190_duplicados WHERE periodo=? AND cnpj=? AND chave=? AND cfop=?",
            grupo,
        ).fetchone() is not None
        return {
            "icms": sum((Decimal(valor) for valor, _, _ in linhas), Decimal(0)),
            "aba": linhas[0][1], "linha": linhas[0][2], "duplicado": duplicado,
        }

    def fechar(self) -> None:
        self._conexao.close()
        self._diretorio.cleanup()

    def __enter__(self) -> "Indice69":
        return self

    def __exit__(self, *_exc) -> None:
        self.fechar()
