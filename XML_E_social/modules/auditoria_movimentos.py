from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import pickle
import sqlite3
import time
import xml.etree.ElementTree as ET
import zlib

from modules.parser_xml import parse_s1200_v10


@dataclass(frozen=True)
class ResumoAuditoriaMovimentos:
    eventos_s1200: int
    eventos_com_repeticao: int
    grupos_legitimos_no_xml: int
    grupos_tecnicos_confirmados: int
    linhas_excedentes_confirmadas: int
    impacto_excedente: float
    eventos_logicamente_duplicados: int


COLUNAS_ASSINATURA = (
    "cpf", "matricula", "per_apur", "cod_categ", "tp_insc_estab",
    "nr_insc_estab", "cod_lotacao", "cod_rubr", "ide_tab_rubr", "vr_rubr",
)


def _emitir(cb, valor: float, mensagem: str) -> None:
    if cb:
        cb(max(0.0, min(1.0, valor)), mensagem)


def _normalizar_valor(valor: object) -> str:
    try:
        return f"{float(valor):.10f}".rstrip("0").rstrip(".") or "0"
    except (TypeError, ValueError):
        return str(valor or "")


def _assinatura_valores(valores) -> tuple[str, ...]:
    saida = [str(valor or "") for valor in valores]
    saida[-1] = _normalizar_valor(saida[-1])
    return tuple(saida)


def _assinatura_item(item: object) -> tuple[str, ...]:
    return _assinatura_valores(getattr(item, coluna, "") for coluna in COLUNAS_ASSINATURA)


