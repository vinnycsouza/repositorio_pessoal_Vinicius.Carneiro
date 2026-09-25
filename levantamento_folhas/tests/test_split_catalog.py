import io,unittest
from unittest.mock import patch
import test_core
import core,openpyxl,catalog_xlsx

class SplitCatalogTests(unittest.TestCase):
    def workbook(self,roots=('08362490','08362490'),split=True):
        w=openpyxl.Workbook();w.remove(w.active)
        for i,root in enumerate(roots,1):
            s=w.create_sheet('00_empresa_'+str(i));s.append(['cnpj_empregador']);s.append([root])
        for i in range(1,3 if split else 2):
            s=w.create_sheet('apoio_s1010_'+str(i) if split else 'apoio_s1010')
            s.append(['cod_rubr','ide_tab_rubr','dsc_rubr','cod_inc_cp','tp_rubr','ini_valid','fim_valid'])
            s.append(['000'+str(i),'RH3','SALARIO','11','1','2018-07',None])
        s=w.create_sheet('03_movimentos_cp_1');s.append(['not used'])
        b=io.BytesIO();w.save(b);b.seek(0);return b
    def test_all_identity_and_catalog_parts(self):
        c=core.import_catalog(self.workbook())
        self.assertEqual(c['empresa_raiz'],'08362490')
        self.assertEqual([r['cod_rubr'] for r in c['rubricas']],['0001','0002'])
        self.assertIn('00_empresa_2',c['identificacao_empresa'])
        self.assertIn('apoio_s1010_2',c['fonte'])
    def test_late_conflict_is_not_ignored(self):
        with self.assertRaisesRegex(ValueError,'empresas diferentes'):
            core.import_catalog(self.workbook(roots=('08362490','02633573')))
    def test_missing_identity_manual_still_works(self):
        c=core.import_catalog(self.workbook(roots=()),'08362490')
        self.assertTrue(c['identificacao_manual'])
    def test_unrelated_sheets_are_not_read(self):
        calls=[];original=catalog_xlsx.rows
        def tracked(z,path):
            calls.append(path);return original(z,path)
        with patch.object(catalog_xlsx,'rows',side_effect=tracked):
            core.import_catalog(self.workbook())
        self.assertNotIn('xl/worksheets/sheet5.xml',calls)
    def test_support_history_preferred_over_summary(self):
        b=self.workbook(split=False);w=openpyxl.load_workbook(b)
        s=w.create_sheet('02_rubricas_cp');s.append(['invalid summary'])
        out=io.BytesIO();w.save(out)
        self.assertEqual(len(core.import_catalog(out)['rubricas']),1)
    def test_numbered_fallback_and_numeric_order(self):
        b=self.workbook();w=openpyxl.load_workbook(b)
        w['apoio_s1010_1'].title='02_rubricas_cp_10';w['apoio_s1010_2'].title='02_rubricas_cp_2'
        out=io.BytesIO();w.save(out)
        c=core.import_catalog(out)
        self.assertEqual([r['cod_rubr'] for r in c['rubricas']],['0002','0001'])

if __name__=='__main__':unittest.main()
