from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from motor import inventariar_sped, triagem_c170


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

    def test_inventario_preserva_hash_e_contagem(self):
        with pasta_temporaria() as tmp:
            arquivo = Path(tmp) / "efd.txt"
            arquivo.write_bytes(b"|0000|TESTE|\r\n|C100|1|\r\n|C100|2|\r\n")
            inventario = inventariar_sped(arquivo, "EFD ICMS/IPI")
            self.assertEqual(inventario["registros"], {"0000": 1, "C100": 2})
            self.assertEqual(inventario["linhas"], 3)
            self.assertEqual(len(inventario["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()

