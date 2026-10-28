"""Читаемое представление ТП для проекта, плана, схемы и отчётов.

Факты и даты принадлежат карточке ТП, ход и исполнитель процессу Поддержки.
Чтение представления не запускает процессы и не меняет предметные данные.
"""
from datetime import date
from sqlalchemy import select
from app.models import User, UserCompany
from app.services import ezs_tp_steps as steps
from app.services import ezs_tp_workflow as workflow

PHASE_STEP = {'collect':'docs_ready','review':'docs_ready','submit':'applied','grid':'contract',
              'correction':'documents_review','works':'works_done','inspect':'checked',
              'documents':'atp','acquaint':None,'supply_prepare':'supply_applied','supply_wait':'supply_contract'}


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except (ValueError, TypeError):
        return None


def step_rows(tc, today=None):
    today = today or date.today()
    w = workflow.data_of(tc)
    result = []
    for row in steps.steps_out(tc, today):
        if row['branch'] == 'supply' and w.supply_mode not in ('direct','via_grid'):
            continue
        assignment = w.responsibilities.get(row['key'], w.responsibilities.get('default', workflow.Responsibility()))
        due = assignment.due or _date(row['plannedDate'])
        if row['key']=='works_done' and due is None:
            due=_date(tc.due_date)
        closed = (row['branch']=='main' and tc.status=='done') or (row['key']=='supply_applied' and bool((tc.steps or {}).get('supply_contract',{}).get('date')))
        result.append(dict(row, plannedDate=due.isoformat() if due else None,
            overdue=bool(due and due < today and not row['date'] and not closed),
            executorId=str(assignment.executor) if assignment.executor else None))
    return result


def deadlines(tc, today=None):
    today = today or date.today()
    w = workflow.data_of(tc)
    if tc.status == 'rejected' or w.archived:
        return []
    result = [dict(key='step:'+r['key'], label=r['label'], due=r['plannedDate'], branch=r['branch'])
              for r in step_rows(tc,today) if r['overdue']]
    for stage in w.stages:
        if stage.due and stage.due < today and not stage.done:
            result.append(dict(key='stage:'+str(stage.id),label=stage.title,due=stage.due.isoformat(),branch='main'))
    for remark in workflow.remarks_out(w,today):
        if remark['overdue']:
            result.append(dict(key='remark:'+remark['id'],label=remark['text'],due=remark['deadline'],
                               branch='supply' if remark['branch']=='supply' else 'main'))
    return result


def summary(tc, today=None, *, history=False):
    today = today or date.today()
    w = workflow.data_of(tc)
    snapshot = (tc.workflow or {}).get('_process') or {}
    rows = step_rows(tc,today)
    due = deadlines(tc,today)
    branches = []
    for key,label,enabled in [('tp_connection','Техприсоединение',tc.method in ('direct','indirect')),
                               ('tp_supply','Электроснабжение',w.supply_mode!='landlord')]:
        if not enabled:
            continue
        item = (snapshot.get('items') or {}).get(key) or {}
        stage = item.get('stage') or {}
        step_key = PHASE_STEP.get(stage.get('code'))
        deadline = next((r['plannedDate'] for r in rows if r['key']==step_key),None)
        if stage.get('code') == 'correction':
            candidates=[r['deadline'] for r in workflow.remarks_out(w,today) if not r['resolved'] and r['branch']=='application']
            deadline=min(candidates) if candidates else deadline
        if stage.get('code') == 'works':
            candidates=[x.due.isoformat() for x in w.stages if x.due and not x.done]
            deadline=min(candidates) if candidates else deadline
        branches.append(dict(key=key,label=label,state=item.get('state'),stage=stage,
            performer=({k:item['performer'].get(k) for k in ('id','name')} if item.get('performer') else None),due=deadline,overdue=bool(deadline and deadline<today.isoformat() and item.get('state')=='running'),
            startedAt=item.get('startedAt'),stepEnteredAt=item.get('stepEnteredAt'),
            steps=(item.get('steps') or []) if history else [],history=(item.get('history') or []) if history else []))
    active = [b for b in branches if b['state']=='running' and b['stage'].get('code') not in ('queued','done')]
    active.sort(key=lambda b:(not b['overdue'],b['due'] or '9999-12-31',b['key']))
    next_work = None
    if active and w.process_enabled and not w.archived and not snapshot.get('error'):
        b=active[0]
        next_work=dict(text=b['label']+': '+(b['stage'].get('name') or 'Продолжить работу'),due=b['due'],
                       performer=b['performer'],source='tech_connection')
    overall = bool(_date(tc.due_date) and _date(tc.due_date)<today and not tc.done_date and tc.status not in ('done','rejected'))
    return dict(enabled=w.process_enabled,scenario=workflow.SCENARIOS[w.scenario] if 'scenario' in (tc.workflow or {}) else 'Сценарий не указан',branches=branches,
                steps=rows,overdue=overall or bool(due),deadlines=due,
                openRemarks=sum(not r.resolved for r in w.remarks),
                stagesTotal=len(w.stages),stagesAccepted=sum(bool(s.accepted) for s in w.stages),
                archived=w.archived,syncedAt=snapshot.get('at'),error=snapshot.get('error'),nextWork=next_work)


