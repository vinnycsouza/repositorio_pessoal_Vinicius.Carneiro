import unittest

from modules.ecac_parser import analisar_texto_dctfweb, processar_arquivos


TEXTO = """
RELATÓRIO DA DECLARAÇÃO COMPLETA - DCTFWeb
Nome do Contribuinte EMPRESA TESTE LTDA CNPJ 20.364.206/0001-08
Período apuração 03/2026 Número do Recibo 50000471049813
Data/Hora da Transmissão 22/04/2026 15:07:44
Número do Recibo da Declaração Retificada 50000470984747
Código da Receita 1082-01 Descrição CP SEGURADOS - EMPREGADOS/AVULSO
Deduções Salário Família: 1.512,02
"""


class EcacParserTest(unittest.TestCase):
    def test_extrai_apenas_dados_necessarios(self):
        registro = analisar_texto_dctfweb(TEXTO, "declaracao.pdf")
        self.assertEqual(registro.cnpj, "20.364.206/0001-08")
        self.assertEqual(registro.competencia, "03/2026")
        self.assertEqual(registro.salario_familia, 1512.02)
        self.assertEqual(registro.recibo, "50000471049813")
        self.assertEqual(registro.recibo_retificado, "50000470984747")

    def test_sem_salario_familia_nao_vira_zero(self):
        registro = analisar_texto_dctfweb(
            TEXTO.replace("Deduções Salário Família: 1.512,02", ""),
            "sem_valor.pdf",
        )
        self.assertIsNone(registro.salario_familia)

    def test_retificadora_mais_recente_substitui_anterior(self):
        anterior = analisar_texto_dctfweb(TEXTO, "anterior.pdf", "hash-a")
        mais_recente = analisar_texto_dctfweb(
            TEXTO.replace("1.512,02", "1.700,00").replace(
                "22/04/2026 15:07:44", "23/04/2026 10:00:00"
            ),
            "retificadora.pdf",
            "hash-b",
        )
        from unittest.mock import patch

        with patch("modules.ecac_parser.iterar_pdfs") as iterador, patch(
            "modules.ecac_parser.analisar_pdf", side_effect=[anterior, mais_recente]
        ):
            iterador.side_effect = [
                iter([("anterior.pdf", b"a")]),
                iter([("retificadora.pdf", b"b")]),
            ]
            resumo, documentos, _ = processar_arquivos(
                [("anterior.pdf", b"a"), ("retificadora.pdf", b"b")]
            )
        self.assertEqual(resumo.iloc[0]["salario_familia"], 1700.0)
        self.assertEqual(
            documentos.loc[documentos["arquivo"] == "anterior.pdf", "situacao"].iloc[0],
            "Substituída por declaração posterior",
        )


if __name__ == "__main__":
    unittest.main()

