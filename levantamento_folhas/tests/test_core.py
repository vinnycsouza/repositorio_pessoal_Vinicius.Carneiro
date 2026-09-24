import io, sys, unittest, zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
import openpyxl

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.d={'cnpj':'02.633.573/0001-88','competencia':'2024-03','tipo':'Mensal','hash':'x','arquivo':'teste.pdf','empresa':'AJ','bases':{'mensal':90000},'totais':{},'checagens':[],'paginas':1,'alertas':[], 'rubricas':[
            {'codigo':'0001','descricao':'SALARIO','lado':'Provento','valor_centavos':100000,'pagina':1},
            {'codigo':'0116','descricao':'FALTAS','lado':'Desconto','valor_centavos':10000,'pagina':1}]}
        self.cat={'empresa_raiz':'02633573','rubricas':[{'cod_rubr':'0001','ide_tab_rubr':'RH3','dsc_rubr':'SALARIO','cod_inc_cp':'11','tp_rubr':'1','ini_valid':'2018-07','fim_valid':''},{'cod_rubr':'0116','ide_tab_rubr':'RH3','dsc_rubr':'FALTAS','cod_inc_cp':'11','tp_rubr':'2','ini_valid':'2018-07','fim_valid':''}]}
        self.a={'name':'Teste','docs':[self.d],'catalog':self.cat,'decisions':{},'errors':[]}
    def test_discount_reduces_and_suggestion_is_not_confirmation(self):
        c=core.reconciliation(self.a)[0]
        self.assertEqual(c['reconstruida_centavos'],90000)
        self.assertEqual(c['diferenca_centavos'],0)
        self.assertEqual(c['estado'],'Hipótese com sugestões')
    def test_old_period_is_pending(self):
        self.d['competencia']='2012-08'
        self.assertEqual(core.details(self.a)[0]['efeito'],'Pendente')
    def test_other_company_is_pending(self):
        self.d['cnpj']='08.362.490/0001-88'
        self.assertEqual(core.details(self.a)[0]['efeito'],'Pendente')
    def test_maternity_not_ordinary_addition(self):
        self.cat['rubricas'][0]['cod_inc_cp']='21'
        self.assertEqual(core.details(self.a)[0]['efeito'],'Pendente')
    def test_ambiguous_history_is_pending(self):
        self.cat['rubricas'].append({**self.cat['rubricas'][0],'cod_inc_cp':'00'})
        self.assertEqual(core.details(self.a)[0]['efeito'],'Pendente')
    def test_excel_numeric_and_identifiers(self):
        b=core.export_excel(self.a); w=openpyxl.load_workbook(io.BytesIO(b),data_only=False)
        s=w['Rubricas detalhadas']; heads=[c.value for c in s[1]]
        self.assertEqual(s.cell(2,heads.index('codigo')+1).value,'0001')
        self.assertEqual(s.cell(2,heads.index('valor (R$)')+1).value,1000)
        self.assertIn('Conferencia bases',w.sheetnames)
    def test_zip_paths_are_not_written(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z: z.writestr('../../outside.pdf',b'%PDF-test')
        items=list(core.unpack('test.zip',b.getvalue()))
        self.assertEqual(len(items),1)
        self.assertEqual(items[0][1],b'%PDF-test')
    def test_missing_base_is_not_zero(self):
        self.d['bases']={}
        c=core.reconciliation(self.a)[0]
        self.assertIsNone(c['informada_centavos']); self.assertIsNone(c['diferenca_centavos'])

if __name__=='__main__': unittest.main()
