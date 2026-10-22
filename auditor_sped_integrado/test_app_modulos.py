from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

from auditor_sped_integrado.catalogo import MODULOS_IMPLEMENTADOS, REGRAS
from auditor_sped_integrado.test_modulos import CHAVE_55, item_c170


class FluxoModulosTest(unittest.TestCase):
    def test_catalogo_tem_apenas_os_dois_modulos_ativos(self):
        codigos = {regra.codigo for regra in REGRAS}
        self.assertEqual(len(codigos), 6)
        self.assertEqual(MODULOS_IMPLEMENTADOS, {
            "PISCOFINS_ICMS_ST_1125", "PISCOFINS_ICMS_69",
        })
        self.assertTrue(MODULOS_IMPLEMENTADOS <= codigos)

    def test_execucao_independente_preserva_relatorio_do_outro_tema(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as pasta:
            pasta = Path(pasta)
            pis, icms = pasta / "pis.xlsx", pasta / "icms.xlsx"
            venda_st = item_c170(CHAVE_55)
            venda_icms = item_c170(CHAVE_55, cfop=5102, item=2, icms=18)
            pd.DataFrame([venda_st, venda_icms]).to_excel(pis, sheet_name="C170", index=False)
            pd.DataFrame([venda_icms]).rename(columns={
                "CNPJ Estabelecimento(C010)": "CNPJ",
                "Chave(C100)": "Chave de Acesso(C100)",
            }).to_excel(icms, sheet_name="C170", index=False)

            app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=30).run()
            app.radio[0].set_value("Informar caminho")
            app.radio[1].set_value("Informar caminho")
            app.run()
            app.text_input[0].set_value(str(icms))
            app.text_input[1].set_value(str(pis))
            app.run()
            next(botao for botao in app.button if "Ler documentos" in botao.label).click().run()
            self.assertFalse(app.exception)
            self.assertEqual(
                app.session_state["preanalise_auditoria"]["cobertura_fontes"]["EFD-Contribuições"],
                {"2023-08": 2},
            )
            botoes = {botao.key: botao for botao in app.button if botao.key}
            self.assertEqual(set(botoes), {"nova_analise", "executar_tema_1125", "executar_tema_69"})

            botoes["executar_tema_69"].click().run()
            self.assertFalse(app.exception)
            resultado = app.session_state["resultado_auditoria"]
            self.assertTrue(resultado["executado_69"])
            self.assertFalse(resultado["executado_1125"])
            relatorio_69 = resultado["relatorio_69"]
            self.assertTrue(relatorio_69)

            next(botao for botao in app.button if botao.key == "executar_tema_1125").click().run()
            self.assertFalse(app.exception)
            resultado = app.session_state["resultado_auditoria"]
            self.assertTrue(resultado["executado_1125"])
            self.assertTrue(resultado["executado_69"])
            self.assertTrue(resultado["relatorio"])
            self.assertEqual(resultado["relatorio_69"], relatorio_69)

            next(campo for campo in app.selectbox if "PE" in campo.options).set_value("PE").run()
            resultado = app.session_state["resultado_auditoria"]
            self.assertFalse(resultado["executado_1125"])
            self.assertTrue(resultado["executado_69"])
            self.assertEqual(resultado["relatorio_69"], relatorio_69)

            next(botao for botao in app.button if botao.key == "nova_analise").click().run()
            self.assertFalse(app.exception)
            self.assertNotIn("preanalise_auditoria", app.session_state)
            self.assertNotIn("resultado_auditoria", app.session_state)
            self.assertTrue(all(campo.value == "Selecionar arquivo" for campo in app.radio))
            self.assertEqual(app.selectbox[0].value, "Automática pela chave da NF-e")


if __name__ == "__main__":
    unittest.main()
