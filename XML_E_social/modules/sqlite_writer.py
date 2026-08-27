from __future__ import annotations

from dataclasses import dataclass
import ctypes
import os
import sqlite3
import time
from typing import Iterable, Sequence


def memoria_disponivel_bytes() -> int:
    if os.name == "nt":
        try:
            class EstadoMemoria(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            estado = EstadoMemoria()
            estado.dwLength = ctypes.sizeof(EstadoMemoria)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
                return int(estado.ullAvailPhys)
        except Exception:
            pass
    return 0


@dataclass(frozen=True)
class BatchPolicy:
    max_itens: int
    max_bytes: int
    pressao_memoria: bool

    @classmethod
    def atual(cls, perfil: str = "analitico") -> "BatchPolicy":
        disponivel = memoria_disponivel_bytes()
        pressao = bool(disponivel and disponivel < 2 * 1024**3)
        if perfil == "segunda_passagem":
            itens_padrao, bytes_padrao = 250, 32 * 1024**2
            env_itens = "ESOCIAL_MAX_ITENS_LOTE_SEGUNDA_PASSAGEM"
            env_bytes = "ESOCIAL_MAX_BYTES_LOTE_SEGUNDA_PASSAGEM"
        else:
            itens_padrao, bytes_padrao = 10_000, 48 * 1024**2
            env_itens = "ESOCIAL_MAX_ITENS_LOTE_SQLITE"
            env_bytes = "ESOCIAL_MAX_BYTES_LOTE_SQLITE"
        if pressao:
            itens_padrao = max(50, itens_padrao // 4)
            bytes_padrao = max(4 * 1024**2, bytes_padrao // 4)
        return cls(
            max_itens=max(1, int(os.environ.get(env_itens, itens_padrao))),
            max_bytes=max(1, int(os.environ.get(env_bytes, bytes_padrao))),
            pressao_memoria=pressao,
        )


class SQLiteWriter:
    """Ponto único para lotes novos da V10 e commits curtos."""

    def __init__(self, conn: sqlite3.Connection, policy: BatchPolicy | None = None):
        self.conn = conn
        self.policy = policy or BatchPolicy.atual()
        self.commits = 0
        self.linhas = 0
        self.inicio = time.perf_counter()

    def executemany(self, sql: str, linhas: Sequence[tuple] | Iterable[tuple]) -> int:
        materializadas = linhas if isinstance(linhas, Sequence) else list(linhas)
        if not materializadas:
            return 0
        self.conn.executemany(sql, materializadas)
        quantidade = len(materializadas)
        self.linhas += quantidade
        return quantidade

    def commit(self) -> None:
        self.conn.commit()
        self.commits += 1

    def registrar_telemetria(self) -> None:
        agora = time.time()
        valores = {
            "sqlite_writer_commits": self.commits,
            "sqlite_writer_linhas": self.linhas,
            "sqlite_writer_lote_max_itens": self.policy.max_itens,
            "sqlite_writer_lote_max_bytes": self.policy.max_bytes,
            "sqlite_writer_pressao_memoria": int(self.policy.pressao_memoria),
        }
        for chave, valor in valores.items():
            self.conn.execute(
                "INSERT INTO telemetria(chave,valor,unidade,atualizado_em) VALUES(?,?,?,?) "
                "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor,atualizado_em=excluded.atualizado_em",
                (chave, str(valor), "quantidade", agora),
            )

