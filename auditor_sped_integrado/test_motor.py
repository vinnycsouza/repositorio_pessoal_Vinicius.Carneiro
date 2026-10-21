from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from auditor_sped_integrado.motor import inventariar_excel, triagem_c170


CHAVE = "1" * 44
TEST_DIR = Path(__file__).resolve().parent


def pasta_temporaria():
    # O sandbox do Windows não permite escrita no diretório temporário global.
    return TemporaryDirectory(dir=TEST_DIR)


class MotorTest(unittest.TestCase):
    def _planilhas(self, pasta: Path, duplicar_icms: bool = False) -> tuple[Path, Path]:
        base = {
            "Chave": CHAVE,
            "Item": 1,
            "Indicador de Operacao": 1,
            "Situacao": "00",
            "Base de ICMS": 100.0,
            "Valor de ICMS": 18.0,
            "Valor de ICMS ST": 0.0,
            "Base de PIS": 100.0,
            "Base de COFINS": 100.0,
        }
        icms, pis = pasta / "icms.xlsx", pasta / "pis.xlsx"
        pd.DataFrame([base, base] if duplicar_icms else [base]).to_excel(icms, sheet_name="C170", index=False)
        pd.DataFrame([base]).to_excel(pis, sheet_name="C170", index=False)
        return icms, pis

    def test_indicio_tem_proveniencia_sem_valor_recuperavel(self):
        with pasta_temporaria() as tmp:
            icms, pis = self._planilhas(Path(tmp))
            achados = triagem_c170(icms, pis)
            self.assertEqual(len(achados), 1)
            self.assertEqual(achados.iloc[0]["regra"], "PISCOFINS_ICMS_69")
            self.assertEqual(achados.iloc[0]["estado"], "Indício para revisão")
            self.assertEqual(achados.iloc[0]["linha_pis"], 2)
            self.assertEqual(len(achados.iloc[0]["arquivo_pis_sha256"]), 64)
            self.assertNotIn("valor_recuperavel", achados.columns)

    def test_item_duplicado_nao_e_classificado_como_credito(self):
        with pasta_temporaria() as tmp:
            icms, pis = self._planilhas(Path(tmp), duplicar_icms=True)
            achados = triagem_c170(icms, pis)
            self.assertEqual(achados["regra"].tolist(), ["CONCILIACAO_C170"])
            self.assertEqual(achados.iloc[0]["estado"], "Ambíguo")

    def test_planilha_sem_aba_c170_e_rejeitada(self):
        with pasta_temporaria() as tmp:
            icms, pis = self._planilhas(Path(tmp))
            pd.DataFrame({"Chave": [CHAVE]}).to_excel(icms, sheet_name="Resumo", index=False)
            with self.assertRaisesRegex(ValueError, "Aba C170 não encontrada"):
                triagem_c170(icms, pis)

    def test_excel_selecionado_pelo_navegador(self):
        with pasta_temporaria() as tmp:
            icms, pis = self._planilhas(Path(tmp))
            dados_icms, dados_pis = icms.read_bytes(), pis.read_bytes()
            inventario = inventariar_excel(dados_icms, "EFD ICMS/IPI", "icms.xlsx")
            self.assertEqual(inventario["abas"], {"C170": 1})
            achados = triagem_c170(dados_icms, dados_pis, nome_icms="icms.xlsx", nome_pis="pis.xlsx")
            self.assertEqual(achados["regra"].tolist(), ["PISCOFINS_ICMS_69"])

    def test_inventario_excel_preserva_hash_e_contagem_por_aba(self):
        with pasta_temporaria() as tmp:
            arquivo = Path(tmp) / "efd.xlsx"
            with pd.ExcelWriter(arquivo) as livro:
                pd.DataFrame({"Chave": [CHAVE, CHAVE]}).to_excel(livro, sheet_name="C100", index=False)
                pd.DataFrame({"Item": [1]}).to_excel(livro, sheet_name="C170", index=False)
            inventario = inventariar_excel(arquivo, "EFD ICMS/IPI")
            self.assertEqual(inventario["abas"], {"C100": 2, "C170": 1})
            self.assertEqual(inventario["linhas"], 3)
            self.assertEqual(len(inventario["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()

