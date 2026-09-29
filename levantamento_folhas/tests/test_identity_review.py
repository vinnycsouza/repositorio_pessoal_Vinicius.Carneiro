import io
import unittest
import openpyxl
import core
import test_twenty

class IdentityReviewTests(unittest.TestCase):
    def setUp(self):
        self.f=test_twenty.TwentyTests();self.f.setUp()
        self.f.f.add('8003','RETENCAO JUDICIAL',17785,'11','Desconto')
        self.f.f.cat['rubricas'][-1]['dsc_rubr']='SUSPENSAO'
        self.a=self.f.a

    def test_conflict_keeps_code_and_suspends_reduction(self):
        row=core.details(self.a)[1]
        self.assertEqual(row['codigo'],'8003')
        self.assertEqual(row['efeito'],'Pendente')
        summary=core.twenty_composition(self.a)[0][0]
        self.assertEqual(summary['saldo_nao_identificado_centavos'],0)
        scenario=summary['cenarios_identidade'][0]
        self.assertEqual(scenario['diferenca_centavos'],17785)
        self.assertEqual(scenario['parcela_centavos'],-17785)

    def test_other_company_not_blocked(self):
        self.f.d['cnpj']='08.362.490/0001-88'
        self.f.f.cat['empresa_raiz']='08362490'
        self.assertEqual(core.details(self.a)[1]['efeito'],'Reduz (sugestão)')

    def test_corrected_catalog_removes_conflict(self):
        self.f.f.cat['rubricas'][-1]['dsc_rubr']='RETENCAO JUDICIAL'
        self.assertEqual(core.details(self.a)[1]['efeito'],'Reduz (sugestão)')

    def test_other_description_preserves_code_priority(self):
        self.f.d['rubricas'][-1]['descricao']='SUSPENSAO RETROATIVA'
        self.assertEqual(core.details(self.a)[1]['efeito'],'Reduz (sugestão)')

    def test_manual_resolution_wins(self):
        row=core.details(self.a)[1]
        self.a['decisions'][row['chave']]={'efeito':'Reduz (manual)','justificativa':'Confirmado na folha'}
        self.assertEqual(core.details(self.a)[1]['efeito'],'Reduz (manual)')
        self.assertEqual(core.twenty_composition(self.a)[0][0]['cenarios_identidade'],[])

    def test_mixed_group_not_assigned(self):
        self.f.mixed()
        scenario=core.twenty_composition(self.a)[0][0]['cenarios_identidade'][0]
        self.assertIsNone(scenario['reconstruida_centavos'])
        self.assertEqual(scenario['conciliacao'],'Inconclusiva')

    def test_export_exposes_both_descriptions(self):
        w=openpyxl.load_workbook(io.BytesIO(core.export_excel(self.a)))
        text=' '.join(str(c.value) for row in w['Composição dos 20%'] for c in row if c.value)
        self.assertIn('RETENCAO JUDICIAL',text)
        self.assertIn('Cadastro: SUSPENSAO',text)
        self.assertIn('Diferença no cenário de identidade',text)
