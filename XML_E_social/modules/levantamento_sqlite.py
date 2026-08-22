from __future__ import annotations

import sqlite3
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from modules.data_source import SQLiteDataSource
from modules.excel_builder import FontePlanilha, ResultadoWorkbook, gerar_workbook


@dataclass(frozen=True)
class FiltrosLevantamento:
    status_cp: str = "Todos"
    carater: str = "Todos"
    tipo: str = "Todos"
    cod_inc_cp: str = "Todos"
    competencias: tuple[str, ...] = ()
    apenas_positivos: bool = True


@dataclass
class ResultadoLevantamentoSQLite:
    total: float
    cpp: float
    qtd_movimentos: int
    qtd_rubricas: int
    qtd_cpfs: int
    resumo_rubricas: pd.DataFrame
    resumo_competencia_rubrica: pd.DataFrame
    resumo_competencia: pd.DataFrame
    movimentos_previa: pd.DataFrame


def _where_filtros(filtros: FiltrosLevantamento, alias: str = "m") -> tuple[str, tuple]:
    prefixo = f"{alias}." if alias else ""
    condicoes: list[str] = []
    params: list[object] = []
    campos = [
        (filtros.status_cp, "status_cp"),
        (filtros.carater, "carater_verba"),
        (filtros.tipo, "tipo_verba"),
    ]
    for valor, campo in campos:
        if valor != "Todos":
            condicoes.append(f"{prefixo}{campo}=?")
            params.append(valor)
    if filtros.cod_inc_cp != "Todos":
        if filtros.cod_inc_cp == "Sem S-1010":
            condicoes.append(f"COALESCE({prefixo}cod_inc_cp,'')=''")
        else:
            condicoes.append(f"{prefixo}cod_inc_cp=?")
            params.append(filtros.cod_inc_cp)
    if filtros.competencias:
        marcas = ",".join("?" for _ in filtros.competencias)
        condicoes.append(f"{prefixo}per_apur IN ({marcas})")
        params.extend(filtros.competencias)
    if filtros.apenas_positivos:
        condicoes.append(f"CAST({prefixo}vr_rubr AS REAL)>0")
    return (" WHERE " + " AND ".join(condicoes) if condicoes else ""), tuple(params)


def _preparar_selecao(
    conn: sqlite3.Connection, chaves: Iterable[str]
) -> None:
    conn.execute("DROP TABLE IF EXISTS temp.lev_rubricas_selecionadas")
    conn.execute(
        "CREATE TEMP TABLE lev_rubricas_selecionadas("
        "cod_rubr TEXT NOT NULL, ide_tab_rubr TEXT NOT NULL, "
        "PRIMARY KEY(cod_rubr,ide_tab_rubr))"
    )
    pares = []
    for chave in chaves:
        cod_rubr, separador, ide_tab_rubr = str(chave).partition("||")
        if separador:
            pares.append((cod_rubr, ide_tab_rubr))
    conn.executemany(
        "INSERT OR IGNORE INTO lev_rubricas_selecionadas VALUES(?,?)", pares
    )


def _base_selecionada_sql(filtros: FiltrosLevantamento) -> tuple[str, tuple]:
    where, params = _where_filtros(filtros, "m")
    sql = (
        "SELECT m.* FROM rel_movimentos_cp m "
        "JOIN temp.lev_rubricas_selecionadas s "
        "ON m.cod_rubr=s.cod_rubr "
        "AND m.ide_tab_rubr=s.ide_tab_rubr"
        + where
    )
    return sql, params


def obter_opcoes_filtros(fonte: SQLiteDataSource) -> dict[str, list[str]]:
    conn = fonte.conectar()
    try:
        tem_catalogo = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='rel_rubricas_cp_base'"
        ).fetchone() is not None

        def distintos(campo: str, tabela: str) -> list[str]:
            return [
                str(row[0])
                for row in conn.execute(
                    f"SELECT DISTINCT CAST({campo} AS TEXT) FROM {tabela} "
                    f"WHERE COALESCE(CAST({campo} AS TEXT),'')<>'' ORDER BY 1"
                )
            ]

        tabela_catalogo = "rel_rubricas_cp_base" if tem_catalogo else "rel_movimentos_cp"
        codigos = distintos("cod_inc_cp", tabela_catalogo)
        sem_s1010 = conn.execute(
            f"SELECT 1 FROM {tabela_catalogo} "
            "WHERE COALESCE(cod_inc_cp,'')='' LIMIT 1"
        ).fetchone()
        if sem_s1010:
            codigos.append("Sem S-1010")
        competencias: list[str]
        if tem_catalogo:
            limites = conn.execute(
                "SELECT MIN(primeira_competencia),MAX(ultima_competencia) "
                "FROM rel_rubricas_cp_base"
            ).fetchone()
            inicio = str(limites[0] or "") if limites else ""
            fim = str(limites[1] or "") if limites else ""
            if re.fullmatch(r"\d{4}-\d{2}", inicio) and re.fullmatch(
                r"\d{4}-\d{2}", fim
            ):
                ano, mes = map(int, inicio.split("-"))
                ano_fim, mes_fim = map(int, fim.split("-"))
                competencias = []
                while (ano, mes) <= (ano_fim, mes_fim):
                    competencias.append(f"{ano:04d}-{mes:02d}")
                    mes += 1
                    if mes == 13:
                        ano += 1
                        mes = 1
            else:
                competencias = distintos("per_apur", "rel_movimentos_cp")
        else:
            competencias = distintos("per_apur", "rel_movimentos_cp")

        return {
            "status_cp": distintos("status_cp", tabela_catalogo),
            "carater": distintos("carater_verba", tabela_catalogo),
            "tipo": distintos("tipo_verba", tabela_catalogo),
            "cod_inc_cp": sorted(codigos),
            "competencias": competencias,
        }
    finally:
        conn.close()


