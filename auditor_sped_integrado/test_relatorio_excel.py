from datetime import datetime
from io import BytesIO
import unittest

import pandas as pd
from openpyxl import load_workbook

from auditor_sped_integrado.conferencia_nfe import ConferenciaNFe
from auditor_sped_integrado.relatorio_excel import gerar_relatorio_excel, resumir_candidatos


class RelatorioExcelTest(unittest.TestCase):
    def test_relatorio_separa_contribuicao_escriturada_de_credito(self):
        vendas = pd.DataFrame([
        {
            "competencia": "2025-01", "cnpj_estabelecimento": "10693312000505",
            "cfop": "5405", "cst_pis": "01", "cst_cofins": "01",
            "aliquota_pis": 1.65, "aliquota_cofins": 7.6, "registros_c175": 2,
            "valor_operacao": 100.0, "base_pis": 80.0, "valor_pis": 1.32,
            "base_cofins": 80.0, "valor_cofins": 6.08,
            "primeira_aba": "C175", "primeira_linha_c175": 2,
        },
        {
            "competencia": "2025-01", "cnpj_estabelecimento": "10693312000505",
            "cfop": "5405", "cst_pis": "04", "cst_cofins": "04",
            "aliquota_pis": 0.0, "aliquota_cofins": 0.0, "registros_c175": 1,
            "valor_operacao": 50.0, "base_pis": 0.0, "valor_pis": 0.0,
            "base_cofins": 0.0, "valor_cofins": 0.0,
            "primeira_aba": "C175", "primeira_linha_c175": 3,
        },
        ])
        candidatos = resumir_candidatos(vendas)
        self.assertEqual(len(candidatos), 1)
        self.assertEqual(candidatos.iloc[0]["pis_escriturado"], 1.32)
        self.assertEqual(candidatos.iloc[0]["contribuicoes_sob_analise"], 7.4)
        self.assertIsNone(candidatos.iloc[0]["credito_pis_calculado"])
        vazio = pd.DataFrame()
        from decimal import Decimal
        with ConferenciaNFe() as conferencia:
            for valor in (Decimal("40"), Decimal("40")):
                conferencia.adicionar(
                    competencia="2025-01", cnpj="10693312000505",
                    chave="51250110693312000505550010000000011000000000", chave_ok=True,
                    uf="51", regime="1", aliquota_pis=Decimal("1.65"),
                    aliquota_cofins=Decimal("7.6"), operacao=valor, desconto=Decimal("0"),
                    base_pis=valor, pis=Decimal("0.66"), base_cofins=valor,
                    cofins=Decimal("3.04"), base_ok=True, duplicado=False,
                    aba="C175", linha=2,
                )
            dados = gerar_relatorio_excel(
                [{"tipo": "EFD-Contribuições", "arquivo": "origem.xlsx", "sha256": "abc",
                  "abas": {"C175": 2}, "linhas": 2}],
                vazio, vazio, vazio, vendas, vazio, "Lucro real", datetime(2026, 10, 21, 15, 0),
                conferencia_nfe=conferencia,
            )
        livro = load_workbook(BytesIO(dados), read_only=False, data_only=False)
        self.assertEqual(livro.sheetnames, ["Resumo_Executivo", "Memoria_Mensal", "Conferencia_NF"])
        self.assertEqual(livro["Resumo_Executivo"]["B12"].value, 1.32)
        self.assertEqual(livro["Resumo_Executivo"]["C12"].value, 6.08)
        self.assertEqual(livro["Resumo_Executivo"]["B18"].data_type, "f")
        nf = livro["Conferencia_NF"]
        self.assertEqual(nf["F2"].value, 2)
        self.assertEqual(nf["I2"].value, 80)
        self.assertEqual(nf["Q2"].value, "Apto para conferência")
        self.assertEqual(nf["T2"].value, "Pendente")
        self.assertTrue(nf["U2"].value.startswith("=IF("))
        self.assertEqual(len(nf.data_validations.dataValidation), 1)
        livro.close()