def _criar_estrutura(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS auditoria_movimentos (
      id INTEGER PRIMARY KEY,
      executada_em REAL NOT NULL,
      evento_id INTEGER NOT NULL,
      arquivo TEXT,
      cpf TEXT, matricula TEXT, per_apur TEXT, cod_categ TEXT,
      tp_insc_estab TEXT, nr_insc_estab TEXT, cod_lotacao TEXT,
      cod_rubr TEXT, ide_tab_rubr TEXT, vr_rubr REAL,
      qtd_sqlite INTEGER NOT NULL, qtd_xml INTEGER NOT NULL,
      linhas_excedentes INTEGER NOT NULL,
      impacto_excedente REAL NOT NULL,
      classificacao TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_aud_mov_evento
      ON auditoria_movimentos(evento_id, classificacao);
    CREATE TABLE IF NOT EXISTS auditoria_correcoes_movimentos (
      id INTEGER PRIMARY KEY,
      executada_em REAL NOT NULL,
      evento_id INTEGER NOT NULL,
      payload_anterior BLOB NOT NULL,
      qtd_anterior INTEGER NOT NULL,
      qtd_corrigida INTEGER NOT NULL,
      UNIQUE(evento_id)
    );
    """)
    conn.commit()


def auditar_movimentos_workspace(
    db_path: str | Path,
    progress_callback=None,
) -> ResumoAuditoriaMovimentos:
    """Compara repetições do SQLite com os itens do XML já armazenado no Workspace."""
    conn = sqlite3.connect(str(Path(db_path)), timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.execute("PRAGMA temp_store=FILE")
    try:
        colunas = {r[1] for r in conn.execute("PRAGMA table_info(dados_remuneracoes)")}
        if "evento_id_origem" not in colunas:
            raise RuntimeError(
                "Este Workspace ainda não possui a identificação do evento de origem. "
                "Use primeiro a atualização de integridade do Workspace."
            )
        _criar_estrutura(conn)
        conn.execute("DELETE FROM auditoria_movimentos")
        conn.commit()
        total_eventos = int(conn.execute(
            "SELECT COUNT(*) FROM eventos WHERE tipo='S-1200' AND ativo=1"
        ).fetchone()[0])
        duplicados_logicos = int(conn.execute(
            "SELECT COUNT(*) FROM eventos WHERE tipo='S-1200' AND duplicado_logico_de IS NOT NULL"
        ).fetchone()[0])
        _emitir(progress_callback, 0.02, "Localizando repetições por evento no SQLite...")
        colunas_sql = ",".join(f"COALESCE(r.{c},'')" for c in COLUNAS_ASSINATURA[:-1])
        inicio_busca = time.monotonic()
        ultimo_aviso = [inicio_busca]
        def progresso_sql() -> int:
            agora_sql = time.monotonic()
            if agora_sql - ultimo_aviso[0] >= 5:
                ultimo_aviso[0] = agora_sql
                _emitir(
                    progress_callback, 0.03,
                    "SQLite está varrendo os movimentos em lotes no disco "
                    f"({int(agora_sql - inicio_busca)}s).",
                )
            return 0
        conn.set_progress_handler(progresso_sql, 250_000)
        candidatos = conn.execute(f"""
            SELECT r.evento_id_origem,e.arquivo,{colunas_sql},r.vr_rubr,COUNT(*)
            FROM dados_remuneracoes r
            JOIN eventos e ON e.id=r.evento_id_origem
            WHERE e.tipo='S-1200' AND e.ativo=1 AND e.duplicado_logico_de IS NULL
            GROUP BY r.evento_id_origem,{colunas_sql},r.vr_rubr
            HAVING COUNT(*)>1
            ORDER BY r.evento_id_origem
        """).fetchall()
        conn.set_progress_handler(None, 0)
        por_evento: dict[int, list[tuple]] = {}
        arquivos: dict[int, str] = {}
        for row in candidatos:
            evento_id = int(row[0])
            arquivos[evento_id] = str(row[1] or "")
            por_evento.setdefault(evento_id, []).append(row[2:])

        agora = time.time()
        confirmados = legitimos = excedentes = 0
        impacto = 0.0
        ids = list(por_evento)
        for indice, evento_id in enumerate(ids, 1):
            blob = conn.execute(
                "SELECT xml_zlib FROM eventos WHERE id=?", (evento_id,)
            ).fetchone()[0]
            itens_xml = parse_s1200_v10(
                ET.fromstring(zlib.decompress(blob)), {}, arquivos[evento_id]
            )
            contagem_xml = Counter(_assinatura_item(item) for item in itens_xml)
            registros = []
            for grupo in por_evento[evento_id]:
                valores, qtd_sqlite = grupo[:-1], int(grupo[-1])
                assinatura = _assinatura_valores(valores)
                qtd_xml = int(contagem_xml.get(assinatura, 0))
                excesso = max(qtd_sqlite - qtd_xml, 0)
                if excesso:
                    classificacao = "DUPLICIDADE_TECNICA_CONFIRMADA"
                    confirmados += 1
                    excedentes += excesso
                    impacto_grupo = excesso * float(valores[-1] or 0)
                    impacto += impacto_grupo
                elif qtd_xml == qtd_sqlite:
                    classificacao = "REPETICAO_EXISTE_NO_XML"
                    legitimos += 1
                    impacto_grupo = 0.0
                else:
                    classificacao = "DIVERGENCIA_XML_SQLITE_REVISAR"
                    impacto_grupo = 0.0
                registros.append((
                    agora, evento_id, arquivos[evento_id], *valores,
                    qtd_sqlite, qtd_xml, excesso, impacto_grupo, classificacao,
                ))
            conn.executemany("""
                INSERT INTO auditoria_movimentos(
                  executada_em,evento_id,arquivo,cpf,matricula,per_apur,cod_categ,
                  tp_insc_estab,nr_insc_estab,cod_lotacao,cod_rubr,ide_tab_rubr,
                  vr_rubr,qtd_sqlite,qtd_xml,linhas_excedentes,impacto_excedente,classificacao
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, registros)
            if indice % 100 == 0:
                conn.commit()
            _emitir(
                progress_callback, 0.05 + 0.94 * indice / max(len(ids), 1),
                f"Conferindo XML armazenado: {indice:,} de {len(ids):,} eventos suspeitos".replace(",", "."),
            )
        conn.execute(
            "INSERT INTO meta(chave,valor) VALUES('auditoria_movimentos_executada_em',?) "
            "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (str(agora),)
        )
        conn.commit()
        _emitir(progress_callback, 1.0, "Auditoria dos movimentos concluída.")
        return ResumoAuditoriaMovimentos(
            eventos_s1200=total_eventos,
            eventos_com_repeticao=len(ids),
            grupos_legitimos_no_xml=legitimos,
            grupos_tecnicos_confirmados=confirmados,
            linhas_excedentes_confirmadas=excedentes,
            impacto_excedente=impacto,
            eventos_logicamente_duplicados=duplicados_logicos,
        )
    finally:
        conn.close()


def listar_auditoria_movimentos(db_path: str | Path, limite: int = 500) -> list[dict]:
    conn = sqlite3.connect(str(Path(db_path)), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        existe = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='auditoria_movimentos'"
        ).fetchone()
        if not existe:
            return []
        return [dict(row) for row in conn.execute(
            "SELECT * FROM auditoria_movimentos "
            "ORDER BY linhas_excedentes DESC,ABS(impacto_excedente) DESC LIMIT ?",
            (int(limite),),
        )]
    finally:
        conn.close()


def corrigir_duplicidades_tecnicas(
    db_path: str | Path,
    confirmar: bool = False,
    progress_callback=None,
) -> dict:
    """Regrava apenas eventos comprovados e reconstrói projeções a partir dos objetos."""
    if not confirmar:
        raise ValueError("A correção exige confirmação explícita.")
    from modules.processador_zip import _ler_objetos, _montar_indice_rubricas
    from modules.sqlite_relatorio import (
        materializar_tabelas_analiticas,
        reiniciar_materializacao_analitica,
    )

    conn = sqlite3.connect(str(Path(db_path)), timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    try:
        _criar_estrutura(conn)
        ids = [int(r[0]) for r in conn.execute(
            "SELECT DISTINCT evento_id FROM auditoria_movimentos "
            "WHERE classificacao='DUPLICIDADE_TECNICA_CONFIRMADA' "
            "AND evento_id NOT IN (SELECT evento_id FROM auditoria_correcoes_movimentos)"
        )]
        rubricas_map = _montar_indice_rubricas(
            _ler_objetos(conn, "rubricas", somente_eventos_ativos=True)
        )
        for indice, evento_id in enumerate(ids, 1):
            evento = conn.execute(
                "SELECT arquivo,xml_zlib FROM eventos WHERE id=?", (evento_id,)
            ).fetchone()
            anteriores = conn.execute(
                "SELECT payload FROM objetos WHERE categoria='remuneracoes' AND evento_id=? ORDER BY id",
                (evento_id,),
            ).fetchall()
            if not anteriores:
                raise RuntimeError(f"Evento {evento_id} sem objeto de remuneração preservado.")
            backup_payloads = sqlite3.Binary(zlib.compress(pickle.dumps(
                [bytes(row[0]) for row in anteriores], protocol=5
            )))
            qtd_anterior = int(conn.execute(
                "SELECT COUNT(*) FROM dados_remuneracoes WHERE evento_id_origem=?",
                (evento_id,),
            ).fetchone()[0])
            itens = parse_s1200_v10(
                ET.fromstring(zlib.decompress(evento[1])), rubricas_map, evento[0]
            )
            novo_payload = sqlite3.Binary(
                zlib.compress(pickle.dumps(itens, protocol=5), level=3)
            )
            with conn:
                conn.execute(
                    "INSERT INTO auditoria_correcoes_movimentos(executada_em,evento_id,payload_anterior,qtd_anterior,qtd_corrigida) "
                    "VALUES(?,?,?,?,?)",
                    (time.time(), evento_id, backup_payloads, qtd_anterior, len(itens)),
                )
                conn.execute(
                    "DELETE FROM objetos WHERE categoria='remuneracoes' AND evento_id=?", (evento_id,)
                )
                conn.execute(
                    "INSERT INTO objetos(categoria,evento_id,payload) VALUES('remuneracoes',?,?)",
                    (evento_id, novo_payload),
                )
            _emitir(progress_callback, 0.25 * indice / max(len(ids), 1),
                    f"Regravando evento confirmado {indice} de {len(ids)}")
        if ids:
            reiniciar_materializacao_analitica(conn)
            materializar_tabelas_analiticas(conn, progress_callback)
        return {"eventos_corrigidos": len(ids), "reconstrucao_concluida": bool(ids)}
    finally:
        conn.close()