def consultar_rubricas(
    fonte: SQLiteDataSource, filtros: FiltrosLevantamento
) -> pd.DataFrame:
    conn = fonte.conectar()
    try:
        tem_catalogo = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='rel_rubricas_cp_base'"
        ).fetchone() is not None

        # Sem recorte por competência, a tabela consolidada contém todas as
        # rubricas necessárias para a seleção e evita reler milhões de movimentos.
        # O filtro de valores positivos continua sendo aplicado, com exatidão, na
        # consulta final do levantamento sobre rel_movimentos_cp.
        if tem_catalogo and not filtros.competencias:
            filtros_catalogo = FiltrosLevantamento(
                status_cp=filtros.status_cp,
                carater=filtros.carater,
                tipo=filtros.tipo,
                cod_inc_cp=filtros.cod_inc_cp,
                competencias=(),
                apenas_positivos=False,
            )
            where, params = _where_filtros(filtros_catalogo, "r")
            sql = """
                SELECT cod_rubr,ide_tab_rubr,dsc_rubr,cod_inc_cp,status_cp,
                       carater_verba,tipo_verba,
                       SUM(CAST(valor_total AS REAL)) valor_total,
                       SUM(CAST(qtd_lancamentos AS INTEGER)) qtd_lancamentos,
                       MAX(CAST(qtd_cpfs AS INTEGER)) qtd_cpfs
                FROM rel_rubricas_cp_base r
            """ + where + """
                GROUP BY cod_rubr,ide_tab_rubr,dsc_rubr,cod_inc_cp,status_cp,
                         carater_verba,tipo_verba
                ORDER BY dsc_rubr,cod_rubr
            """
        else:
            where, params = _where_filtros(filtros, "m")
            sql = """
        SELECT cod_rubr,ide_tab_rubr,dsc_rubr,cod_inc_cp,status_cp,
               carater_verba,tipo_verba,
               SUM(CAST(vr_rubr AS REAL)) valor_total,
               COUNT(*) qtd_lancamentos,
               COUNT(DISTINCT cpf) qtd_cpfs
        FROM rel_movimentos_cp m
    """ + where + """
        GROUP BY cod_rubr,ide_tab_rubr,dsc_rubr,cod_inc_cp,status_cp,
                 carater_verba,tipo_verba
        ORDER BY dsc_rubr,cod_rubr
            """
        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
    if not df.empty:
        df["chave_rubrica"] = (
            df["cod_rubr"].fillna("").astype(str)
            + "||"
            + df["ide_tab_rubr"].fillna("").astype(str)
        )
    return df


