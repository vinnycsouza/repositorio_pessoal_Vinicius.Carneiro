import unittest
from unittest.mock import patch

import pandas as pd

from modules.comparador import comparar, normalizar_competencia
from modules.levantamento_parser import identificar_modelo, importar_modelo


class ModelosTest(unittest.TestCase):
    def importar(self, modelo, *bases):
        with patch("modules.levantamento_parser.pd.ExcelFile"), patch(
            "modules.levantamento_parser.pd.read_excel", side_effect=bases
        ):
            return importar_modelo(b"modelo", modelo)

    def test_identifica_modelos(self):
        self.assertEqual(identificar_modelo(["K300_FILTRADO", "K150_SELECIONADAS"]), "MANAD")
        self.assertEqual(identificar_modelo(["00_empresa", "03_movimentos"]), "XML/eSocial")
        self.assertIsNone(identificar_modelo(["Planilha1"]))

    def test_manad_converte_e_preserva_repeticoes(self):
        linha = {"CNPJ/CEI": "20364206000108", "DT_COMP": "012021", "COD_RUBR": "9501", "VLR_RUBR": "1.234,56"}
        base = pd.DataFrame([linha, linha, dict(linha, COD_RUBR="9999")])
        cadastro = pd.DataFrame([{"COD_RUBRICA": "9501", "DESC_RUBRICA": "Salário Família"}])
        preparado, detalhe, avisos = self.importar("MANAD", base, cadastro)
        self.assertEqual(len(detalhe), 2)
        self.assertEqual(preparado.iloc[0]["competencia"], "01/2021")
        self.assertAlmostEqual(preparado.iloc[0]["valor_levantamento"], 2469.12)
        self.assertTrue(any("repetidas" in a for a in avisos))

    def base_xml(self, **extra):
        return pd.DataFrame([dict({"nr_insc_estab": "02633573000188", "tp_insc_estab": "1", "per_apur": "2026-01", "vr_rubr": 0, "dsc_rubr": "SALARIO-FAMILIA", "evento_id_origem": 10, "caminho_item": "item[1]"}, **extra)])

    def test_xml_preserva_zero_cnpj_e_trilha(self):
        preparado, detalhe, _ = self.importar("XML/eSocial", self.base_xml())
        self.assertEqual(preparado.iloc[0]["cnpj"], "02633573000188")
        self.assertEqual(preparado.iloc[0]["valor_levantamento"], 0)
        self.assertEqual(detalhe.iloc[0]["evento_id_origem"], 10)

    def test_xml_sem_verba_nao_vira_zero(self):
        preparado, _, avisos = self.importar("XML/eSocial", self.base_xml(dsc_rubr="SALARIO MATERNIDADE"))
        self.assertTrue(preparado.empty)
        self.assertTrue(any("não representa valor zero" in a for a in avisos))

    def test_rejeita_raiz_periodo_anual_e_valor_invalido(self):
        for extra in [{"nr_insc_estab": "02633573"}, {"per_apur": "2026"}, {"vr_rubr": "inválido"}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.importar("XML/eSocial", self.base_xml(**extra))

    def test_comparacao_cronologica_preserva_ausencia(self):
        ecac = pd.DataFrame([{"cnpj": "20364206000108", "competencia": c, "salario_familia": None} for c in ["01/2023", "12/2021", "01/2022"]])
        levantamento = pd.DataFrame([{"cnpj": "20364206000108", "competencia": c, "valor_levantamento": 10} for c in ecac.competencia])
        resultado = comparar(ecac, levantamento)
        self.assertEqual(resultado.competencia.tolist(), ["12/2021", "01/2022", "01/2023"])
        self.assertTrue(resultado.valor_ecac.isna().all())
        self.assertEqual(normalizar_competencia("012021"), "01/2021")


if __name__ == "__main__":
    unittest.main()
