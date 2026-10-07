import io
import unittest

import openpyxl
import pandas as pd

from modules.ecac_parser import analisar_texto_dctfweb, processar_arquivos
from modules.excel_output import gerar_excel_comparativo, gerar_excel_ecac
from modules.maternidade import (
    aplicar_classificacao, comparar_maternidade, competencia, ler_manad,
    normalizar_esocial, normalizar_manad, sugerir_classificacao, validar,
)
from test_ecac_parser import TEXTO


class MaternidadeTest(unittest.TestCase):
    def base_manad(self, codigo="8006", valor="809,32", periodo="012023"):
        return pd.DataFrame([{"REG": "K300", "CNPJ/CEI": "20364206000108", "IND_FL": "1", "COD_LTC": "77", "COD_REG_TRAB": "483", "DT_COMP": periodo, "COD_RUBR": codigo, "VLR_RUBR": valor, "IND_RUBR": "P", "IND_BASE_IRRF": "1", "IND_BASE_PS": "1"}])

    def detalhe(self):
        base = pd.concat([self.base_manad(), self.base_manad("8110", "185,84")], ignore_index=True)
        normal = normalizar_manad(base, {"8006": "Situação Maternidade Empresa", "8110": "Maternidade Adicionais"}, "levantamento.xlsx")
        return validar(normal, normal, "MANAD")[0]

    def ecac(self, valor=995.16):
        return pd.DataFrame([{"cnpj": "20.364.206/0001-08", "competencia": "01/2023", "salario_maternidade": valor}])

    def test_extracao_maternidade_mensal_anual_e_ausente(self):
        texto = TEXTO.replace("Salário Família: 1.512,02", "Salário Maternidade: 995,16")
        self.assertEqual(analisar_texto_dctfweb(texto, "a.pdf").salario_maternidade, 995.16)
        anual = analisar_texto_dctfweb(texto.replace("03/2026", "2026"), "b.pdf")
        self.assertEqual(anual.competencia, "2026")
        self.assertIsNone(analisar_texto_dctfweb(TEXTO, "c.pdf").salario_maternidade)
        zero = analisar_texto_dctfweb(texto.replace("995,16", "0,00"), "d.pdf")
        self.assertEqual(zero.salario_maternidade, 0)

    def test_duas_colunas_credito_e_divergencia_sem_credito_negativo(self):
        d = self.detalhe()
        d = aplicar_classificacao(d, sugerir_classificacao(d))
        r = comparar_maternidade(self.ecac(), d).iloc[0]
        self.assertEqual(r["Principal"], 809.32)
        self.assertEqual(r["Total identificado"], 995.16)
        self.assertEqual(r["Potencial crédito sem apoios"], 0)
        self.assertEqual(r["Potencial crédito com apoios"], 0)
        self.assertEqual(r["Declarado superior sem apoios"], 185.84)
        r = comparar_maternidade(self.ecac(700), d).iloc[0]
        self.assertEqual(r["Potencial crédito sem apoios"], 109.32)
        self.assertEqual(r["Potencial crédito com apoios"], 295.16)

    def test_ausencia_nao_vira_credito_zero(self):
        d = self.detalhe()
        d = aplicar_classificacao(d, sugerir_classificacao(d))
        r = comparar_maternidade(self.ecac(None), d).iloc[0]
        self.assertTrue(pd.isna(r["Potencial crédito com apoios"]))
        ecac = pd.concat([self.ecac(), pd.DataFrame([{"cnpj": "20364206000108", "competencia": "02/2023", "salario_maternidade": 50}])])
        r = comparar_maternidade(ecac, d).iloc[1]
        self.assertTrue(pd.isna(r["Principal"]))
        self.assertTrue(pd.isna(r["Potencial crédito com apoios"]))

    def test_validador_nao_soma_apoios_ausentes(self):
        detalhe = self.detalhe().drop(columns=["validacao", "descricao_validador", "incidencia_validador", "candidata"])
        validado, faltas = validar(detalhe.iloc[:1], detalhe, "MANAD")
        self.assertEqual(len(validado), 1)
        self.assertEqual(len(faltas), 1)
        self.assertAlmostEqual(validado.valor.sum(), 809.32)

    def test_repeticoes_preservadas_e_excesso_detectado(self):
        detalhe = self.detalhe().iloc[:1]
        excesso = pd.concat([detalhe, detalhe], ignore_index=True)
        validado, _ = validar(excesso, detalhe, "MANAD")
        self.assertEqual(len(validado), 2)
        self.assertIn("Repetição excedente", validado.iloc[1].validacao)

    def test_descricao_alternativa_e_revisao_obrigatoria(self):
        normal = normalizar_manad(self.base_manad(), {"8006": "Afastamento especial"}, "a.xlsx")
        detalhe, _ = validar(normal, normal, "MANAD")
        self.assertEqual(len(detalhe), 1)
        classes = sugerir_classificacao(detalhe)
        self.assertEqual(classes.iloc[0].grupo, "Revisar")
        with self.assertRaises(ValueError):
            aplicar_classificacao(detalhe, classes)

    def test_periodo_13_e_reclassificacao_controlada(self):
        self.assertEqual(competencia("132023"), "2023")
        base = normalizar_manad(self.base_manad(periodo="022023"), {"8006": "13º Maternidade Rescisão"}, "a.xlsx")
        detalhe, _ = validar(base, base, "MANAD")
        classes = sugerir_classificacao(detalhe)
        classes["grupo"] = "Apoio"
        with self.assertRaises(ValueError):
            aplicar_classificacao(detalhe, classes)
        classes["justificativa"] = "Revisão do período de apuração"
        classes["competencia_destino"] = "2023"
        resultado = aplicar_classificacao(detalhe, classes)
        self.assertEqual(resultado.iloc[0].competencia, "2023")
        self.assertEqual(resultado.iloc[0].competencia_original, "02/2023")

    def test_manad_cp1252_cadastro_e_multiplos_blocos(self):
        txt = "K150|20364206000108|01012023|8006|Situação Maternidade Empresa\nK300|20364206000108|1|77|483|012023|8006|809,32|P|1|1"
        fonte, _ = ler_manad(txt.encode("cp1252"), "manad.txt")
        self.assertEqual(fonte.iloc[0].descricao, "Situação Maternidade Empresa")
        self.assertEqual(fonte.iloc[0].linha_origem, 2)
        self.assertEqual(fonte.iloc[0].valor, 809.32)

    def test_esocial_identificacao_e_cadastro(self):
        base = pd.DataFrame([{"nr_insc_estab": "02633573000188", "tp_insc_estab": "1", "per_apur": "2023-01", "cod_rubr": "0014", "ide_tab_rubr": "RH", "dsc_rubr": "Salário maternidade", "vr_rubr": 100, "arquivo": "evento.xml", "caminho_item": "item[1]", "status_auditoria": "S1010_VALIDO", "cod_inc_cp": "21"}])
        fonte = normalizar_esocial(base, "incidencia.xlsx")
        detalhe, faltas = validar(fonte, fonte, "Relatórios eSocial")
        self.assertEqual(detalhe.iloc[0].validacao, "Lançamento confere")
        self.assertEqual(detalhe.iloc[0].incidencia_validador, "21")
        self.assertTrue(faltas.empty)
        fonte.loc[0, "cnpj"] = "20364206000108"
        with self.assertRaises(ValueError):
            validar(detalhe, fonte, "Relatórios eSocial")

    def test_exportacao_maternidade_e_composicao(self):
        d = self.detalhe()
        classes = sugerir_classificacao(d)
        d = aplicar_classificacao(d, classes)
        resultado = comparar_maternidade(self.ecac(), d)
        dados = gerar_excel_comparativo(resultado, self.ecac(), d, d, classes, pd.DataFrame())
        w = openpyxl.load_workbook(io.BytesIO(dados), data_only=True)
        self.assertIn("Composição das rubricas", w.sheetnames)
        self.assertIn("Classificação", w.sheetnames)
        self.assertEqual(w["Comparativo"]["C2"].value, 809.32)
        ecac = gerar_excel_ecac(self.ecac(), pd.DataFrame(), pd.DataFrame())
        self.assertIn("Salário Maternidade", openpyxl.load_workbook(io.BytesIO(ecac)).sheetnames)


if __name__ == "__main__":
    unittest.main()
