import sqlite3
import tempfile
import unittest
from pathlib import Path

from modules.processador_zip import _criar_schema, _processar_xml_ingestao
from modules.telemetria import TelemetriaCarga


XML = b'''<eSocial xmlns="http://www.esocial.gov.br/schema/evt/evtRemun/v_S_01_03_00">
<evtRemun Id="ID1"><ideEvento><indRetif>1</indRetif><perApur>2026-01</perApur></ideEvento>
<ideEmpregador><tpInsc>1</tpInsc><nrInsc>12345678000199</nrInsc></ideEmpregador></evtRemun></eSocial>'''


class PacotesV10Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "teste.db"
        self.conn = sqlite3.connect(self.db)
        _criar_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_carga_inicial_nao_faz_select_previo_por_hash(self):
        comandos = []
        self.conn.set_trace_callback(comandos.append)
        resultado = _processar_xml_ingestao(
            self.conn, "novo.xml", XML, len(XML), id_carga=None
        )
        self.assertEqual(resultado, "S-1200")
        selects_hash = [c for c in comandos if c.lstrip().upper().startswith("SELECT") and "hash_conteudo" in c]
        self.assertEqual(selects_hash, [])

    def test_duplicata_inicial_e_barrada_pelo_indice(self):
        self.assertEqual(_processar_xml_ingestao(self.conn, "a.xml", XML, len(XML)), "S-1200")
        self.assertEqual(_processar_xml_ingestao(self.conn, "b.xml", XML, len(XML)), "duplicado")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0], 1)

    def test_schema_e_telemetria_local(self):
        telemetria = TelemetriaCarga()
        _processar_xml_ingestao(self.conn, "a.xml", XML, len(XML), telemetria=telemetria)
        telemetria.persistir(self.conn, str(self.db))
        linha = self.conn.execute(
            "SELECT namespace_xml,versao_layout,identificacao_parser FROM eventos"
        ).fetchone()
        self.assertEqual(linha[1], "S_01_03_00")
        self.assertEqual(linha[2], "sniffer_confirmado")
        self.assertGreater(self.conn.execute("SELECT COUNT(*) FROM telemetria").fetchone()[0], 5)
        self.assertEqual(self.conn.execute("SELECT quantidade FROM telemetria_eventos WHERE tipo='S-1200'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
