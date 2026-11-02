"""Persisted organizer revision of one CalendarEvent, never a delivery counter.

Existing writers hold calendar_series.lock_event (series head before instance)
through their transaction. New rows start at zero; retries, reads, recipient
addition and attendee replies merely reuse that row's committed version.
"""
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.models import CalendarEvent

MAX_SEQUENCE = 2_147_483_647
LEGACY_BOUND = 2_000_000_000
ORGANIZER_FIELDS = (
    "title", "description", "starts_at", "ends_at", "all_day", "tz",
    "location", "conference_url", "status", "cancel_reason", "recurrence", "recurrence_until",
)


def version(event: CalendarEvent) -> int:
    value = event.protocol_sequence
    if type(value) is not int or not 0 <= value <= MAX_SEQUENCE:
        raise RuntimeError("Invalid persisted calendar protocol revision")
    return value


def state(event: CalendarEvent) -> tuple:
    return tuple(deepcopy(getattr(event, name)) for name in ORGANIZER_FIELDS)


def advance_if_changed(event: CalendarEvent, before: tuple) -> bool:
    """Called once after organizer mutation, before commit, under its row lock."""
    if state(event) == before:
        return False
    current = version(event)
    if current == MAX_SEQUENCE:
        raise HTTPException(409, "Исчерпан номер версии календарного приглашения")
    event.protocol_sequence = current + 1
    return True


async def share_series_url(db, event: CalendarEvent) -> None:
    """Fill existing siblings under the caller's common series-head lock.

The current row belongs to the caller's single state snapshot. Initial creation
keeps zero; newly materialized instances already inherit the URL, not revision.
Every changed sibling uses this same revision owner, with no independent counter.
"""
    root = event.series_id or event.id
    siblings = (await db.scalars(select(CalendarEvent).where(
        or_(CalendarEvent.id == root, CalendarEvent.series_id == root),
        CalendarEvent.id != event.id,
        CalendarEvent.conference_url.is_(None), CalendarEvent.status != "cancelled")
        .order_by(CalendarEvent.id).with_for_update()
        .execution_options(populate_existing=True))).all()
    for sibling in siblings:
        before = state(sibling)
        sibling.conference_url = event.conference_url
        advance_if_changed(sibling, before)
