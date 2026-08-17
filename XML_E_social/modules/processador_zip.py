from __future__ import annotations

import hashlib
import json
import os
import pickle
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile
import zlib
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Tuple, Union
import xml.etree.ElementTree as ET

import pandas as pd

from modules.parser_xml import (
    BaseContribuicao, BaseTrabalhador, RubricaInfo, RubricaPagamento,
    parse_s1010, parse_s1200, parse_s3000, parse_s5001, parse_s5011,
    obter_recibo_principal,
)
from utils.helpers import localname
from modules.sqlite_relatorio import (
    materializar_tabelas_analiticas,
    carregar_pacote_resumido,
    reiniciar_materializacao_analitica,
)
from modules.progresso import emitir_progresso
from modules.event_metadata import inspecionar_evento

Fonte = Tuple[str, Union[bytes, bytearray, memoryview, str, os.PathLike]]
ProgressCallback = Callable[[float, str], None]

EVENTOS_SUPORTADOS = {"S-1000", "S-1005", "S-1010", "S-1020", "S-1200", "S-3000", "S-5001", "S-5011"}
EVENTOS_SEGUNDA_PASSAGEM = {"S-1200", "S-5001", "S-5011"}
CHECKPOINT_INTERVALO = 500
BATCH_SEGUNDA_PASSAGEM = 250
MAX_BYTES_LOTE_SEGUNDA_PASSAGEM = 32 * 1024 * 1024
MAX_NIVEL_ZIP = 8
MAX_XML_INDIVIDUAL = 256 * 1024 * 1024
ARQUIVO_BLOQUEIO_WORKSPACE = ".processamento.lock"


def organizar_fontes_carga_inicial(
    fontes_principais: Iterable[Fonte],
    fontes_historico: Iterable[Fonte] | None = None,
    fontes_recibos: Iterable[Fonte] | None = None,
) -> list[Fonte]:
    """Ordena a carga inicial do periodo mais antigo para o mais recente.

    O historico e opcional. A fonte principal e os recibos conservam o fluxo
    existente quando ele nao e informado.
    """
    return list(fontes_historico or []) + list(fontes_principais) + list(
        fontes_recibos or []
    )


def _progresso(
    callback: ProgressCallback | None,
    etapa: str,
    valor_etapa: float,
    mensagem: str,
    detalhes: str = "",
) -> None:
    emitir_progresso(callback, etapa, valor_etapa, mensagem, detalhes)


def _formatar_bytes(valor: float) -> str:
    unidades = ("B", "KB", "MB", "GB", "TB")
    numero = max(0.0, float(valor))
    for unidade in unidades:
        if numero < 1024 or unidade == unidades[-1]:
            return f"{numero:.1f} {unidade}"
        numero /= 1024
    return f"{numero:.1f} TB"


def _formatar_tempo(segundos: float | None) -> str:
    if segundos is None or segundos < 0:
        return "calculando"
    total = int(segundos)
    horas, resto = divmod(total, 3600)
    minutos, secs = divmod(resto, 60)
    if horas:
        return f"{horas}h {minutos:02d}min"
    if minutos:
        return f"{minutos}min {secs:02d}s"
    return f"{secs}s"


def _resumo_fontes_descobertas(
    conn: sqlite3.Connection,
    fonte_atual: int | None = None,
    fracao_atual: float = 0.0,
    id_carga: int | None = None,
) -> dict[str, int | float]:
    filtro = " WHERE id_carga=?" if id_carga is not None else ""
    params = (id_carga,) if id_carga is not None else ()
    linhas = conn.execute(
        "SELECT id,status,MAX(COALESCE(tamanho_bytes,0),1) FROM fontes" + filtro,
        params,
    ).fetchall()
    resumo: dict[str, int | float] = {
        "descobertas": len(linhas),
        "concluidas": 0,
        "pendentes": 0,
        "processando": 0,
        "erros": 0,
        "faltam": 0,
        "volume_descoberto": 0,
        "volume_concluido": 0,
        "volume_restante": 0,
        "volume_erro": 0,
        "fracao": 0.0,
    }
    fracao_atual = max(0.0, min(1.0, float(fracao_atual)))
    volume_processado = 0.0
    for fonte_id, status, peso in linhas:
        peso = int(peso)
        resumo["volume_descoberto"] += peso
        if status == "concluida":
            resumo["concluidas"] += 1
            resumo["volume_concluido"] += peso
            volume_processado += peso
        elif status == "erro":
            resumo["erros"] += 1
            resumo["volume_erro"] += peso
            # Fonte já tentada não permanece pendente; conserva o avanço da barra.
            volume_processado += peso
        elif status == "processando":
            resumo["processando"] += 1
            resumo["faltam"] += 1
            if fonte_atual is not None and int(fonte_id) == int(fonte_atual):
                volume_processado += peso * fracao_atual
                resumo["volume_restante"] += int(round(peso * (1.0 - fracao_atual)))
            else:
                resumo["volume_restante"] += peso
        else:
            resumo["pendentes"] += 1
            resumo["faltam"] += 1
            resumo["volume_restante"] += peso
    total = int(resumo["volume_descoberto"])
    resumo["fracao"] = volume_processado / max(total, 1)
    return resumo


def _fracao_ingestao_descoberta(
    conn: sqlite3.Connection,
    fonte_atual: int | None = None,
    fracao_atual: float = 0.0,
    id_carga: int | None = None,
) -> float:
    resumo = _resumo_fontes_descobertas(
        conn, fonte_atual, fracao_atual, id_carga,
    )
    return float(resumo["fracao"])


def _texto_resumo_fontes(resumo: dict[str, int | float]) -> str:
    texto = (
        f"fontes descobertas {int(resumo['descobertas']):,} | "
        f"lidas {int(resumo['concluidas']):,} | "
        f"faltam {int(resumo['faltam']):,} "
        f"(pendentes {int(resumo['pendentes']):,}; em leitura {int(resumo['processando']):,}) | "
        f"com erro {int(resumo['erros']):,} | "
        f"volume descoberto {_formatar_bytes(float(resumo['volume_descoberto']))} | "
        f"concluído {_formatar_bytes(float(resumo['volume_concluido']))} | "
        f"restante conhecido {_formatar_bytes(float(resumo['volume_restante']))}"
    )
    return texto.replace(",", ".")


def _base_workspaces() -> Path:
    configurada = os.environ.get("ESOCIAL_WORKSPACES_DIR", "").strip()
    if configurada:
        base = Path(configurada).expanduser()
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "XML_eSocial" / "workspaces"
    else:
        base = Path.home() / ".xml_esocial" / "workspaces"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _nome_seguro(nome: str) -> str:
    return "".join(c if c.isalnum() or c in "._-[]" else "_" for c in str(nome))[-180:] or "arquivo"


