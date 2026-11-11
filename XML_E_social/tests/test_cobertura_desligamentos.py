import sqlite3
import unittest
from io import BytesIO
from types import SimpleNamespace

import pandas as pd
from openpyxl import Workbook

from modules.levantamento_sqlite import cobertura_desligamentos_excel, cobertura_desligamentos_sqlite


class CoberturaDesligamentosTest(unittest.TestCase):
    def fonte(self, com_s2299=True):
        conn = sqlite3.connect(":memory:")
        colunas = "(cod_rubr TEXT,ide_tab_rubr TEXT,dsc_rubr TEXT,per_apur TEXT,cod_inc_cp TEXT)"
        conn.execute("CREATE TABLE rel_movimentos_cp " + colunas)
        conn.executemany("INSERT INTO rel_movimentos_cp VALUES (?,?,?,?,?)", [
            ("0292", "A", "Folha", "2026-01", "11"),
            ("7896", "A", "Compartilhada", "2026-02", "00"),
        ])
        if com_s2299:
            conn.execute("CREATE TABLE rel_movimentos_s2299 " + colunas)
            conn.executemany("INSERT INTO rel_movimentos_s2299 VALUES (?,?,?,?,?)", [
                ("0292", "B", "Rescisão", "2026-02", "12"),
                ("7896", "A", "Compartilhada", "2026-02", "00"),
                ("5511", "A", "Histórica", "2021-04", "00"),
                ("7896", "A", "Compartilhada", "2026-02", "00"),
            ])
        return SimpleNamespace(conectar=lambda: conn)

    def test_compara_codigo_tabela_e_periodo_sem_filtrar_cp(self):
        qtd, rubricas = cobertura_desligamentos_sqlite(self.fonte(), ("2026-02",))
        self.assertEqual(qtd, 2)
        self.assertEqual(list(zip(rubricas.cod_rubr, rubricas.ide_tab_rubr)), [("0292", "B")])

    def test_distingue_fonte_indisponivel_de_periodo_sem_movimento(self):
        self.assertIsNone(cobertura_desligamentos_sqlite(self.fonte(False))[0])
        self.assertEqual(cobertura_desligamentos_sqlite(self.fonte(), ("2026-01",))[0], 0)

    def test_excel_le_abas_particionadas_e_preserva_zeros(self):
        wb = Workbook(write_only=True)
        for nome, itens in {
            "03_movimentos_cp_1": [("7896", "A", "2026-02", "Comum")],
            "03_movimentos_cp_2": [("7897", "A", "2026-02", "Comum")],
            "apoio_s2299_1": [("7897", "A", "2026-02", "Comum")],
            "apoio_s2299_2": [("0292", "A", "2026-02", "Rescisão")],
        }.items():
            aba = wb.create_sheet(nome)
            aba.append(["cod_rubr", "ide_tab_rubr", "per_apur", "dsc_rubr"])
            for item in itens:
                aba.append(item)
        arquivo = BytesIO()
        wb.save(arquivo)
        arquivo.seek(0)
        with pd.ExcelFile(arquivo, engine="openpyxl") as xls:
            qtd, rubricas = cobertura_desligamentos_excel(xls, ("2026-02",))
        self.assertEqual(qtd, 2)
        self.assertEqual(rubricas.cod_rubr.tolist(), ["0292"])
