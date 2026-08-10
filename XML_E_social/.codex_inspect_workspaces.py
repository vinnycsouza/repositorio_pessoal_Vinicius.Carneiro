import os
import sqlite3
from pathlib import Path


base = Path(os.environ["LOCALAPPDATA"]) / "XML_eSocial" / "workspaces"
for workspace in sorted(base.glob("esocial_v3_*"), key=lambda p: p.stat().st_mtime, reverse=True):
    db = workspace / "processamento.db"
    if not db.is_file():
        continue
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
        meta = dict(conn.execute(
            "SELECT chave,valor FROM meta WHERE chave IN ('status','fase','atualizado_em')"
        ))
        fontes = list(conn.execute(
            "SELECT nome,caminho,status,total_membros,ultimo_indice "
            "FROM fontes WHERE nivel=0 ORDER BY id"
        ))
        eventos = int(conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0])
        conn.close()
        print(f"WORKSPACE: {workspace}")
        print(f"STATUS: {meta.get('status','')} | FASE: {meta.get('fase','')} | EVENTOS: {eventos}")
        for nome, caminho, status, total, ultimo in fontes:
            print(f"FONTE: {nome} | CAMINHO: {caminho} | STATUS: {status} | CHECKPOINT: {ultimo}/{total}")
        print()
    except Exception as exc:
        print(f"WORKSPACE: {workspace}\nERRO_LEITURA: {type(exc).__name__}: {exc}\n")
