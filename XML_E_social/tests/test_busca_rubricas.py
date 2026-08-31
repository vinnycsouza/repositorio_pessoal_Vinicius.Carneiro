import unittest
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

from modules.busca_rubricas import (
    atualizar_selecao_rubricas,
    combinar_filtros_sql,
    extrair_termos_busca,
    filtrar_dataframe_por_chaves,
    filtrar_rubricas_por_multibusca,
    filtro_sql_chaves_rubricas,
    montar_manifesto_escopo_rubricas,
    termos_sem_correspondencia,
)
from modules.sqlite_relatorio import contar_movimentos_exportacao_sqlite


class BuscaRubricasTest(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame([
            {"cod_rubr": "100", "dsc_rubr": "Salário mensal"},
            {"cod_rubr": "1000", "dsc_rubr": "Gratificação"},
            {"cod_rubr": "A.20", "dsc_rubr": "Bônus especial"},
            {"cod_rubr": "300", "dsc_rubr": "Salario família"},
        ])

    def test_codigo_exige_correspondencia_exata(self):
        resultado, _ = filtrar_rubricas_por_multibusca(self.df, "100")
        self.assertEqual(resultado["cod_rubr"].tolist(), ["100"])
        self.assertEqual(resultado.iloc[0]["correspondencia_busca"], "Código exato: 100")

    def test_manifesto_distingue_encontradas_e_ausentes(self):
        catalogo = pd.DataFrame([
            {"cod_rubr": "100", "ide_tab_rubr": "T1", "dsc_rubr": "Salário",
             "qtd_lancamentos": 4, "valor_total": 50},
            {"cod_rubr": "100", "ide_tab_rubr": "T2", "dsc_rubr": "Salário antigo",
             "qtd_lancamentos": 2, "valor_total": 10},
        ])
        manifesto = montar_manifesto_escopo_rubricas(
            catalogo, ["100||T1"], ["100", "999"], "codigo_exato"
        )
        incluida = manifesto[manifesto["incluida"].eq("Sim")].iloc[0]
        ausente = manifesto[manifesto["termo_solicitado"].eq("999")].iloc[0]
        self.assertEqual(incluida["versoes_historicas"], 2)
        self.assertEqual(incluida["qtd_lancamentos"], 4)
        self.assertEqual(ausente["encontrada"], "Não")

    def test_manifesto_registra_correspondencia_por_descricao(self):
        catalogo = pd.DataFrame([{
            "cod_rubr": "DIFE", "ide_tab_rubr": "T1",
            "dsc_rubr": "Desconto de INSS de férias",
            "qtd_lancamentos": 3, "valor_total": 100,
        }])
        manifesto = montar_manifesto_escopo_rubricas(
            catalogo, ["DIFE||T1"], ["férias"], "descricao"
        )
        self.assertEqual(manifesto.iloc[0]["termo_solicitado"], "férias")
        self.assertEqual(
            manifesto.iloc[0]["motivo_correspondencia"], "Trecho da descrição"
        )

    def test_descricao_ignora_acentos_e_caixa(self):
        resultado, _ = filtrar_rubricas_por_multibusca(
            self.df, "SALARIO", modo="descricao"
        )
        self.assertEqual(set(resultado["cod_rubr"]), {"100", "300"})

    def test_ponto_nao_quebra_codigo(self):
        self.assertEqual(extrair_termos_busca("A.20; 300"), ["A.20", "300"])
        resultado, _ = filtrar_rubricas_por_multibusca(self.df, "A.20")
        self.assertEqual(resultado["cod_rubr"].tolist(), ["A.20"])

    def test_lista_usa_logica_ou_e_remove_duplicados(self):
        resultado, termos = filtrar_rubricas_por_multibusca(
            self.df, "100\n300"
        )
        self.assertEqual(termos, ["100", "300"])
        self.assertEqual(set(resultado["cod_rubr"]), {"100", "300"})

    def test_informa_termos_sem_correspondencia(self):
        termos = ["100", "INEXISTENTE"]
        self.assertEqual(
            termos_sem_correspondencia(self.df, termos),
            ["INEXISTENTE"],
        )

    def test_codigo_dife_nao_encontra_descricao_diferencial(self):
        df = pd.DataFrame([
            {"cod_rubr": "DIFE", "dsc_rubr": "Desconto INSS férias"},
            {"cod_rubr": "V115", "dsc_rubr": "DIFERENCIAL GEOGRÁFICO"},
        ])
        por_codigo, _ = filtrar_rubricas_por_multibusca(df, "DIFE")
        self.assertEqual(por_codigo["cod_rubr"].tolist(), ["DIFE"])

        por_descricao, _ = filtrar_rubricas_por_multibusca(
            df, "DIFE", modo="descricao"
        )
        self.assertEqual(por_descricao["cod_rubr"].tolist(), ["V115"])

    def test_substituir_nao_mantem_selecao_antiga(self):
        self.assertEqual(
            atualizar_selecao_rubricas(
                {"ANTIGA||1", "MANTER||1"}, {"NOVA||1"}, "substituir"
            ),
            ["NOVA||1"],
        )

    def test_adicionar_e_remover_sao_acoes_separadas(self):
        adicionadas = atualizar_selecao_rubricas(
            {"A||1"}, {"B||1"}, "adicionar"
        )
        self.assertEqual(adicionadas, ["A||1", "B||1"])
        self.assertEqual(
            atualizar_selecao_rubricas(adicionadas, {"A||1"}, "remover"),
            ["B||1"],
        )

    def test_filtro_dataframe_respeita_codigo_e_tabela(self):
        df = pd.DataFrame([
            {"cod_rubr": "100", "ide_tab_rubr": "A", "valor": 10},
            {"cod_rubr": "100", "ide_tab_rubr": "B", "valor": 20},
            {"cod_rubr": "200", "ide_tab_rubr": "A", "valor": 30},
        ])
        resultado = filtrar_dataframe_por_chaves(df, ["100||B"])
        self.assertEqual(resultado["valor"].tolist(), [20])

    def test_filtro_sql_combina_modo_e_chave_com_exatidao(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE movimentos(cod_rubr TEXT,ide_tab_rubr TEXT,status_cp TEXT)"
        )
        conn.executemany(
            "INSERT INTO movimentos VALUES(?,?,?)",
            [("100", "A", "Incide CP"), ("100", "B", "Incide CP"),
             ("100", "B", "Não incide CP")],
        )
        filtro = combinar_filtros_sql(
            "WHERE status_cp='Incide CP'",
            filtro_sql_chaves_rubricas(["100||B"]),
        )
        linhas = conn.execute("SELECT cod_rubr,ide_tab_rubr FROM movimentos" + filtro).fetchall()
        conn.close()
        self.assertEqual(linhas, [("100", "B")])

    def test_none_mantem_completo_e_lista_vazia_nao_exporta(self):
        self.assertEqual(filtro_sql_chaves_rubricas(None), "")
        self.assertEqual(filtro_sql_chaves_rubricas([]), "0=1")

    def test_contagem_sqlite_aplica_modo_e_rubrica(self):
        with tempfile.TemporaryDirectory() as pasta:
            banco = Path(pasta) / "processamento.db"
            conn = sqlite3.connect(banco)
            conn.execute(
                "CREATE TABLE rel_movimentos_cp("
                "cod_rubr TEXT,ide_tab_rubr TEXT,status_cp TEXT)"
            )
            conn.executemany(
                "INSERT INTO rel_movimentos_cp VALUES(?,?,?)",
                [("100", "A", "Incide CP"), ("100", "B", "Incide CP"),
                 ("100", "B", "Não incide CP")],
            )
            conn.commit()
            conn.close()
            self.assertEqual(
                contar_movimentos_exportacao_sqlite(
                    banco, "incidencia_cp_padrao", ["100||B"]
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