def _adquirir_bloqueio_workspace(workspace: Path):
    """Impede duas escritas concorrentes no mesmo Workspace.

    O arquivo permanece vazio/inofensivo; a trava pertence ao processo e e
    liberada automaticamente pelo sistema operacional se o app for encerrado.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    caminho = workspace / ARQUIVO_BLOQUEIO_WORKSPACE
    arquivo = caminho.open("a+b")
    try:
        arquivo.seek(0, os.SEEK_END)
        if arquivo.tell() == 0:
            arquivo.write(b"0")
            arquivo.flush()
        arquivo.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return arquivo
    except OSError as exc:
        arquivo.close()
        raise RuntimeError(
            "Este Workspace já está sendo processado por outra instância do "
            "aplicativo. Feche a execução anterior e tente novamente."
        ) from exc


def _liberar_bloqueio_workspace(arquivo) -> None:
    if arquivo is None or arquivo.closed:
        return
    try:
        arquivo.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(arquivo.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)
    finally:
        arquivo.close()


def _conectar(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # Agrupamentos e indices de empresas grandes podem exceder a RAM. O SQLite
    # usa arquivos temporarios no disco, preservando memoria para parser/Excel.
    conn.execute("PRAGMA temp_store=FILE")
    conn.execute("PRAGMA cache_size=-131072")
    conn.execute("PRAGMA busy_timeout=120000")
    return conn


def _conectar_somente_leitura(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"file:{db_path.resolve().as_posix()}?mode=ro",
        uri=True,
        timeout=5,
    )
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _criar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS meta (
        chave TEXT PRIMARY KEY,
        valor TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS fontes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        caminho TEXT NOT NULL,
        nivel INTEGER NOT NULL DEFAULT 0,
        prefixo TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pendente',
        ultimo_indice INTEGER NOT NULL DEFAULT -1,
        total_membros INTEGER NOT NULL DEFAULT 0,
        tamanho_bytes INTEGER NOT NULL DEFAULT 0,
        UNIQUE(caminho, prefixo)
    );
    CREATE TABLE IF NOT EXISTS eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        arquivo TEXT NOT NULL,
        tipo TEXT NOT NULL,
        tamanho_bytes INTEGER NOT NULL DEFAULT 0,
        envelope_recibo INTEGER NOT NULL DEFAULT 0,
        xml_zlib BLOB,
        processado_segunda INTEGER NOT NULL DEFAULT 0,
        UNIQUE(arquivo)
    );
    CREATE INDEX IF NOT EXISTS idx_eventos_tipo_segunda ON eventos(tipo, processado_segunda, id);
    CREATE TABLE IF NOT EXISTS contagem_eventos (
        tipo TEXT PRIMARY KEY,
        quantidade INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS objetos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        categoria TEXT NOT NULL,
        evento_id INTEGER,
        payload BLOB NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_objetos_categoria ON objetos(categoria);
    CREATE TABLE IF NOT EXISTS erros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        arquivo TEXT NOT NULL,
        erro TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS historico_cargas (
        id_carga INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id TEXT NOT NULL,
        data_inicio REAL NOT NULL,
        data_fim REAL,
        origem TEXT NOT NULL DEFAULT '',
        assinatura_fontes TEXT NOT NULL DEFAULT '',
        quantidade_arquivos_recebidos INTEGER NOT NULL DEFAULT 0,
        quantidade_xml_localizados INTEGER NOT NULL DEFAULT 0,
        quantidade_xml_novos INTEGER NOT NULL DEFAULT 0,
        quantidade_duplicados INTEGER NOT NULL DEFAULT 0,
        quantidade_erros INTEGER NOT NULL DEFAULT 0,
        periodo_minimo_adicionado TEXT NOT NULL DEFAULT '',
        periodo_maximo_adicionado TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'processando',
        mensagem_erro TEXT NOT NULL DEFAULT ''
    );
    """)
    col_eventos = {r[1] for r in conn.execute("PRAGMA table_info(eventos)")}
    if "hash_conteudo" not in col_eventos:
        conn.execute("ALTER TABLE eventos ADD COLUMN hash_conteudo TEXT")
    if "id_carga" not in col_eventos:
        conn.execute("ALTER TABLE eventos ADD COLUMN id_carga INTEGER")
    for coluna, definicao in (
        ("ativo", "INTEGER NOT NULL DEFAULT 1"),
        ("id_evento_esocial", "TEXT NOT NULL DEFAULT ''"),
        ("ind_retif", "TEXT NOT NULL DEFAULT ''"),
        ("recibo_evento", "TEXT NOT NULL DEFAULT ''"),
        ("recibo_referencia", "TEXT NOT NULL DEFAULT ''"),
    ):
        if coluna not in col_eventos:
            conn.execute(f"ALTER TABLE eventos ADD COLUMN {coluna} {definicao}")
    col_fontes = {r[1] for r in conn.execute("PRAGMA table_info(fontes)")}
    if "id_carga" not in col_fontes:
        conn.execute("ALTER TABLE fontes ADD COLUMN id_carga INTEGER")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_eventos_hash_conteudo "
        "ON eventos(hash_conteudo) WHERE hash_conteudo IS NOT NULL AND hash_conteudo<>''"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fontes_carga_status ON fontes(id_carga,status,id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_historico_cargas_status ON historico_cargas(status,id_carga)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eventos_recibo_ativo ON eventos(recibo_evento,ativo,tipo)")
    # Workspaces anteriores só permitem retropreencher eventos cujo XML foi
    # preservado para a segunda passagem.
    for evento_id, xml_zlib, hash_atual, recibo_atual in conn.execute(
        "SELECT id,xml_zlib,hash_conteudo,recibo_evento FROM eventos WHERE xml_zlib IS NOT NULL"
    ):
        try:
            xml_bruto = zlib.decompress(xml_zlib)
            if not hash_atual:
                digest = hashlib.sha256(xml_bruto).hexdigest()
                conn.execute(
                    "UPDATE OR IGNORE eventos SET hash_conteudo=? WHERE id=?",
                    (digest, evento_id),
                )
            if not recibo_atual:
                root = ET.fromstring(xml_bruto)
                id_evt, ind_retif, recibo_evt, recibo_ref = _metadados_retificacao(root)
                conn.execute(
                    "UPDATE eventos SET id_evento_esocial=?,ind_retif=?,recibo_evento=?,"
                    "recibo_referencia=? WHERE id=?",
                    (id_evt, ind_retif, recibo_evt, recibo_ref, evento_id),
                )
        except Exception:
            pass
    conn.commit()


def _meta_get(conn: sqlite3.Connection, chave: str, padrao: str = "") -> str:
    row = conn.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
    return row[0] if row else padrao


def _meta_set(conn: sqlite3.Connection, chave: str, valor: object) -> None:
    conn.execute(
        "INSERT INTO meta(chave, valor) VALUES(?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
        (chave, str(valor)),
    )


def _salvar_objetos(conn: sqlite3.Connection, categoria: str, evento_id: int | None, objetos: object) -> None:
    conn.execute(
        "INSERT INTO objetos(categoria, evento_id, payload) VALUES (?, ?, ?)",
        (categoria, evento_id, sqlite3.Binary(zlib.compress(pickle.dumps(objetos, protocol=5), level=3))),
    )


def _ler_objetos(conn: sqlite3.Connection, categoria: str) -> list:
    saida: list = []
    for (payload,) in conn.execute("SELECT payload FROM objetos WHERE categoria=? ORDER BY id", (categoria,)):
        obj = pickle.loads(zlib.decompress(payload))
        if isinstance(obj, list):
            saida.extend(obj)
        else:
            saida.append(obj)
    return saida


def _eh_retorno_evento_completo(root: ET.Element) -> bool:
    return localname(root.tag) == "retornoEventoCompleto" or any(localname(el.tag) == "recibo" for el in root.iter())


def _montar_indice_rubricas(rubricas: List[RubricaInfo]):
    # Eventos de tabela são sequenciais. Uma exclusão remove a versão de mesma
    # chave/vigência; inclusão/alteração posterior substitui a versão anterior.
    # Assim uma exclusão nunca vira um cadastro vazio elegível para o S-1200.
    versoes: dict[tuple[str, str, str], RubricaInfo] = {}
    for rubrica in rubricas:
        chave_versao = (
            str(rubrica.cod_rubr or "").strip(),
            str(rubrica.ide_tab_rubr or "").strip(),
            str(rubrica.ini_valid or "").strip(),
        )
        if rubrica.origem_bloco == "exclusao":
            versoes.pop(chave_versao, None)
        else:
            versoes[chave_versao] = rubrica

    mapa = {}
    ordenadas = sorted(
        versoes.values(),
        key=lambda r: (0 if r.fonte_dados == "Download principal" else 1, r.ini_valid, r.fim_valid),
    )
    for r in ordenadas:
        cod, tab = str(r.cod_rubr or "").strip(), str(r.ide_tab_rubr or "").strip()
        mapa.setdefault((cod, tab), []).append(r)
        mapa.setdefault((cod, ""), []).append(r)
    return mapa


def _materializar_fontes(
    conn: sqlite3.Connection,
    workspace: Path,
    fontes: Iterable[Fonte],
    id_carga: int | None = None,
) -> None:
    pasta = workspace / "fontes"
    pasta.mkdir(parents=True, exist_ok=True)
    existentes = conn.execute("SELECT COUNT(*) FROM fontes").fetchone()[0]
    if existentes and id_carga is None:
        return

    for indice, (nome, fonte) in enumerate(fontes):
        if isinstance(fonte, (str, os.PathLike)):
            caminho = Path(fonte).expanduser().resolve()
        else:
            marcador = f"carga_{id_carga:06d}_" if id_carga is not None else ""
            caminho = pasta / f"{marcador}{indice:04d}_{_nome_seguro(nome)}"
            with caminho.open("wb") as fp:
                view = memoryview(bytes(fonte))
                bloco = 1024 * 1024
                for ini in range(0, len(view), bloco):
                    fp.write(view[ini:ini + bloco])
        tamanho = caminho.stat().st_size if caminho.exists() else 0
        prefixo = (
            f"[Carga {id_carga}] {nome}" if id_carga is not None else str(nome)
        )
        conn.execute(
            "INSERT INTO fontes(nome, caminho, nivel, prefixo, tamanho_bytes, id_carga) "
            "VALUES (?, ?, 0, ?, ?, ?)",
            (str(nome), str(caminho), prefixo, tamanho, id_carga),
        )
    conn.commit()


def _registrar_contagem(conn: sqlite3.Connection, tipo: str) -> None:
    conn.execute(
        "INSERT INTO contagem_eventos(tipo, quantidade) VALUES(?, 1) "
        "ON CONFLICT(tipo) DO UPDATE SET quantidade=quantidade+1",
        (tipo,),
    )


def _registrar_duracao(
    conn: sqlite3.Connection, chave: str, inicio: float
) -> None:
    """Persiste telemetria local, sem dados dos XML e sem alterar o fluxo."""
    _meta_set(conn, f"tempo_{chave}_segundos", f"{time.perf_counter() - inicio:.3f}")


def _metadados_retificacao(root: ET.Element) -> tuple[str, str, str, str]:
    evento = next(
        (el for el in root.iter() if localname(el.tag).startswith("evt")), None
    )
    id_evento = str(evento.attrib.get("Id", "") if evento is not None else "")
    ide_evento = next(
        (el for el in root.iter() if localname(el.tag) == "ideEvento"), None
    )

    def texto(bloco: ET.Element | None, nome: str) -> str:
        if bloco is None:
            return ""
        return next(
            (str(el.text or "").strip() for el in bloco.iter() if localname(el.tag) == nome),
            "",
        )

    ind_retif = texto(ide_evento, "indRetif")
    recibo_referencia = texto(ide_evento, "nrRecibo") if ind_retif == "2" else ""
    bloco_recibo = next(
        (el for el in root.iter() if localname(el.tag) == "recibo"), None
    )
    recibo_evento = texto(bloco_recibo, "nrRecibo")
    if not recibo_evento and ind_retif != "2":
        recibo_evento = obter_recibo_principal(root)
    return id_evento, ind_retif, recibo_evento, recibo_referencia


def _processar_xml_ingestao(
    conn: sqlite3.Connection,
    arquivo: str,
    xml_bytes: bytes,
    tamanho: int,
    id_carga: int | None = None,
) -> str:
    hash_conteudo = hashlib.sha256(xml_bytes).hexdigest()
    evento_existente = conn.execute(
        "SELECT id,arquivo,tipo,envelope_recibo FROM eventos "
        "WHERE hash_conteudo=? LIMIT 1", (hash_conteudo,)
    ).fetchone()
    if evento_existente:
        if id_carga is not None:
            conn.execute(
                "UPDATE historico_cargas SET quantidade_duplicados=quantidade_duplicados+1,"
                "quantidade_xml_localizados=quantidade_xml_localizados+1 WHERE id_carga=?",
                (id_carga,),
            )
            if evento_existente[2] == "S-1010":
                # Permite aplicar correções de parser em Workspace existente ao
                # reenviar o mesmo recibo, sem duplicar fisicamente o evento.
                try:
                    root_existente = ET.fromstring(xml_bytes)
                    itens = parse_s1010(
                        root_existente,
                        arquivo=str(evento_existente[1]),
                        fonte_dados=(
                            "Recibo S-1010" if evento_existente[3]
                            else "Download principal"
                        ),
                    )
                    conn.execute(
                        "DELETE FROM objetos WHERE categoria='rubricas' AND evento_id=?",
                        (int(evento_existente[0]),),
                    )
                    _salvar_objetos(
                        conn, "rubricas", int(evento_existente[0]), itens
                    )
                    _meta_set(conn, f"carga_{id_carga}_reprocessou_s1010", 1)
                    root_existente.clear()
                except Exception as exc:
                    conn.execute(
                        "INSERT INTO erros(arquivo,erro) VALUES(?,?)",
                        (str(arquivo), f"Falha ao reprocessar S-1010 duplicado: {exc}"),
                    )
        return "duplicado"
    if id_carga is not None:
        conn.execute(
            "UPDATE historico_cargas SET quantidade_xml_localizados=quantidade_xml_localizados+1 "
            "WHERE id_carga=?", (id_carga,),
        )
    if tamanho > MAX_XML_INDIVIDUAL:
        conn.execute("INSERT INTO erros(arquivo, erro) VALUES (?, ?)", (arquivo, "XML acima do limite individual de segurança"))
        conn.execute(
            "INSERT OR IGNORE INTO eventos(arquivo, tipo, tamanho_bytes, hash_conteudo, id_carga) "
            "VALUES (?, 'XML_INVALIDO', ?, ?, ?)",
            (arquivo, tamanho, hash_conteudo, id_carga),
        )
        if id_carga is not None:
            conn.execute("UPDATE historico_cargas SET quantidade_erros=quantidade_erros+1 WHERE id_carga=?", (id_carga,))
        return "erro"
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        conn.execute("INSERT INTO erros(arquivo, erro) VALUES (?, ?)", (arquivo, f"XML inválido ou ilegível: {exc}"))
        conn.execute(
            "INSERT OR IGNORE INTO eventos(arquivo, tipo, tamanho_bytes, hash_conteudo, id_carga) "
            "VALUES (?, 'XML_INVALIDO', ?, ?, ?)",
            (arquivo, tamanho, hash_conteudo, id_carga),
        )
        if id_carga is not None:
            conn.execute("UPDATE historico_cargas SET quantidade_erros=quantidade_erros+1 WHERE id_carga=?", (id_carga,))
        return "erro"

    metadados = inspecionar_evento(root)
    tipo = metadados.tipo
    recibo = metadados.envelope_recibo
    id_evento = metadados.id_evento_esocial
    ind_retif = metadados.ind_retif
    recibo_evento = metadados.recibo_evento
    recibo_referencia = metadados.recibo_referencia
    blob = None
    if tipo in EVENTOS_SEGUNDA_PASSAGEM or tipo == "S-1010":
        blob = sqlite3.Binary(zlib.compress(xml_bytes, level=1))
    cur = conn.execute(
        "INSERT OR IGNORE INTO eventos(arquivo, tipo, tamanho_bytes, envelope_recibo, xml_zlib, hash_conteudo, id_carga,"
        "id_evento_esocial,ind_retif,recibo_evento,recibo_referencia) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (arquivo, tipo, tamanho, int(recibo), blob, hash_conteudo, id_carga,
         id_evento, ind_retif, recibo_evento, recibo_referencia),
    )
    if cur.rowcount == 0:
        if id_carga is not None:
            conn.execute(
                "UPDATE historico_cargas SET quantidade_duplicados=quantidade_duplicados+1 WHERE id_carga=?",
                (id_carga,),
            )
        root.clear()
        return "duplicado"
    evento_id = int(cur.lastrowid)
    if ind_retif == "2" and recibo_referencia:
        substituidos = [
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM eventos WHERE id<>? AND tipo=? AND ativo=1 AND recibo_evento=?",
                (evento_id, tipo, recibo_referencia),
            )
        ]
        if substituidos:
            marcas = ",".join("?" for _ in substituidos)
            conn.execute(
                f"UPDATE eventos SET ativo=0 WHERE id IN ({marcas})", substituidos
            )
            conn.execute(
                f"DELETE FROM objetos WHERE evento_id IN ({marcas})", substituidos
            )
    _registrar_contagem(conn, tipo)
    if id_carga is not None:
        periodo = metadados.periodo
        conn.execute(
            "UPDATE historico_cargas SET quantidade_xml_novos=quantidade_xml_novos+1,"
            "periodo_minimo_adicionado=CASE WHEN ?<>'' AND (periodo_minimo_adicionado='' OR ?<periodo_minimo_adicionado) THEN ? ELSE periodo_minimo_adicionado END,"
            "periodo_maximo_adicionado=CASE WHEN ?<>'' AND (periodo_maximo_adicionado='' OR ?>periodo_maximo_adicionado) THEN ? ELSE periodo_maximo_adicionado END "
            "WHERE id_carga=?",
            (periodo, periodo, periodo, periodo, periodo, periodo, id_carga),
        )

    if tipo in EVENTOS_SUPORTADOS:
        empresa = {
            "arquivo_origem": arquivo,
            "tp_insc_empregador": metadados.tp_insc_empregador,
            "cnpj_empregador": metadados.cnpj_empregador,
            "nome_empresa": metadados.nome_empresa,
        }
        _salvar_objetos(conn, "empresa", evento_id, empresa)

    if tipo == "S-1010":
        itens = parse_s1010(
            root,
            arquivo=arquivo,
            fonte_dados="Recibo S-1010" if recibo else "Download principal",
        )
        _salvar_objetos(conn, "rubricas", evento_id, itens)
    elif tipo == "S-3000":
        item = parse_s3000(root)
        item["arquivo_origem"] = arquivo
        _salvar_objetos(conn, "exclusoes", evento_id, item)
    root.clear()
    return tipo


