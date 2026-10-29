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
        parties = [Counterparty(id=uuid.uuid4(), company_id=cid, name='Вымышленный контрагент '+str(i)) for i in range(2)]
        db.add_all(parties)
        await db.flush()
        contracts = [Contract(id=uuid.uuid4(), company_id=cid, number='SYN-'+str(i),
            date='2026-10-29', type='service', counterparty_id=parties[i].id,
            scope_type='locations') for i in range(2)]
        db.add_all(contracts)
        await db.flush()
        db.add_all([ContractLocation(company_id=cid, contract_id=c.id, location_id=points[i].id)
            for i,c in enumerate(contracts)])
        equipment = [EzsEquipmentUnit(id=uuid.uuid4(), company_id=cid, kind='station', vendor='Synthetic',
            model='Fixture', current_location_id=p.id, state='in_operation') for p in points]
        db.add_all(equipment)
        at = datetime(2026,10,29,10)
        for i,p in enumerate([*points, foreign]):
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
        kind = DocKind(id=uuid.uuid4(), company_id=cid, code='pilot', name='Вымышленный документ', fields=[], route=[])
        db.add(kind)
        await db.flush()
        docs = [DocCard(id=uuid.uuid4(), company_id=cid, kind_id=kind.id,
            title='Вымышленный закрытый документ '+str(i), confidentiality='private',
            author_id=users[i].id, object_id=points[0].id, current_revision=1) for i in range(2)]
        db.add_all(docs)
        await db.flush()
        versions=[]
        for i,doc in enumerate(docs):
            data = b'SYNTHETIC PARTNER PILOT DOCUMENT '+str(i).encode()+b'\n'
            fid=uuid.uuid4()
            path=upload/(str(fid)+'.txt')
            path.write_bytes(data); path.chmod(0o600)
            digest=hashlib.sha256(data).hexdigest()
            db.add(SourceFile(id=fid, company_id=cid, file_name='synthetic.txt', mime_type='text/plain',
                size=len(data), storage_path=str(path), fingerprint=digest))
            version=DocVersion(id=uuid.uuid4(), company_id=cid, doc_id=doc.id, revision=1, role='body',
                file_id=fid, file_name='synthetic.txt', mime='text/plain', size_bytes=len(data), sha256=digest)
            db.add(version); versions.append(version)
        await db.flush()
        for c in companies:
            await recompute_visits(db,c.id)
        await db.commit()
        # Учётки Ядра остаются у владельца сервера и не попадают в manifest клиента.
        return {'companyId':str(cid), 'foreignCompanyId':str(foreign_cid),
            'owner':{'email':owner.email,'password':password,'userId':str(owner.id)},
            'employee':{'email':employee.email,'password':password,'userId':str(employee.id)},
            'objects':[p.id for p in points], 'foreignObject':foreign.id,
            'counterparties':[str(p.id) for p in parties], 'contracts':[str(c.id) for c in contracts],
            'equipment':[str(e.id) for e in equipment], 'documents':[str(d.id) for d in docs],
            'documentVersions':[str(v.id) for v in versions],
            'expectedDocumentHashes':{str(d.id):v.sha256 for d,v in zip(docs,versions)},
            'objectObservationDays':{p.id:day for p,day in zip(points,['2026-10-29','2026-10-28','2026-10-30'])},
            'asOf':'2026-10-29'}
