"""Microbenchmark reproduzivel do caminho de XMLs novos do Pacote 8.1."""
from __future__ import annotations

import hashlib
import sqlite3
import time


def executar(quantidade: int = 20_000) -> dict[str, float]:
    hashes = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(quantidade)]

    def medir(com_select: bool) -> float:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE eventos(hash TEXT UNIQUE, arquivo TEXT)")
        inicio = time.perf_counter()
        for indice, digest in enumerate(hashes):
            if com_select:
                conn.execute("SELECT 1 FROM eventos WHERE hash=?", (digest,)).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO eventos(hash,arquivo) VALUES(?,?)",
                (digest, f"{indice}.xml"),
            )
        conn.commit()
        duracao = time.perf_counter() - inicio
        conn.close()
        return duracao

    anterior = medir(True)
    atual = medir(False)
    return {
        "itens": float(quantidade),
        "anterior_segundos": anterior,
        "atual_segundos": atual,
        "ganho_percentual": (anterior - atual) / anterior * 100 if anterior else 0.0,
    }


if __name__ == "__main__":
    resultado = executar()
    for chave, valor in resultado.items():
        print(f"{chave}: {valor:.3f}")
