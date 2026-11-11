import io
import os
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook

from modules.parser_xml import (
    parse_s1000_contexto,
    parse_s1010,
    parse_s1020_contexto,
    parse_s1200,
    parse_s1200_v10,
    parse_s2200_contexto,
    parse_s2299,
)
from modules.processador_zip import _montar_indice_rubricas, processar_fontes_esocial
from modules.data_source import SQLiteDataSource, WorkspaceContext
from modules.levantamento_sqlite import (
    FiltrosLevantamento, consultar_levantamento, consultar_rubricas,
    gerar_excel_levantamento_sqlite, obter_opcoes_filtros,
)


S1010 = """<eSocial><evtTabRubrica Id="I1010"><ideEvento/><ideEmpregador>
<tpInsc>1</tpInsc><nrInsc>12345678</nrInsc></ideEmpregador><infoRubrica><inclusao>
<ideRubrica><codRubr>100</codRubr><ideTabRubr>1</ideTabRubr><iniValid>2026-01</iniValid>
</ideRubrica><dadosRubrica><dscRubr>Salário</dscRubr><natRubr>1000</natRubr>
<tpRubr>1</tpRubr><codIncCP>11</codIncCP></dadosRubrica></inclusao></infoRubrica>
</evtTabRubrica></eSocial>"""

S1200 = """<eSocial><evtRemun Id="I1200"><ideEvento><indRetif>1</indRetif>
<perApur>2026-01</perApur></ideEvento><ideEmpregador><tpInsc>1</tpInsc>
<nrInsc>12345678</nrInsc></ideEmpregador><ideTrabalhador><cpfTrab>12345678901</cpfTrab>
<dmDev><ideDmDev>D1</ideDmDev><codCateg>101</codCateg><infoPerApur><ideEstabLot>
<tpInsc>1</tpInsc><nrInsc>12345678000199</nrInsc><codLotacao>L1</codLotacao>
<remunPerApur><matricula>M1</matricula><itensRemun><codRubr>100</codRubr>
<ideTabRubr>1</ideTabRubr><vrRubr>100.00</vrRubr></itensRemun></remunPerApur>
</ideEstabLot></infoPerApur></dmDev></ideTrabalhador><recibo><nrRecibo>R1</nrRecibo>
</recibo></evtRemun></eSocial>"""

S2299 = """<eSocial><evtDeslig Id="I2299"><ideEvento><indRetif>1</indRetif></ideEvento>
<ideEmpregador><tpInsc>1</tpInsc><nrInsc>12345678</nrInsc></ideEmpregador>
<ideVinculo><cpfTrab>12345678901</cpfTrab><matricula>M1</matricula></ideVinculo>
<infoDeslig><dtDeslig>2026-01-31</dtDeslig><codCateg>101</codCateg><verbasResc>
<dmDev><ideDmDev>D-RESC</ideDmDev><ideEstabLot><tpInsc>1</tpInsc>
<nrInsc>12345678000199</nrInsc><codLotacao>L1</codLotacao><detVerbas>
<codRubr>100</codRubr><ideTabRubr>1</ideTabRubr><vrRubr>75.50</vrRubr>
</detVerbas></ideEstabLot></dmDev></verbasResc></infoDeslig><recibo>
<nrRecibo>RD1</nrRecibo></recibo></evtDeslig></eSocial>"""


def zip_xmls(**arquivos: str) -> bytes:
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as compactado:
        for nome, xml in arquivos.items():
            compactado.writestr(nome, xml)
    return memoria.getvalue()


