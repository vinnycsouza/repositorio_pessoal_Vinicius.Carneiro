import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from modules.workspace_manager import (
    abrir_workspace,
    enviar_workspace_para_lixeira,
    formatar_tamanho,
    listar_workspaces_disponiveis,
    obter_info_workspace,
    pasta_padrao_workspaces,
)


class WorkspaceManagerTest(unittest.TestCase):
    def _criar_workspace(self, pasta: str, status: str = "concluido") -> Path:
        workspace = Path(pasta) / "esocial_v3_teste"
        workspace.mkdir()
        db_path = workspace / "processamento.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE meta(chave TEXT PRIMARY KEY, valor TEXT)")
            conn.execute("INSERT INTO meta VALUES('status', ?)", (status,))
            conn.commit()
        finally:
            conn.close()
        (workspace / "arquivo.log").write_text("teste", encoding="utf-8")
        return workspace

    def test_obtem_informacoes_do_workspace_atual(self):
        with tempfile.TemporaryDirectory() as pasta:
            workspace = self._criar_workspace(pasta)
            info = obter_info_workspace(
                {
                    "workspace_temporario": str(workspace),
                    "empresa": pd.DataFrame(
                        [{"nome_empresa": "Empresa Teste", "cnpj_empregador": "12345678000199"}]
                    ),
                }
            )
            self.assertEqual(info.nome_empresa, "Empresa Teste")
            self.assertEqual(info.cnpj, "12.345.678/0001-99")
            self.assertEqual(info.status, "Concluído")
            self.assertGreater(info.tamanho_total, 0)
            self.assertGreater(info.tamanho_sqlite, 0)

    def test_identifica_workspace_em_processamento(self):
        with tempfile.TemporaryDirectory() as pasta:
            workspace = self._criar_workspace(pasta, status="processando")
            info = obter_info_workspace({"workspace_temporario": str(workspace)})
            self.assertEqual(info.status, "Em processamento")

    def test_envia_para_lixeira_sem_exclusao_definitiva(self):
        with tempfile.TemporaryDirectory() as pasta:
            workspace = self._criar_workspace(pasta)
            with patch("modules.workspace_manager.send2trash") as enviar:
                enviar_workspace_para_lixeira(workspace)
            enviar.assert_called_once_with(str(workspace.resolve()))
            self.assertTrue(workspace.exists())

    @unittest.skipUnless(os.name == "nt", "Abertura principal testada no Windows")
    def test_abre_workspace_no_explorador_do_windows(self):
        with tempfile.TemporaryDirectory() as pasta:
            workspace = self._criar_workspace(pasta)
            with patch("modules.workspace_manager.os.startfile") as abrir:
                abrir_workspace(workspace)
            abrir.assert_called_once_with(str(workspace.resolve()))

    def test_formata_tamanho(self):
        self.assertEqual(formatar_tamanho(1024**3), "1,0 GB")
        self.assertEqual(formatar_tamanho(None), "Não disponível")

    def test_lista_workspaces_com_metadados_sem_carregar_tabelas_inteiras(self):
        with tempfile.TemporaryDirectory() as pasta:
            workspace = self._criar_workspace(pasta)
            db_path = workspace / "processamento.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE dados_empresa(nome_empresa TEXT,cnpj_empregador TEXT)"
                )
                conn.execute(
                    "INSERT INTO dados_empresa VALUES('Empresa Catálogo','12345678000199')"
                )
                conn.execute("CREATE TABLE eventos(id INTEGER PRIMARY KEY)")
                conn.executemany("INSERT INTO eventos DEFAULT VALUES", [(), (), ()])
                conn.execute("CREATE TABLE rel_movimentos_cp(per_apur TEXT)")
                conn.executemany(
                    "INSERT INTO rel_movimentos_cp VALUES(?)",
                    [("2025-01",), ("2026-06",)],
                )
                conn.execute("INSERT INTO meta VALUES('atualizado_em','100')")
                conn.commit()
            finally:
                conn.close()

            itens = listar_workspaces_disponiveis(pasta)
            self.assertEqual(len(itens), 1)
            item = itens[0]
            self.assertEqual(item.nome_empresa, "Empresa Catálogo")
            self.assertEqual(item.cnpj, "12.345.678/0001-99")
            self.assertEqual(item.quantidade_xml, 3)
            self.assertEqual(item.periodo_minimo, "2025-01")
            self.assertEqual(item.periodo_maximo, "2026-06")
            self.assertTrue(item.carregavel)
            self.assertIn("Empresa Catálogo", item.rotulo)

    def test_lista_interrompido_mas_nao_permite_carregamento(self):
        with tempfile.TemporaryDirectory() as pasta:
            self._criar_workspace(pasta, status="interrompido")
            item = listar_workspaces_disponiveis(pasta)[0]
            self.assertEqual(item.status, "Interrompido")
            self.assertFalse(item.carregavel)

    def test_ignora_pasta_sem_processamento_db(self):
        with tempfile.TemporaryDirectory() as pasta:
            (Path(pasta) / "pasta_qualquer").mkdir()
            self.assertEqual(listar_workspaces_disponiveis(pasta), [])

    def test_pasta_padrao_respeita_configuracao(self):
        with tempfile.TemporaryDirectory() as pasta:
            with patch.dict(os.environ, {"ESOCIAL_WORKSPACES_DIR": pasta}):
                self.assertEqual(pasta_padrao_workspaces(), Path(pasta).resolve())


if __name__ == "__main__":
    unittest.main()
