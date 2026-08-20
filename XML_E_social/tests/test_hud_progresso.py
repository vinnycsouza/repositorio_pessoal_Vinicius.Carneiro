import unittest

from modules.hud_progresso import extrair_hud_ingestao


DETALHES = (
    "Fonte: 2018 a 2021/35265128.zip | itens 36.191/83.571 | "
    "247,1 MB/575,9 MB | 527.719 XMLs catalogados | 417,5 itens/s | "
    "1,2 MB/s | decorrido 1min 27s | ETA da fonte 1min 53s | "
    "fontes descobertas 145 | lidas 23 | faltam 122 "
    "(pendentes 121; em leitura 1) | com erro 0 | "
    "volume descoberto 30,0 GB | concluído 2,0 GB | restante conhecido 28,0 GB."
)


class HUDProgressoTest(unittest.TestCase):
    def test_extrai_todos_os_campos_sem_recalcular_metricas_da_engine(self):
        dados = extrair_hud_ingestao(DETALHES)
        self.assertEqual(dados.fonte, "2018 a 2021/35265128.zip")
        self.assertEqual(dados.itens_lidos, "36.191 de 83.571")
        self.assertEqual(dados.itens_restantes, "47.380")
        self.assertEqual(dados.volume_lido, "247,1 MB de 575,9 MB")
        self.assertEqual(dados.xml_catalogados, "527.719")
        self.assertEqual(dados.ritmo, "417,5 itens/s")
        self.assertEqual(dados.eta, "1min 53s")
        self.assertEqual(dados.fontes_descobertas, "145")
        self.assertEqual(dados.fontes_concluidas, "23")
        self.assertEqual(dados.fontes_em_leitura, "1")
        self.assertEqual(dados.fontes_pendentes, "121")
        self.assertEqual(dados.fontes_com_erro, "0")
        self.assertEqual(dados.volume_restante, "28,0 GB")
        self.assertEqual(dados.tempo_decorrido, "1min 27s")

    def test_mensagem_sem_metricas_permanece_segura(self):
        dados = extrair_hud_ingestao("Preparando a ingestão...")
        self.assertEqual(dados.fonte, "—")
        self.assertEqual(dados.itens_restantes, "—")
        self.assertEqual(dados.eta, "calculando")


if __name__ == "__main__":
    unittest.main()
