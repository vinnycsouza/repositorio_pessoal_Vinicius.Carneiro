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
    detectar_tipo_evento, parse_s1010, parse_s1200, parse_s3000,
    parse_s5001, parse_s5011, parse_empresa_info,
)
from utils.helpers import localname

Fonte = Tuple[str, Union[bytes, bytearray, memoryview, str, os.PathLike]]
ProgressCallback = Callable[[float, str], None]

EVENTOS_SUPORTADOS = {"S-1000", "S-1005", "S-1010", "S-1020", "S-1200", "S-3000", "S-5001", "S-5011"}
EVENTOS_SEGUNDA_PASSAGEM = {"S-1200", "S-5001", "S-5011"}
CHECKPOINT_INTERVALO = 500
BATCH_SEGUNDA_PASSAGEM = 250
MAX_NIVEL_ZIP = 8
MAX_XML_INDIVIDUAL = 256 * 1024 * 1024


def _progresso(callback: ProgressCallback | None, valor: float, mensagem: str) -> None:
    if callback:
        callback(max(0.0, min(1.0, float(valor))), mensagem)


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


def _conectar(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-131072")
    conn.execute("PRAGMA busy_timeout=120000")
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
    """)
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
    mapa = {}
    ordenadas = sorted(
        rubricas,
        key=lambda r: (0 if r.fonte_dados == "Download principal" else 1, r.ini_valid, r.fim_valid),
    )
    for r in ordenadas:
        cod, tab = str(r.cod_rubr or "").strip(), str(r.ide_tab_rubr or "").strip()
        mapa.setdefault((cod, tab), []).append(r)
        mapa.setdefault((cod, ""), []).append(r)
    return mapa


def _materializar_fontes(conn: sqlite3.Connection, workspace: Path, fontes: Iterable[Fonte]) -> None:
    pasta = workspace / "fontes"
    pasta.mkdir(parents=True, exist_ok=True)
    existentes = conn.execute("SELECT COUNT(*) FROM fontes").fetchone()[0]
    if existentes:
        return

    for indice, (nome, fonte) in enumerate(fontes):
        if isinstance(fonte, (str, os.PathLike)):
            caminho = Path(fonte).expanduser().resolve()
        else:
            caminho = pasta / f"{indice:04d}_{_nome_seguro(nome)}"
            with caminho.open("wb") as fp:
                view = memoryview(bytes(fonte))
                bloco = 1024 * 1024
                for ini in range(0, len(view), bloco):
                    fp.write(view[ini:ini + bloco])
        tamanho = caminho.stat().st_size if caminho.exists() else 0
        conn.execute(
            "INSERT INTO fontes(nome, caminho, nivel, prefixo, tamanho_bytes) VALUES (?, ?, 0, ?, ?)",
            (str(nome), str(caminho), str(nome), tamanho),
        )
    conn.commit()


def _registrar_contagem(conn: sqlite3.Connection, tipo: str) -> None:
    conn.execute(
        "INSERT INTO contagem_eventos(tipo, quantidade) VALUES(?, 1) "
        "ON CONFLICT(tipo) DO UPDATE SET quantidade=quantidade+1",
        (tipo,),
    )


def _processar_xml_ingestao(
    conn: sqlite3.Connection,
    arquivo: str,
    xml_bytes: bytes,
    tamanho: int,
) -> None:
    if tamanho > MAX_XML_INDIVIDUAL:
        conn.execute("INSERT INTO erros(arquivo, erro) VALUES (?, ?)", (arquivo, "XML acima do limite individual de segurança"))
        conn.execute(
            "INSERT OR IGNORE INTO eventos(arquivo, tipo, tamanho_bytes) VALUES (?, 'XML_INVALIDO', ?)",
            (arquivo, tamanho),
        )
        return
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        conn.execute("INSERT INTO erros(arquivo, erro) VALUES (?, ?)", (arquivo, f"XML inválido ou ilegível: {exc}"))
        conn.execute(
            "INSERT OR IGNORE INTO eventos(arquivo, tipo, tamanho_bytes) VALUES (?, 'XML_INVALIDO', ?)",
            (arquivo, tamanho),
        )
        return

    tipo = detectar_tipo_evento(root)
    recibo = _eh_retorno_evento_completo(root)
    _registrar_contagem(conn, tipo)

    blob = None
    if tipo in EVENTOS_SEGUNDA_PASSAGEM:
        blob = sqlite3.Binary(zlib.compress(xml_bytes, level=1))
    cur = conn.execute(
        "INSERT OR IGNORE INTO eventos(arquivo, tipo, tamanho_bytes, envelope_recibo, xml_zlib) "
        "VALUES (?, ?, ?, ?, ?)",
        (arquivo, tipo, tamanho, int(recibo), blob),
    )
    if cur.rowcount == 0:
        root.clear()
        return
    evento_id = int(cur.lastrowid)

    if tipo in EVENTOS_SUPORTADOS:
        empresa = parse_empresa_info(root, arquivo)
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
        "INSERT OR IGNORE INTO fontes(nome, caminho, nivel, prefixo, tamanho_bytes) VALUES (?, ?, ?, ?, ?)",
        (nome_membro, str(destino), nivel, caminho_logico, int(tamanho)),
    )


def _ingerir_fontes(conn: sqlite3.Connection, workspace: Path, progress_callback: ProgressCallback | None) -> None:
    while True:
        fonte = conn.execute(
            "SELECT id, nome, caminho, nivel, prefixo, ultimo_indice FROM fontes "
            "WHERE status != 'concluida' ORDER BY id LIMIT 1"
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
                _processar_xml_ingestao(conn, str(prefixo), caminho.read_bytes(), caminho.stat().st_size)
                conn.execute("UPDATE fontes SET ultimo_indice=0, total_membros=1, status='concluida' WHERE id=?", (fonte_id,))
                conn.commit()
            continue

        try:
            with zipfile.ZipFile(caminho, "r") as zf:
                infos = zf.infolist()
                total = len(infos)
                conn.execute("UPDATE fontes SET total_membros=?, status='processando' WHERE id=?", (total, fonte_id))
                conn.commit()
                inicio = max(int(ultimo_indice) + 1, 0)
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
                                    _processar_xml_ingestao(conn, caminho_logico, conteudo, info.file_size)
                                else:
                                    with zf.open(info, "r") as fp:
                                        _adicionar_zip_aninhado(
                                            conn, workspace, fonte_id, indice, prefixo,
                                            info.filename, fp, info.file_size, int(nivel) + 1,
                                        )
                            except Exception as exc:
                                conn.execute("INSERT INTO erros(arquivo, erro) VALUES (?, ?)", (caminho_logico, str(exc)))
                    if indice % CHECKPOINT_INTERVALO == 0 or indice == total - 1:
                        conn.execute("UPDATE fontes SET ultimo_indice=? WHERE id=?", (indice, fonte_id))
                        _meta_set(conn, "fase", "ingestao")
                        _meta_set(conn, "atualizado_em", time.time())
                        conn.commit()
                        total_eventos = conn.execute("SELECT COALESCE(SUM(quantidade),0) FROM contagem_eventos").fetchone()[0]
                        _progresso(
                            progress_callback, 0.05 + 0.48 * ((indice + 1) / max(total, 1)),
                            f"Ingestão SQLite: {indice + 1:,} de {total:,} itens da fonte atual; {total_eventos:,} XMLs catalogados".replace(",", "."),
                        )
                conn.execute("UPDATE fontes SET status='concluida' WHERE id=?", (fonte_id,))
                conn.commit()
        except (zipfile.BadZipFile, PermissionError, OSError) as exc:
            conn.execute("UPDATE fontes SET status='erro' WHERE id=?", (fonte_id,))
            conn.execute("INSERT INTO erros(arquivo, erro) VALUES (?, ?)", (str(prefixo), f"ZIP inválido ou inacessível: {exc}"))
            conn.commit()


def _segunda_passagem(conn: sqlite3.Connection, progress_callback: ProgressCallback | None) -> None:
    rubricas = _ler_objetos(conn, "rubricas")
    rubricas_map = _montar_indice_rubricas(rubricas)
    total = conn.execute(
        "SELECT COUNT(*) FROM eventos WHERE tipo IN ('S-1200','S-5001','S-5011')"
    ).fetchone()[0]
    concluidos = conn.execute(
        "SELECT COUNT(*) FROM eventos WHERE tipo IN ('S-1200','S-5001','S-5011') AND processado_segunda=1"
    ).fetchone()[0]

    while True:
        lote = conn.execute(
            "SELECT id, arquivo, tipo, xml_zlib FROM eventos "
            "WHERE tipo IN ('S-1200','S-5001','S-5011') AND processado_segunda=0 "
            "ORDER BY id LIMIT ?",
            (BATCH_SEGUNDA_PASSAGEM,),
        ).fetchall()
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
            progress_callback,
            0.55 + 0.38 * (concluidos / max(total, 1)),
            f"Segunda passagem SQLite: {concluidos:,} de {total:,} eventos relevantes".replace(",", "."),
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
            conn = _conectar(db)
            _criar_schema(conn)
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
                            conn = _conectar(db)
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
            conn = _conectar(db)
            _criar_schema(conn)
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
    conn = _conectar(db_path)
    _criar_schema(conn)
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
            progress_callback,
            0.01,
            "Retomando processamento interrompido pelo checkpoint SQLite..." if retomando
            else "Criando workspace persistente e banco SQLite...",
        )
        fase = _meta_get(conn, "fase", "preparacao")
        if fase in {"preparacao", "ingestao"}:
            _ingerir_fontes(conn, workspace, progress_callback)
            _meta_set(conn, "fase", "segunda_passagem")
            conn.commit()

        _progresso(progress_callback, 0.55, "Iniciando ou retomando a segunda passagem...")
        _segunda_passagem(conn, progress_callback)

        _meta_set(conn, "fase", "consolidacao")
        conn.commit()
        _progresso(progress_callback, 0.94, "Aplicando exclusões S-3000 e montando os DataFrames...")
        resultado = _finalizar_resultado(conn, workspace)
        _meta_set(conn, "fase", "concluido")
        _meta_set(conn, "status", "concluido")
        _meta_set(conn, "atualizado_em", time.time())
        conn.commit()
        _progresso(progress_callback, 1.0, "Processamento concluído. Workspace preservado para auditoria.")
        return resultado
    except BaseException:
        _meta_set(conn, "status", "interrompido")
        _meta_set(conn, "atualizado_em", time.time())
        conn.commit()
        raise
    finally:
        conn.close()


def processar_zip_esocial(zip_bytes: bytes, progress_callback: ProgressCallback | None = None) -> Dict[str, object]:
    return processar_fontes_esocial([("upload.zip", zip_bytes)], progress_callback=progress_callback)
