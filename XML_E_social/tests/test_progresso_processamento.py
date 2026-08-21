import unittest
import sqlite3

from modules.progresso import ETAPAS, criar_progresso, emitir_progresso
from modules.processador_zip import (
    _nome_fonte_para_hud,
    _resumo_fontes_descobertas,
    _texto_resumo_fontes,
)


class ProgressoProcessamentoTest(unittest.TestCase):
    def test_hud_preserva_pasta_logica_sem_expor_caminho_fisico(self):
        self.assertEqual(
            _nome_fonte_para_hud("2018 a 2021/35265128.zip"),
            "2018 a 2021/35265128.zip",
        )
        self.assertEqual(
            _nome_fonte_para_hud(r"C:\Arquivo zip\FEDEX.zip"),
            "FEDEX.zip",
        )

    def test_resumo_fontes_conta_status_e_volume_restante(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                "CREATE TABLE fontes(id INTEGER,status TEXT,tamanho_bytes INTEGER,id_carga INTEGER)"
            )
            conn.executemany(
                "INSERT INTO fontes VALUES(?,?,?,?)",
                [
                    (1, "concluida", 1_000, 7),
                    (2, "processando", 2_000, 7),
                    (3, "pendente", 3_000, 7),
                    (4, "erro", 4_000, 7),
                    (5, "concluida", 9_000, 8),
                ],
            )
            resumo = _resumo_fontes_descobertas(conn, 2, 0.25, id_carga=7)
        finally:
            conn.close()

        self.assertEqual(resumo["descobertas"], 4)
        self.assertEqual(resumo["concluidas"], 1)
        self.assertEqual(resumo["processando"], 1)
        self.assertEqual(resumo["pendentes"], 1)
        self.assertEqual(resumo["faltam"], 2)
        self.assertEqual(resumo["erros"], 1)
        self.assertEqual(resumo["volume_descoberto"], 10_000)
        self.assertEqual(resumo["volume_concluido"], 1_000)
        self.assertEqual(resumo["volume_restante"], 4_500)
        self.assertEqual(resumo["volume_erro"], 4_000)
        self.assertAlmostEqual(resumo["fracao"], 0.55)

    def test_texto_resumo_explica_que_fontes_sao_descobertas(self):
        resumo = {
            "descobertas": 10, "concluidas": 4, "faltam": 5,
            "pendentes": 4, "processando": 1, "erros": 1,
            "volume_descoberto": 10_000, "volume_concluido": 4_000,
            "volume_restante": 5_000,
        }
        texto = _texto_resumo_fontes(resumo)
        self.assertIn("fontes descobertas 10", texto)
        self.assertIn("lidas 4", texto)
        self.assertIn("faltam 5", texto)
        self.assertIn("com erro 1", texto)
        self.assertIn("restante conhecido", texto)

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
