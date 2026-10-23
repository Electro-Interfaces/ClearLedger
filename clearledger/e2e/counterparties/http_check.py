"""HTTP регрессии Контрагентов. Нужен только выделенный локальный server.py."""
import json
import os
import unittest
import uuid
from pathlib import Path

import httpx

BASE = 'http://127.0.0.1:18547'
results = []


class CounterpartyHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = httpx.Client(base_url=BASE, timeout=40, headers={'Connection': 'close'})
        cls.client.post('/api/__test/reset').raise_for_status()
        cls.rows = cls.client.get('/api/references/counterparties?company_id=counterparty-test').json()
        cls.alpha = next(row for row in cls.rows if row['name'] == 'Тест Альфа')
        cls.beta = next(row for row in cls.rows if row['name'] == 'Тест Бета')

    def tearDown(self):
        self.client.post('/api/__test/actor/admin').raise_for_status()

    def create(self, **fields):
        data = dict(company_id='counterparty-test', name='Тест '+uuid.uuid4().hex[:8], inn=str(uuid.uuid4().int)[:10])
        return self.client.post('/api/references/counterparties', json=data | fields)

    def test_create_read_update_and_clear(self):
        r = self.create(phone='123', email='test@example.invalid', kpp='111111111'); self.assertEqual(r.status_code,201,r.text)
        cp = r.json(); r = self.client.patch('/api/references/counterparties/'+cp['id'],json=dict(phone=None,email=None,kpp=None,name='Новое имя'))
        self.assertEqual(r.status_code,200,r.text)
        rows = self.client.get('/api/references/counterparties?company_id=counterparty-test').json()
        saved = next(row for row in rows if row['id']==cp['id'])
        self.assertEqual(saved['name'],'Новое имя'); self.assertIsNone(saved['phone']);self.assertIsNone(saved['email']);self.assertIsNone(saved['kpp'])

    def test_duplicate_create_and_update_have_same_rule(self):
        self.assertEqual(self.create(inn=self.alpha['inn'],kpp=self.alpha['kpp']).status_code,409)
        for body in [dict(inn=self.alpha['inn'],kpp=self.alpha['kpp']),dict(inn=self.alpha['inn'],kpp=None)]:
            r=self.client.patch('/api/references/counterparties/'+self.beta['id'],json=body)
            self.assertEqual(r.status_code,409,r.text)
        self.assertEqual(self.create(inn=self.alpha['inn'],kpp='222222222').status_code,201)

    def test_same_identity_can_edit_name(self):
        r=self.client.patch('/api/references/counterparties/'+self.alpha['id'],json=dict(name='Тест Альфа',inn=self.alpha['inn'],kpp=self.alpha['kpp']))
        self.assertEqual(r.status_code,200,r.text)

    def test_blank_names_and_lengths_reject_without_write(self):
        for name in ['', '   ', 'x'*501]:
            self.assertEqual(self.create(name=name).status_code,422)
            self.assertEqual(self.client.patch('/api/references/counterparties/'+self.beta['id'],json={'name':name}).status_code,422)
        for field, limit in [('inn',20),('kpp',20),('phone',100),('email',255),('bankAccount',30),('bankBik',12),('directorPosition',150)]:
            self.assertEqual(self.create(**{field:'x'*(limit+1)}).status_code,422,field)
        self.assertEqual(self.create(name='x'*500).status_code,201)

    def test_used_delete_is_conflict_and_keeps_links(self):
        r=self.client.delete('/api/references/counterparties/'+self.alpha['id']);self.assertEqual(r.status_code,409,r.text)
        contacts=self.client.get('/api/references/counterparties/'+self.alpha['id']+'/contacts').json();self.assertEqual(len(contacts),1)
        contracts=self.client.get('/api/references/contracts?company_id=counterparty-test').json();self.assertEqual(len(contracts),1)

    def test_unused_delete_and_missing_id(self):
        cp=self.create().json();r=self.client.delete('/api/references/counterparties/'+cp['id']);self.assertEqual(r.status_code,204,r.text)
        self.assertEqual(self.client.delete('/api/references/counterparties/'+cp['id']).status_code,404)
        self.assertEqual(self.client.delete('/api/references/counterparties/bad-id').status_code,400)

    def test_contact_validation_and_crud(self):
        path='/api/references/counterparties/'+self.beta['id']+'/contacts'
        for body in [{'name':'  '},{'name':'x'*256},{'name':'Тест','role':'unknown'}]:
            self.assertIn(self.client.post(path,json=body).status_code,(400,422))
        r=self.client.post(path,json={'name':' Тест инженер ','role':'tech','position':'Инженер','phone':'123'});self.assertEqual(r.status_code,201,r.text)
        contact=r.json();self.assertEqual(contact['name'],'Тест инженер')
        self.assertEqual(self.client.delete('/api/references/counterparties/'+self.beta['id']).status_code,409)
        r=self.client.put(path+'/'+contact['id'],json={'name':'Тест инженер','role':'tech','phone':None});self.assertEqual(r.status_code,200,r.text);self.assertIsNone(r.json()['phone'])
        self.assertEqual(self.client.delete(path+'/'+contact['id']).status_code,204)

    def test_foreign_company_inaccessible_to_member(self):
        foreign=self.client.get('/api/references/counterparties?company_id=foreign-test').json()[0]
        self.client.post('/api/__test/actor/member').raise_for_status()
        self.assertEqual(self.client.get('/api/references/counterparties?company_id=foreign-test').status_code,403)
        for method, data in [('PATCH',{'name':'Чужая правка'}),('DELETE',None)]:
            self.assertEqual(self.client.request(method,'/api/references/counterparties/'+foreign['id'],json=data).status_code,404)
        self.assertEqual(self.client.get('/api/references/counterparties/'+foreign['id']+'/contacts').status_code,404)


class Record(unittest.TextTestResult):
    def addSuccess(self,test):
        super().addSuccess(test);results.append({'scenario':test.id(),'status':'PASS'})
    def addFailure(self,test,err):
        super().addFailure(test,err);results.append({'scenario':test.id(),'status':'FAIL','error':self._exc_info_to_string(err,test)})
    def addError(self,test,err):
        super().addError(test,err);results.append({'scenario':test.id(),'status':'ERROR','error':self._exc_info_to_string(err,test)})


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(CounterpartyHTTP)
    result=unittest.TextTestRunner(verbosity=2,resultclass=Record).run(suite)
    path=Path(os.environ['COUNTERPARTY_HTTP_RESULTS']);path.write_text(json.dumps(results,ensure_ascii=False,indent=2))
    raise SystemExit(not result.wasSuccessful())
