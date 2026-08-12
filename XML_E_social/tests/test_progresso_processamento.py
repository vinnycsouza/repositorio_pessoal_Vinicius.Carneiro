import unittest

from modules.progresso import ETAPAS, criar_progresso, emitir_progresso


class ProgressoProcessamentoTest(unittest.TestCase):
    def test_faixas_das_etapas_sao_continuas_e_terminam_em_cem(self):
        anterior = 0.0
        for etapa in ETAPAS:
            inicio = criar_progresso(etapa, 0.0, "início")
            fim = criar_progresso(etapa, 1.0, "fim")
            self.assertAlmostEqual(inicio.percentual_geral, anterior)
            self.assertGreaterEqual(fim.percentual_geral, inicio.percentual_geral)
            anterior = fim.percentual_geral
        self.assertAlmostEqual(anterior, 1.0)

    def test_percentual_local_e_limitado_sem_afetar_a_etapa_seguinte(self):
        abaixo = criar_progresso("ingestao", -1, "teste")
        acima = criar_progresso("ingestao", 2, "teste")
        proxima = criar_progresso("segunda_passagem", 0, "teste")
        self.assertEqual(abaixo.percentual_etapa, 0.0)
        self.assertEqual(acima.percentual_etapa, 1.0)
        self.assertAlmostEqual(acima.percentual_geral, proxima.percentual_geral)

    def test_callback_detalhado_recebe_as_duas_porcentagens(self):
        chamadas = []

        def callback(geral, mensagem, info):
            chamadas.append((geral, mensagem, info))

        callback._suporta_progresso_detalhado = True
        emitir_progresso(callback, "materializacao", 0.5, "persistindo", "10/20 blocos")
        geral, mensagem, info = chamadas[0]
        self.assertAlmostEqual(geral, 0.75)
        self.assertEqual(info.percentual_etapa, 0.5)
        self.assertEqual(info.detalhes, "10/20 blocos")
        self.assertEqual(mensagem, "persistindo")

    def test_callback_antigo_permanece_compativel(self):
        chamadas = []
        emitir_progresso(
            lambda valor, mensagem: chamadas.append((valor, mensagem)),
            "integridade", 1.0, "pronto",
        )
        self.assertEqual(chamadas, [(0.98, "pronto")])


if __name__ == "__main__":
    unittest.main()