class ParsersV10Test(unittest.TestCase):
    def setUp(self):
        self.rubricas = parse_s1010(ET.fromstring(S1010), "s1010.xml")
        self.mapa = _montar_indice_rubricas(self.rubricas)

    def test_s1200_v10_equivale_ao_legado_no_contrato_atual(self):
        root = ET.fromstring(S1200)
        legado = [asdict(item) for item in parse_s1200(root, self.mapa, "s1200.xml")]
        novo = [asdict(item) for item in parse_s1200_v10(root, self.mapa, "s1200.xml")]
        self.assertEqual(novo, legado)

    def test_s2299_fica_segregado_com_origem_e_cruzamento_s1010(self):
        itens = parse_s2299(ET.fromstring(S2299), self.mapa, "s2299.xml")
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0].origem_movimento, "S-2299")
        self.assertEqual(itens[0].nr_recibo_evento, "RD1")
        self.assertEqual(itens[0].cod_inc_cp, "11")
        self.assertEqual(itens[0].per_apur, "2026-01")
        self.assertAlmostEqual(itens[0].vr_rubr, 75.5)

    def test_contextos_nao_criam_regra_tributaria(self):
        s1000 = ET.fromstring("""<eSocial><evtInfoEmpregador><ideEmpregador><tpInsc>1</tpInsc>
        <nrInsc>12345678</nrInsc></ideEmpregador><infoEmpregador><inclusao><idePeriodo>
        <iniValid>2026-01</iniValid></idePeriodo><infoCadastro><classTrib>99</classTrib>
        <indDesFolha>1</indDesFolha></infoCadastro></inclusao></infoEmpregador>
        </evtInfoEmpregador></eSocial>""")
        s1020 = ET.fromstring("""<eSocial><evtTabLotacao><ideEmpregador><tpInsc>1</tpInsc>
        <nrInsc>12345678</nrInsc></ideEmpregador><infoLotacao><inclusao><ideLotacao>
        <codLotacao>L1</codLotacao><iniValid>2026-01</iniValid></ideLotacao><dadosLotacao>
        <tpLotacao>01</tpLotacao><fpas>612</fpas><codTercs>3139</codTercs></dadosLotacao>
        </inclusao></infoLotacao></evtTabLotacao></eSocial>""")
        s2200 = ET.fromstring("""<eSocial><evtAdmissao><trabalhador><cpfTrab>12345678901</cpfTrab>
        </trabalhador><vinculo><matricula>M1</matricula><dtAdm>2026-01-02</dtAdm>
        <infoRegimeTrab><tpRegTrab>1</tpRegTrab><tpRegPrev>1</tpRegPrev></infoRegimeTrab>
        <infoContrato><codCateg>101</codCateg><codCargo>C1</codCargo><CBOCargo>411010</CBOCargo>
        </infoContrato></vinculo></evtAdmissao></eSocial>""")
        self.assertEqual(parse_s1000_contexto(s1000, "a.xml")[0].classificacao_tributaria, "99")
        self.assertEqual(parse_s1020_contexto(s1020, "b.xml")[0].fpas, "612")
        self.assertEqual(parse_s2200_contexto(s2200, "c.xml")[0].cod_categ, "101")


