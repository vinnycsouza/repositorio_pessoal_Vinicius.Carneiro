from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from auditor_sped_integrado.diagnostico_st import (
    diagnosticar_st_c100, diagnosticar_st_c170, diagnosticar_st_c190, diagnosticar_vendas_st_c175,
)


class DiagnosticoSTTest(unittest.TestCase):
    def test_c190_quantifica_sem_somar_ao_c170(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as pasta:
            arquivo = Path(pasta) / "icms.xlsx"
            pd.DataFrame([{
                "Mês": "Agosto", "Ano": 2023, "CNPJ": "10693312000181",
                "Indicador de Operação(C100)": 0, "CFOP": 1403, "Valor de Icms ST": 8.75,
            }]).to_excel(arquivo, sheet_name="C190 - Analítico", index=False)
            resultado = diagnosticar_st_c190(arquivo)
            self.assertEqual(resultado["registros_c190"].sum(), 1)
            self.assertAlmostEqual(resultado["valor_icms_st_destacado"].sum(), 8.75)

    def test_c175_separa_tributado_de_aliquota_zero(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as pasta:
            arquivo = Path(pasta) / "contribuicoes.xlsx"
            base = {
                "Mês": "Agosto", "Ano": 2023, "CNPJ Estabelecimento(C010)": "10693312000181",
                "Situação(C100)": "00", "CFOP": 5405, "Valor da Operação": 100,
                "CST PIS": "01", "Valor BC PIS": 100, "Aliquota PIS perc.": 1.65, "Valor PIS": 1.65,
                "CST COFINS": "01", "Valor BC COFINS": 100, "Aliquota COFINS perc.": 7.6, "Valor COFINS": 7.6,
            }
            with pd.ExcelWriter(arquivo) as livro:
                pd.DataFrame([base]).to_excel(livro, sheet_name="C175 - Analítico", index=False)
                pd.DataFrame([{**base, "CST PIS": "04", "CST COFINS": "04", "Valor PIS": 0,
                               "Valor COFINS": 0}, {**base, "CFOP": 5102}]).to_excel(
                                   livro, sheet_name="C175 - Analítico--2", index=False)
            resultado = diagnosticar_vendas_st_c175(arquivo)
            self.assertEqual(resultado["registros_c175"].sum(), 2)
            self.assertEqual(set(resultado["cst_pis"]), {"01", "04"})
            self.assertAlmostEqual(resultado["valor_pis"].sum(), 1.65)

    def test_c100_le_aba_de_continuacao(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as pasta:
            arquivo = Path(pasta) / "contribuicoes.xlsx"
            base = {
                "Mês": "Agosto", "Ano": 2023, "CNPJ Estabelecimento(C010)": "10693312000181",
                "Indicador de Operação": 0, "Situação": "00", "Valor de ICMS - ST": 12.34,
            }
            with pd.ExcelWriter(arquivo) as livro:
                pd.DataFrame([{**base, "Valor de ICMS - ST": 0}]).to_excel(livro, sheet_name="C100 - Nota Fiscal", index=False)
                pd.DataFrame([base, {**base, "Situação": "02"}]).to_excel(livro, sheet_name="C100 - Nota Fiscal--2", index=False)
            resultado = diagnosticar_st_c100(arquivo)
            self.assertEqual(resultado["documentos_com_st"].sum(), 1)
            self.assertAlmostEqual(resultado["valor_icms_st_destacado"].sum(), 12.34)
            self.assertEqual(resultado.iloc[0]["aba"], "C100 - Nota Fiscal--2")

    def test_soma_entradas_e_separa_transferencias(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as pasta:
            arquivo = Path(pasta) / "contribuicoes.xlsx"
            comum = {
                "Mês": "Agosto", "Ano": 2023, "CNPJ Estabelecimento(C010)": "10693312000181",
                "Indicador de Operação(C100)": 0, "Situação(C100)": "00",
            }
            linhas = [
                {**comum, "CFOP": 1403, "Valor de Icms ST": 10.25},
                {**comum, "CFOP": 1403, "Valor de Icms ST": 2.10},
                {**comum, "CFOP": 1409, "Valor de Icms ST": 5.00},
                {**comum, "CFOP": 5405, "Indicador de Operação(C100)": 1, "Valor de Icms ST": 100.00},
                {**comum, "CFOP": 1403, "Situação(C100)": "02", "Valor de Icms ST": 100.00},
            ]
            with pd.ExcelWriter(arquivo) as livro:
                pd.DataFrame({"Mês": ["Agosto"], "Ano": [2023], "COD_INC_TRIB": [1]}).to_excel(livro, sheet_name="0110", index=False)
                pd.DataFrame(linhas).to_excel(livro, sheet_name="C170 - Itens da Nota", index=False)
            resultado = diagnosticar_st_c170(arquivo)
            self.assertEqual(resultado["itens_com_st"].sum(), 3)
            self.assertAlmostEqual(resultado["valor_icms_st_destacado"].sum(), 17.35)
            self.assertEqual(resultado.set_index("cfop").loc["1409", "tipo_operacao"], "Transferência")
            self.assertEqual(set(resultado["regime_0110"]), {"1"})


if __name__ == "__main__":
    unittest.main()
