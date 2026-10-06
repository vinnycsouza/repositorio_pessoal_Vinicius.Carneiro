import unittest

import pandas as pd

from modules.comparador import comparar, preparar_levantamento


class ComparadorTest(unittest.TestCase):
    def test_compara_por_cnpj_e_competencia(self):
        ecac = pd.DataFrame([
            {"cnpj": "20.364.206/0001-08", "competencia": "03/2026", "salario_familia": 1512.02}
        ])
        bruto = pd.DataFrame([
            {"CNPJ": "20364206000108", "Período": "2026-03", "Descrição": "Salário Família", "Valor": 2000.0}
        ])
        levantamento = preparar_levantamento(
            bruto, "CNPJ", "Período", "Valor", "MANAD", "Descrição", "salario familia"
        )
        resultado = comparar(ecac, levantamento).iloc[0]
        self.assertAlmostEqual(resultado["diferença_potencial"], 487.98)
        self.assertEqual(resultado["situação"], "Potencial valor não deduzido")


if __name__ == "__main__":
    unittest.main()

