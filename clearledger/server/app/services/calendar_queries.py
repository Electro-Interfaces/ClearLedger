"""Предметные селекторы календаря; company/product/date/visibility задаёт caller.

«Мои встречи» описывает участие, само по себе права на пространство не выдаёт.
Selector только строит SQL-выражение, без запросов, flush или commit.
"""
import uuid

from sqlalchemy import or_, select


def my_events_clause(user_id: uuid.UUID):
    """Мои встречи: те, что я собрал, и те, куда меня позвали.

    Общий календарь компании сюда не входит намеренно: «все встречи всех» —
    другой экран с другим вопросом, и подмешивать его значит утопить свои три
    встречи в сотне чужих.
    """
    from app.models import CalendarAttendee, CalendarEvent

    return or_(
        CalendarEvent.organizer_id == user_id,
        CalendarEvent.id.in_(select(CalendarAttendee.event_id).where(
            CalendarAttendee.user_id == user_id)),
    )
