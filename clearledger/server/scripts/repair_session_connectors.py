"""Восстановить только пустые номера портов по однозначным ключам книги.

По умолчанию READ ONLY. Применение: резервная копия выбранных строк, проверка
плана на копии БД, затем --apply --expect-plan SHA --source-sha256 SHA.
Не меняет время, энергию, исход, деньги или уже заполненный номер порта.
Планы хранить вне публичного репозитория.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text, update

from app.database import async_session_factory
from app.models import ChargeSession, Company
from app.services.asuim_normalize import _read_sheet, detect_sheets, map_sessions
from app.services.asuim_session_connectors import build_session_connector_index, source_text
from app.services.mapping import normalize_default
from app.services.stations_normalize import build_source_station_index


def connector_repair_plan(existing, source_rows, station_index):
    """Нет номера/времени/связи в источнике — нет правки. Конфликт — не выбор первого."""
    source = {}
    ambiguous = set()
    for row in source_rows:
        key = row["session_ext_id"]
        signature = (row.get("source_station_id"), row.get("connector_no"),
                     row.get("started_at"), row.get("connector_type"))
        if key in source and source[key][0] != signature:
            ambiguous.add(key)
        source[key] = (signature, row)
    changes = []
    counts = Counter()
    for session in existing:
        if source_text(session.connector_no):
            counts["already_numbered"] += 1
            continue
        counts["missing_before"] += 1
        key = session.session_ext_id
        if key in ambiguous:
            counts["ambiguous_source"] += 1
            continue
        row = source.get(key, (None, {}))[1]
        number = source_text(row.get("connector_no"))
        if not number:
            counts["not_resolved_by_workbook"] += 1
            continue
        source_station = row.get("source_station_id")
        resolved_station = station_index.get(source_station)
        if (not resolved_station or session.location_id != resolved_station
                or (session.source_station_id and session.source_station_id != source_station)):
            counts["station_conflict"] += 1
            continue
        if not row.get("started_at") or session.started_at != row["started_at"]:
            counts["start_conflict"] += 1
            continue
        old_type, new_type = session.connector_type, row.get("connector_type")
        if old_type and new_type and normalize_default("connector", old_type) != normalize_default("connector", new_type):
            counts["type_conflict"] += 1
            continue
        changes.append({"id": str(session.id), "old": session.connector_no, "new": number,
                        "station_id": session.location_id, "started_at": session.started_at.isoformat()})
    changes.sort(key=lambda row: row["id"])
    counts["restore"] = len(changes)
    return changes, dict(counts)


async def run(args):
    import openpyxl
    path = Path(args.workbook)
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if args.source_sha256 and source_sha != args.source_sha256:
        raise ValueError("SHA256 книги изменился")
    if args.apply and not (args.source_sha256 and args.expect_plan):
        raise ValueError("Применение требует хеша проверенной книги и плана")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = detect_sheets(wb)
        if not {"sessions", "connectors"} <= sheets.keys():
            raise ValueError("Нужны листы сессий и коннекторов одной книги")
        index = build_session_connector_index(_read_sheet(wb[sheets["connectors"]]))
        source = map_sessions(_read_sheet(wb[sheets["sessions"]]), connector_index=index)
    finally:
        wb.close()
    async with async_session_factory() as db:
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        if not args.apply:
            await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text("SET LOCAL statement_timeout='120s'"))
        await db.execute(text("SET LOCAL lock_timeout='5s'"))
        company = (await db.execute(select(Company).where(Company.slug == args.company))).scalar_one()
        existing = (await db.execute(select(ChargeSession).where(
            ChargeSession.company_id == company.id))).scalars()
        changes, counts = connector_repair_plan(existing, source, await build_source_station_index(db, company.id))
        plan = {"company_id": str(company.id), "source_sha256": source_sha, "changes": changes}
        digest = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if args.plan_out:
            import os
            fd = os.open(args.plan_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as output:
                json.dump({**plan, "plan_sha256": digest, "counts": counts}, output, ensure_ascii=False, indent=2)
        if args.apply:
            if digest != args.expect_plan:
                raise ValueError("План изменился: применение отменено")
            from datetime import datetime
            from uuid import UUID
            for row in changes:
                result = await db.execute(update(ChargeSession).where(
                    ChargeSession.id == UUID(row["id"]), ChargeSession.company_id == company.id,
                    ChargeSession.connector_no == row["old"],
                    ChargeSession.location_id == row["station_id"],
                    ChargeSession.started_at == datetime.fromisoformat(row["started_at"]),
                ).values(connector_no=row["new"]))
                if result.rowcount != 1:
                    raise ValueError("Строка изменилась: вся транзакция отменяется")
            await db.commit()
        else:
            await db.rollback()
        print(json.dumps({"mode": "apply" if args.apply else "read-only", "source_sha256": source_sha,
                          "plan_sha256": digest, "counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("company")
    parser.add_argument("--workbook", required=True)
    parser.add_argument("--source-sha256")
    parser.add_argument("--plan-out")
    parser.add_argument("--expect-plan")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))