def _adicionar_zip_aninhado(
    conn: sqlite3.Connection,
    workspace: Path,
    fonte_id: int,
    indice: int,
    prefixo: str,
    nome_membro: str,
    origem_stream,
    tamanho: int,
    nivel: int,
    id_carga: int | None = None,
) -> None:
    if nivel > MAX_NIVEL_ZIP:
        return
    pasta = workspace / "fontes_aninhadas"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{fonte_id:06d}_{indice:09d}_{_nome_seguro(Path(nome_membro).name)}"
    if not destino.exists():
        with destino.open("wb") as fp:
            shutil.copyfileobj(origem_stream, fp, length=1024 * 1024)
    caminho_logico = f"{prefixo}::{nome_membro}"
    conn.execute(
        "INSERT OR IGNORE INTO fontes(nome, caminho, nivel, prefixo, tamanho_bytes, id_carga) VALUES (?, ?, ?, ?, ?, ?)",
        (nome_membro, str(destino), nivel, caminho_logico, int(tamanho), id_carga),
    )


def _ingerir_fontes(
    conn: sqlite3.Connection,
    workspace: Path,
    progress_callback: ProgressCallback | None,
    id_carga: int | None = None,
) -> None:
    inicio_ingestao = time.perf_counter()
    xml_inicio = int(conn.execute(
        "SELECT COALESCE(SUM(quantidade),0) FROM contagem_eventos"
    ).fetchone()[0])
    _progresso(
        progress_callback, "ingestao",
        _fracao_ingestao_descoberta(conn, id_carga=id_carga),
        "Preparando a ingestão das fontes no SQLite...",
        "Inventariando as fontes e retomando os checkpoints disponíveis. "
        + _texto_resumo_fontes(_resumo_fontes_descobertas(conn, id_carga=id_carga)),
    )
    while True:
        filtro_carga = " AND id_carga=?" if id_carga is not None else ""
        params = (id_carga,) if id_carga is not None else ()
        fonte = conn.execute(
            "SELECT id, nome, caminho, nivel, prefixo, ultimo_indice FROM fontes "
            "WHERE status IN ('pendente','processando')" + filtro_carga + " ORDER BY id LIMIT 1",
            params,
        ).fetchone()
        if not fonte:
            break
        fonte_id, nome, caminho_txt, nivel, prefixo, ultimo_indice = fonte
        caminho = Path(caminho_txt)
        if not caminho.exists():
            conn.execute("UPDATE fontes SET status='erro' WHERE id=?", (fonte_id,))
            conn.execute("INSERT INTO erros(arquivo, erro) VALUES (?, ?)", (str(prefixo), "Fonte não localizada para retomada"))
            conn.commit()
            continue

        if caminho.suffix.lower() == ".xml":
            if ultimo_indice < 0:
                _processar_xml_ingestao(conn, str(prefixo), caminho.read_bytes(), caminho.stat().st_size, id_carga)
                conn.execute("UPDATE fontes SET ultimo_indice=0, total_membros=1, status='concluida' WHERE id=?", (fonte_id,))
                conn.commit()
                fracao = _fracao_ingestao_descoberta(conn, id_carga=id_carga)
                resumo_fontes = _resumo_fontes_descobertas(conn, id_carga=id_carga)
                total_eventos = int(conn.execute(
                    "SELECT COALESCE(SUM(quantidade),0) FROM contagem_eventos"
                ).fetchone()[0])
                _progresso(
                    progress_callback, "ingestao", fracao,
                    f"XML individual catalogado: {nome}",
                    (
                        f"{total_eventos:,} XMLs catalogados até agora | "
                        f"{_texto_resumo_fontes(resumo_fontes)}"
                    ).replace(",", "."),
                )
            continue

        try:
            with zipfile.ZipFile(caminho, "r") as zf:
                infos = zf.infolist()
                total = len(infos)
                conn.execute("UPDATE fontes SET total_membros=?, status='processando' WHERE id=?", (total, fonte_id))
                conn.commit()
                inicio = max(int(ultimo_indice) + 1, 0)
                total_bytes = sum(max(0, int(info.file_size)) for info in infos)
                bytes_concluidos = sum(max(0, int(info.file_size)) for info in infos[:inicio])
                bytes_inicio = bytes_concluidos
                inicio_fonte = time.perf_counter()
                ultima_atualizacao_visual = 0.0
                for indice in range(inicio, total):
                    info = infos[indice]
                    if not info.is_dir():
                        ext = Path(info.filename).suffix.lower()
                        if ext in {".xml", ".zip"}:
                            caminho_logico = f"{prefixo}::{info.filename}"
                            try:
                                if ext == ".xml":
                                    with zf.open(info, "r") as fp:
                                        conteudo = fp.read(MAX_XML_INDIVIDUAL + 1)
                                    _processar_xml_ingestao(conn, caminho_logico, conteudo, info.file_size, id_carga)
                                else:
                                    with zf.open(info, "r") as fp:
                                        _adicionar_zip_aninhado(
                                            conn, workspace, fonte_id, indice, prefixo,
                                            info.filename, fp, info.file_size, int(nivel) + 1, id_carga,
                                        )
                            except Exception as exc:
                                conn.execute("INSERT INTO erros(arquivo, erro) VALUES (?, ?)", (caminho_logico, str(exc)))
                    bytes_concluidos += max(0, int(info.file_size))
                    agora_visual = time.perf_counter()
                    checkpoint = indice % CHECKPOINT_INTERVALO == 0 or indice == total - 1
                    if checkpoint:
                        conn.execute("UPDATE fontes SET ultimo_indice=? WHERE id=?", (indice, fonte_id))
                        _meta_set(conn, "fase", "ingestao")
                        _meta_set(conn, "atualizado_em", time.time())
                        conn.commit()
                    if checkpoint or agora_visual - ultima_atualizacao_visual >= 1.0:
                        ultima_atualizacao_visual = agora_visual
                        total_eventos = conn.execute("SELECT COALESCE(SUM(quantidade),0) FROM contagem_eventos").fetchone()[0]
                        fracao_fonte = (indice + 1) / max(total, 1)
                        resumo_fontes = _resumo_fontes_descobertas(
                            conn, fonte_id, fracao_fonte, id_carga,
                        )
                        fracao_ingestao = float(resumo_fontes["fracao"])
                        decorrido_fonte = max(agora_visual - inicio_fonte, 0.001)
                        decorrido_total = max(agora_visual - inicio_ingestao, 0.001)
                        itens_feitos = indice + 1 - inicio
                        bytes_feitos = max(0, bytes_concluidos - bytes_inicio)
                        velocidade_itens = itens_feitos / decorrido_fonte
                        velocidade_bytes = bytes_feitos / decorrido_fonte
                        restantes = max(total - indice - 1, 0)
                        eta = restantes / velocidade_itens if velocidade_itens > 0 else None
                        detalhes = (
                            f"Fonte: {Path(str(nome)).name} | "
                            f"itens {indice + 1:,}/{total:,} | "
                            f"{_formatar_bytes(bytes_concluidos)}/{_formatar_bytes(total_bytes)} | "
                            f"{int(total_eventos):,} XMLs catalogados | "
                            f"{velocidade_itens:,.1f} itens/s | {_formatar_bytes(velocidade_bytes)}/s | "
                            f"decorrido {_formatar_tempo(decorrido_total)} | ETA da fonte {_formatar_tempo(eta)} | "
                            f"{_texto_resumo_fontes(resumo_fontes)}"
                        ).replace(",", ".")
                        _progresso(
                            progress_callback, "ingestao", fracao_ingestao,
                            f"Lendo {Path(str(nome)).name}: {indice + 1:,} de {total:,} itens".replace(",", "."),
                            detalhes,
                        )
                conn.execute("UPDATE fontes SET status='concluida' WHERE id=?", (fonte_id,))
                conn.commit()
        except (zipfile.BadZipFile, PermissionError, OSError) as exc:
            conn.execute("UPDATE fontes SET status='erro' WHERE id=?", (fonte_id,))
            conn.execute("INSERT INTO erros(arquivo, erro) VALUES (?, ?)", (str(prefixo), f"ZIP inválido ou inacessível: {exc}"))
            conn.commit()
    total_eventos = int(conn.execute(
        "SELECT COALESCE(SUM(quantidade),0) FROM contagem_eventos"
    ).fetchone()[0])
    resumo_final = _resumo_fontes_descobertas(conn, id_carga=id_carga)
    _progresso(
        progress_callback, "ingestao", 1.0,
        "Ingestão SQLite concluída.",
        (
            f"{total_eventos:,} XMLs catalogados; "
            f"{max(total_eventos - xml_inicio, 0):,} nesta execução; "
            f"tempo {_formatar_tempo(time.perf_counter() - inicio_ingestao)} | "
            f"{_texto_resumo_fontes(resumo_final)}."
        ).replace(",", "."),
    )


