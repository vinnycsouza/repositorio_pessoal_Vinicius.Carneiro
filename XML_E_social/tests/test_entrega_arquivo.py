import tempfile
import unittest
from pathlib import Path

from modules.entrega_arquivo import (
    LIMITE_DOWNLOAD_STREAMLIT,
    copiar_para_downloads,
    exige_entrega_local,
)


class EntregaArquivoTest(unittest.TestCase):
    def test_identifica_arquivo_acima_do_limite_sem_ler_conteudo(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "grande.xlsx"
            with arquivo.open("wb") as fp:
                fp.truncate(LIMITE_DOWNLOAD_STREAMLIT + 1)
            self.assertTrue(exige_entrega_local(arquivo))

    def test_copia_para_downloads_sem_sobrescrever_existente(self):
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            origem = raiz / "relatorio.xlsx"
            downloads = raiz / "Downloads"
            origem.write_bytes(b"conteudo")

            primeiro = copiar_para_downloads(origem, downloads)
            segundo = copiar_para_downloads(origem, downloads)

            self.assertEqual(primeiro.name, "relatorio.xlsx")
            self.assertEqual(segundo.name, "relatorio (1).xlsx")
            self.assertEqual(segundo.read_bytes(), b"conteudo")


if __name__ == "__main__":
    unittest.main()
