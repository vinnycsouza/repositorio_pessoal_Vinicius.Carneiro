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
    def test_previdencia_missing_and_zero_are_distinct(self):
        self.d['previdencia']={'previdencia_empresa_total':{'valor_centavos':0,'pagina':2}}
        rows=core.previdencia_rows(self.d)
        self.assertEqual(len(rows),4)
        self.assertIsNone(rows[0]['valor_centavos'])
        self.assertEqual(rows[1]['valor_centavos'],0)
        w=openpyxl.load_workbook(io.BytesIO(core.export_excel(self.a)))
        s=w['Resumo previdenciario']
        self.assertIsNone(s['E2'].value)
        self.assertEqual(s['E3'].value,0)

    def test_no_automatic_interest_selection(self):
        rows=core.details(self.a)
        self.assertTrue(all(not r['selecionada'] for r in rows))
        self.assertEqual(rows[1]['grupo'],'Reduções da base')

    def test_historical_reference_is_visible_but_not_applied(self):
        self.d['competencia']='2012-08'
        row=core.details(self.a)[0]
        self.assertEqual(row['codIncCP'],'11')
        self.assertEqual(row['descricao_relatorio'],'SALARIO')
        self.assertEqual(row['correspondencia'],'Sem vigência compatível')
        self.assertEqual(row['grupo'],'Não determinado')

    def test_selection_does_not_change_effect(self):
        row=core.details(self.a)[1]
        self.a['selections']={core.selection_key(row):True}
        after=core.details(self.a)[1]
        self.assertTrue(after['selecionada'])
        self.assertEqual(after['grupo'],'Reduções da base')
        self.assertEqual(core.reconciliation(self.a)[0]['reconstruida_centavos'],90000)

    def test_brazilian_display_and_numeric_excel(self):
        self.assertEqual(core.brl(253071630),'R$ 2.530.716,30')
        self.assertEqual(core.brl(-30000),'R$ -300,00')
        self.assertEqual(core.brl(0),'R$ 0,00')
        self.assertEqual(core.brl(None),'Não informado')
        w=openpyxl.load_workbook(io.BytesIO(core.export_excel(self.a)))
        s=w['Cruzamento por folha']; headings=[c.value for c in s[1]]
        cell=s.cell(2,headings.index('valor (R$)')+1)
        self.assertEqual(cell.data_type,'n')
        self.assertIn('R$',cell.number_format)
        self.assertEqual(w['Possiveis acrescimos'].max_row,2)
        self.assertEqual(w['Reducoes da base'].max_row,2)

    def test_missing_base_is_not_zero(self):
        self.d['bases']={}
        c=core.reconciliation(self.a)[0]
        self.assertIsNone(c['informada_centavos']); self.assertIsNone(c['diferenca_centavos'])

if __name__=='__main__': unittest.main()