def _segunda_passagem(conn: sqlite3.Connection, progress_callback: ProgressCallback | None) -> None:
    rubricas = _ler_objetos(conn, "rubricas")
    rubricas_map = _montar_indice_rubricas(rubricas)
    total = conn.execute(
        "SELECT COUNT(*) FROM eventos WHERE ativo=1 AND tipo IN ('S-1200','S-5001','S-5011')"
    ).fetchone()[0]
    concluidos = conn.execute(
        "SELECT COUNT(*) FROM eventos WHERE ativo=1 AND tipo IN ('S-1200','S-5001','S-5011') AND processado_segunda=1"
    ).fetchone()[0]
    limite_bytes = max(
        1,
        int(os.environ.get(
            "ESOCIAL_MAX_BYTES_LOTE_SEGUNDA_PASSAGEM",
            str(MAX_BYTES_LOTE_SEGUNDA_PASSAGEM),
        )),
    )
    inicio_etapa = time.perf_counter()
    _progresso(
        progress_callback, "segunda_passagem", concluidos / max(total, 1),
        "Iniciando ou retomando a segunda passagem...",
        f"{concluidos:,} de {total:,} eventos relevantes já processados".replace(",", "."),
    )

    while True:
        cursor = conn.execute(
            "SELECT id, arquivo, tipo, xml_zlib FROM eventos "
            "WHERE ativo=1 AND tipo IN ('S-1200','S-5001','S-5011') AND processado_segunda=0 "
            "ORDER BY id LIMIT ?",
            (BATCH_SEGUNDA_PASSAGEM,),
        )
        lote = []
        bytes_lote = 0
        for registro in cursor:
            tamanho_blob = len(registro[3] or b"")
            if lote and bytes_lote + tamanho_blob > limite_bytes:
                break
            lote.append(registro)
            bytes_lote += tamanho_blob
        cursor.close()
        if not lote:
            break

        for evento_id, arquivo, tipo, xml_zlib in lote:
            try:
                root = ET.fromstring(zlib.decompress(xml_zlib))
                if tipo == "S-1200":
                    itens = parse_s1200(root, rubricas_map, arquivo)
                    _salvar_objetos(conn, "remuneracoes", evento_id, itens)
                elif tipo == "S-5001":
                    itens = parse_s5001(root, arquivo)
                    _salvar_objetos(conn, "bases_trabalhador", evento_id, itens)
                elif tipo == "S-5011":
                    itens = parse_s5011(root, arquivo)
                    _salvar_objetos(conn, "bases_contribuicao", evento_id, itens)
                root.clear()
            except Exception as exc:
                conn.execute("INSERT INTO erros(arquivo, erro) VALUES (?, ?)", (arquivo, f"Falha na segunda passagem: {exc}"))
            conn.execute("UPDATE eventos SET processado_segunda=1 WHERE id=?", (evento_id,))
            concluidos += 1

        _meta_set(conn, "fase", "segunda_passagem")
        _meta_set(conn, "atualizado_em", time.time())
        conn.commit()
        _progresso(
            progress_callback, "segunda_passagem", concluidos / max(total, 1),
            f"Segunda passagem SQLite: {concluidos:,} de {total:,} eventos relevantes".replace(",", "."),
            (
                f"{concluidos:,}/{total:,} eventos | "
                f"decorrido {_formatar_tempo(time.perf_counter() - inicio_etapa)}"
            ).replace(",", "."),
        )
    _progresso(
        progress_callback, "segunda_passagem", 1.0,
        "Segunda passagem concluída.",
        f"{total:,} eventos relevantes conferidos.".replace(",", "."),
    )


