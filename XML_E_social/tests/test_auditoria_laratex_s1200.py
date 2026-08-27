import unittest

from benchmarks.auditar_laratex_s1200 import comparar


class AuditoriaLaraTexS1200Test(unittest.TestCase):
    def test_separa_rubrica_totalmente_ausente_e_divergencia(self):
        laratex = {
            ("A", "T1", "2026-01"): [2, 1000],
            ("B", "T1", "2026-01"): [1, 500],
        }
        workspace = {
            ("A", "T1", "2026-01"): [2, 900],
            ("C", "T1", "2026-01"): [1, 100],
        }
        resultado = comparar(laratex, workspace)
        self.assertEqual(resultado["rubricas_totalmente_ausentes"], 1)
        self.assertEqual(resultado["chaves_competencia_ausentes"], 1)
        self.assertEqual(resultado["chaves_com_contagem_ou_valor_divergente"], 1)
        self.assertEqual(resultado["rubricas_ausentes"][0]["codigo"], "B")
        self.assertEqual(resultado["ausencias_por_competencia"][0]["valor"], 5.0)


if __name__ == "__main__":
    unittest.main()
