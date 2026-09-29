import io
import unittest
import openpyxl
import core
import test_twenty


class ConciliationTests(unittest.TestCase):
    def setUp(self):
        fixture=test_twenty.TwentyTests();fixture.setUp()
        self.fixture=fixture
        self.a=fixture.a
        self.d=fixture.d

    def summary(self):
        return core.twenty_composition(self.a)[0][0]

    def maternity(self,cp='21'):
        self.fixture.f.add('0900','SALARIO MATERNIDADE',10000,cp)
        self.d['rubricas'][0]['valor_centavos']-=10000

    def test_exact_and_explicit_tolerance(self):
        self.assertEqual(self.summary()['conciliacao'],'Fechamento exato')
        self.d['rubricas'][0]['valor_centavos']-=1
        self.assertEqual(self.summary()['conciliacao'],'Divergente')
        self.a['tolerancia_conciliacao_centavos']=1
        self.assertEqual(self.summary()['conciliacao'],'Dentro da tolerância')
        self.d['rubricas'][0]['valor_centavos']+=3
        self.assertEqual(self.summary()['diferenca_absoluta_centavos'],2)
        self.assertEqual(self.summary()['conciliacao'],'Divergente')

    def test_maternity_is_diagnostic_only(self):
        self.maternity()
        result=self.summary()
        self.assertEqual(result['parcela_projetada_centavos'],2990000)
        scenario=result['cenarios_historicos'][0]
        self.assertEqual(scenario['conciliacao'],'Fechamento exato')
        self.assertEqual(scenario['reconstruida_centavos'],3000000)
        self.assertEqual(core.details(self.a)[1]['efeito'],'Pendente')

    def test_conflicting_maternity_not_adopted(self):
        self.maternity()
        catalog=self.fixture.f.cat['rubricas']
        catalog.append({**catalog[-1],'cod_inc_cp':'11'})
        self.assertEqual(self.summary()['cenarios_historicos'][0]['diferenca_centavos'],0)
        self.assertEqual(self.summary()['parcela_projetada_centavos'],2990000)

    def test_thirteenth_not_used_to_close_monthly(self):
        self.maternity('22')
        summaries,_=core.twenty_composition(self.a)
        self.assertEqual(summaries[0]['cenarios_historicos'],[])
        self.assertEqual(summaries[1]['cenarios_historicos'][0]['conciliacao'],'Inconclusiva')

    def test_mixed_groups_remain_inconclusive(self):
        self.maternity();self.fixture.mixed()
        self.assertEqual(self.summary()['conciliacao'],'Inconclusiva')
        scenario=self.summary()['cenarios_historicos'][0]
        self.assertIsNone(scenario['reconstruida_centavos'])

    def test_manual_exclusion_preserved(self):
        self.maternity()
        row=core.details(self.a)[1]
        self.a['decisions'][row['chave']]={'efeito':'Não integra (manual)'}
        self.assertEqual(self.summary()['cenarios_historicos'],[])
        self.assertEqual(core.details(self.a)[1]['efeito'],'Não integra (manual)')

    def test_other_company_and_tables_not_used(self):
        self.maternity()
        catalog=self.fixture.f.cat
        catalog['rubricas'].append({**catalog['rubricas'][-1],'ide_tab_rubr':'OTHER'})
        self.assertEqual(self.summary()['cenarios_historicos'],[])
        catalog['empresa_raiz']='99999999'
        self.assertEqual(self.summary()['cenarios_historicos'],[])

    def test_excel_contains_diagnostic_and_original_projection(self):
        self.maternity()
        workbook=openpyxl.load_workbook(io.BytesIO(core.export_excel(self.a)))
        sheet=workbook['Composição dos 20%']
        texts=[str(c.value) for row in sheet for c in row if c.value is not None]
        self.assertTrue(any('Conciliação: Divergente' in t for t in texts))
        values={row[0].value:row[3].value for row in sheet if row[0].value}
        self.assertEqual(values['Total projetado / hipótese'],29900)
        self.assertEqual(values['Base no cenário com maternidade'],30000)

    def test_invalid_tolerance_rejected(self):
        for value in (-1,True,1.5,'1'):
            self.a['tolerancia_conciliacao_centavos']=value
            with self.assertRaises(ValueError):self.summary()
