"""Только вымышленные записи Ядра; без production seed и OAuth grant через ORM."""
from datetime import datetime, timedelta
import hashlib
import secrets
import uuid


async def seed(factory, upload):
    from app.auth import hash_password
    from app.models import (Company, User, UserCompany, ServiceLocation, Counterparty,
        Contract, ContractLocation, EzsEquipmentUnit, ChargeSession, DocKind, DocCard,
        DocVersion, SourceFile)
    from app.services.charge_visits import recompute_visits
    upload.mkdir(mode=0o700, parents=True, exist_ok=True)
    async with factory() as db:
        companies = [Company(id=uuid.uuid4(), name='Вымышленная энергия ' + str(i),
            slug='pilot-synthetic-' + str(i), profile_id='energy') for i in range(2)]
        db.add_all(companies)
        await db.flush()
        cid, foreign_cid = [c.id for c in companies]
        password = secrets.token_urlsafe(24)
        users = [User(id=uuid.uuid4(), company_id=cid, email=name+'@example.invalid',
            name='Вымышленный '+name, password_hash=hash_password(password),
            role='user', is_superadmin=False, mail_only=False)
            for name in ('pilot-owner', 'pilot-employee')]
        db.add_all(users)
        await db.flush()
        owner, employee = users
        points = [ServiceLocation(id='pilot-object-'+str(i), company_id=cid, code='SYN-'+str(i),
            name='Вымышленная ЭЗС '+str(i), type='ev_charging', status='active') for i in range(3)]
        foreign = ServiceLocation(id='pilot-foreign-object', company_id=foreign_cid, code='SYN-FOREIGN',
            name='Чужая вымышленная ЭЗС', type='ev_charging', status='active')
        db.add_all([*points, foreign])
        db.add_all([UserCompany(user_id=owner.id, company_id=cid, role='admin', modules=None),
            UserCompany(user_id=employee.id, company_id=cid, role='user', modules=['equipment'],
                object_scope=[points[0].id])])
        parties = [Counterparty(id=uuid.uuid4(), company_id=(foreign_cid if i==3 else cid),
            name='Вымышленный контрагент '+str(i)) for i in range(4)]
        db.add_all(parties)
        await db.flush()
        contracts = [Contract(id=uuid.uuid4(), company_id=p.company_id, number='SYN-'+str(i),
            date='2026-10-29', type='service', counterparty_id=p.id, scope_type='locations')
            for i,p in enumerate(parties)]
        db.add_all(contracts)
        await db.flush()
        all_points=[*points,foreign]
        db.add_all([ContractLocation(company_id=c.company_id, contract_id=c.id, location_id=all_points[i].id)
            for i,c in enumerate(contracts)])
        equipment = [EzsEquipmentUnit(id=uuid.uuid4(), company_id=p.company_id, kind='station', vendor='Synthetic',
            model='Fixture', current_location_id=p.id, state='in_operation') for p in all_points]
        db.add_all(equipment)
        at = datetime(2026,10,29,10)
        for i,p in enumerate(all_points):
            for n,energy in enumerate((0,12,7)):
                # Разные дни выявляют ошибочную общую границу наблюдений:
                # второй разрешённый объект старше, скрытый и чужой новее.
                day_offset=(0,-1,1,2)[i]
                start = at + timedelta(days=day_offset,minutes=n*8)
                db.add(ChargeSession(company_id=p.company_id, location_id=p.id, station_code=p.code,
                    source_station_id=p.id, user_id='synthetic-visitor-'+str(i),
                    session_ext_id=f'synthetic-{i}-{n}', started_at=start,
                    finished_at=start+timedelta(minutes=5), energy_kwh=energy,
                    result='Complete' if energy else 'CompleteError', duration_min=5, amount=0, tariff=0))
        kinds=[DocKind(id=uuid.uuid4(), company_id=c.id, code='pilot', name='Вымышленный документ', fields=[], route=[])
            for c in companies]
        db.add_all(kinds)
        await db.flush()
        docs = [DocCard(id=uuid.uuid4(), company_id=cid, kind_id=kinds[0].id,
            title='Вымышленный закрытый документ '+str(i), confidentiality='private',
            author_id=users[i].id, object_id=points[0].id, current_revision=1) for i in range(2)]
        docs.extend([DocCard(id=uuid.uuid4(),company_id=cid,kind_id=kinds[0].id,
            title='Вымышленный общий документ',confidentiality='company',author_id=owner.id,
            object_id=points[1].id,current_revision=1),
            DocCard(id=uuid.uuid4(),company_id=foreign_cid,kind_id=kinds[1].id,
            title='Чужой вымышленный документ',confidentiality='company',
            object_id=foreign.id,current_revision=1)])
        db.add_all(docs)
        await db.flush()
        versions=[]
        for i,doc in enumerate(docs):
            data = b'SYNTHETIC PARTNER PILOT DOCUMENT '+str(i).encode()+b'\n'
            fid=uuid.uuid4()
            path=upload/(str(fid)+'.txt')
            path.write_bytes(data); path.chmod(0o600)
            digest=hashlib.sha256(data).hexdigest()
            db.add(SourceFile(id=fid, company_id=doc.company_id, file_name='synthetic.txt', mime_type='text/plain',
                size=len(data), storage_path=str(path), fingerprint=digest))
            version=DocVersion(id=uuid.uuid4(), company_id=doc.company_id, doc_id=doc.id, revision=1, role='body',
                file_id=fid, file_name='synthetic.txt', mime='text/plain', size_bytes=len(data), sha256=digest)
            db.add(version); versions.append(version)
        await db.flush()
        for c in companies:
            await recompute_visits(db,c.id)
        await db.commit()
        # Учётки Ядра остаются у владельца сервера и не попадают в manifest клиента.
        def vector(rows):
            return {'allowed':[str(rows[i].id) for i in (0,1)],
                'foreign':[str(rows[3].id)],'ungranted':[str(rows[2].id)]}
        vectors={'objects':vector(all_points),'equipment':vector(equipment),
            'counterparties':vector(parties),'contracts':vector(contracts),
            'documents':{'allowed':[str(docs[i].id) for i in (0,2)],
                'foreign':[str(docs[3].id)],'ungranted':[str(docs[1].id)]}}
        return {'companyId':str(cid), 'foreignCompanyId':str(foreign_cid),
            'owner':{'email':owner.email,'password':password,'userId':str(owner.id)},
            'employee':{'email':employee.email,'password':password,'userId':str(employee.id)},
            'objects':[p.id for p in points], 'foreignObject':foreign.id,
            'counterparties':[str(p.id) for p in parties[:3]], 'contracts':[str(c.id) for c in contracts[:3]],
            'equipment':[str(e.id) for e in equipment[:3]], 'documents':[str(d.id) for d in docs[:3]],
            'documentVersions':[str(v.id) for v in versions[:3]],'vectors':vectors,
            'allowedContent':{'docId':str(docs[0].id),'versionId':str(versions[0].id),'sha256':versions[0].sha256},
            'deniedContent':[{'docId':str(docs[i].id),'versionId':str(versions[i].id)} for i in (1,3)],
            'expectedDocumentHashes':{str(d.id):v.sha256 for d,v in zip(docs,versions)},
            'objectObservationDays':{p.id:day for p,day in zip(points,['2026-10-29','2026-10-28','2026-10-30'])},
            'asOf':'2026-10-29'}
