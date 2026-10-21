"""Acumula vendas C175 por NF-e sem manter todas as linhas em memória."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory


def _centavos(valor: Decimal) -> int:
    return int((valor * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class ConferenciaNFe:
    def __init__(self) -> None:
        self._diretorio = TemporaryDirectory(prefix="auditor_sped_nfe_", dir=Path(__file__).resolve().parent)
        self._conexao = sqlite3.connect(str(Path(self._diretorio.name) / "vendas.db"))
        self._conexao.execute("""CREATE TABLE vendas (
            competencia TEXT, cnpj TEXT, chave TEXT, chave_ok INTEGER, uf TEXT,
            regime TEXT, aliquota_pis REAL, aliquota_cofins REAL,
            operacao INTEGER, desconto INTEGER, base_pis INTEGER, pis INTEGER,
            base_cofins INTEGER, cofins INTEGER, base_ok INTEGER, duplicado INTEGER,
            aba TEXT, linha INTEGER, fonte_pis TEXT, fonte_cofins TEXT
        )""")
        self._pendentes: list[tuple] = []

    def adicionar(
        self, *, competencia: str, cnpj: str, chave: str, chave_ok: bool,
        uf: str, regime: str, aliquota_pis: Decimal, aliquota_cofins: Decimal,
        operacao: Decimal, desconto: Decimal, base_pis: Decimal, pis: Decimal,
        base_cofins: Decimal, cofins: Decimal, base_ok: bool,
        duplicado: bool, aba: str, linha: int,
        fonte_pis: str = "C175", fonte_cofins: str = "C175",
    ) -> None:
        # Uma linha sem chave fica identificável individualmente para revisão.
        identificador = chave or f"SEM_CHAVE:{aba}:{linha}"
        self._pendentes.append((
            competencia, cnpj, identificador, int(chave_ok), uf, regime,
            float(aliquota_pis), float(aliquota_cofins),
            *(_centavos(v) for v in (operacao, desconto, base_pis, pis, base_cofins, cofins)),
            int(base_ok), int(duplicado), aba, linha, fonte_pis, fonte_cofins,
        ))
        if len(self._pendentes) >= 5000:
            self._gravar()

    def _gravar(self) -> None:
        if self._pendentes:
            self._conexao.executemany("INSERT INTO vendas VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self._pendentes)
            self._pendentes.clear()

    def linhas(self):
        self._gravar()
        self._conexao.execute("CREATE INDEX IF NOT EXISTS vendas_por_nfe ON vendas (competencia, cnpj, chave)")
        consulta = """SELECT competencia, cnpj, chave, MIN(chave_ok), MIN(uf),
            MIN(regime), MIN(aliquota_pis), MAX(aliquota_pis),
            MIN(aliquota_cofins), MAX(aliquota_cofins),
            COUNT(*)-SUM(duplicado), SUM(operacao), SUM(desconto),
            SUM(base_pis), SUM(pis), SUM(base_cofins), SUM(cofins),
            SUM(CASE WHEN base_ok=0 AND duplicado=0 THEN 1 ELSE 0 END),
            SUM(duplicado), MIN(aba), MIN(linha),
            MAX(CASE WHEN fonte_pis='C175' THEN '' ELSE fonte_pis END),
            MAX(CASE WHEN fonte_cofins='C175' THEN '' ELSE fonte_cofins END)
            FROM vendas GROUP BY competencia, cnpj, chave
            ORDER BY competencia, cnpj, chave"""
        for linha in self._conexao.execute(consulta):
            yield linha

    def fechar(self) -> None:
        self._conexao.close()
        self._diretorio.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()