async def read(db,tc,today=None):
    out=summary(tc,today,history=True)
    state=await workflow.read(db,tc)
    w=workflow.data_of(tc)
    ids={r.executor for r in w.responsibilities.values() if r.executor}
    ids|={s.executor for s in w.stages if s.executor}
    people=dict((await db.execute(select(User.id,User.name).join(UserCompany,UserCompany.user_id==User.id)
        .where(UserCompany.company_id==tc.company_id,User.id.in_(ids)))).all()) if ids else {}
    default=w.responsibilities.get('default',workflow.Responsibility())
    for row in out['steps']:
        assignment=w.responsibilities.get(row['key'],default)
        row['executor']=people.get(assignment.executor or default.executor)
    out.update(kit=dict(required=len(state['kit']),present=sum(x['present'] for x in state['kit']),
                        checked=sum(x['reviewed'] for x in state['kit']),ready=state['ready'],missing=state['missing']),
               supplyKit=dict(required=len(state['supplyKit']),present=sum(x['present'] for x in state['supplyKit']),
                              checked=sum(x['reviewed'] for x in state['supplyKit']),ready=state['supplyReady']),
               handover=state['handover'],supplyComplete=state['supplyComplete'],
               finalMissing=state['finalMissing'],
               stages=[dict(s.model_dump(mode='json'),executor=people.get(s.executor or default.executor)) for s in w.stages],
               remarks=workflow.remarks_out(w,today))
    return out


def _sql_date(expr):
    return f"CASE WHEN pg_input_is_valid({expr}, 'date') THEN ({expr})::date END"


def _sql_step_due(alias,step):
    raw=f"coalesce({alias}.workflow, '{{}}'::jsonb)"
    key=step['key']
    explicit=f"coalesce({raw}->'responsibilities'->'{key}'->>'due', {raw}->'responsibilities'->'default'->>'due')"
    result=_sql_date(explicit)
    if step.get('after'):
        previous=steps.STEP_BY_KEY[step['after']]
        fact=f'{alias}.{previous["field"]}' if previous.get('field') else f"{alias}.steps->'{previous['key']}'->>'date'"
        result=f'coalesce(({result}), ({_sql_date(fact)}) + {step["norm"]})'
    if key=='works_done':
        result=f'coalesce(({result}), ({_sql_date(alias+".due_date")}))'
    return result


