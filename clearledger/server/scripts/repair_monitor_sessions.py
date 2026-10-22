"""Восстановление ключей и незавершённых сессий после исправления импорта АСУиМ.

По умолчанию только план. Применение требует хеша плана и SHA256 исходной книги.
JSON-план содержит телефоны: хранить только в закрытом каталоге, не в Git.
Перед применением обязательна проверенная резервная копия БД.

  python scripts/repair_monitor_sessions.py rushydro --workbook /app/uploads/....xlsx \
      --source-sha256 ... --plan-out /private/plan.json
  # После проверки плана и репетиции на восстановленной БД:
  ... --apply --expect-plan <plan_sha256>

Никакие неизвестные исторические исходы здесь не восстанавливаются по эвристике.
"""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text, update
from app.database import async_session_factory
from app.models import ChargeSession, Company, CorporateClient, EzsCustomer
from app.services.asuim_normalize import _read_sheet, detect_sheets, map_sessions
from app.services.charge_sessions_normalize import finalize_pending_session, is_meter_error, missing_org_enrichment
from app.services.stations_normalize import build_source_station_index

FIELDS = ('user_id', 'source_customer_id', 'source_station_id', 'location_id',
          'finished_at', 'duration_min', 'result', 'energy_kwh', 'amount', 'tariff',
          'client_name', 'client_tariff', 'client_amount')


def encode(value):
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def same(a, b):
    if a is None or b is None:
        return a is b
    # SQL NUMERIC и десятичное значение из XLSX сравниваем без ошибки float.
    from decimal import Decimal
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        return Decimal(str(a)) == Decimal(str(b))
    return a == b


async def make_plan(db, company_id, source_rows):
    customers = {c.customer_ext_id: c.phone for c in (await db.execute(
        select(EzsCustomer).where(EzsCustomer.company_id == company_id)
    )).scalars() if c.phone and re.fullmatch(r'\+\d{10,15}', c.phone)}
    clients = list((await db.execute(select(CorporateClient).where(
        CorporateClient.company_id == company_id))).scalars())
    orgs = {c.phone: {'phone': c.phone, 'name': c.name, 'mode': c.mode, 'rate': c.rate,
                     'discount': c.discount_pct} for c in clients if c.phone and c.name}
    matrix = {c.name: c.matrix for c in clients if c.matrix}
    stations = await build_source_station_index(db, company_id)
    source = {}
    for row in source_rows:
        sid = row['session_ext_id']
        if sid in source:
            raise ValueError('В книге повторяется ID сессии: план не построен')
        if (row.get('suspicious') or is_meter_error(row.get('energy_kwh'), row.get('duration_min'))):
            continue
        source[sid] = row
    changes = []
    counts = Counter()
    for session in (await db.execute(select(ChargeSession).where(
        ChargeSession.company_id == company_id).order_by(ChargeSession.session_ext_id)
    )).scalars():
        old = {f: getattr(session, f) for f in FIELDS}
        candidate = SimpleNamespace(**old, started_at=session.started_at, user_type=session.user_type,
                                    region=session.region, connector_type=session.connector_type)
        # Только внешний ID, однозначно принадлежащий клиенту этой компании.
        if session.user_id in customers and not str(session.user_id).startswith('+'):
            candidate.user_id = customers[session.user_id]
            candidate.source_customer_id = session.source_customer_id or session.user_id
            counts['identity_from_registry'] += 1
        row = source.get(session.session_ext_id)
        if row is not None:
            if row.get('started_at') != session.started_at:
                raise ValueError('Начало сессии отличается от источника: требуется разбор')
            if (row.get('user_id') or '').startswith('+'):
                candidate.user_id = row['user_id']
            for f in ('source_station_id', 'source_customer_id'):
                if row.get(f):
                    if old[f] and old[f] != row[f]:
                        raise ValueError('Постоянный ключ отличается: требуется разбор')
                    setattr(candidate, f, row[f])
            lid = stations.get(row.get('source_station_id'))
            # Чужие/неоднозначные ID и уже установленные связи не переписываем.
            if not candidate.location_id and lid:
                candidate.location_id = lid
                counts['locations_restored'] += 1
            if finalize_pending_session(candidate, row):
                counts['sessions_finalized'] += 1
        if candidate.user_id in orgs:
            values = missing_org_enrichment(candidate, orgs[candidate.user_id], matrix)
            if values:
                for field, value in values.items():
                    setattr(candidate, field, value)
                counts['corporate_enriched'] += 1
        if candidate.duration_min < 0:
            candidate.duration_min = 0
            counts['negative_durations_clamped'] += 1
        new = {f: getattr(candidate, f) for f in FIELDS if not same(old[f], getattr(candidate, f))}
        if new:
            changes.append({'id': str(session.id), 'session_ext_id': session.session_ext_id,
                            'old': {f: old[f] for f in new}, 'new': new})
            counts.update('field_' + f for f in new)
    counts['sessions_changed'] = len(changes)
    return changes, dict(counts)


async def run(args):
    import openpyxl
    path = Path(args.workbook)
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if source_sha != args.source_sha256:
        raise ValueError('SHA256 книги не совпал')
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = detect_sheets(wb).get('sessions')
        if not sheet:
            raise ValueError('В книге нет листа сессий АСУиМ')
        source = map_sessions(_read_sheet(wb[sheet]))
        # Сырые строки с ФИО не нужны ни для плана, ни для исправления.
        for row in source:
            row.pop('raw', None)
    finally:
        wb.close()
    async with async_session_factory() as db:
        if not args.apply:
            await db.execute(text('SET TRANSACTION READ ONLY'))
        await db.execute(text("SET LOCAL lock_timeout='15s'"))
        await db.execute(text("SET LOCAL statement_timeout='180s'"))
        company = (await db.execute(select(Company).where(Company.slug == args.company))).scalar_one()
        if args.apply:
            if not args.expect_plan:
                raise ValueError('--apply требует --expect-plan')
            # Блокирует конкурирующие записи импорта до атомарного коммита.
            await db.execute(text('LOCK TABLE charge_sessions IN SHARE ROW EXCLUSIVE MODE'))
        changes, summary = await make_plan(db, company.id, source)
        plan = {'version': 1, 'company': str(company.id), 'source_sha256': source_sha,
                'summary': summary, 'changes': changes}
        raw = json.dumps(plan, default=encode, ensure_ascii=False, sort_keys=True).encode()
        fingerprint = hashlib.sha256(raw).hexdigest()
        plan['plan_sha256'] = fingerprint
        # Не перезаписываем результаты предыдущей проверки/применения.
        with os.fdopen(os.open(args.plan_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
            json.dump(plan, out, default=encode, ensure_ascii=False)
        if args.apply:
            if fingerprint != args.expect_plan:
                raise ValueError('План изменился после проверки: транзакция отменена')
            if changes:
                await db.execute(update(ChargeSession), [
                    {'id': uuid.UUID(change['id']), **change['new']} for change in changes
                ])
            await db.flush()
            if changes:
                from app.services.charge_visits import recompute_visits
                from app.services.charge_mart import rebuild_mart
                from app.services.analytics_cache import bump_version
                await recompute_visits(db, company.id)
                await rebuild_mart(db, company.id)
                await bump_version(db, company.id)
            else:
                await db.rollback()
        else:
            await db.rollback()
    print(json.dumps({'applied': args.apply, 'plan_sha256': fingerprint, 'summary': summary}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('company')
    parser.add_argument('--workbook', required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--plan-out', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-plan')
    asyncio.run(run(parser.parse_args()))