def _dataframe_objetos(conn: sqlite3.Connection, categoria: str, dataclass_obj: bool = True) -> pd.DataFrame:
    itens = _ler_objetos(conn, categoria)
    if dataclass_obj:
        itens = [asdict(x) if hasattr(x, "__dataclass_fields__") else x for x in itens]
    return pd.DataFrame(itens)


def _finalizar_resultado(conn: sqlite3.Connection, workspace: Path) -> Dict[str, object]:
    rubricas = _ler_objetos(conn, "rubricas")
    exclusoes = _ler_objetos(conn, "exclusoes")
    remuneracoes = _ler_objetos(conn, "remuneracoes")
    bases_trabalhador = _ler_objetos(conn, "bases_trabalhador")
    bases_contribuicao = _ler_objetos(conn, "bases_contribuicao")
    empresas = _ler_objetos(conn, "empresa")

    recibos_excluidos = {x.get("nrRecEvt", "") for x in exclusoes if isinstance(x, dict) and x.get("nrRecEvt")}
    remuneracoes = [r for r in remuneracoes if getattr(r, "nr_recibo_evento", "") not in recibos_excluidos]
    bases_trabalhador = [b for b in bases_trabalhador if getattr(b, "nr_recibo_base", "") not in recibos_excluidos]
    bases_contribuicao = [b for b in bases_contribuicao if getattr(b, "nr_recibo_base", "") not in recibos_excluidos]

    inventario = pd.read_sql_query(
        "SELECT arquivo, tipo, tamanho_bytes, "
        "CASE WHEN tipo IN ('S-1000','S-1005','S-1010','S-1020','S-1200','S-3000','S-5001','S-5011') THEN 1 ELSE 0 END AS parseado, "
        "CASE envelope_recibo WHEN 1 THEN 'Sim' ELSE 'Não' END AS envelope_recibo "
        "FROM eventos ORDER BY id",
        conn,
    )
    erros = pd.read_sql_query("SELECT arquivo, erro FROM erros ORDER BY id", conn)
    contagem = pd.read_sql_query(
        "SELECT tipo, quantidade AS xml_localizados FROM contagem_eventos "
        "WHERE tipo IN ('S-1000','S-1005','S-1010','S-1020','S-1200','S-3000','S-5001','S-5011') ORDER BY tipo",
        conn,
    )
    parseados = pd.DataFrame([
        {"tipo": "S-1010", "xml_parseados": int(contagem.loc[contagem["tipo"].eq("S-1010"), "xml_localizados"].sum()) if not contagem.empty else 0},
        {"tipo": "S-1200", "xml_parseados": conn.execute("SELECT COUNT(*) FROM eventos WHERE tipo='S-1200' AND processado_segunda=1").fetchone()[0]},
        {"tipo": "S-5001", "xml_parseados": conn.execute("SELECT COUNT(*) FROM eventos WHERE tipo='S-5001' AND processado_segunda=1").fetchone()[0]},
        {"tipo": "S-5011", "xml_parseados": conn.execute("SELECT COUNT(*) FROM eventos WHERE tipo='S-5011' AND processado_segunda=1").fetchone()[0]},
        {"tipo": "S-3000", "xml_parseados": len(exclusoes)},
    ])
    layout = contagem.merge(parseados, on="tipo", how="outer").fillna(0)
    if not layout.empty:
        layout[["xml_localizados", "xml_parseados"]] = layout[["xml_localizados", "xml_parseados"]].astype(int)
        layout["nao_parseados"] = layout["xml_localizados"] - layout["xml_parseados"]

    df_empresa = pd.DataFrame(empresas)
    if not df_empresa.empty:
        df_empresa = df_empresa.drop_duplicates().copy()
        df_empresa["tem_nome"] = df_empresa["nome_empresa"].fillna("").astype(str).str.strip().ne("")
        df_empresa = df_empresa.sort_values(["tem_nome", "cnpj_empregador"], ascending=[False, True]).drop(columns=["tem_nome"])

    return {
        "inventario": inventario,
        "rubricas": pd.DataFrame([asdict(x) for x in rubricas]),
        "exclusoes": pd.DataFrame(exclusoes),
        "remuneracoes": pd.DataFrame([asdict(x) for x in remuneracoes]),
        "bases_trabalhador": pd.DataFrame([asdict(x) for x in bases_trabalhador]),
        "bases_contribuicao": pd.DataFrame([asdict(x) for x in bases_contribuicao]),
        "erros_xml": erros,
        "layout_check": layout,
        "empresa": df_empresa,
        "recibos_excluidos": recibos_excluidos,
        "workspace_temporario": str(workspace),
        "quantidade_xml_spool": int(conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]),
        "workspace_removido": False,
        "engine": "V3 SQLite + checkpoint",
    }