class IntegracaoV10Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"ESOCIAL_WORKSPACES_DIR": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_s2299_e_materializado_sem_alterar_rel_movimentos_cp(self):
        resultado = processar_fontes_esocial([(
            "empresa.zip",
            zip_xmls(**{"s1010.xml": S1010, "s2299.xml": S2299}),
        )])
        conn = sqlite3.connect(Path(resultado["db_path"]))
        try:
            s1200 = conn.execute("SELECT COUNT(*) FROM rel_movimentos_cp").fetchone()[0]
            s2299 = conn.execute("SELECT COUNT(*) FROM rel_movimentos_s2299").fetchone()[0]
            parser = conn.execute(
                "SELECT parser_versao FROM eventos WHERE tipo='S-2299'"
            ).fetchone()[0]
            versao = conn.execute(
                "SELECT valor FROM meta WHERE chave='versao_engine'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(s1200, 0)
        self.assertEqual(s2299, 1)
        self.assertIn("s2299", parser)
        self.assertEqual(versao, "10.0.0")

    def test_levantamento_escolhe_eventos_sem_alterar_a_folha_padrao(self):
        exclusivo = S2299.replace('Id="I2299"', 'Id="I2299B"').replace(
            "<nrRecibo>RD1", "<nrRecibo>RD2"
        ).replace("<matricula>M1", "<matricula>M2").replace(
            "2026-01-31", "2026-02-01"
        ).replace("<codRubr>100", "<codRubr>0292")
        resultado = processar_fontes_esocial([("empresa.zip", zip_xmls(**{
            "s1010.xml": S1010, "s1200.xml": S1200, "s2299.xml": S2299,
            "s2299b.xml": exclusivo,
            "s1010b.xml": S1010.replace('Id="I1010"', 'Id="I1010B"').replace(
                "<codRubr>100", "<codRubr>0292"
            ).replace("<codIncCP>11", "<codIncCP>00"),
        }))])
        fonte = SQLiteDataSource(WorkspaceContext.from_path(resultado["db_path"]))
        self.assertEqual(obter_opcoes_filtros(fonte, "Completo")["competencias"], ["2026-01", "2026-02"])
        catalogo = consultar_rubricas(fonte, FiltrosLevantamento(origem="S-2299"))
        self.assertEqual(set(catalogo.chave_rubrica), {"100||1", "0292||1"})
        for origem, total, movimentos, cpp in [
            ("S-1200", 100.0, 1, 20.0), ("S-2299", 151.0, 2, 30.2), ("Completo", 251.0, 3, 50.2),
        ]:
            with self.subTest(origem=origem):
                dados = consultar_levantamento(
                    fonte, FiltrosLevantamento(origem=origem), ["100||1", "0292||1"], 20.0,
                )
                self.assertEqual((dados.total, dados.qtd_movimentos), (total, movimentos))
                self.assertAlmostEqual(dados.cpp, cpp)
                if origem == "Completo":
                    por_origem = dados.resumo_rubricas.groupby("origem_levantamento").cpp_estimado.sum()
                    self.assertAlmostEqual(por_origem["S-1200"], 20.0)
                    self.assertAlmostEqual(por_origem["S-2299"], 30.2)
                    self.assertEqual(set(dados.movimentos_previa.cod_inc_cp), {"00", "11"})
        recorte = consultar_levantamento(
            fonte, FiltrosLevantamento(origem="Completo", competencias=("2026-01",)), ["100||1", "0292||1"], 20.0,
        )
        self.assertEqual(recorte.total, 175.5)
        self.assertEqual(set(recorte.movimentos_previa.origem_levantamento), {"S-1200", "S-2299"})
        destino = Path(self.temp.name) / "completo.xlsx"
        gerar_excel_levantamento_sqlite(
            fonte, destino, FiltrosLevantamento(origem="Completo", competencias=("2026-01",)),
            ["100||1", "0292||1"], recorte, resultado["empresa"], pd.DataFrame(), True,
        )
        wb = load_workbook(destino, read_only=True)
        try:
            linhas = wb["03_movimentos"].values
            colunas = next(linhas)
            self.assertEqual({(r[colunas.index("origem_levantamento")], r[colunas.index("ide_dm_dev")]) for r in linhas},
                             {("S-1200", "D1"), ("S-2299", "D-RESC")})
            resumo = wb["02_resumo_rubricas"].values
            campos = next(resumo)
            self.assertAlmostEqual(sum(r[campos.index("cpp_estimado")] for r in resumo), 35.1)
        finally:
            wb.close()

    def test_s1200_v10_so_assume_resultado_depois_da_equivalencia(self):
        with patch.dict(os.environ, {"ESOCIAL_V10_PARSER_S1200": "v10"}):
            resultado = processar_fontes_esocial([(
                "empresa.zip",
                zip_xmls(**{"s1010.xml": S1010, "s1200.xml": S1200}),
            )])
        conn = sqlite3.connect(Path(resultado["db_path"]))
        try:
            parser = conn.execute(
                "SELECT parser_versao FROM eventos WHERE tipo='S-1200'"
            ).fetchone()[0]
            equivalencias = conn.execute(
                "SELECT valor FROM meta WHERE chave='parser_s1200_sombra_equivalente'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertIn("s1200", parser)
        self.assertEqual(equivalencias, "1")


if __name__ == "__main__":
    unittest.main()
