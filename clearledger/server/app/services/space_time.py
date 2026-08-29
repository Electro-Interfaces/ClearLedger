"""Время пространства: чей сейчас день, когда человека можно трогать.

Пространство растянуто от Владивостока до Москвы, и до этого сервиса сервер
считал «сегодня» по UTC. В Москве это врало с полуночи до трёх, во Владивостоке —
полсуток. Один расчёт на всё пространство, чтобы «сегодня» в очереди, в
раскладке и в сводке означало один и тот же день.

Здесь три разных вопроса, и путать их нельзя.

1. **Какой сегодня день у ОРГАНИЗАЦИИ.** Срок «до 20-го» — обязательство перед
   компанией, и день у него один на всех: иначе Владивосток просрочен за семь
   часов до Москвы, работая по тому же договору. Решается поясом компании.
2. **Какой сегодня день у ЧЕЛОВЕКА.** «Мой день», «вчера осталось», «отложить до
   завтра» — про его утро, а не про офис головной компании. Витрина шлёт свою
   местную дату параметром; когда не прислала, отвечает пояс человека.
3. **Можно ли писать человеку СЕЙЧАС.** Регламентное напоминание не бывает
   срочнее сна: в тишину оно не пропускается и не теряется, а сдвигается на
   начало ближайшего рабочего окна.

Функции чистые и проверяются без базы (`server/tests/test_space_time.py`):
арифметика окон и часовых поясов — то место, где ошибка не падает, а тихо
доставляет вчерашнее.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Пояс, когда человек и компания молчат. Пространство живёт в России, головная
# компания пилота — в Москве; выдумывать UTC как «нейтральный» вариант нельзя,
# в нём не работает никто.
DEFAULT_TZ = "Europe/Moscow"
DEFAULT_WORK_START = time(9, 0)
DEFAULT_WORK_END = time(18, 0)


def zone(name: str | None) -> ZoneInfo:
    """Пояс по имени IANA. Неизвестное имя не роняет регламент.

    Имя приходит из настроек человека и из справочника компании, то есть его
    когда-нибудь введут руками или перенесут из чужой системы. Планировщик,
    падающий на строке «Moscow» вместо «Europe/Moscow», перестаёт доставлять
    ВСЁ и всем — цена опечатки несоразмерна.
    """
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def local_date(now: datetime, tz: str | None) -> date:
    """Какое сегодня число в этом поясе."""
    return now.astimezone(zone(tz)).date()


def _at(day: date, moment: time, tz: ZoneInfo) -> datetime:
    """Местное время дня как момент на оси. Через `zoneinfo`, а не сложением
    смещения: смещение меняется при переводе часов, и «каждый день в 9:00»
    иначе уезжает на час."""
    return datetime.combine(day, moment, tzinfo=tz)


def in_window(now: datetime, tz: str | None,
              work_start: time | None = None, work_end: time | None = None,
              workdays_only: bool = True) -> bool:
    """Рабочее ли сейчас время у человека.

    Выходные считаются тишиной по умолчанию: напоминание о визе, пришедшее в
    субботу утром, к понедельнику уже прочитано и забыто — и именно поэтому не
    сработает.
    """
    z = zone(tz)
    здесь = now.astimezone(z)
    if workdays_only and здесь.weekday() >= 5:
        return False
    начало = work_start or DEFAULT_WORK_START
    конец = work_end or DEFAULT_WORK_END
    if начало >= конец:
        # Окно, заданное задом наперёд, — это не ночная смена, а опечатка в
        # настройке. Ночную смену пришлось бы считать через полночь, и молча
        # угадывать, что имел в виду человек, хуже, чем вернуться к умолчанию.
        начало, конец = DEFAULT_WORK_START, DEFAULT_WORK_END
    return начало <= здесь.timetz().replace(tzinfo=None) < конец


def next_window(now: datetime, tz: str | None,
                work_start: time | None = None, work_end: time | None = None,
                workdays_only: bool = True) -> datetime:
    """Когда откроется ближайшее рабочее окно. Если оно открыто — сейчас.

    Это и есть «сдвинуть, а не пропустить»: у доставки всегда есть будущее
    время, и напоминание не теряется от того, что сработало ночью.
    """
    z = zone(tz)
    начало = work_start or DEFAULT_WORK_START
    конец = work_end or DEFAULT_WORK_END
    if начало >= конец:
        начало, конец = DEFAULT_WORK_START, DEFAULT_WORK_END
    if in_window(now, tz, начало, конец, workdays_only):
        return now
    здесь = now.astimezone(z)
    день = здесь.date()
    # Сегодняшнее окно ещё не открылось — ждём его; иначе ищем следующий день.
    if здесь.timetz().replace(tzinfo=None) >= конец:
        день = день + timedelta(days=1)
    for _ in range(8):
        if not (workdays_only and день.weekday() >= 5):
            момент = _at(день, начало, z)
            if момент > now:
                return момент
        день = день + timedelta(days=1)
    return now  # недостижимо: неделя всегда содержит рабочий день


def digest_slots(day: date, tz: str | None,
                 work_start: time | None = None,
                 work_end: time | None = None) -> list[datetime]:
    """Два окна доставки сводки за этот день: начало работы и середина.

    Два, а не поток: на 1,27 млн напоминаний измерено, что каждый лишний алерт
    в одной единице внимания снижает принятие на 30%, а отклонивший ПЕРВОЕ
    напоминание серии отклоняет следующие в 88% случаев. Дело не в привыкании,
    а в перегрузке — значит лечится не текстом, а числом сообщений.

    Время считается от рабочего окна человека, а не задаётся отдельной парой
    настроек: «после обеда» у того, кто работает с шести, наступает раньше, и
    настройка, которую никто не откроет, врала бы у половины людей.
    """
    z = zone(tz)
    начало = work_start or DEFAULT_WORK_START
    конец = work_end or DEFAULT_WORK_END
    if начало >= конец:
        начало, конец = DEFAULT_WORK_START, DEFAULT_WORK_END
    утро = _at(day, начало, z)
    вечер = _at(day, конец, z)
    середина = утро + (вечер - утро) / 2
    return [утро, середина]


def slot_for(now: datetime, tz: str | None,
             work_start: time | None = None, work_end: time | None = None,
             workdays_only: bool = True) -> datetime | None:
    """Какое окно доставки наступило и ещё не сменилось следующим.

    Возвращает момент окна — он же ключ сводки: пока окно то же, сводка та же и
    правится, а не пишется заново. Новое сообщение на каждое срабатывание
    превращает личную комнату в свалку, и напоминание в ней тонет.

    `None` — сейчас не время: тишина, выходной или день ещё не дошёл до первого
    окна.
    """
    if not in_window(now, tz, work_start, work_end, workdays_only):
        return None
    сегодня = local_date(now, tz)
    подошедшие = [s for s in digest_slots(сегодня, tz, work_start, work_end) if s <= now]
    return подошедшие[-1] if подошедшие else None


def push_ttl(now: datetime, tz: str | None,
             work_end: time | None = None) -> int:
    """Сколько секунд push имеет смысл ждать браузер: до конца рабочего окна.

    По умолчанию веб-push хранится до четырёх недель, и вернувшийся из офлайна
    получает вчерашнее как новое. Напоминание о визе, доставленное через сутки,
    — не напоминание, а шум, за который выключают уведомления целиком.
    """
    z = zone(tz)
    здесь = now.astimezone(z)
    конец = _at(здесь.date(), work_end or DEFAULT_WORK_END, z)
    if конец <= now:
        конец = конец + timedelta(days=1)
    return max(300, int((конец - now).total_seconds()))


def as_utc(value: datetime) -> datetime:
    """Момент с поясом. Наивное время в базе трактуем как UTC — так его туда и
    клали."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
