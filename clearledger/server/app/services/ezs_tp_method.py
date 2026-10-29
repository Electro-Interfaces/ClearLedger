"""Методика ТП: исходные сведения, документы и связь со штатными процессами.

Ходом владеет Поддержка; этот модуль передаёт факты, а не выбирает ребро графа.
Ознакомление — штатные DocCard/DocVersion/DocAcquaint, с подписью самого получателя.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import uuid
import zipfile
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.models import (EzsSite, EzsTechConnection, ServiceLocation, Contract, Organization,
                        User, DocKind, DocCard, DocVersion, DocAcquaint, SourceFile, DocRelation)


def capacity_profile(tc):
    raw = str(tc.voltage or '0.4').lower().replace(',', '.').replace(' ', '')
    match = re.fullmatch(r'(\d+(?:\.\d+)?)(кв|kv|в|v)?', raw)
    kv = (float(match[1]) / (1000 if match[2] in ('в', 'v') else 1)) if match else None
    unknown = tc.power_kwt is None or (getattr(tc, 'workflow', None) or {}).get('scenario') in ('increase','redistribution') and tc.existing_power_kwt is None
    total = None if unknown else max(0, float(tc.power_kwt)) + max(0, float(tc.existing_power_kwt or 0))
    return {'totalKw': total, 'voltageKv': kv,
            'band': 'Мощность не указана' if total is None else 'до 150 кВт' if total <= 150 else 'свыше 150 до 670 кВт' if total <= 670 else 'свыше 670 кВт',
            'applicationForm': 'undetermined' if total is None else 'standard150' if total <= 150 else 'operator',
            'sourceUrl': 'https://utp.rossetimr.ru/docs/format-requests-contracts-samples-filling'}


async def prefill(db, tc, site, *, apply=False):
    """Только незаполненное, с происхождением; мощность станции не равна мощности ТП."""
    from app.services import ezs_tp_workflow as tp
    w = tp.data_of(tc)
    loc = await db.get(ServiceLocation, site.location_id) if site.location_id else None
    if loc is not None and loc.company_id != tc.company_id: loc = None
    meta = (loc.extra_metadata or {}) if loc else {}
    # Эти явные ключи паспорта относятся к присоединению, а не к номиналу зарядных постов.
    candidates = {
        'existing_power_kwt': (meta.get('connectedPowerKwt'), 'Паспорт объекта: присоединённая мощность'),
        'voltage': (meta.get('connectionVoltageKv'), 'Паспорт объекта: напряжение присоединения'),
        'grid_operator': (meta.get('gridOperator'), 'Паспорт объекта: сетевая организация'),
        'energy_supplier': (meta.get('energySupplier'), 'Паспорт объекта: сбытовая организация'),
        'tp_coords': (meta.get('tpCoordinates'), 'Паспорт объекта: координаты точки присоединения'),
        'power_kwt': (site.planned_power_kwt, 'Паспорт проекта: планируемая мощность'),
    }
    if w.supply_contract_id:
        contract = await db.get(Contract, w.supply_contract_id)
        if contract and contract.company_id == tc.company_id:
            from app.models import Counterparty
            counterparty = await db.get(Counterparty, contract.counterparty_id) if contract.counterparty_id else None
            if counterparty and counterparty.company_id == tc.company_id:
                candidates['energy_supplier'] = (counterparty.name, 'Контрагент выбранного договора электроснабжения')
    # Прежнее ТП того же объекта — подтверждённый факт, если запись однозначна.
    if loc and candidates['existing_power_kwt'][0] is None:
        old = (await db.execute(select(EzsTechConnection).join(EzsSite, EzsSite.id == EzsTechConnection.site_id)
               .where(EzsSite.location_id == loc.id, EzsTechConnection.company_id == tc.company_id,
                      EzsTechConnection.id != tc.id, EzsTechConnection.status == 'done'))).scalars().all()
        if len(old) == 1:
            previous = old[0]
            candidates['existing_power_kwt'] = (((previous.power_kwt or 0)+(previous.existing_power_kwt or 0)) if previous.power_kwt is not None or previous.existing_power_kwt is not None else None, 'Исполненное ТП этого объекта')
            for field in ('voltage', 'grid_operator', 'energy_supplier', 'tp_coords'):
                if candidates[field][0] in (None, ''):
                    candidates[field] = (getattr(previous, field), 'Исполненное ТП этого объекта')
    out = []
    for field, (value, source) in candidates.items():
        if getattr(tc, field) not in (None, '') or value in (None, ''): continue
        if field in ('power_kwt', 'existing_power_kwt'):
            try: value = float(str(value).replace(',', '.'))
            except ValueError: continue
            if value < 0: continue
        else: value = str(value)
        out.append({'field': field, 'value': value, 'source': source})
        if apply: setattr(tc, field, value)
    return out


async def handover_state(db, tc):
    ref = (tc.workflow or {}).get('_handover')
    if not ref: return {'exists': False, 'recipients': [], 'done': False}
    rows = (await db.execute(select(DocAcquaint, User.name).join(User, User.id == DocAcquaint.user_id)
            .where(DocAcquaint.company_id == tc.company_id, DocAcquaint.doc_id == uuid.UUID(ref['docId']),
                   DocAcquaint.snapshot_sha256 == ref['snapshot']))).all()
    return dict(ref, exists=True, done=bool(rows) and all(x.status == 'done' for x, _ in rows),
                recipients=[{'id': str(x.user_id), 'name': name, 'status': x.status,
                             'readAt': x.read_at.isoformat() if x.read_at else None} for x, name in rows])


async def create_handover(db, tc):
    from app.services import ezs_tp_workflow as tp
    from app.services.doc_approvals import _document_snapshot
    from app.services.doc_access import _docs_members
    from app.services.notify import notify_person, NOTICES_ROOM_KIND
    w = tp.data_of(tc)
    if not w.archived or (tc.workflow or {}).get('_handover'): return
    kinds, _, signatures = await tp.evidence(db, tc, w)
    if tp.final_missing(tc, w, kinds): return
    controllers = {r.controller for r in w.responsibilities.values() if r.controller}
    people = await _docs_members(db, tc.company_id, controllers)
    if set(people) != controllers or not people:
        raise HTTPException(400, 'Все контролирующие должны иметь доступ к «Треку» для ознакомления')
    site = await db.get(EzsSite, tc.site_id)
    packet_kinds = set(tp.required_kinds(tc,w) + tp.supply_kinds(tc,w)) | {
        'tu','tp_contract','tp_act','tp_avtu','tp_meter_act','power_contract',
        'tp_design','tp_tests','tp_circuit','tp_existing_act','tp_indirect','tp_power_share'}
    signatures = {k:v for k,v in signatures.items() if k in packet_kinds}
    ids = {uuid.UUID(f) for files in signatures.values() for f in files}
    sources = (await db.execute(select(SourceFile).where(SourceFile.company_id == tc.company_id,
                                                        SourceFile.id.in_(ids)))).scalars().all() if ids else []
    if {f.id for f in sources} != ids: raise HTTPException(409, 'Часть итоговых файлов недоступна')
    for f in sources:
        if not Path(f.storage_path).is_file(): raise HTTPException(409, 'Итоговый файл отсутствует в хранилище')
    kind = (await db.execute(select(DocKind).where(DocKind.company_id == tc.company_id,
                                                  DocKind.code == 'tp_completion'))).scalar_one_or_none()
    if kind is None:
        kind = DocKind(company_id=tc.company_id, code='tp_completion', name='Комплект завершения ТП', family='internal')
        db.add(kind); await db.flush()
    archive = dict((tc.workflow or {}).get('_archive') or {})
    archive['files'] = signatures
    digest = hashlib.sha256(json.dumps(archive, sort_keys=True).encode()).hexdigest()
    source_ref = f'tp-package:{tc.id}:{digest}'
    card = DocCard(company_id=tc.company_id, kind_id=kind.id, kind_code=kind.code,
        title=f'Комплект завершения ТП · {site.title or site.project_no}',
        summary='Итоговые документы техприсоединения. Каждый получатель подтверждает ознакомление за себя.',
        subject_ref=source_ref, source='api', source_ref=source_ref, organization_id=w.organization_id,
        object_id=site.location_id, confidentiality='private', status='in_force',
        attrs={'siteId':str(site.id),'techConnectionId':str(tc.id),'archive':archive,
               'supplyContractId': str(w.supply_contract_id) if w.supply_contract_id else None},
        current_revision=1, has_files=True)
    db.add(card); await db.flush()
    db.add(DocRelation(company_id=tc.company_id,doc_id=card.id,kind="related",target_ref=f"site:{site.id}"))
    from app.services import file_store
    def write_archive(stream):
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json', json.dumps(card.attrs, ensure_ascii=False, indent=2))
            for i, f in enumerate(sources, 1):
                z.write(f.storage_path, f"{i:03d}_{Path(f.file_name.replace(chr(92), '/')).name}")
    stored = file_store.put_generated(db, tc.company_id, write_archive,
        file_name='Комплект ТП.zip', mime='application/zip', purpose='attachment')
    file_id = stored.id
    db.add(DocVersion(company_id=tc.company_id,doc_id=card.id,file_id=file_id,
        file_name='Комплект ТП.zip',mime='application/zip',size_bytes=stored.size,sha256=stored.fingerprint))
    await db.flush()
    snapshot, sha = await _document_snapshot(db,card)
    for uid, person in people.items():
        db.add(DocAcquaint(company_id=tc.company_id,doc_id=card.id,user_id=uid,
             document_snapshot=snapshot,snapshot_sha256=sha,reason='manual',required=True))
        await notify_person(db,tc.company_id,person,
            f'Ознакомьтесь с итоговым комплектом ТП: [Открыть документ](/docs/work?doc={card.id})',
            room_kind=NOTICES_ROOM_KIND,event_category='tech_connection')
    tc.workflow=dict(tc.workflow or {},_handover={'docId':str(card.id),'snapshot':sha,
                     'createdAt':datetime.now(timezone.utc).isoformat()})
    await db.flush()


def summary_facts(tc, w, state, handover):
    steps=tc.steps or {}
    has=lambda name:bool(steps.get(name,{}).get('date'))
    open_remarks=lambda branch:any(not x.resolved and x.branch==branch for x in w.remarks)
    return {
        'tp_files_ready':not state['missing'], 'tp_ready':state['ready'],
        'tp_applied':bool(tc.application_date),'tp_contract':bool(tc.contract_date),
        'tp_works':has('works_done') and has('notified'), 'tp_checked':has('checked') and not open_remarks('inspection'),
        'tp_final':w.archived and not state['finalMissing'],
        'tp_read':handover.get('done',False), 'tp_remarks':open_remarks('application'),
        'tp_supply_applied':has('supply_applied') and state.get('supplyReady',False),
        'tp_supply_done':state.get('supplyComplete',False),
    }


async def reconcile(db, tc):
    from app.services import ezs_tp_workflow as tp, projects_process
    from app.services.space_projection import ProjectionError
    w=tp.data_of(tc)
    # Проверяется заново: права могли отозвать после назначения.
    try:
        await tp.validate_refs(db,tc,w)
        await create_handover(db,tc)
        if not w.process_enabled: return
        state=await tp.read(db,tc); handover=state['handover']
        context=summary_facts(tc,w,state,handover)
        site=await db.get(EzsSite,tc.site_id)
        default=w.responsibilities.get('default',tp.Responsibility())
        roles={'tp_collect':default.provider,'tp_review':default.executor,
               'tp_submit':(w.responsibilities.get('applied') or default).executor or default.executor,
               'tp_grid':default.executor,
               'tp_works':(w.responsibilities.get('works_done') or default).executor or default.executor,
               'tp_inspect':(w.responsibilities.get('checked') or default).executor or default.executor,
               'tp_control':default.controller,'tp_supply':(w.responsibilities.get('supply_applied') or default).executor or default.executor}
        participants=[]
        for role,uid in roles.items():
            person=await db.get(User,uid) if uid else None
            if not person: raise HTTPException(400,'Не назначены участники процесса')
            participants.append({'roleCode':role,'email':person.email,'ecoUserId':str(uid)})
        processes={}
        definitions=[]
        if tc.method in ('direct','indirect'):definitions.append('tp_connection')
        if w.supply_mode!='landlord':definitions.append('tp_supply')
        for definition in definitions:
            result=await projects_process.sync_subject_process(db,tc.company_id,definition,'tech_connection',tc.id,
                       title=f'ТП · {site.title or site.project_no}',context=context,participants=participants)
            if result.get('participantsUnknown'):raise ProjectionError('Назначенные участники ещё не синхронизированы с Поддержкой')
            processes[definition]={'id':result['processId'],'stage':result.get('currentStep'),
                                  'state':result.get('state'),'performer':result.get('performer'),'participants':result.get('participants'),
                                  'startedAt':result.get('startedAt'),'stepEnteredAt':result.get('stepEnteredAt'),
                                  'steps':result.get('steps') or [],'history':result.get('history') or []}
        previous=(tc.workflow or {}).get('_process',{})
        tc.workflow=dict(tc.workflow or {},_process={'items':processes,'at':datetime.now(timezone.utc).isoformat(),'error':None})
        # Адресное сообщение при передаче, вне внешних писем Поддержки.
        from app.services.notify import notify_person, NOTICES_ROOM_KIND
        for key,item in processes.items():
            code=(item.get('stage') or {}).get('code')
            old=(((previous.get('items') or {}).get(key) or {}).get('stage') or {}).get('code')
            assignee = item.get('performer') or {}
            previous_assignee = ((previous.get('items') or {}).get(key) or {}).get('performer') or {}
            if code and assignee.get('email') and (code != old or assignee.get('id') != previous_assignee.get('id')):
                person = (await db.execute(select(User).where(User.email == assignee['email'], User.id.in_(set(roles.values()))))).scalar_one_or_none()
                if person:
                    await notify_person(db,tc.company_id,person,
                        f'Вам передана работа по ТП: {item["stage"]["name"]}. [Открыть проект](/projects?mode=projects&sub=pr_project&project={site.id}&ptab=tp)',
                        room_kind=NOTICES_ROOM_KIND,event_category='tech_connection')
    except (ProjectionError, HTTPException) as exc:
        state=dict((tc.workflow or {}).get('_process',{}))
        state.update(error=getattr(exc,'detail',None) or str(exc),attemptedAt=datetime.now(timezone.utc).isoformat())
        tc.workflow=dict(tc.workflow or {},_process=state)


async def assert_step_actor(db, tc, user, key):
    from app.models import UserCompany
    from app.services import ezs_tp_workflow as tp
    w=tp.data_of(tc)
    if not w.process_enabled or user is None or user.is_superadmin: return
    member=await db.get(UserCompany,(user.id,tc.company_id))
    if member and member.role=='admin':return
    default=w.responsibilities.get('default',tp.Responsibility())
    assignment=w.responsibilities.get(key,default)
    allowed={assignment.executor or default.executor,assignment.controller or default.controller}
    if key=='docs_ready':allowed.add(assignment.provider or default.provider)
    if user.id not in allowed:raise HTTPException(403,'Факт шага подтверждает назначенный исполнитель или контролирующий')
