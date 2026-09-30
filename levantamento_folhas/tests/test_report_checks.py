import copy,io,unittest
import openpyxl
import core,simple_report,test_twenty

class ReportCheckTests(unittest.TestCase):
    def setUp(self):
        self.f=test_twenty.TwentyTests();self.f.setUp()
        self.a=self.f.a

    def test_exact_with_pending_is_visible_without_changing_projection(self):
        self.f.f.add('9999','SEM REFERENCIA',1000,'99')
        checks=simple_report.report_checks(simple_report.blocks(self.a))
        self.assertEqual(checks['conciliacao']['Fechamento exato'],1)
        self.assertEqual(checks['exatos_com_pendencias'],1)
        self.assertEqual(checks['extracao'],{'incompleta':1})
        w=openpyxl.load_workbook(io.BytesIO(core.export_excel(self.a)))
        s=w['Composição dos 20%']
        row=next(r for r in s if r[0].value=='Fechamentos exatos com rubricas pendentes')
        self.assertEqual(row[3].value,1)
        self.assertEqual(row[3].number_format,'0')

    def test_all_three_checks_required(self):
        self.f.d['checagens']=[{'teste':k,'diferenca_centavos':0} for k in ('proventos','descontos')]
        self.assertEqual(simple_report.report_checks(simple_report.blocks(self.a))['extracao'],{'incompleta':1})
        self.f.d['checagens'].append({'teste':'liquido','diferenca_centavos':0})
        self.assertEqual(simple_report.report_checks(simple_report.blocks(self.a))['extracao'],{'confere':1})
        self.f.d['checagens'][0]['diferenca_centavos']=1
        self.assertEqual(simple_report.report_checks(simple_report.blocks(self.a))['extracao'],{'divergente':1})

    def test_missing_blocks_not_counted_and_overlap_flagged(self):
        original=copy.deepcopy(self.a)
        checks=simple_report.report_checks(simple_report.blocks(self.a))
        self.assertEqual(sum(checks['conciliacao'].values()),1)
        other=copy.deepcopy(self.f.d);other['hash']='second'
        self.a['docs'].append(other)
        self.assertEqual(simple_report.report_checks(simple_report.blocks(self.a))['possiveis_sobreposicoes'],1)
        self.a['docs'].pop()
        self.assertEqual(self.a,original)

    def test_pending_details_have_catalog_description(self):
        self.f.f.add('0265','SALARIO MATERNIDADE',1000,'21')
        w=openpyxl.load_workbook(io.BytesIO(core.export_excel(self.a)))
        text=' '.join(str(c.value) for row in w['Composição da base total'] for c in row if c.value)
        self.assertIn('Cadastro: SALARIO MATERNIDADE; incidência CP: 21',text)
