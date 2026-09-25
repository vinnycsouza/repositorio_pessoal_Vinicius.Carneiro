import unittest
import test_refinement as fixtures
import core

class TwentyTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.RefinementTests();self.f.setUp()
        self.f.add('0012','PRO LABORE',3000000,'11',qty='2')
        self.d=self.f.d;self.a=self.f.a
        self.d['bases']={'mensal':3000000}
        self.d['grupos_empresa']=[{'base':'Mensal','grupo':'Alíquota de 20%','quantidade_base':2,'aliquota_percentual':20,
                                   'base_centavos':3000000,'contribuicao_centavos':600000,'pagina':1,
                                   'linha_contribuicao':'Valor da previdência empresa 2 20% 6.000,00'}]

    def mixed(self):
        self.d['bases']['mensal']+=100000
        self.d['grupos_empresa'].append({'base':'Mensal','grupo':'Contribuição zerada','quantidade_base':1,
                                        'aliquota_percentual':None,'base_centavos':100000,'contribuicao_centavos':0,
                                        'linha_contribuicao':'Valor da previdência empresa 0 0,00','pagina':1})

    def test_all_twenty_uses_signed_projection(self):
        self.f.add('0870','ATRASO',1000,'11','Desconto')
        s,e=core.twenty_composition(self.a)
        self.assertEqual(s[0]['parcela_projetada_centavos'],2999000)
        self.assertEqual(s[0]['saldo_nao_identificado_centavos'],1000)
        self.assertEqual(len(e),2)

    def test_mixed_does_not_assign_general_rubric(self):
        self.mixed();self.d['rubricas'][0]['quantidade']='3'
        s,e=core.twenty_composition(self.a)
        self.assertEqual(s[0]['parcela_projetada_centavos'],0)
        self.assertEqual(s[0]['saldo_nao_identificado_centavos'],3000000)
        self.assertEqual(e,[])

    def test_mixed_unique_hint_is_explicitly_conditional(self):
        self.mixed();s,e=core.twenty_composition(self.a)
        self.assertEqual(s[0]['situacao'],'Hipótese por valor e quantidade')
        self.assertEqual(s[0]['saldo_nao_identificado_centavos'],0)
        self.assertIn('não comprovado',s[0]['criterio'])

    def test_competing_hints_are_not_double_counted(self):
        self.mixed();self.f.add('0999','OUTRA',3000000,'11',qty='2')
        s,e=core.twenty_composition(self.a)
        self.assertEqual(s[0]['parcela_projetada_centavos'],0)
        self.assertEqual(len(e),2)
        self.assertTrue(all(r['parcela_centavos'] is None for r in e))

    def test_inconsistent_reference_is_unavailable(self):
        self.d['grupos_empresa'][0]['quantidade_base']=3
        s,e=core.twenty_composition(self.a)
        self.assertIsNone(s[0]['base_20_centavos'])
        self.assertIsNone(s[0]['parcela_projetada_centavos'])
        self.assertEqual(e,[])

    def test_zero_reference_has_no_projection(self):
        g=self.d['grupos_empresa'][0];g.update(grupo='Contribuição zerada',contribuicao_centavos=0,aliquota_percentual=None)
        s,e=core.twenty_composition(self.a)
        self.assertEqual(s[0]['base_20_centavos'],0)
        self.assertIsNone(s[0]['parcela_projetada_centavos'])
        self.assertEqual(e,[])

    def test_conflicting_candidate_closes_only_conditional_scenario(self):
        self.f.cat['rubricas'].append({**self.f.cat['rubricas'][0],'cod_inc_cp':'00'})
        s,e=core.twenty_composition(self.a)
        self.assertEqual(s[0]['parcela_projetada_centavos'],0)
        self.assertEqual(s[0]['saldo_nao_identificado_centavos'],3000000)
        self.assertEqual(s[0]['saldo_condicionado_centavos'],0)
        self.assertEqual(e[0]['parcela_candidata_centavos'],3000000)
        self.assertIsNone(e[0]['parcela_centavos'])
        self.assertEqual(core.details(self.a)[0]['efeito'],'Pendente')

    def test_conflicting_candidate_not_allocated_to_mixed_group(self):
        self.mixed()
        self.f.cat['rubricas'].append({**self.f.cat['rubricas'][0],'cod_inc_cp':'00'})
        s,e=core.twenty_composition(self.a)
        self.assertIsNone(s[0]['saldo_condicionado_centavos'])
        self.assertEqual(e,[])
