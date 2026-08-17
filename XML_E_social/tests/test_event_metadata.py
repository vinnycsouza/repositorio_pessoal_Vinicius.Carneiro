import xml.etree.ElementTree as ET
import unittest

from modules.event_metadata import inspecionar_evento
from modules.parser_xml import detectar_tipo_evento, obter_recibo_principal, parse_empresa_info
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


if __name__ == "__main__":
    unittest.main()
