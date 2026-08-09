import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from modules.processador_zip import _segunda_passagem
from modules.sqlite_relatorio import _metricas_movimentos, carregar_pacote_resumido


class OtimizacoesGrandesVolumesTest(unittest.TestCase):
    def test_lote_por_bytes_processa_todos_os_eventos_sem_saltar(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript("""
                CREATE TABLE eventos(
                    id INTEGER PRIMARY KEY, arquivo TEXT, tipo TEXT,
                    xml_zlib BLOB, processado_segunda INTEGER, ativo INTEGER
                );
                CREATE TABLE objetos(
                    id INTEGER PRIMARY KEY, categoria TEXT,
                    evento_id INTEGER, payload BLOB
                );
                CREATE TABLE erros(id INTEGER PRIMARY KEY, arquivo TEXT, erro TEXT);
                CREATE TABLE meta(chave TEXT PRIMARY KEY, valor TEXT);
            """)
            blob = zlib.compress(b"<eSocial/>")
            conn.executemany(
                "INSERT INTO eventos VALUES(?,?,?,?,0,1)",
                [(indice, f"evento_{indice}.xml", "S-1200", blob) for indice in range(1, 6)],
            )
            with patch.dict(
                "os.environ", {"ESOCIAL_MAX_BYTES_LOTE_SEGUNDA_PASSAGEM": "1"}
            ), patch("modules.processador_zip.parse_s1200", return_value=[]):
                _segunda_passagem(conn, None)
            processados = conn.execute(
                "SELECT COUNT(*) FROM eventos WHERE processado_segunda=1"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(processados, 5)

    def test_metricas_consolidadas_preservam_contagens_e_valores(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                "CREATE TABLE rel_movimentos_cp(vr_rubr REAL, considerado_cp TEXT, status_cp TEXT)"
            )
            conn.executemany(
                "INSERT INTO rel_movimentos_cp VALUES(?,?,?)",
                [
                    (100.0, "Sim", "Incide CP"),
                    (25.5, "Não", "Não incide CP"),
                    (-10.0, "Não", "Sem S-1010"),
                    (5.0, "Não", "Revisar codIncCP"),
                    (None, "Não", "Não incide CP"),
                ],
            )
            metricas = _metricas_movimentos(conn)
        finally:
            conn.close()

        self.assertEqual(metricas["total"], 5)
        self.assertAlmostEqual(metricas["valor_total"], 120.5)
        self.assertAlmostEqual(metricas["valor_incide"], 100.0)
        self.assertAlmostEqual(metricas["valor_nao_incide"], 25.5)
        self.assertEqual(metricas["qtd_padrao"], 1)
        self.assertEqual(metricas["qtd_prioritaria"], 2)
        self.assertEqual(metricas["qtd_classificados"], 4)
        self.assertEqual(metricas["qtd_sem_s1010"], 1)

    def test_pacote_resumido_reutiliza_metricas_consolidadas(self):
        with tempfile.TemporaryDirectory() as pasta:
            db = Path(pasta) / "processamento.db"
            conn = sqlite3.connect(db)
            try:
                conn.executescript("""
                    CREATE TABLE rel_movimentos_cp(
                        vr_rubr REAL, considerado_cp TEXT, status_cp TEXT
                    );
                    INSERT INTO rel_movimentos_cp VALUES(10,'Sim','Incide CP');
                    INSERT INTO rel_movimentos_cp VALUES(20,'Não','Sem S-1010');
                    CREATE TABLE rel_rubricas_cp_base(status_cp TEXT, carater_verba TEXT, valor_total REAL);
                    CREATE TABLE dados_bases_trabalhador(valor REAL);
                    CREATE TABLE rel_base_trabalhador(status_conferencia TEXT);
                    CREATE TABLE rel_sem_s1010(valor_rubrica REAL);
                    CREATE TABLE rel_s5001_resumo(valor_s5001 REAL);
                    CREATE TABLE rel_controle_integridade(tabela TEXT, quantidade INTEGER, soma_valores REAL);
                """)
                conn.commit()
            finally:
                conn.close()

            pacote = carregar_pacote_resumido(db)
            self.assertEqual(pacote["total_movimentos_cp"], 2)
            self.assertEqual(pacote["total_movimentos_cp_padrao"], 1)
            self.assertEqual(pacote["total_movimentos_sem_s1010"], 1)


if __name__ == "__main__":
    unittest.main()
