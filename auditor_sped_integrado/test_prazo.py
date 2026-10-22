from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from auditor_sped_integrado.diagnostico_st import diagnosticar_vendas_st_c170
from auditor_sped_integrado.modulo_69 import levantar_tema_69
from auditor_sped_integrado.prazo import classificar_competencia, data_corte
from auditor_sped_integrado.test_modulos import CHAVE_55, item_c170


class PrazoTest(unittest.TestCase):
    def test_corte_calendario_e_mes_limite(self):
        referencia = date(2026, 10, 22)
        self.assertEqual(data_corte(referencia), date(2021, 10, 22))
        self.assertEqual(classificar_competencia("2021-09", referencia), "anterior")
        self.assertEqual(classificar_competencia("2021-10", referencia), "limite")
        self.assertEqual(classificar_competencia("2021-11", referencia), "dentro")
        self.assertEqual(classificar_competencia("2026-11", referencia), "futura")
        self.assertEqual(data_corte(date(2024, 2, 29)), date(2019, 2, 28))

    def test_ambos_modulos_excluem_competencia_antiga_e_mes_limite(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as pasta:
            pasta = Path(pasta)
            pis, icms = pasta / "pis.xlsx", pasta / "icms.xlsx"
            linhas = []
            for mes, ano, chave in (
                ("Setembro", 2021, CHAVE_55[:2] + "2109" + CHAVE_55[6:]),
                ("Outubro", 2021, CHAVE_55[:2] + "2110" + CHAVE_55[6:]),
                ("Novembro", 2021, CHAVE_55[:2] + "2111" + CHAVE_55[6:]),
            ):
                linhas.append({**item_c170(chave, cfop=5102, icms=18), "Mês": mes, "Ano": ano})
            pd.DataFrame(linhas).to_excel(pis, sheet_name="C170", index=False)
            pd.DataFrame(linhas).to_excel(icms, sheet_name="C170", index=False)
            ref = date(2026, 10, 22)
            candidatos_69, contagens = levantar_tema_69(icms, pis, data_referencia=ref)
            self.assertEqual(len(candidatos_69), 1)
            self.assertEqual(candidatos_69.iloc[0]["competencia"], "2021-11")
            self.assertEqual(contagens["prazo_c170_anterior"], 1)
            self.assertEqual(contagens["prazo_c170_limite"], 1)
            arquivo_st = pasta / "st.xlsx"
            pd.DataFrame([{**linha, "CFOP": 5405} for linha in linhas]).to_excel(
                arquivo_st, sheet_name="C170", index=False
            )
            st = diagnosticar_vendas_st_c170(arquivo_st, data_referencia=ref)
            self.assertEqual(list(st["competencia"]), ["2021-11"])
            self.assertEqual(st.attrs["recorte_prazo"], {"anterior": 1, "limite": 1, "dentro": 1})


if __name__ == "__main__":
    unittest.main()