def consultar_levantamento(
    fonte: SQLiteDataSource,
    filtros: FiltrosLevantamento,
    chaves: Iterable[str],
    aliquota: float,
    limite_previa: int = 5_000,
) -> ResultadoLevantamentoSQLite:
    conn = fonte.conectar()
    try:
        _preparar_selecao(conn, chaves)
        base_sql, params = _base_selecionada_sql(filtros)
        metricas = conn.execute(
            "SELECT COALESCE(SUM(CAST(vr_rubr AS REAL)),0),COUNT(*),"
            "COUNT(DISTINCT cod_rubr),COUNT(DISTINCT cpf) FROM ("
            + base_sql
            + ") base",
            params,
        ).fetchone()
        resumo_rubricas = pd.read_sql_query(
            "SELECT cod_rubr,dsc_rubr,nat_rubr,cod_inc_cp,status_cp,"
            "carater_verba,tipo_verba,SUM(CAST(vr_rubr AS REAL)) valor_total,"
            "COUNT(*) qtd_lancamentos,COUNT(DISTINCT cpf) qtd_cpfs,"
            "MIN(per_apur) primeira_competencia,MAX(per_apur) ultima_competencia "
            "FROM (" + base_sql + ") base GROUP BY cod_rubr,dsc_rubr,nat_rubr,"
            "cod_inc_cp,status_cp,carater_verba,tipo_verba ORDER BY valor_total DESC",
            conn,
            params=params,
        )
        resumo_comp_rubr = pd.read_sql_query(
            "SELECT per_apur,cod_rubr,dsc_rubr,cod_inc_cp,status_cp,carater_verba,"
            "tipo_verba,SUM(CAST(vr_rubr AS REAL)) valor_total,COUNT(*) qtd_lancamentos,"
            "COUNT(DISTINCT cpf) qtd_cpfs FROM (" + base_sql + ") base "
            "GROUP BY per_apur,cod_rubr,dsc_rubr,cod_inc_cp,status_cp,carater_verba,"
            "tipo_verba ORDER BY per_apur,valor_total DESC",
            conn,
            params=params,
        )
        previa = pd.read_sql_query(
            base_sql + " LIMIT ?", conn, params=params + (int(limite_previa),)
        )
    finally:
        conn.close()

    total = float(metricas[0] or 0)
    for df in (resumo_rubricas, resumo_comp_rubr):
        if not df.empty:
            df["cpp_estimado"] = pd.to_numeric(
                df["valor_total"], errors="coerce"
            ).fillna(0) * (float(aliquota) / 100.0)
    if resumo_comp_rubr.empty:
        matriz = pd.DataFrame(columns=["Periodo de apuracao", "Total", "CPP estimada"])
    else:
        base_matriz = resumo_comp_rubr.copy()
        base_matriz["rubrica_resumo"] = (
            base_matriz["cod_rubr"].fillna("").astype(str).str.strip()
            + " - "
            + base_matriz["dsc_rubr"].fillna("").astype(str).str.strip()
        ).str.strip(" -")
        matriz = (
            base_matriz.pivot_table(
                index="per_apur",
                columns="rubrica_resumo",
                values="valor_total",
                aggfunc="sum",
                fill_value=0,
            )
            .reset_index()
            .rename(columns={"per_apur": "Periodo de apuracao"})
        )
        colunas = [c for c in matriz.columns if c != "Periodo de apuracao"]
        matriz["Total"] = matriz[colunas].sum(axis=1) if colunas else 0.0
        matriz["CPP estimada"] = matriz["Total"] * (float(aliquota) / 100.0)
        matriz = matriz.sort_values("Periodo de apuracao")
    return ResultadoLevantamentoSQLite(
        total=total,
        cpp=total * (float(aliquota) / 100.0),
        qtd_movimentos=int(metricas[1] or 0),
        qtd_rubricas=int(metricas[2] or 0),
        qtd_cpfs=int(metricas[3] or 0),
        resumo_rubricas=resumo_rubricas,
        resumo_competencia_rubrica=resumo_comp_rubr,
        resumo_competencia=matriz,
        movimentos_previa=previa,
    )


def gerar_excel_levantamento_sqlite(
    fonte: SQLiteDataSource,
    caminho_saida: str | Path,
    filtros: FiltrosLevantamento,
    chaves: Iterable[str],
    resultado: ResultadoLevantamentoSQLite,
    df_empresa: pd.DataFrame,
    df_parametros: pd.DataFrame,
    incluir_movimentos: bool,
    progress_callback=None,
) -> ResultadoWorkbook:
    conn = fonte.conectar()
    try:
        _preparar_selecao(conn, chaves)
        base_sql, params = _base_selecionada_sql(filtros)
        if incluir_movimentos:
            fonte_movimentos = FontePlanilha(
                "03_movimentos", query=base_sql, params=params
            )
        else:
            fonte_movimentos = FontePlanilha(
                "03_movimentos",
                dataframe=pd.DataFrame(
                    {
                        "Informação": [
                            "A aba detalhada 03_movimentos não foi incluída nesta exportação.",
                            "Para incluir os movimentos detalhados, marque a opção correspondente antes de preparar o arquivo.",
                            "Os valores do levantamento estão preservados nas abas de resumo.",
                        ],
                        "Valor": [
                            f"Movimentos detalhados disponíveis no recorte: {resultado.qtd_movimentos:,}".replace(",", "."),
                            "Exportação otimizada para arquivos grandes",
                            "Total levantado: R$ "
                            + f"{resultado.total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                        ],
                    }
                ),
            )
        return gerar_workbook(
            caminho_saida,
            [
                FontePlanilha("00_empresa", dataframe=df_empresa),
                FontePlanilha("01_resumo", dataframe=df_parametros),
                FontePlanilha("02_resumo_rubricas", dataframe=resultado.resumo_rubricas),
                fonte_movimentos,
                FontePlanilha("04_resumo_competencia", dataframe=resultado.resumo_competencia),
                FontePlanilha("05_competencia_rubrica", dataframe=resultado.resumo_competencia_rubrica),
            ],
            conexao=conn,
            progress_callback=progress_callback,
        )
    finally:
        conn.close()