def listar_processamentos_interrompidos() -> list[dict]:
    saida = []
    for pasta in _base_workspaces().glob("esocial_v3_*"):
        db = pasta / "processamento.db"
        if not db.exists():
            continue
        try:
            conn = _conectar_somente_leitura(db)
            status = _meta_get(conn, "status", "interrompido")
            if status != "concluido":
                total = conn.execute("SELECT COALESCE(SUM(quantidade),0) FROM contagem_eventos").fetchone()[0]
                relevantes = conn.execute("SELECT COUNT(*) FROM eventos WHERE tipo IN ('S-1200','S-5001','S-5011')").fetchone()[0]
                processados = conn.execute("SELECT COUNT(*) FROM eventos WHERE processado_segunda=1").fetchone()[0]
                saida.append({
                    "id": pasta.name,
                    "workspace": str(pasta),
                    "fase": _meta_get(conn, "fase", "preparacao"),
                    "xml_catalogados": int(total),
                    "eventos_relevantes": int(relevantes),
                    "segunda_processados": int(processados),
                    "atualizado_em": float(_meta_get(conn, "atualizado_em", "0") or 0),
                })
            conn.close()
        except Exception:
            continue
    return sorted(saida, key=lambda x: x["atualizado_em"], reverse=True)


def descartar_processamento(workspace_id: str) -> bool:
    pasta = _base_workspaces() / Path(workspace_id).name
    if pasta.exists() and pasta.name.startswith("esocial_v3_"):
        shutil.rmtree(pasta, ignore_errors=True)
    return not pasta.exists()


def limpar_workspaces_temporarios_antigos() -> dict:
    removidas = 0
    bytes_liberados = 0
    falhas = []
    bases = [Path(tempfile.gettempdir()), _base_workspaces()]
    padroes = ["esocial_engine_v2_*", "esocial_v3_*"]
    for base in bases:
        for padrao in padroes:
            for pasta in base.glob(padrao):
                if not pasta.is_dir():
                    continue
                # Workspaces V3 incompletos são preservados para permitir retomada.
                if pasta.name.startswith("esocial_v3_"):
                    db = pasta / "processamento.db"
                    try:
                        if db.exists():
                            conn = _conectar_somente_leitura(db)
                            status = _meta_get(conn, "status", "interrompido")
                            conn.close()
                            if status != "concluido":
                                continue
                    except Exception:
                        continue
                try:
                    tamanho = sum(arq.stat().st_size for arq in pasta.rglob("*") if arq.is_file())
                    shutil.rmtree(pasta)
                    removidas += 1
                    bytes_liberados += tamanho
                except Exception as exc:
                    falhas.append(f"{pasta}: {exc}")
    return {"pastas_removidas": removidas, "bytes_liberados": bytes_liberados, "falhas": falhas}



def _assinatura_fontes(fontes: Iterable[Fonte]) -> tuple[str, list[Fonte]]:
    """Cria uma assinatura rápida e estável sem ler integralmente arquivos grandes."""
    fontes_lista = list(fontes)
    partes: list[dict[str, object]] = []
    for nome, fonte in fontes_lista:
        item: dict[str, object] = {"nome": str(nome)}
        if isinstance(fonte, (str, os.PathLike)):
            caminho = Path(fonte).expanduser().resolve()
            stat = caminho.stat()
            item.update({
                "tipo": "caminho",
                "caminho": str(caminho),
                "tamanho": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            })
        else:
            dados = bytes(fonte)
            amostra = dados if len(dados) <= 2 * 1024 * 1024 else dados[:1024 * 1024] + dados[-1024 * 1024:]
            item.update({
                "tipo": "memoria",
                "tamanho": len(dados),
                "amostra_sha256": hashlib.sha256(amostra).hexdigest(),
            })
        partes.append(item)
    bruto = json.dumps(partes, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(bruto).hexdigest(), fontes_lista


def _workspace_interrompido_por_assinatura(assinatura: str) -> Path | None:
    candidatos: list[tuple[float, Path]] = []
    for pasta in _base_workspaces().glob("esocial_v3_*"):
        db = pasta / "processamento.db"
        if not db.exists():
            continue
        conn = None
        try:
            conn = _conectar_somente_leitura(db)
            if _meta_get(conn, "assinatura_fontes", "") != assinatura:
                continue
            if _meta_get(conn, "status", "") == "concluido":
                continue
            atualizado = float(_meta_get(conn, "atualizado_em", "0") or 0)
            candidatos.append((atualizado, pasta))
        except Exception:
            continue
        finally:
            if conn is not None:
                conn.close()
    return max(candidatos, default=(0.0, None), key=lambda x: x[0])[1]


def _atualizar_metadados_workspace(conn: sqlite3.Connection) -> None:
    agora = time.time()
    total = int(conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0])
    _meta_set(conn, "ultima_atualizacao", agora)
    _meta_set(conn, "data_ultima_consolidacao", agora)
    _meta_set(conn, "total_xml_processados", total)
    cargas = int(conn.execute(
        "SELECT COUNT(*) FROM historico_cargas WHERE status='concluida'"
    ).fetchone()[0])
    _meta_set(conn, "quantidade_total_cargas", cargas)
    for tipo in ("S-1010", "S-1200", "S-5001", "S-5011", "S-3000"):
        qtd = int(conn.execute("SELECT COUNT(*) FROM eventos WHERE tipo=?", (tipo,)).fetchone()[0])
        _meta_set(conn, "quantidade_" + tipo.lower().replace("-", ""), qtd)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rel_movimentos_cp'").fetchone():
        periodo = conn.execute(
            "SELECT COALESCE(MIN(per_apur),''),COALESCE(MAX(per_apur),'') FROM rel_movimentos_cp"
        ).fetchone()
        _meta_set(conn, "periodo_minimo", periodo[0])
        _meta_set(conn, "periodo_maximo", periodo[1])


def _registrar_carga_inicial_se_necessario(
    conn: sqlite3.Connection, workspace: Path, assinatura: str
) -> None:
    if conn.execute("SELECT 1 FROM historico_cargas LIMIT 1").fetchone():
        return
    total_xml = int(conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0])
    total_fontes = int(conn.execute(
        "SELECT COUNT(*) FROM fontes WHERE nivel=0 AND id_carga IS NULL"
    ).fetchone()[0])
    total_erros = int(conn.execute("SELECT COUNT(*) FROM erros").fetchone()[0])
    periodo_minimo = ""
    periodo_maximo = ""
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rel_movimentos_cp'"
    ).fetchone():
        periodo_minimo, periodo_maximo = conn.execute(
            "SELECT COALESCE(MIN(per_apur),''),COALESCE(MAX(per_apur),'') FROM rel_movimentos_cp"
        ).fetchone()
    agora = time.time()
    inicio = float(_meta_get(conn, "criado_em", str(agora)) or agora)
    conn.execute(
        "INSERT INTO historico_cargas(workspace_id,data_inicio,data_fim,origem,assinatura_fontes,"
        "quantidade_arquivos_recebidos,quantidade_xml_localizados,quantidade_xml_novos,"
        "quantidade_erros,periodo_minimo_adicionado,periodo_maximo_adicionado,status) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,'concluida')",
        (workspace.name, inicio, agora, "Carga inicial", assinatura,
         total_fontes, total_xml, total_xml, total_erros,
         periodo_minimo, periodo_maximo),
    )


