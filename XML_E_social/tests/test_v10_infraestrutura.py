import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.processador_zip import (
    _criar_schema,
    preparar_workspace_para_relatorios,
)
from modules.sqlite_writer import BatchPolicy, SQLiteWriter
from modules.xsd_validator import modo_validacao_xsd, validar_xml_xsd


class ValidacaoXSDTest(unittest.TestCase):
    def test_validacao_fica_desligada_por_padrao(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(modo_validacao_xsd(), "desligada")
            resultado = validar_xml_xsd(b"<eSocial/>", "S-1200", "a" * 64)
        self.assertFalse(resultado.executada)
        self.assertTrue(resultado.valida)
        self.assertEqual(resultado.status, "desligada")

    def test_modo_completo_sem_diretorio_nao_rejeita_xml(self):
        with patch.dict(
            os.environ,
            {"ESOCIAL_VALIDACAO_XSD": "completa", "ESOCIAL_XSD_DIR": ""},
            clear=True,
        ):
            resultado = validar_xml_xsd(b"<eSocial/>", "S-1200", "b" * 64)
        self.assertFalse(resultado.executada)
        self.assertTrue(resultado.valida)
        self.assertEqual(resultado.status, "diretorio_xsd_nao_configurado")

    def test_amostragem_zero_e_deterministica(self):
        with patch.dict(
            os.environ,
            {"ESOCIAL_VALIDACAO_XSD": "amostral", "ESOCIAL_XSD_TAXA_AMOSTRA": "0"},
            clear=True,
        ):
            resultado = validar_xml_xsd(b"<eSocial/>", "S-1200", "f" * 64)
        self.assertEqual(resultado.status, "fora_da_amostra")


class EscritaAdaptativaTest(unittest.TestCase):
    def test_pressao_de_memoria_reduz_lote(self):
        with patch("modules.sqlite_writer.memoria_disponivel_bytes", return_value=1024**3):
            policy = BatchPolicy.atual("analitico")
        self.assertTrue(policy.pressao_memoria)
        self.assertEqual(policy.max_itens, 2_500)
        self.assertEqual(policy.max_bytes, 12 * 1024**2)

    def test_writer_registra_telemetria(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            "CREATE TABLE destino(valor INTEGER);"
            "CREATE TABLE telemetria(chave TEXT PRIMARY KEY,valor TEXT,unidade TEXT,atualizado_em REAL);"
        )
        writer = SQLiteWriter(conn, BatchPolicy(10, 1024, False))
        writer.executemany("INSERT INTO destino(valor) VALUES(?)", [(1,), (2,)])
        writer.commit()
        writer.registrar_telemetria()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM destino").fetchone()[0], 2)
        self.assertEqual(
            conn.execute(
                "SELECT valor FROM telemetria WHERE chave='sqlite_writer_linhas'"
            ).fetchone()[0],
            "2",
        )
        conn.close()


class MigracaoWorkspaceV10Test(unittest.TestCase):
    def test_migracao_cria_backup_logico_e_mantem_meta_anterior(self):
        with tempfile.TemporaryDirectory() as pasta:
            workspace = Path(pasta)
            db_path = workspace / "processamento.db"
            conn = sqlite3.connect(db_path)
            _criar_schema(conn)
            conn.execute(
                "INSERT INTO meta(chave,valor) VALUES('marcador_legado','preservar')"
            )
            conn.execute(
                "INSERT INTO meta(chave,valor) VALUES('versao_consistencia_recibo_s1200','3') "
                "ON CONFLICT(chave) DO UPDATE SET valor='3'"
            )
            conn.commit()
            conn.close()

            resultado = preparar_workspace_para_relatorios(db_path)
            self.assertEqual(resultado["verificacao_executada"], 1)

            conn = sqlite3.connect(db_path)
            try:
                migracao = conn.execute(
                    "SELECT id,status FROM migracoes_workspace ORDER BY id DESC LIMIT 1"
                ).fetchone()
                backup = conn.execute(
                    "SELECT valor FROM backup_logico_migracao "
                    "WHERE migracao_id=? AND categoria='meta' AND chave='marcador_legado'",
                    (migracao[0],),
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(migracao[1], "concluida")
            self.assertEqual(backup[0], "preservar")


if __name__ == "__main__":
    unittest.main()
