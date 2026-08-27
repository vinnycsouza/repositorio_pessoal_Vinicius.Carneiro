from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import os
import platform
import sqlite3
import sys
import time

from modules.v10_core import ENGINE_VERSION, PARSER_VERSION, SCHEMA_SQLITE_VERSION


def memoria_processo_bytes() -> tuple[int, int]:
    """Retorna RSS atual e pico quando o sistema oferece a informacao."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(pmc)
            ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb
            )
            return int(pmc.WorkingSetSize), int(pmc.PeakWorkingSetSize)
        except Exception:
            pass
    return 0, 0


@dataclass
class TelemetriaCarga:
    """Acumulador local: nenhuma gravacao SQLite e feita por XML."""

    inicio_parede: float = field(default_factory=time.perf_counter)
    inicio_cpu: float = field(default_factory=time.process_time)
    contadores: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    tempos: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    tipos: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(float)))

    def somar(self, chave: str, valor: int = 1) -> None:
        self.contadores[chave] += int(valor)

    def tempo(self, chave: str, segundos: float) -> None:
        self.tempos[chave] += max(0.0, float(segundos))

    def evento(self, tipo: str, tamanho: int, segundos: float) -> None:
        item = self.tipos[tipo or "DESCONHECIDO"]
        item["quantidade"] += 1
        item["bytes"] += max(0, int(tamanho))
        item["segundos"] += max(0.0, float(segundos))

    def persistir(self, conn: sqlite3.Connection, db_path: str = "") -> None:
        parede = max(time.perf_counter() - self.inicio_parede, 0.0)
        cpu = max(time.process_time() - self.inicio_cpu, 0.0)
        atual, pico = memoria_processo_bytes()
        metricas: dict[str, tuple[object, str]] = {
            "tempo_parede_segundos": (parede, "s"),
            "tempo_cpu_segundos": (cpu, "s"),
            "espera_aproximada_segundos": (max(parede - cpu, 0.0), "s"),
            "memoria_atual_bytes": (atual, "bytes"),
            "memoria_pico_bytes": (pico, "bytes"),
            "versao_engine": (ENGINE_VERSION, "texto"),
            "versao_python": (platform.python_version(), "texto"),
            "plataforma": (sys.platform, "texto"),
            "versao_schema_sqlite": (SCHEMA_SQLITE_VERSION, "numero"),
            "parser": ("ElementTree+EventSniffer+" + PARSER_VERSION, "texto"),
        }
        for chave, valor in self.contadores.items():
            metricas[chave] = (valor, "quantidade")
        for chave, valor in self.tempos.items():
            metricas[f"tempo_{chave}_segundos"] = (valor, "s")
        if db_path:
            for sufixo, chave in (("", "sqlite_bytes"), ("-wal", "wal_bytes"), ("-shm", "shm_bytes")):
                caminho = db_path + sufixo
                metricas[chave] = (os.path.getsize(caminho) if os.path.exists(caminho) else 0, "bytes")
        for chave, (valor, unidade) in metricas.items():
            conn.execute(
                "INSERT INTO telemetria(chave,valor,unidade,atualizado_em) VALUES(?,?,?,?) "
                "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor,unidade=excluded.unidade,atualizado_em=excluded.atualizado_em",
                (chave, str(valor), unidade, time.time()),
            )
        for tipo, item in self.tipos.items():
            quantidade = int(item["quantidade"])
            segundos = float(item["segundos"])
            conn.execute(
                "INSERT INTO telemetria_eventos(tipo,quantidade,bytes,tempo_segundos,media_ms) VALUES(?,?,?,?,?) "
                "ON CONFLICT(tipo) DO UPDATE SET quantidade=excluded.quantidade,bytes=excluded.bytes,tempo_segundos=excluded.tempo_segundos,media_ms=excluded.media_ms",
                (tipo, quantidade, int(item["bytes"]), segundos, segundos * 1000 / max(quantidade, 1)),
            )