def _resolver_workspace_existente(caminho: str | os.PathLike) -> tuple[Path, Path]:
    informado = Path(caminho).expanduser().resolve()
    db_path = informado if informado.suffix.lower() == ".db" else informado / "processamento.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"processamento.db não localizado em: {informado}")
    return db_path.parent, db_path


def atualizar_workspace_incremental(
    workspace_ou_db: str | os.PathLike,
    fontes: Iterable[Fonte] | None,
    progress_callback: ProgressCallback | None = None,
    origem: str = "Complementos",
) -> Dict[str, object]:
    """Adiciona XMLs ao mesmo Workspace, com SHA-256, histórico e retomada."""
    workspace, db_path = _resolver_workspace_existente(workspace_ou_db)
    bloqueio = _adquirir_bloqueio_workspace(workspace)
    try:
        conn = _conectar(db_path)
        _criar_schema(conn)
    except BaseException:
        _liberar_bloqueio_workspace(bloqueio)
        raise
    assinatura = ""
    fontes_lista: list[Fonte] = []
    if fontes is not None:
        assinatura, fontes_lista = _assinatura_fontes(fontes)
    try:
        carga = conn.execute(
            "SELECT id_carga,assinatura_fontes FROM historico_cargas "
            "WHERE status IN ('processando','interrompida') ORDER BY id_carga DESC LIMIT 1"
        ).fetchone()
        retomando = carga is not None
        if retomando:
            id_carga = int(carga[0])
            if assinatura and carga[1] and assinatura != carga[1]:
                raise ValueError(
                    "Existe uma carga incremental interrompida com outras fontes. "
                    "Retome-a antes de iniciar novos complementos."
                )
            conn.execute(
                "UPDATE historico_cargas SET status='processando',mensagem_erro='' WHERE id_carga=?",
                (id_carga,),
            )
        else:
            if not fontes_lista:
                raise ValueError("Nenhum ZIP/XML complementar foi informado.")
            cur = conn.execute(
                "INSERT INTO historico_cargas(workspace_id,data_inicio,origem,assinatura_fontes,"
                "quantidade_arquivos_recebidos,status) VALUES(?,?,?,?,?,'processando')",
                (workspace.name, time.time(), origem, assinatura, len(fontes_lista)),
            )
            id_carga = int(cur.lastrowid)
            _materializar_fontes(conn, workspace, fontes_lista, id_carga=id_carga)
        _meta_set(conn, "status", "processando")
        _meta_set(conn, "fase", "carga_incremental_ingestao")
        _meta_set(conn, "carga_incremental_ativa", id_carga)
        conn.commit()

        _progresso(
            progress_callback, "preparacao", 1.0,
            "Retomando carga incremental pelo checkpoint SQLite..." if retomando
            else "Iniciando carga incremental no Workspace existente...",
        )
        inicio_etapa = time.perf_counter()
        _ingerir_fontes(conn, workspace, progress_callback, id_carga=id_carga)
        _registrar_duracao(conn, "ingestao_incremental", inicio_etapa)

        novos_s1010 = int(conn.execute(
            "SELECT COUNT(*) FROM eventos WHERE id_carga=? AND tipo='S-1010'", (id_carga,)
        ).fetchone()[0])
        novos_s1010 += int(
            _meta_get(conn, f"carga_{id_carga}_reprocessou_s1010", "0") or 0
        )
        novas_retificacoes = int(conn.execute(
            "SELECT COUNT(*) FROM eventos WHERE id_carga=? AND ind_retif='2'", (id_carga,)
        ).fetchone()[0])
        if novos_s1010:
            _progresso(
                progress_callback, "segunda_passagem", 0.0,
                "Reaplicando vigências S-1010 à base acumulada...",
            )
            conn.execute(
                "DELETE FROM objetos WHERE categoria='remuneracoes' AND evento_id IN "
                "(SELECT id FROM eventos WHERE tipo='S-1200')"
            )
            conn.execute("UPDATE eventos SET processado_segunda=0 WHERE tipo='S-1200' AND ativo=1")
            conn.commit()

        _meta_set(conn, "fase", "carga_incremental_segunda_passagem")
        conn.commit()
        inicio_etapa = time.perf_counter()
        _segunda_passagem(conn, progress_callback)
        _registrar_duracao(conn, "segunda_passagem_incremental", inicio_etapa)

        if novos_s1010 or novas_retificacoes:
            reiniciar_materializacao_analitica(conn)
        _meta_set(conn, "fase", "carga_incremental_consolidacao")
        conn.commit()
        _progresso(
            progress_callback, "materializacao", 0.0,
            "Recalculando consolidações da base acumulada...",
        )
        inicio_etapa = time.perf_counter()
        materializar_tabelas_analiticas(conn, progress_callback=progress_callback)
        _registrar_duracao(conn, "consolidacao_incremental", inicio_etapa)
        agora = time.time()
        conn.execute(
            "UPDATE historico_cargas SET data_fim=?,status='concluida',mensagem_erro='' WHERE id_carga=?",
            (agora, id_carga),
        )
        _atualizar_metadados_workspace(conn)
        _meta_set(conn, "status", "concluido")
        _meta_set(conn, "fase", "concluido")
        _meta_set(conn, "atualizado_em", agora)
        conn.execute("DELETE FROM meta WHERE chave='carga_incremental_ativa'")
        conn.commit()
    except BaseException as exc:
        carga_id = locals().get("id_carga")
        if carga_id is not None:
            conn.execute(
                "UPDATE historico_cargas SET status='interrompida',mensagem_erro=? WHERE id_carga=?",
                (str(exc)[:2000], carga_id),
            )
        _meta_set(conn, "status", "interrompido")
        _meta_set(conn, "atualizado_em", time.time())
        conn.commit()
        raise
    finally:
        conn.close()
        _liberar_bloqueio_workspace(bloqueio)

    resultado = carregar_resultado_sqlite_existente(db_path)
    resultado["carga_incremental"] = obter_resumo_carga_incremental(db_path, id_carga)
    return resultado


