"""Сводка «Секретаря»: окно доставки вместо потока.

До этого регламент писал по поводу на повод и сразу: виза, ознакомление, срок
задачи, эскалация — каждое своим письмом, в любое время суток. Это и есть поток,
и он лечится не текстом, а числом сообщений: на 1,27 млн напоминаний измерено,
что каждый лишний алерт в одной единице внимания снижает принятие на 30%, а
отклонивший ПЕРВОЕ напоминание серии отклоняет следующие в 88% случаев.
Гипотезу привыкания там проверяли отдельно и не подтвердили — дело в перегрузке.

Отсюда три правила, и все три живут здесь.

1. **Два окна в день** — начало рабочего дня и середина, в поясе человека.
   Регламентное в тишину не прорывается: «за сутки до срока» не бывает срочнее
   сна. Немедленно уходит только то, что человек сам поставил на это время
   (`PersonalReminder`), — и оно идёт мимо сводки.
2. **Одно сообщение на окно.** Новые поводы дописываются в него правкой. Новое
   сообщение на каждый повод превращает личную комнату в свалку, и напоминание
   тонет в ней ровно так же, как тонет напоминание в ленте Slack.
3. **Сдвиг, а не потеря.** Повод, набранный в тишину, не помечается сказанным и
   собирается заново, когда окно откроется. Повод, у которого к этому времени
   истёк смысл (предупреждение о сроке, который уже прошёл), молча выбрасывается:
   доставить его вовремя было нельзя, а не вовремя он не нужен.

Что сюда НЕ попадает и не попадёт: счётчик откладываний. Ни в чью сводку, кроме
собственной. Увидев его, руководитель получит повод спросить, люди перестанут
откладывать и начнут закрывать формально — и мы потеряем самый честный сигнал
системы.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PersonalDigest, User
from app.services import space_time

logger = logging.getLogger("clearledger.digest")

# Разделитель внутри `said`: ключ повода и его строка. Ключ отвечает «это уже
# сказано», строка — «как это выглядело», и хранить их порознь незачем: сводка
# правится целиком, и текст сказанного нужен, чтобы его не потерять.
_SEP = "\t"


@dataclass
class Line:
    """Один повод в сводке.

    `key` уникален в пределах сводки: «виза по документу X» — один повод, сколько
    бы раз регламент за окно ни прошёл. `mark` вызывается ТОЛЬКО после успешной
    доставки: пометить сказанным то, что не доехало, значит потерять повод
    навсегда. `expires_at` — момент, после которого повод бессмыслен.
    """
    key: str
    text: str
    mark: Callable[[], None] | None = None
    expires_at: datetime | None = None


@dataclass
class Bucket:
    """Что накопилось за один проход регламента, по людям.

    Живёт ровно один тик: собирают поводы разные проходы, доставляет один. Так
    сводка получается из всего сразу, а не тремя сообщениями подряд от трёх
    независимых механизмов, каждый из которых по отдельности прав.
    """
    lines: dict[tuple[uuid.UUID, uuid.UUID], list[Line]] = field(default_factory=dict)
    _tz: dict[uuid.UUID, str] = field(default_factory=dict)

    async def tz(self, db: AsyncSession, company_id: uuid.UUID) -> str:
        """Пояс организации — им датируются СРОКИ.

        Срок «до 20-го» — обязательство перед компанией, и день у него один на
        всех: считай его по получателю, и Владивосток просрочен за семь часов до
        Москвы, работая по тому же договору. Кэш живёт один тик, компаний в
        стеке единицы — запрос на строку тут был бы платой ни за что.
        """
        from app.models import Company

        if company_id not in self._tz:
            self._tz[company_id] = (await db.scalar(
                select(Company.tz).where(Company.id == company_id))
            ) or space_time.DEFAULT_TZ
        return self._tz[company_id]

    def add(self, company_id: uuid.UUID, user_id: uuid.UUID, key: str, text: str,
            mark: Callable[[], None] | None = None,
            expires_at: datetime | None = None) -> None:
        self.lines.setdefault((company_id, user_id), []).append(
            Line(key=key, text=text, mark=mark, expires_at=expires_at))

    def __bool__(self) -> bool:
        return bool(self.lines)


def _said_pairs(row: PersonalDigest | None) -> list[tuple[str, str]]:
    if row is None or not row.said:
        return []
    out = []
    for line in row.said.split("\n"):
        key, _, text = line.partition(_SEP)
        if key and text:
            out.append((key, text))
    return out


def select_new(said: list[tuple[str, str]], lines: list[Line],
               now: datetime) -> list[Line]:
    """Что из принесённого действительно надо сказать в этом окне.

    Два отсева, и оба важнее, чем кажутся. Уже сказанное не повторяем — иначе
    правка сводки дублирует строки внутри одного сообщения. Просроченное по
    смыслу выбрасываем: предупреждение «успейте до 17:00», доставленное в 17:30,
    не просто бесполезно — оно врёт.

    Повторы внутри самой пачки тоже гасим: один повод могут принести два прохода
    (виза основному согласующему и та же виза ему же как заместителю).
    """
    сказано = {k for k, _ in said}
    новые: list[Line] = []
    for line in lines:
        if line.key in сказано:
            continue
        if line.expires_at is not None and line.expires_at <= now:
            continue
        новые.append(line)
        сказано.add(line.key)
    return новые


def compose(slot: datetime, tz: str | None, pairs: list[tuple[str, str]]) -> str:
    """Текст сводки. Заголовок называет окно, чтобы человек видел, что это одно
    сообщение за утро, а не первое из десяти."""
    время = slot.astimezone(space_time.zone(tz)).strftime("%H:%M")
    голова = f"Сводка на {время}"
    return "\n".join([голова] + [f"• {text}" for _, text in pairs])


async def deliver(db: AsyncSession, now: datetime, bucket: Bucket) -> int:
    """Разнести накопленное по сводкам окна. Возвращает число доставленных поводов.

    Порядок важен: сперва окно, потом сообщение, и только потом отметки
    «сказано». Обратный порядок оставил бы повод помеченным при сорванной
    доставке — то есть потерянным без следа.
    """
    from app.services import notify

    if not bucket:
        return 0
    people = {uid for _, uid in bucket.lines}
    users = {u.id: u for u in (await db.execute(
        select(User).where(User.id.in_(people)))).scalars()}

    доставлено = 0
    for (company_id, user_id), lines in bucket.lines.items():
        user = users.get(user_id)
        if user is None:
            continue
        slot = space_time.slot_for(now, user.tz, user.work_start, user.work_end)
        if slot is None:
            # Тишина, выходной или день ещё не дошёл до первого окна. Ничего не
            # помечаем: поводы соберутся заново, когда окно откроется.
            continue

        row = (await db.execute(select(PersonalDigest).where(
            PersonalDigest.company_id == company_id,
            PersonalDigest.user_id == user_id,
            PersonalDigest.slot_at == slot))).scalar_one_or_none()
        pairs = _said_pairs(row)
        # Повод, у которого истёк смысл, не помечается сказанным: он не сказан,
        # он снят — и следующий проход не найдёт его заново, потому что условие
        # его появления уже не выполняется.
        новые = select_new(pairs, lines, now)
        if not новые:
            continue

        pairs = pairs + [(l.key, l.text) for l in новые]
        text = compose(slot, user.tz, pairs)
        try:
            message_id = await notify.notify_person(
                db, company_id, user, text,
                edit_message_id=row.message_id if row is not None else None,
                ttl=space_time.push_ttl(now, user.tz, user.work_end),
                # Регламентная сводка не будит экран: у неё нет минуты, ради
                # которой стоит вибрировать в кармане.
                urgency="low")
        except Exception:  # noqa: BLE001 — сорванная доставка не валит остальных
            logger.exception("Сводка для %s не доставлена", user_id)
            continue

        if row is None:
            row = PersonalDigest(company_id=company_id, user_id=user_id, slot_at=slot)
            db.add(row)
        row.message_id = message_id
        row.said = "\n".join(f"{k}{_SEP}{t}" for k, t in pairs)
        row.updated_at = datetime.now(timezone.utc)
        for line in новые:
            if line.mark is not None:
                line.mark()
        доставлено += len(новые)
    return доставлено
