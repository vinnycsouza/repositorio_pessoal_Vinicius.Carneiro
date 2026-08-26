import io
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from modules.data_source import SQLiteDataSource, WorkspaceContext
from modules.levantamento_sqlite import (
    FiltrosLevantamento,
    consultar_levantamento,
    consultar_rubricas,
    gerar_excel_levantamento_sqlite,
)
from modules.processador_zip import (
    atualizar_workspace_incremental,
    carregar_resultado_sqlite_existente,
    corrigir_duplicados_s1200_por_recibo,
    obter_resumo_carga_incremental,
    organizar_fontes_carga_inicial,
    processar_fontes_esocial,
)
from modules.sqlite_relatorio import (
    _SQL_MOVIMENTOS_CP_EFETIVOS,
    gerar_excel_saida_sqlite,
)


def zip_xmls(**arquivos: str) -> bytes:
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome, xml in arquivos.items():
            zf.writestr(nome, xml)
    return memoria.getvalue()


S1200 = """<eSocial><evtRemun Id="ID1200"><ideEvento><indRetif>1</indRetif><perApur>2026-01</perApur></ideEvento><ideEmpregador><tpInsc>1</tpInsc><nrInsc>12345678000199</nrInsc></ideEmpregador><ideTrabalhador><cpfTrab>12345678901</cpfTrab></ideTrabalhador><dmDev><ideDmDev>1</ideDmDev><codCateg>101</codCateg><infoPerApur><ideEstabLot><tpInsc>1</tpInsc><nrInsc>12345678000199</nrInsc><codLotacao>1</codLotacao><remunPerApur><matricula>1</matricula><itensRemun><codRubr>100</codRubr><ideTabRubr>1</ideTabRubr><vrRubr>100.00</vrRubr></itensRemun></remunPerApur></ideEstabLot></infoPerApur></dmDev><recibo><nrRecibo>R1</nrRecibo></recibo></evtRemun></eSocial>"""

S1010 = """<eSocial><evtTabRubrica Id="ID1010"><ideEvento><iniValid>2026-01</iniValid></ideEvento><ideEmpregador><tpInsc>1</tpInsc><nrInsc>12345678000199</nrInsc></ideEmpregador><infoRubrica><inclusao><ideRubrica><codRubr>100</codRubr><ideTabRubr>1</ideTabRubr><iniValid>2026-01</iniValid></ideRubrica><dadosRubrica><dscRubr>Salário</dscRubr><natRubr>1000</natRubr><tpRubr>1</tpRubr><codIncCP>11</codIncCP></dadosRubrica></inclusao></infoRubrica></evtTabRubrica></eSocial>"""

S3000 = """<eSocial><evtExclusao Id="ID3000"><ideEvento><perApur>2026-01</perApur></ideEvento><ideEmpregador><tpInsc>1</tpInsc><nrInsc>12345678000199</nrInsc></ideEmpregador><infoExclusao><tpEvento>S-1200</tpEvento><nrRecEvt>R1</nrRecEvt></infoExclusao></evtExclusao></eSocial>"""

S1200_RETIF = S1200.replace(
    '<indRetif>1</indRetif><perApur>',
    '<indRetif>2</indRetif><nrRecibo>R1</nrRecibo><perApur>',
).replace('<vrRubr>100.00</vrRubr>', '<vrRubr>250.00</vrRubr>').replace(
    '<nrRecibo>R1</nrRecibo></recibo>', '<nrRecibo>R2</nrRecibo></recibo>'
)

S1200_MESMO_RECIBO_OUTRO_XML = S1200.replace('Id="ID1200"', 'Id="ID1200-COPIA"')


class CargaIncrementalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"ESOCIAL_WORKSPACES_DIR": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _inicial(self):
        return processar_fontes_esocial(
            [("inicial.zip", zip_xmls(**{"s1200.xml": S1200}))]
        )

    def test_carga_inicial_combina_historico_antes_do_principal_e_recibos(self):
        fontes = organizar_fontes_carga_inicial(
            [("[PRINCIPAL] atual.zip", b"atual")],
            fontes_historico=[("[HISTORICO] antigo.zip", b"antigo")],
            fontes_recibos=[("[RECIBOS] recibos.zip", b"recibos")],
        )
        self.assertEqual(
            [nome for nome, _ in fontes],
            [
                "[HISTORICO] antigo.zip",
                "[PRINCIPAL] atual.zip",
                "[RECIBOS] recibos.zip",
            ],
        )

    def test_carga_inicial_sem_historico_preserva_fluxo_padrao(self):
        fontes = organizar_fontes_carga_inicial(
            [("[PRINCIPAL] atual.zip", b"atual")],
            fontes_recibos=[("[RECIBOS] recibos.zip", b"recibos")],
        )
        self.assertEqual(
            [nome for nome, _ in fontes],
            ["[PRINCIPAL] atual.zip", "[RECIBOS] recibos.zip"],
        )

    def test_carga_historica_preserva_ordem_de_original_e_retificacao(self):
        fontes = organizar_fontes_carga_inicial(
            [("[PRINCIPAL] recente.zip", zip_xmls(**{"retificacao.xml": S1200_RETIF}))],
            fontes_historico=[
                ("[HISTORICO] antigo.zip", zip_xmls(**{"original.xml": S1200}))
            ],
        )
        resultado = processar_fontes_esocial(fontes)
        conn = sqlite3.connect(Path(resultado["db_path"]))
        try:
            ativos, inativos = conn.execute(
                "SELECT SUM(ativo=1),SUM(ativo=0) FROM eventos WHERE tipo='S-1200'"
            ).fetchone()
            total = conn.execute(
                "SELECT SUM(CAST(vr_rubr AS REAL)) FROM rel_movimentos_cp"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual((ativos, inativos), (1, 1))
        self.assertAlmostEqual(total, 250.0)

    def test_complemento_novo_permanece_no_mesmo_workspace(self):
        inicial = self._inicial()
        workspace = Path(inicial["workspace_temporario"])
        atualizado = atualizar_workspace_incremental(
            workspace, [("rubricas.zip", zip_xmls(**{"s1010.xml": S1010}))]
        )
        self.assertEqual(Path(atualizado["workspace_temporario"]), workspace)
        self.assertEqual(len(list(Path(self.temp.name).glob("esocial_v3_*"))), 1)
        conn = sqlite3.connect(workspace / "processamento.db")
        try:
            status = conn.execute(
                "SELECT status_cp FROM rel_movimentos_cp WHERE cod_rubr='100'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(status, "Incide CP")
        self.assertEqual(atualizado["pacote_sqlite"]["total_movimentos_cp"], 1)

        relatorio = Path(self.temp.name) / "relatorio_atualizado.xlsx"
        gerar_excel_saida_sqlite(
            workspace / "processamento.db",
            relatorio,
            atualizado["empresa"],
            atualizado["pacote_sqlite"]["resumo_visual"],
            atualizado["pacote_sqlite"]["rubricas_cp"],
        )
        self.assertTrue(relatorio.is_file())

        fonte = SQLiteDataSource(WorkspaceContext.from_path(workspace))
        filtros = FiltrosLevantamento(status_cp="Incide CP")
        rubricas = consultar_rubricas(fonte, filtros)
        chave = rubricas.iloc[0]["chave_rubrica"]
        levantamento = consultar_levantamento(fonte, filtros, [chave], 20.0)
        destino_levantamento = Path(self.temp.name) / "levantamento_atualizado.xlsx"
        gerar_excel_levantamento_sqlite(
            fonte,
            destino_levantamento,
            filtros,
            [chave],
            levantamento,
            atualizado["empresa"],
            pd.DataFrame([{"Indicador": "Carga incremental", "Valor": "OK"}]),
            True,
        )
        self.assertTrue(destino_levantamento.is_file())
        self.assertEqual(levantamento.qtd_movimentos, 1)

    def test_duplicado_com_nome_diferente_e_ignorado_por_sha256(self):
        inicial = self._inicial()
        workspace = Path(inicial["workspace_temporario"])
        atualizado = atualizar_workspace_incremental(
            workspace, [("misturado.zip", zip_xmls(**{"renomeado.xml": S1200, "novo.xml": S1010}))]
        )
        resumo = atualizado["carga_incremental"]
        self.assertEqual(resumo["quantidade_xml_localizados"], 2)
        self.assertEqual(resumo["quantidade_xml_novos"], 1)
        self.assertEqual(resumo["quantidade_duplicados"], 1)
        conn = sqlite3.connect(workspace / "processamento.db")
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0], 2)
        finally:
            conn.close()

    def test_mesmo_recibo_em_xml_distinto_nao_duplica_movimentos(self):
        resultado = processar_fontes_esocial([
            ("sobrepostos.zip", zip_xmls(
                **{"primeiro.xml": S1200, "segundo.xml": S1200_MESMO_RECIBO_OUTRO_XML}
            ))
        ])
        conn = sqlite3.connect(Path(resultado["db_path"]))
        try:
            ativos, inativos = conn.execute(
                "SELECT SUM(ativo=1),SUM(ativo=0) FROM eventos WHERE tipo='S-1200'"
            ).fetchone()
            movimentos = conn.execute("SELECT COUNT(*) FROM rel_movimentos_cp").fetchone()[0]
            vinculo = conn.execute(
                "SELECT COUNT(*) FROM eventos WHERE duplicado_logico_de IS NOT NULL"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual((ativos, inativos), (1, 1))
        self.assertEqual(movimentos, 1)
        self.assertEqual(vinculo, 1)

    def test_corrige_workspace_legado_sem_reprocessar_xml(self):
        resultado = self._inicial()
        conn = sqlite3.connect(Path(resultado["db_path"]))
        try:
            canonico = conn.execute(
                "SELECT id FROM eventos WHERE tipo='S-1200'"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO eventos(arquivo,tipo,tamanho_bytes,envelope_recibo,xml_zlib,"
                "processado_segunda,hash_conteudo,ativo,id_evento_esocial,ind_retif,"
                "recibo_evento,recibo_referencia) "
                "SELECT 'copia.xml',tipo,tamanho_bytes,envelope_recibo,xml_zlib,1,'hash-copia',0,"
                "'ID-COPIA',ind_retif,recibo_evento,recibo_referencia FROM eventos WHERE id=?",
                (canonico,),
            )
            copia = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            payload = conn.execute(
                "SELECT payload FROM objetos WHERE categoria='remuneracoes' AND evento_id=?",
                (canonico,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO objetos(categoria,evento_id,payload) VALUES('remuneracoes',?,?)",
                (copia, payload),
            )
            conn.execute("INSERT INTO dados_remuneracoes SELECT * FROM dados_remuneracoes LIMIT 1")
            conn.execute(
                "UPDATE dados_remuneracoes SET arquivo='copia.xml' "
                "WHERE rowid=(SELECT MAX(rowid) FROM dados_remuneracoes)"
            )
            conn.execute(
                "DELETE FROM meta WHERE chave='versao_consistencia_recibo_s1200'"
            )
            conn.commit()
            resumo = corrigir_duplicados_s1200_por_recibo(conn)
            movimentos = conn.execute("SELECT COUNT(*) FROM rel_movimentos_cp").fetchone()[0]
            inventario = conn.execute("SELECT COUNT(*) FROM eventos WHERE tipo='S-1200'").fetchone()[0]
            linhas_brutas = conn.execute("SELECT COUNT(*) FROM dados_remuneracoes").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(resumo["eventos_inativados"], 1)
        self.assertEqual(resumo["objetos_preservados"], 1)
        self.assertEqual(movimentos, 1)
        self.assertEqual(inventario, 2)
        self.assertEqual(linhas_brutas, 2)

    def test_carregamento_reconstroi_consolidacao_interrompida(self):
        resultado = self._inicial()
        db = Path(resultado["db_path"])
        conn = sqlite3.connect(db)
        try:
            conn.execute("DROP TABLE rel_movimentos_cp")
            conn.execute("CREATE TABLE rel_movimentos_cp_nova(lixo TEXT)")
            conn.execute(
                "INSERT INTO meta(chave,valor) VALUES('versao_consistencia_recibo_s1200','2') "
                "ON CONFLICT(chave) DO UPDATE SET valor='2'"
            )
            conn.commit()
        finally:
            conn.close()
        mensagens = []
        carregado = carregar_resultado_sqlite_existente(
            db.parent,
            somente_levantamento=True,
            progress_callback=lambda valor, mensagem: mensagens.append(
                (valor, mensagem)
            ),
        )
        conn = sqlite3.connect(db)
        try:
            movimentos = conn.execute("SELECT COUNT(*) FROM rel_movimentos_cp").fetchone()[0]
            versao = conn.execute(
                "SELECT valor FROM meta WHERE chave='versao_consistencia_recibo_s1200'"
            ).fetchone()[0]
            temporaria = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='rel_movimentos_cp_nova'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(movimentos, 1)
        self.assertEqual(versao, "3")
        self.assertIsNone(temporaria)
        self.assertTrue(carregado["modo_sqlite_seguro"])
        self.assertTrue(any(
            "única varredura" in mensagem for _, mensagem in mensagens
        ))
        self.assertTrue(any(
            "Consolidações dos relatórios concluídas" in mensagem
            for _, mensagem in mensagens
        ))

    def test_plano_de_reconstrucao_varre_remuneracoes_uma_unica_vez(self):
        resultado = self._inicial()
        conn = sqlite3.connect(Path(resultado["db_path"]))
        try:
            # Reproduz um Workspace antigo que ainda não possui esse índice novo.
            conn.execute("DROP INDEX IF EXISTS idx_remun_arquivo")
            plano = [
                str(row[3])
                for row in conn.execute(
                    "EXPLAIN QUERY PLAN " + _SQL_MOVIMENTOS_CP_EFETIVOS
                )
            ]
        finally:
            conn.close()
        texto = " | ".join(plano)
        self.assertIn("SCAN r", texto)
        self.assertIn("SEARCH e USING INDEX", texto)
        self.assertIn("(arquivo=?)", texto)
        self.assertLess(texto.index("SCAN r"), texto.index("SEARCH e USING INDEX"))

    def test_s1010_duplicado_pode_ser_reprocessado_sem_duplicar_evento(self):
        inicial = processar_fontes_esocial(
            [("inicial.zip", zip_xmls(**{"s1200.xml": S1200, "s1010.xml": S1010}))]
        )
        workspace = Path(inicial["workspace_temporario"])
        atualizado = atualizar_workspace_incremental(
            workspace, [("recibo_reenviado.zip", zip_xmls(**{"outro_nome.xml": S1010}))]
        )
        resumo = atualizado["carga_incremental"]
        self.assertEqual(resumo["quantidade_xml_novos"], 0)
        self.assertEqual(resumo["quantidade_duplicados"], 1)
        conn = sqlite3.connect(workspace / "processamento.db")
        try:
            eventos = conn.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
            objetos = conn.execute(
                "SELECT COUNT(*) FROM objetos WHERE categoria='rubricas'"
            ).fetchone()[0]
            status = conn.execute(
                "SELECT status_cp FROM rel_movimentos_cp WHERE cod_rubr='100'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(eventos, 2)
        self.assertEqual(objetos, 1)
        self.assertEqual(status, "Incide CP")

    def test_s3000_reaplica_exclusao_sobre_base_acumulada(self):
        inicial = self._inicial()
        workspace = Path(inicial["workspace_temporario"])
        atualizado = atualizar_workspace_incremental(
            workspace, [("exclusao.zip", zip_xmls(**{"s3000.xml": S3000}))]
        )
        self.assertEqual(atualizado["pacote_sqlite"]["total_movimentos_cp"], 0)

    def test_retificacao_substitui_evento_anterior(self):
        inicial = self._inicial()
        workspace = Path(inicial["workspace_temporario"])
        atualizado = atualizar_workspace_incremental(
            workspace, [("retificacao.zip", zip_xmls(**{"retificacao.xml": S1200_RETIF}))]
        )
        conn = sqlite3.connect(workspace / "processamento.db")
        try:
            ativos, inativos = conn.execute(
                "SELECT SUM(ativo=1),SUM(ativo=0) FROM eventos WHERE tipo='S-1200'"
            ).fetchone()
            quantidade, total = conn.execute(
                "SELECT COUNT(*),SUM(CAST(vr_rubr AS REAL)) FROM rel_movimentos_cp"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual((ativos, inativos), (1, 1))
        self.assertEqual(quantidade, 1)
        self.assertAlmostEqual(total, 250.0)
        self.assertEqual(atualizado["pacote_sqlite"]["total_movimentos_cp"], 1)

    def test_retomada_reutiliza_historico_interrompido(self):
        inicial = self._inicial()
        workspace = Path(inicial["workspace_temporario"])
        fonte = [("rubricas.zip", zip_xmls(**{"s1010.xml": S1010}))]
        with patch("modules.processador_zip._segunda_passagem", side_effect=RuntimeError("interrupção simulada")):
            with self.assertRaisesRegex(RuntimeError, "interrupção simulada"):
                atualizar_workspace_incremental(workspace, fonte)
        interrompida = obter_resumo_carga_incremental(workspace)
        self.assertEqual(interrompida["status"], "interrompida")
        id_carga = interrompida["id_carga"]
        atualizado = atualizar_workspace_incremental(workspace, fonte)
        self.assertEqual(atualizado["carga_incremental"]["id_carga"], id_carga)
        self.assertEqual(atualizado["carga_incremental"]["status"], "concluida")
        self.assertEqual(atualizado["carga_incremental"]["quantidade_xml_novos"], 1)


if __name__ == "__main__":
    unittest.main()