def obter_resumo_carga_incremental(
    workspace_ou_db: str | os.PathLike, id_carga: int | None = None
) -> dict[str, object]:
    _, db_path = _resolver_workspace_existente(workspace_ou_db)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        filtro = " WHERE id_carga=?" if id_carga is not None else " ORDER BY id_carga DESC LIMIT 1"
        params = (id_carga,) if id_carga is not None else ()
        row = conn.execute("SELECT * FROM historico_cargas" + filtro, params).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def processar_fontes_esocial(
    fontes: Iterable[Fonte] | None,
    progress_callback: ProgressCallback | None = None,
    workspace_id: str | None = None,
) -> Dict[str, object]:
    """Engine V3: SQLite persistente, checkpoint e retomada após interrupções."""
    retomando = False
    fontes_lista: list[Fonte] = []
    assinatura = ""
    if workspace_id:
        workspace = _base_workspaces() / Path(workspace_id).name
        if not workspace.exists():
            raise FileNotFoundError("Workspace de retomada não localizado.")
        retomando = True
    else:
        if fontes is None:
            raise ValueError("Nenhuma fonte ZIP/XML foi informada.")
        assinatura, fontes_lista = _assinatura_fontes(fontes)
        anterior = _workspace_interrompido_por_assinatura(assinatura)
        if anterior is not None:
            workspace = anterior
            retomando = True
        else:
            workspace = _base_workspaces() / f"esocial_v3_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            workspace.mkdir(parents=True, exist_ok=False)

    db_path = workspace / "processamento.db"
    bloqueio = _adquirir_bloqueio_workspace(workspace)
    try:
        conn = _conectar(db_path)
        _criar_schema(conn)
    except BaseException:
        _liberar_bloqueio_workspace(bloqueio)
        raise
    try:
        if not retomando:
            if not fontes_lista:
                raise ValueError("Nenhuma fonte ZIP/XML foi informada.")
            _materializar_fontes(conn, workspace, fontes_lista)
            _meta_set(conn, "criado_em", time.time())
            _meta_set(conn, "assinatura_fontes", assinatura)
        elif assinatura and not _meta_get(conn, "assinatura_fontes", ""):
            _meta_set(conn, "assinatura_fontes", assinatura)
        _meta_set(conn, "status", "processando")
        _meta_set(conn, "atualizado_em", time.time())
        conn.commit()

        _progresso(
            progress_callback, "preparacao", 1.0,
            "Retomando processamento interrompido pelo checkpoint SQLite..." if retomando
            else "Criando workspace persistente e banco SQLite...",
        )
        fase = _meta_get(conn, "fase", "preparacao")
        if fase in {"preparacao", "ingestao"}:
            inicio_etapa = time.perf_counter()
            _ingerir_fontes(conn, workspace, progress_callback)
            _registrar_duracao(conn, "ingestao", inicio_etapa)
            _meta_set(conn, "fase", "segunda_passagem")
            conn.commit()

        inicio_etapa = time.perf_counter()
        _segunda_passagem(conn, progress_callback)
        _registrar_duracao(conn, "segunda_passagem", inicio_etapa)

        _meta_set(conn, "fase", "consolidacao_sqlite")
        conn.commit()
        _progresso(
            progress_callback, "materializacao", 0.0,
            "Consolidando o relatório no SQLite sem carregar bases gigantes na memória...",
        )
        inicio_etapa = time.perf_counter()
        materializar_tabelas_analiticas(conn, progress_callback=progress_callback)
        _registrar_duracao(conn, "consolidacao", inicio_etapa)
        _registrar_carga_inicial_se_necessario(
            conn, workspace, _meta_get(conn, "assinatura_fontes", assinatura)
        )
        _atualizar_metadados_workspace(conn)
        inicio_etapa = time.perf_counter()
        pacote = carregar_pacote_resumido(db_path)
        _registrar_duracao(conn, "resumo", inicio_etapa)

        # Apenas conjuntos pequenos e prévias seguem para a interface. As bases completas
        # permanecem no SQLite e são exportadas em streaming.
        empresas = _ler_objetos(conn, "empresa")
        df_empresa = pd.DataFrame(empresas)
        if not df_empresa.empty:
            df_empresa = df_empresa.drop_duplicates().copy()
            df_empresa["tem_nome"] = df_empresa["nome_empresa"].fillna("").astype(str).str.strip().ne("")
            df_empresa = df_empresa.sort_values(["tem_nome", "cnpj_empregador"], ascending=[False, True]).drop(columns=["tem_nome"])
        df_rubricas = pd.read_sql_query("SELECT * FROM dados_rubricas", conn)
        df_exclusoes = pd.read_sql_query("SELECT * FROM dados_exclusoes", conn)
        df_erros = pd.read_sql_query("SELECT arquivo, erro FROM erros ORDER BY id LIMIT 5000", conn)
        df_inventario = pd.read_sql_query("SELECT arquivo,tipo,tamanho_bytes,CASE WHEN tipo IN ('S-1000','S-1005','S-1010','S-1020','S-1200','S-3000','S-5001','S-5011') THEN 1 ELSE 0 END parseado,CASE envelope_recibo WHEN 1 THEN 'Sim' ELSE 'Não' END envelope_recibo FROM eventos ORDER BY id LIMIT 5000", conn)
        df_layout = pd.read_sql_query("SELECT tipo, quantidade AS xml_localizados FROM contagem_eventos ORDER BY tipo", conn)
        total_movimentos = int(pacote.get("total_movimentos_cp", 0))
        limite_dataframe_integral = int(os.environ.get("ESOCIAL_LIMITE_DATAFRAME_INTEGRAL", "300000"))
        modo_sqlite_seguro = total_movimentos > limite_dataframe_integral
        if modo_sqlite_seguro:
            df_remuneracoes_saida = pacote["movimentos_cp"]
            df_bases_trabalhador_saida = pacote["s5001_resumo"]
            df_bases_contribuicao_saida = pd.DataFrame()
        else:
            df_remuneracoes_saida = pd.read_sql_query("SELECT * FROM rel_movimentos_cp", conn)
            df_bases_trabalhador_saida = pd.read_sql_query("SELECT * FROM dados_bases_trabalhador", conn)
            df_bases_contribuicao_saida = pd.read_sql_query("SELECT * FROM dados_bases_contribuicao", conn)

        resultado = {
            "inventario": df_inventario,
            "rubricas": df_rubricas,
            "exclusoes": df_exclusoes,
            "remuneracoes": df_remuneracoes_saida,
            "bases_trabalhador": df_bases_trabalhador_saida,
            "bases_contribuicao": df_bases_contribuicao_saida,
            "erros_xml": df_erros,
            "layout_check": df_layout,
            "empresa": df_empresa,
            "recibos_excluidos": set(),
            "workspace_temporario": str(workspace),
            "db_path": str(db_path),
            "modo_sqlite_seguro": modo_sqlite_seguro,
            "pacote_sqlite": pacote,
            "quantidade_xml_spool": int(conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]),
            "workspace_removido": False,
            "engine": "V3 SQLite + checkpoint + relatório streaming",
        }
        _meta_set(conn, "fase", "concluido")
        _meta_set(conn, "status", "concluido")
        _meta_set(conn, "atualizado_em", time.time())
        conn.commit()
        _progresso(
            progress_callback, "finalizacao", 1.0,
            "Processamento concluído. Workspace preservado para auditoria.",
        )
        return resultado
    except BaseException:
        _meta_set(conn, "status", "interrompido")
        _meta_set(conn, "atualizado_em", time.time())
        conn.commit()
        raise
    finally:
        conn.close()
        _liberar_bloqueio_workspace(bloqueio)


def processar_zip_esocial(zip_bytes: bytes, progress_callback: ProgressCallback | None = None) -> Dict[str, object]:
    return processar_fontes_esocial([("upload.zip", zip_bytes)], progress_callback=progress_callback)


def carregar_resultado_sqlite_existente(db_path: str | os.PathLike) -> Dict[str, object]:
    """Carrega um processamento.db já concluído sem reler os XMLs."""
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"Banco SQLite não localizado: {db_path}")
    conn = _conectar(db_path)
    try:
        obrigatorias = {"eventos", "meta", "rel_movimentos_cp", "rel_rubricas_cp_base"}
        existentes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        faltantes = sorted(obrigatorias - existentes)
        if faltantes:
            raise ValueError("Banco incompatível ou incompleto. Tabelas ausentes: " + ", ".join(faltantes))

        pacote = carregar_pacote_resumido(db_path)
        df_empresa = pd.read_sql_query("SELECT * FROM dados_empresa", conn) if "dados_empresa" in existentes else pd.DataFrame()
        if not df_empresa.empty:
            df_empresa = df_empresa.drop_duplicates().copy()
        df_rubricas = pd.read_sql_query("SELECT * FROM dados_rubricas", conn) if "dados_rubricas" in existentes else pd.DataFrame()
        df_exclusoes = pd.read_sql_query("SELECT * FROM dados_exclusoes", conn) if "dados_exclusoes" in existentes else pd.DataFrame()
        df_erros = pd.read_sql_query("SELECT arquivo, erro FROM erros ORDER BY id LIMIT 5000", conn) if "erros" in existentes else pd.DataFrame()
        df_inventario = pd.read_sql_query(
            "SELECT arquivo,tipo,tamanho_bytes,CASE WHEN tipo IN ('S-1000','S-1005','S-1010','S-1020','S-1200','S-3000','S-5001','S-5011') THEN 1 ELSE 0 END parseado,CASE envelope_recibo WHEN 1 THEN 'Sim' ELSE 'Não' END envelope_recibo FROM eventos ORDER BY id LIMIT 5000",
            conn,
        )
        df_layout = pd.read_sql_query("SELECT tipo, quantidade AS xml_localizados FROM contagem_eventos ORDER BY tipo", conn) if "contagem_eventos" in existentes else pd.DataFrame()
        return {
            "inventario": df_inventario,
            "rubricas": df_rubricas,
            "exclusoes": df_exclusoes,
            "remuneracoes": pacote["movimentos_cp"],
            "bases_trabalhador": pacote["s5001_resumo"],
            "bases_contribuicao": pd.DataFrame(),
            "erros_xml": df_erros,
            "layout_check": df_layout,
            "empresa": df_empresa,
            "recibos_excluidos": set(),
            "workspace_temporario": str(db_path.parent),
            "db_path": str(db_path),
            "modo_sqlite_seguro": True,
            "pacote_sqlite": pacote,
            "quantidade_xml_spool": int(conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]),
            "workspace_removido": False,
            "engine": "V3 SQLite existente",
        }
    finally:
        conn.close()
