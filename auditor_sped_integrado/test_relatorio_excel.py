from datetime import datetime
from io import BytesIO
import unittest

import pandas as pd
from openpyxl import load_workbook

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
        self.assertIsNone(candidatos.iloc[0]["credito_pis_calculado"])
        vazio = pd.DataFrame()
        dados = gerar_relatorio_excel(
            [{"tipo": "EFD-Contribuições", "arquivo": "origem.xlsx", "sha256": "abc",
              "abas": {"C175": 2}, "linhas": 2}],
            vazio, vazio, vazio, vendas, vazio, "Lucro real", datetime(2026, 10, 21, 15, 0),
        )
        livro = load_workbook(BytesIO(dados), read_only=True, data_only=True)
        self.assertEqual(livro.sheetnames, [
            "Resumo", "C175_5405", "ST_C170", "ST_C100", "ST_C190",
            "Triagem_C170", "Inventario", "Metodo",
        ])
        resumo = livro["Resumo"]
        self.assertEqual(resumo["F7"].value, 1.32)
        self.assertIsNone(resumo["K7"].value)
        self.assertEqual(resumo["M7"].value, "Receita escriturada sob revisão")
        self.assertEqual(livro["Inventario"]["B2"].value, "origem.xlsx")
        livro.close()