def overdue_sql(alias='t',today='CURRENT_DATE'):
    """Те же сроки для отбора/сводки PostgreSQL, без сохранённого флага просрочки."""
    if alias not in ('t','tc','ezs_tech_connections') or today not in ('CURRENT_DATE',':today',':tp_today'):
        raise ValueError('Неизвестный источник сроков ТП')
    now=f'CAST({today} AS date)'
    valid=_sql_date
    def fact(step):
        return f'{alias}.{step["field"]}' if step.get('field') else f"{alias}.steps->'{step['key']}'->>'date'"
    raw=f"coalesce({alias}.workflow, '{{}}'::jsonb)"
    conditions=[]
    for step in steps.STEPS:
        key=step['key']
        planned=_sql_step_due(alias,step)
        applies=(f"{raw}->>'supply_mode' in ('direct','via_grid')" if step.get('branch')=='supply'
                 else f"{alias}.method in ('direct','indirect') and {alias}.status<>'done'")
        if key=='supply_applied':
            applies+=f" and nullif({alias}.steps->'supply_contract'->>'date','') is null"
        if step.get('only'):
            applies+=f" and {alias}.method='{step['only']}'"
        conditions.append(f"(({applies}) and nullif({fact(step)},'') is null and ({planned}) < {now})")
    stage_due=valid("s->>'due'")
    conditions.append(f"exists(select 1 from jsonb_array_elements(coalesce({raw}->'stages','[]'::jsonb)) s where nullif(s->>'done','') is null and ({stage_due}) < {now})")
    remark_date=valid("r->>'due'")
    received=valid("r->>'received'")
    remark_due=f"coalesce(({remark_date}), ({received}) + CASE WHEN r->>'branch'='application' OR r->>'branch' is null THEN 20 ELSE 0 END)"
    conditions.append(f"exists(select 1 from jsonb_array_elements(coalesce({raw}->'remarks','[]'::jsonb)) r where nullif(r->>'resolved','') is null and ({remark_due}) < {now})")
    overall=f"(({valid(alias+'.due_date')}) < {now} and nullif({alias}.done_date,'') is null and {alias}.status not in ('done','rejected'))"
    return f"({overall} OR ({alias}.status<>'rejected' and coalesce({raw}->>'archived','false')<>'true' and ({' OR '.join(conditions)})))"


def has_next_sql(alias='t'):
    if alias not in ('t','ezs_tech_connections'):
        raise ValueError('Неизвестный источник работы ТП')
    raw=f"coalesce({alias}.workflow, '{{}}'::jsonb)"
    return f"({raw}->>'process_enabled'='true' and coalesce({raw}->>'archived','false')<>'true' and nullif({raw}->'_process'->>'error','') is null and exists(select 1 from jsonb_each(coalesce({raw}->'_process'->'items','{{}}'::jsonb)) p where p.value->>'state'='running' and p.value->'stage'->>'code' not in ('queued','done') and ((p.key='tp_connection' and {alias}.method in ('direct','indirect')) or (p.key='tp_supply' and coalesce({raw}->>'supply_mode','landlord')<>'landlord'))))"


def next_deadline_sql(alias='t'):
    if alias not in ('t','ezs_tech_connections'):
        raise ValueError('Неизвестный источник работы ТП')
    raw=f"coalesce({alias}.workflow, '{{}}'::jsonb)"
    cases=[]
    for phase,key in PHASE_STEP.items():
        if key:
            due=_sql_step_due(alias,steps.STEP_BY_KEY[key])
            if phase.startswith('supply_'):
                due=f"CASE WHEN {raw}->>'supply_mode' in ('direct','via_grid') THEN ({due}) END"
            if phase=='correction':
                rd=_sql_date("r->>'due'");received=_sql_date("r->>'received'")
                due=f"coalesce((select min(coalesce(({rd}), ({received})+20)) from jsonb_array_elements(coalesce({raw}->'remarks','[]'::jsonb)) r where coalesce(r->>'branch','application')='application' and nullif(r->>'resolved','') is null), ({due}))"
            if phase=='works':
                sd=_sql_date("s->>'due'")
                due=f"coalesce((select min(({sd})) from jsonb_array_elements(coalesce({raw}->'stages','[]'::jsonb)) s where nullif(s->>'done','') is null), ({due}))"
            cases.append(f"WHEN '{phase}' THEN ({due})")
    return f"(select min(CASE p.value->'stage'->>'code' {' '.join(cases)} END) from jsonb_each(coalesce({raw}->'_process'->'items','{{}}'::jsonb)) p where p.value->>'state'='running' and ((p.key='tp_connection' and {alias}.method in ('direct','indirect')) or (p.key='tp_supply' and coalesce({raw}->>'supply_mode','landlord')<>'landlord')))"
