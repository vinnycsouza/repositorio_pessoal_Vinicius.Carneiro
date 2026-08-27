import xml.etree.ElementTree as ET
import unittest

from modules.event_metadata import (
    identificar_evento_rapido,
    inspecionar_evento,
    inspecionar_evento_streaming,
)
from modules.parser_xml import (
    detectar_tipo_evento,
    obter_recibo_evento_atual,
    obter_recibo_principal,
    parse_empresa_info,
)
from modules.processador_zip import _eh_retorno_evento_completo, _metadados_retificacao


AMOSTRAS = [
    """<eSocial xmlns="http://www.esocial.gov.br/schema/evt/evtRemun/v_S_01_03_00">
      <evtRemun Id="ID1200"><ideEvento><indRetif>1</indRetif><perApur>2026-07</perApur></ideEvento>
      <ideEmpregador><tpInsc>1</tpInsc><nrInsc>12345678000199</nrInsc></ideEmpregador>
      <ideTrabalhador><cpfTrab>12345678901</cpfTrab></ideTrabalhador></evtRemun></eSocial>""",
    """<retornoEventoCompleto><eSocial><evtRubrica Id="ID1010"><ideEvento><indRetif>2</indRetif>
      <nrRecibo>REC-ANTERIOR</nrRecibo></ideEvento><ideEmpregador><tpInsc>1</tpInsc>
      <nrInsc>12345678000199</nrInsc></ideEmpregador><infoRubrica><inclusao><ideRubrica>
      <iniValid>2026-01</iniValid></ideRubrica></inclusao></infoRubrica></evtRubrica></eSocial>
      <recibo><nrRecibo>REC-NOVO</nrRecibo></recibo></retornoEventoCompleto>""",
    """<eSocial><evtBasesTrab Id="ID5001"><ideEvento><perApur>2026-06</perApur></ideEvento>
      <ideEmpregador><tpInsc>1</tpInsc><nrInsc>12.345.678/0001-99</nrInsc></ideEmpregador>
      <nrRecArqBase>BASE-1</nrRecArqBase></evtBasesTrab></eSocial>""",
    """<eSocial><evtInfoEmpregador Id="ID1000"><ideEvento/><ideEmpregador><tpInsc>1</tpInsc>
      <nrInsc>12345678000199</nrInsc></ideEmpregador><infoEmpregador><inclusao><dadosIsencao>
      <nmRazao>Empresa Teste</nmRazao></dadosIsencao></inclusao></infoEmpregador></evtInfoEmpregador></eSocial>""",
    """<documento><conteudo>sem evento conhecido</conteudo></documento>""",
]


class EventMetadataTest(unittest.TestCase):
    def test_inspecao_compartilhada_equivale_as_buscas_legadas(self):
        for xml in AMOSTRAS:
            with self.subTest(xml=xml[:60]):
                root = ET.fromstring(xml)
                novo = inspecionar_evento(root)
                legado = _metadados_retificacao(root)
                empresa = parse_empresa_info(root, "amostra.xml")

                self.assertEqual(novo.tipo, detectar_tipo_evento(root))
                self.assertEqual(
                    novo.envelope_recibo, _eh_retorno_evento_completo(root)
                )
                self.assertEqual(
                    (
                        novo.id_evento_esocial,
                        novo.ind_retif,
                        novo.recibo_evento,
                        novo.recibo_referencia,
                    ),
                    legado,
                )
                self.assertEqual(
                    novo.tp_insc_empregador, empresa["tp_insc_empregador"]
                )
                self.assertEqual(
                    novo.cnpj_empregador, empresa["cnpj_empregador"]
                )
                self.assertEqual(novo.nome_empresa, empresa["nome_empresa"])

    def test_recibo_principal_sem_envelope_e_preservado(self):
        root = ET.fromstring(AMOSTRAS[2])
        self.assertEqual(
            inspecionar_evento(root).recibo_evento,
            obter_recibo_principal(root),
        )

    def test_retificacao_separa_recibo_atual_da_referencia(self):
        root = ET.fromstring(AMOSTRAS[1])
        metadados = inspecionar_evento(root)
        self.assertEqual(metadados.recibo_evento, "REC-NOVO")
        self.assertEqual(metadados.recibo_referencia, "REC-ANTERIOR")
        self.assertEqual(obter_recibo_evento_atual(root), "REC-NOVO")

    def test_retificacao_sem_envelope_nao_promove_referencia(self):
        root = ET.fromstring(
            "<eSocial><evtRemun><ideEvento><indRetif>2</indRetif>"
            "<nrRecibo>REC-ANTERIOR</nrRecibo></ideEvento></evtRemun></eSocial>"
        )
        self.assertEqual(obter_recibo_evento_atual(root), "")

    def test_namespace_versao_e_sniffer_confirmado(self):
        xml = AMOSTRAS[0].encode()
        pista = identificar_evento_rapido(xml)
        metadados = inspecionar_evento(ET.fromstring(xml), pista)
        self.assertEqual(pista.tipo, "S-1200")
        self.assertEqual(metadados.versao_layout, "S_01_03_00")
        self.assertEqual(metadados.identificacao_parser, "sniffer_confirmado")
        self.assertFalse(metadados.versao_desconhecida)

    def test_versao_desconhecida_e_marcada_sem_rejeicao(self):
        xml = AMOSTRAS[0].replace("S_01_03_00", "S_09_99_00").encode()
        metadados = inspecionar_evento(
            ET.fromstring(xml), identificar_evento_rapido(xml)
        )
        self.assertEqual(metadados.tipo, "S-1200")
        self.assertTrue(metadados.versao_desconhecida)

    def test_inspecao_streaming_preserva_metadados_comuns(self):
        for xml in AMOSTRAS[:3]:
            with self.subTest(xml=xml[:50]):
                bruto = xml.encode()
                pista = identificar_evento_rapido(bruto)
                completo = inspecionar_evento(ET.fromstring(bruto), pista)
                streaming = inspecionar_evento_streaming(bruto, pista)
                self.assertEqual(streaming.tipo, completo.tipo)
                self.assertEqual(streaming.id_evento_esocial, completo.id_evento_esocial)
                self.assertEqual(streaming.recibo_evento, completo.recibo_evento)
                self.assertEqual(streaming.recibo_referencia, completo.recibo_referencia)
                self.assertEqual(streaming.periodo, completo.periodo)
                self.assertEqual(streaming.cnpj_empregador, completo.cnpj_empregador)


if __name__ == "__main__":
    unittest.main()
