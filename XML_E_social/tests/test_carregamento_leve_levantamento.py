import sqlite3
import tempfile
import unittest
from pathlib import Path

from modules.processador_zip import carregar_resultado_sqlite_existente


class CarregamentoLeveLevantamentoTest(unittest.TestCase):
    def test_nao_carrega_previas_nem_varre_pacote_geral(self):
        with tempfile.TemporaryDirectory() as pasta:
            db = Path(pasta) / "processamento.db"
            conn = sqlite3.connect(db)
            try:
                conn.executescript("""
                    CREATE TABLE meta(chave TEXT PRIMARY KEY, valor TEXT);
                    INSERT INTO meta VALUES('status','concluido');
                    CREATE TABLE eventos(id INTEGER PRIMARY KEY, arquivo TEXT, tipo TEXT,
                        tamanho_bytes INTEGER, envelope_recibo INTEGER);
                    CREATE TABLE rel_movimentos_cp(cod_rubr TEXT);
                    CREATE TABLE rel_rubricas_cp_base(cod_rubr TEXT);
                    CREATE TABLE rel_controle_integridade(
                        tabela TEXT, quantidade INTEGER, soma_valores REAL);
                    INSERT INTO rel_controle_integridade
                        VALUES('rel_movimentos_cp',25000000,123.0);
                    CREATE TABLE contagem_eventos(tipo TEXT, quantidade INTEGER);
                    INSERT INTO contagem_eventos VALUES('S-1200',7000000);
                    CREATE TABLE dados_empresa(nome_empresa TEXT,cnpj_empregador TEXT);
                    INSERT INTO dados_empresa VALUES('Empresa Teste','12345678000199');
                    INSERT INTO dados_empresa VALUES('Empresa Teste','12345678000199');
                """)
                conn.commit()
            finally:
                conn.close()

            resultado = carregar_resultado_sqlite_existente(
                db, somente_levantamento=True
            )
            self.assertTrue(resultado["modo_sqlite_seguro"])
            self.assertTrue(resultado["inventario"].empty)
            self.assertTrue(resultado["pacote_sqlite"]["movimentos_cp"].empty)
            self.assertEqual(
                resultado["pacote_sqlite"]["total_movimentos_cp"], 25_000_000
            )
            self.assertEqual(resultado["quantidade_xml_spool"], 7_000_000)
            self.assertEqual(len(resultado["empresa"]), 1)


if __name__ == "__main__":
    unittest.main()
