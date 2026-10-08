import importlib.util
import unittest
from unittest.mock import patch

import pandas as pd

import test_maternidade as fixtures


class Arquivo:
    def __init__(self, nome):
        self.name = nome

    def getvalue(self):
        return self.name.encode()


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Streamlit indisponível")
class InterfaceMaternidadeTest(unittest.TestCase):
    def test_fluxo_manad_download_e_invalidacao_ao_mudar_classificacao(self):
        from streamlit.testing.v1 import AppTest
        fixture = fixtures.MaternidadeTest()
        detalhe = fixture.detalhe()
        fonte = detalhe.drop(columns=["validacao", "descricao_validador", "incidencia_validador", "candidata"])
        ecac = fixture.ecac()
        app = AppTest.from_file("app.py").run()
        self.assertFalse(app.exception)
        app.sidebar.radio[0].set_value("2. Comparar levantamentos")

        def upload(label, **kwargs):
            if label.startswith("Levantamento"):
                return Arquivo("levantamento.xlsx")
            if label.startswith("MANAD"):
                return Arquivo("manad.txt")
            return Arquivo("dctf.pdf")

        with patch("streamlit.file_uploader", side_effect=upload), patch(
            "modules.maternidade.ler_levantamento", return_value=fonte
        ), patch("modules.maternidade.ler_manad", return_value=(fonte, [])), patch(
            "modules.ecac_parser.processar_arquivos", return_value=(ecac, pd.DataFrame(), pd.DataFrame())
        ):
            app.run()
            self.assertFalse(app.exception)
            app.checkbox[0].set_value(True).run()
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("download_button")), 1)
            self.assertTrue(any(h.value == "Resultado da conciliação" for h in app.subheader))
            grupos = [s for s in app.selectbox if s.label == "Como considerar esta rubrica?"]
            self.assertEqual(len(grupos), 2)
            grupos[1].set_value("Excluir").run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("download_button")), 0)
            grupos = [s for s in app.selectbox if s.label == "Como considerar esta rubrica?"]
            grupos[0].set_value("Revisar").run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button[0].disabled)
            self.assertFalse(app.error)
            self.assertTrue(any("Faltam classificar 1" in w.value for w in app.warning))
            grupos = [s for s in app.selectbox if s.label == "Como considerar esta rubrica?"]
            grupos[0].set_value("Principal").run()
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("download_button")), 1)
            resultado = app.session_state["comparativo_maternidade"][0]
            self.assertEqual(resultado.iloc[0]["Apoios considerados"], 0)


if __name__ == "__main__":
    unittest.main()
