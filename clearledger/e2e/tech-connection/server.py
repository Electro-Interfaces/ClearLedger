"""Изолированный стенд для браузера, только localhost/tp_test."""
import asyncio
import os
import sys
from pathlib import Path
os.environ['DATABASE_URL'] = os.environ['TEST_DATABASE_URL']
root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root/'server/tests'), str(root/'server')]
from test_tp_workflow_integration import TpIntegration, RUN
if not RUN: raise RuntimeError('Только локальная tp_test')
TpIntegration.setUpClass()
case = TpIntegration()
asyncio.run(case.asyncSetUp())
asyncio.run(case.client.aclose())
app = case.app
@app.get('/api/__test/identity')
async def identity():
    return {'companyId':str(case.company.id), 'siteId':str(case.site.id), 'organizationId':str(case.org.id), 'personId':str(case.user.id)}
import uvicorn
uvicorn.run(app, host='127.0.0.1', port=18539, log_level='warning')
