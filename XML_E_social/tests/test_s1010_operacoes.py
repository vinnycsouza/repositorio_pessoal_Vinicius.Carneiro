import xml.etree.ElementTree as ET
import unittest

from modules.parser_xml import parse_s1010, selecionar_rubrica_vigente
from modules.processador_zip import _montar_indice_rubricas


def evento_s1010(operacao: str, ini: str, cod_inc_cp: str = "") -> str:
    dados = ""
    if operacao != "exclusao":
        dados = (
            "<dadosRubrica><dscRubr>Rubrica 273</dscRubr><natRubr>1807</natRubr>"
            f"<tpRubr>1</tpRubr><codIncCP>{cod_inc_cp}</codIncCP></dadosRubrica>"
        )
    return (
        "<eSocial><evtTabRubrica><infoRubrica>"
        f"<{operacao}><ideRubrica><codRubr>273</codRubr><ideTabRubr>0001</ideTabRubr>"
        f"<iniValid>{ini}</iniValid></ideRubrica>{dados}</{operacao}>"
        "</infoRubrica></evtTabRubrica></eSocial>"
    )


class OperacoesS1010Test(unittest.TestCase):
    def _parse(self, operacao: str, ini: str, cp: str = ""):
        return parse_s1010(
            ET.fromstring(evento_s1010(operacao, ini, cp)),
            arquivo=f"{operacao}_{ini}.xml",
            fonte_dados="Recibo S-1010",
        )

    def test_exclusao_nao_vira_cadastro_vazio_e_alteracao_posterior_prevalece(self):
        rubricas = []
        rubricas += self._parse("inclusao", "2025-10", "11")
        rubricas += self._parse("exclusao", "2025-11")
        rubricas += self._parse("alteracao", "2025-10", "00")

        self.assertEqual(rubricas[1].origem_bloco, "exclusao")
        mapa = _montar_indice_rubricas(rubricas)
        selecao = selecionar_rubrica_vigente(mapa, "273", "0001", "2025-11")
        self.assertIsNotNone(selecao.rubrica)
        self.assertEqual(selecao.rubrica.origem_bloco, "alteracao")
        self.assertEqual(selecao.rubrica.cod_inc_cp, "00")

    def test_exclusao_remove_a_mesma_chave_e_vigencia(self):
        rubricas = []
        rubricas += self._parse("inclusao", "2025-10", "11")
        rubricas += self._parse("exclusao", "2025-10")
        mapa = _montar_indice_rubricas(rubricas)
        selecao = selecionar_rubrica_vigente(mapa, "273", "0001", "2025-11")
        self.assertIsNone(selecao.rubrica)
        self.assertEqual(selecao.status_auditoria, "SEM_S1010")

    def test_vigencia_anterior_ao_esocial_continua_valida_sem_fim(self):
        rubricas = self._parse("inclusao", "2017-01", "11")
        mapa = _montar_indice_rubricas(rubricas)

        selecao = selecionar_rubrica_vigente(mapa, "273", "0001", "2018-01")

        self.assertIsNotNone(selecao.rubrica)
        self.assertEqual(selecao.rubrica.ini_valid, "2017-01")
        self.assertEqual(selecao.rubrica.cod_inc_cp, "11")
        self.assertEqual(selecao.status_auditoria, "S1010_ANTERIOR_ESOCIAL")
        self.assertEqual(selecao.origem_validacao, "S-1010 anterior ao eSocial")
        self.assertEqual(
            selecao.criterio, "codRubr+ideTabRubr+vigencia_anterior_esocial"
        )

    def test_vigencia_anterior_ao_esocial_vale_em_competencia_atual(self):
        rubricas = self._parse("inclusao", "2016-06", "11")
        mapa = _montar_indice_rubricas(rubricas)

        selecao = selecionar_rubrica_vigente(mapa, "273", "0001", "2026-07")

        self.assertIsNotNone(selecao.rubrica)
        self.assertEqual(selecao.rubrica.ini_valid, "2016-06")
        self.assertEqual(selecao.status_auditoria, "S1010_ANTERIOR_ESOCIAL")
        self.assertEqual(selecao.origem_validacao, "S-1010 anterior ao eSocial")

    def test_vigencia_a_partir_de_2018_mantem_nomenclatura_normal(self):
        rubricas = self._parse("inclusao", "2018-01", "11")
        mapa = _montar_indice_rubricas(rubricas)

        selecao = selecionar_rubrica_vigente(mapa, "273", "0001", "2026-07")

        self.assertEqual(selecao.status_auditoria, "S1010_VALIDO")
        self.assertEqual(selecao.origem_validacao, "S-1010 válido")


if __name__ == "__main__":
    unittest.main()
