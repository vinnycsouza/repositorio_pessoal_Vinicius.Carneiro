import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import pickle
import zlib

from modules.auditoria_movimentos import (
    auditar_movimentos_workspace,
    corrigir_duplicidades_tecnicas,
    listar_auditoria_movimentos,
)


def xml_s1200(qtd_itens: int) -> bytes:
    itens = "".join(
        "<itensRemun><codRubr>R1</codRubr><ideTabRubr>T1</ideTabRubr><vrRubr>10.00</vrRubr></itensRemun>"
        for _ in range(qtd_itens)
    )
    return (
        "<eSocial><evtRemun><ideEvento><perApur>2024-01</perApur></ideEvento>"
        "<ideTrabalhador><cpfTrab>123</cpfTrab><dmDev><ideDmDev>D1</ideDmDev>"
        "<codCateg>101</codCateg><infoPerApur><ideEstabLot><tpInsc>1</tpInsc>"
        "<nrInsc>1</nrInsc><codLotacao>L1</codLotacao><remunPerApur>"
        "<matricula>M1</matricula>" + itens +
        "</remunPerApur></ideEstabLot></infoPerApur></dmDev></ideTrabalhador>"
        "</evtRemun></eSocial>"
    ).encode()


class AuditoriaMovimentosTest(unittest.TestCase):
    def _banco(self, pasta: Path, qtd_xml: int, qtd_sqlite: int) -> Path:
        db = pasta / "processamento.db"
        conn = sqlite3.connect(db)
        conn.executescript("""
        CREATE TABLE meta(chave TEXT PRIMARY KEY,valor TEXT);
        CREATE TABLE eventos(id INTEGER PRIMARY KEY,arquivo TEXT,tipo TEXT,ativo INTEGER,
          duplicado_logico_de INTEGER,xml_zlib BLOB);
        CREATE TABLE dados_remuneracoes(
          evento_id_origem INTEGER,cpf TEXT,matricula TEXT,per_apur TEXT,cod_categ TEXT,
          tp_insc_estab TEXT,nr_insc_estab TEXT,cod_lotacao TEXT,cod_rubr TEXT,
          ide_tab_rubr TEXT,vr_rubr REAL);
        """)
        conn.execute(
            "INSERT INTO eventos VALUES(1,'s1200.xml','S-1200',1,NULL,?)",
            (zlib.compress(xml_s1200(qtd_xml)),),
        )
        conn.executemany(
            "INSERT INTO dados_remuneracoes VALUES(1,'123','M1','2024-01','101','1','1','L1','R1','T1',10)",
            [()] * qtd_sqlite,
        )
        conn.commit()
        conn.close()
        return db

    def test_confirma_excesso_somente_quando_sqlite_supera_xml(self):
        with tempfile.TemporaryDirectory(dir=".test_tmp") as tmp:
            db = self._banco(Path(tmp), 1, 3)
            resumo = auditar_movimentos_workspace(db)
            self.assertEqual(resumo.linhas_excedentes_confirmadas, 2)
            self.assertEqual(resumo.impacto_excedente, 20.0)
            self.assertEqual(
                listar_auditoria_movimentos(db)[0]["classificacao"],
                "DUPLICIDADE_TECNICA_CONFIRMADA",
            )

    def test_preserva_repeticao_que_existe_no_xml(self):
        with tempfile.TemporaryDirectory(dir=".test_tmp") as tmp:
            db = self._banco(Path(tmp), 2, 2)
            resumo = auditar_movimentos_workspace(db)
            self.assertEqual(resumo.linhas_excedentes_confirmadas, 0)
            self.assertEqual(resumo.grupos_legitimos_no_xml, 1)

    def test_correcao_e_confirmada_auditavel_e_idempotente(self):
        with tempfile.TemporaryDirectory(dir=".test_tmp") as tmp:
            db = self._banco(Path(tmp), 1, 3)
            auditar_movimentos_workspace(db)
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE objetos(id INTEGER PRIMARY KEY,categoria TEXT,evento_id INTEGER,payload BLOB)")
            payload_antigo = zlib.compress(pickle.dumps(["duplicado"] * 3, protocol=5))
            conn.execute(
                "INSERT INTO objetos(categoria,evento_id,payload) VALUES('remuneracoes',1,?)",
                (payload_antigo,),
            )
            conn.commit()
            conn.close()
            with patch("modules.sqlite_relatorio.reiniciar_materializacao_analitica"), \
                 patch("modules.sqlite_relatorio.materializar_tabelas_analiticas"):
                resultado = corrigir_duplicidades_tecnicas(db, confirmar=True)
                repeticao = corrigir_duplicidades_tecnicas(db, confirmar=True)
            self.assertEqual(resultado["eventos_corrigidos"], 1)
            self.assertEqual(repeticao["eventos_corrigidos"], 0)
            conn = sqlite3.connect(db)
            try:
                novo = conn.execute(
                    "SELECT payload FROM objetos WHERE categoria='remuneracoes' AND evento_id=1"
                ).fetchone()[0]
                itens = pickle.loads(zlib.decompress(novo))
                self.assertEqual(len(itens), 1)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM auditoria_correcoes_movimentos").fetchone()[0], 1
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
