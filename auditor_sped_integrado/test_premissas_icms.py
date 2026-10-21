from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from auditor_sped_integrado.diagnostico_st import diagnosticar_vendas_st_c175
from auditor_sped_integrado.premissas_icms import (
    buscar_premissa, simular_potencial, validar_historico_regime,
)


def chave(ano: int, mes: int) -> str:
    return f"26{ano % 100:02d}{mes:02d}10773984000105650010000000001000000000"


class PremissasICMSTest(unittest.TestCase):
    def test_historico_declarado_compara_com_0110(self):
        historico = validar_historico_regime(pd.DataFrame([
            {"inicio": "2018-01", "fim": "2018-12", "regime": "Lucro presumido"},
            {"inicio": "2019-01", "fim": "2026-12", "regime": "Lucro real"},
        ]))
        base = pd.DataFrame([{
            "competencia": "2018-12", "cnpj_estabelecimento": "10773984000105",
            "uf_nfe": "26", "regime_0110": "", "cfop": "5405",
            "cst_pis": "01", "cst_cofins": "01", "aliquota_pis": 0.65,
            "aliquota_cofins": 3.0, "registros_c175": 1,
            "registros_base_conferida": 1, "registros_base_divergente": 0,
            "registros_chave_invalida": 0, "registros_duplicados_entre_abas": 0,
            "base_pis_conferida": 100.0, "base_cofins_conferida": 100.0,
            "valor_pis_conferido": 0.65, "valor_cofins_conferido": 3.0,
        }])
        estimativa = simular_potencial(base, historico).iloc[0]
        self.assertEqual(estimativa["fonte_regime"], "Histórico informado")
        self.assertEqual(estimativa["codigo_regime_calculo"], "2")
        self.assertAlmostEqual(estimativa["total_simulado"], 0.66)
        base["regime_0110"] = float("nan")
        self.assertAlmostEqual(simular_potencial(base, historico).iloc[0]["total_simulado"], 0.66)
        base["regime_0110"] = "1"
        conflito = simular_potencial(base, historico).iloc[0]
        self.assertIsNone(conflito["total_simulado"])
        self.assertEqual(conflito["estado_simulacao"], "Divergência entre 0110 e histórico informado")
        base["regime_0110"] = "2"
        base["aliquota_pis"] = 1.65
        incompatível = simular_potencial(base, historico).iloc[0]
        self.assertIsNone(incompatível["total_simulado"])
        self.assertEqual(
            incompatível["estado_simulacao"],
            "Alíquotas C175 incompatíveis com regime básico informado",
        )

    def test_vigencia_pe_e_uf_sem_catalogo(self):
        self.assertEqual(buscar_premissa("26", "2023-12").aliquota_geral, 18)
        self.assertEqual(buscar_premissa("26", "2024-01").aliquota_geral, 20.5)
        self.assertEqual(buscar_premissa("51", "2024-01").aliquota_geral, 17)
        self.assertIsNone(buscar_premissa("35", "2024-01"))

    def test_regime_e_aliquotas_por_competencia_com_bloqueios(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as pasta:
            arquivo = Path(pasta) / "contribuicoes.xlsx"
            linhas = []
            for ano, mes, aliq_pis, aliq_cofins in [
                (2018, 12, 0.65, 3.0),
                (2024, 1, 1.65, 7.6),
            ]:
                linhas.append({
                    "Mês": "Dezembro" if mes == 12 else "Janeiro", "Ano": ano,
                    "CNPJ Estabelecimento(C010)": "10773984000105",
                    "Chave(C100)": chave(ano, mes), "Situação(C100)": "00",
                    "CFOP": 5405, "Valor da Operação": 100,
                    "Valor do Desconto": 0, "CST PIS": "01",
                    "Valor BC PIS": 100, "Aliquota PIS perc.": aliq_pis,
                    "Valor PIS": round(aliq_pis, 2), "CST COFINS": "01",
                    "Valor BC COFINS": 100, "Aliquota COFINS perc.": aliq_cofins,
                    "Valor COFINS": aliq_cofins,
                })
            linhas.append({**linhas[1], "Valor da Operação": 90})
            with pd.ExcelWriter(arquivo) as livro:
                pd.DataFrame([
                    {"Mês": "Dezembro", "Ano": 2018, "COD_INC_TRIB": 2},
                    {"Mês": "Janeiro", "Ano": 2024, "COD_INC_TRIB": 1},
                ]).to_excel(livro, sheet_name="0110", index=False)
                pd.DataFrame(linhas).to_excel(livro, sheet_name="C175 - Analítico", index=False)
            vendas = diagnosticar_vendas_st_c175(arquivo)
            self.assertEqual(set(vendas["regime_0110"]), {"1", "2"})
            self.assertEqual(vendas["registros_base_divergente"].sum(), 1)
            simulado = simular_potencial(vendas).set_index("competencia")
            self.assertEqual(simulado.loc["2018-12", "aliquota_icms_referencia"], 18)
            self.assertEqual(simulado.loc["2024-01", "aliquota_icms_referencia"], 20.5)
            self.assertAlmostEqual(simulado.loc["2018-12", "pis_simulado"], 0.12)
            self.assertAlmostEqual(simulado.loc["2024-01", "pis_simulado"], 0.34)
            self.assertEqual(
                simulado.loc["2024-01", "estado_simulacao"],
                "Simulação parcial; bases divergentes preservadas para revisão",
            )
            repetido = vendas.copy()
            repetido.loc[repetido["competencia"] == "2024-01", "registros_duplicados_entre_abas"] = 1
            bloqueado = simular_potencial(repetido).set_index("competencia")
            self.assertTrue(pd.isna(bloqueado.loc["2024-01", "total_simulado"]))
            self.assertEqual(
                bloqueado.loc["2024-01", "estado_simulacao"],
                "Registros repetidos entre abas; simulação bloqueada",
            )


if __name__ == "__main__":
    unittest.main()
