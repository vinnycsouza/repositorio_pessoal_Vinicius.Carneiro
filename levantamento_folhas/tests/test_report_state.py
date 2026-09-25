import unittest
import test_core
import report_state

class ReportStateTests(unittest.TestCase):
    def test_company_change_resets_filters_and_old_download(self):
        s={};a={'id':3,'name':'AJ','docs':[{'cnpj':'AJ'}]}
        report_state.context(s,a);s.update(report_companies=['AJ'],report_periods=['2024-01'],excel=b'old',excel_signature='old')
        report_state.context(s,{'id':4,'name':'Adserv','docs':[{'cnpj':'Adserv'}]})
        self.assertNotIn('excel',s);self.assertNotIn('report_periods',s)
        report_state.multiselect(s,'report_companies',['Adserv'])
        self.assertEqual(s['report_companies'],['Adserv'])
    def test_valid_manual_selection_survives_reruns(self):
        s={};report_state.multiselect(s,'p',['a','b','c']);s['p']=['b']
        report_state.multiselect(s,'p',['a','b','c']);self.assertEqual(s['p'],['b'])
        report_state.multiselect(s,'p',['b','d']);self.assertEqual(s['p'],['b'])
    def test_intentional_empty_selection_remains_empty(self):
        s={};report_state.multiselect(s,'p',['a','b']);s['p']=[]
        report_state.multiselect(s,'p',['a','b']);self.assertEqual(s['p'],[])
    def test_removed_scope_defaults_to_available_values(self):
        s={};report_state.multiselect(s,'p',['a']);report_state.multiselect(s,'p',['b'])
        self.assertEqual(s['p'],['b'])
        report_state.multiselect(s,'p',[]);report_state.multiselect(s,'p',['c'])
        self.assertEqual(s['p'],['c'])
    def test_single_competence_remains_valid(self):
        s={};report_state.single(s,'m',['2018-01','2019-01']);self.assertEqual(s['m'],'2019-01')
        report_state.single(s,'m',['2017-01']);self.assertEqual(s['m'],'2017-01')
        report_state.single(s,'m',[]);self.assertIsNone(s['m'])

if __name__=='__main__':unittest.main()
