"""Синтетическая приёмка представлений ТП на отдельной локальной tp_test."""
import asyncio,os,sys,copy
from pathlib import Path
from datetime import date,timedelta
os.environ['DATABASE_URL']=os.environ['TEST_DATABASE_URL']
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'server/tests'),str(root/'server')]
from test_tp_workflow_integration import TpIntegration,RUN
from app import models as m
if not RUN:raise RuntimeError('Только локальная tp_test')
TpIntegration.setUpClass();case=TpIntegration()
async def prepare():
 await case.asyncSetUp();await case.client.aclose()
 def day(n):return (date.today()+timedelta(days=n)).isoformat()
 def at(n):return day(n)+'T00:00:00Z'
 import uuid
 async with case.sessions() as db:
  tc=await db.get(m.EzsTechConnection,case.tc.id)
  tc.status='in_progress';tc.application_date=day(-25);tc.contract_date=day(-15);tc.due_date=day(10)
  tc.steps={'docs_ready':{'date':day(-26)},'documents_review':{'date':day(-23)},'accepted':{'date':day(-20)},'supply_applied':{'date':day(-2)}}
  w=copy.deepcopy(case.w);w.update(process_enabled=True,supply_mode='direct')
  w['responsibilities'].update({'works_done':{'executor':str(case.user.id),'due':day(2)},'supply_contract':{'executor':str(case.user.id),'due':day(3)}})
  w['stages']=[{'id':str(uuid.uuid4()),'title':'Подготовка щита','due':day(-8),'done':day(-7),'notified':day(-6),'accepted':day(-5),'executor':str(case.user.id)},
               {'id':str(uuid.uuid4()),'title':'Кабель до ЭЗС','due':day(-1),'executor':str(case.user.id)}]
  w['remarks']=[{'id':str(uuid.uuid4()),'branch':'application','text':'Уточнить план размещения','received':day(-23),'due':day(-21),'resolved':day(-21),'response':'План исправлен'},
                {'id':str(uuid.uuid4()),'branch':'inspection','text':'Предъявить протокол измерений','received':day(-2),'due':day(-1),'response':''}]
  stages=[('queued','Назначение участников'),('collect','Сбор документов'),('review','Проверка комплекта'),('submit','Подача заявки'),('grid','Получение договора и ТУ'),('correction','Дополнение документов'),('works','Мероприятия ТУ'),('inspect','Проверка сетевой'),('documents','Итоговые документы'),('acquaint','Ознакомление'),('done','Завершено')]
  path=[('queued','collect',-27),('collect','review',-26),('review','submit',-25),('submit','grid',-24),('grid','correction',-23),('correction','grid',-21),('grid','works',-15)]
  person={'id':'synthetic','name':'Тест энергетик'}
  w['_process']={'at':at(0),'items':{'tp_connection':{'id':'synthetic-main','state':'running','stage':{'code':'works','name':'Мероприятия ТУ'},'performer':person,'startedAt':at(-28),'stepEnteredAt':at(-15),
      'steps':[{'code':code,'name':name,'is_initial':code=='queued','is_finish':code=='done'} for code,name in stages],
      'history':[{'from_code':a,'to_code':b,'at':at(n)} for a,b,n in path]},
      'tp_supply':{'id':'synthetic-supply','state':'running','stage':{'code':'supply_wait','name':'Заключить договор со сбытом'},'performer':person,'startedAt':at(-3),'stepEnteredAt':at(-2),
      'steps':[{'code':'supply_prepare','name':'Подготовить комплект сбыта','is_initial':True},{'code':'supply_wait','name':'Заключить договор со сбытом'},{'code':'done','name':'Договор заключён','is_finish':True}],
      'history':[{'from_code':'supply_prepare','to_code':'supply_wait','at':at(-2)}]}}}
  tc.workflow=w;await db.commit()
asyncio.run(prepare())
app=case.app
@app.get('/api/__test/identity')
async def identity():return {'companyId':str(case.company.id),'siteId':str(case.site.id),'site':{'id':str(case.site.id),'stage':'construction','kind':'new_build','stageSince':date.today().isoformat()}}
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=18549,log_level='warning')
