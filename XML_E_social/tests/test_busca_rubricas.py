import unittest

import pandas as pd

from modules.busca_rubricas import (
    atualizar_selecao_rubricas,
    extrair_termos_busca,
    filtrar_rubricas_por_multibusca,
    termos_sem_correspondencia,
)


class BuscaRubricasTest(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame([
            {"cod_rubr": "100", "dsc_rubr": "Salário mensal"},
            {"cod_rubr": "1000", "dsc_rubr": "Gratificação"},
            {"cod_rubr": "A.20", "dsc_rubr": "Bônus especial"},
            {"cod_rubr": "300", "dsc_rubr": "Salario família"},
        ])

    def test_codigo_exige_correspondencia_exata(self):
        resultado, _ = filtrar_rubricas_por_multibusca(self.df, "100")
        self.assertEqual(resultado["cod_rubr"].tolist(), ["100"])
        self.assertEqual(resultado.iloc[0]["correspondencia_busca"], "Código exato: 100")

    def test_descricao_ignora_acentos_e_caixa(self):
        resultado, _ = filtrar_rubricas_por_multibusca(self.df, "SALARIO")
        self.assertEqual(set(resultado["cod_rubr"]), {"100", "300"})

    def test_ponto_nao_quebra_codigo(self):
        self.assertEqual(extrair_termos_busca("A.20; 300"), ["A.20", "300"])
        resultado, _ = filtrar_rubricas_por_multibusca(self.df, "A.20")
        self.assertEqual(resultado["cod_rubr"].tolist(), ["A.20"])

    def test_lista_usa_logica_ou_e_remove_duplicados(self):
        resultado, termos = filtrar_rubricas_por_multibusca(
            self.df, "100\nbonus; BÔNUS; 300"
        )
        self.assertEqual(termos, ["100", "bonus", "300"])
        self.assertEqual(set(resultado["cod_rubr"]), {"100", "A.20", "300"})

    def test_informa_termos_sem_correspondencia(self):
        termos = ["100", "INEXISTENTE", "familia"]
        self.assertEqual(
            termos_sem_correspondencia(self.df, termos),
            ["INEXISTENTE"],
        )

    def test_substituir_nao_mantem_selecao_antiga(self):
        self.assertEqual(
            atualizar_selecao_rubricas(
                {"ANTIGA||1", "MANTER||1"}, {"NOVA||1"}, "substituir"
            ),
            ["NOVA||1"],
        )

    def test_adicionar_e_remover_sao_acoes_separadas(self):
        adicionadas = atualizar_selecao_rubricas(
            {"A||1"}, {"B||1"}, "adicionar"
        )
        self.assertEqual(adicionadas, ["A||1", "B||1"])
        self.assertEqual(
            atualizar_selecao_rubricas(adicionadas, {"A||1"}, "remover"),
            ["B||1"],
        )


if __name__ == "__main__":
    unittest.main()
