"""Номенклатурная матрица: кто что может по каждой позиции на каждой станции.

Матрица — единый справочник компании. Позиция заводится один раз; всё, что
различается между станциями, описано правилами к ней, а не второй карточкой.
Разбор целиком — `edge/docs/nomenklaturnaya-matrica.html`.

Здесь живёт одна вещь, но главная: **разрешение права**. Функция отвечает не
только «можно или нельзя», но и **каким правилом** это решено и какие правила
оно перебило. Без второго ответа система становится непрозрачной: станция
говорит «не могу поменять цену», товаровед смотрит на список правил и гадает.
Поэтому объяснение — не отладочная роскошь, а часть контракта.

Два предмета, одна механика:

  · `price`      — кто вправе менять цену: станция или центр;
  · `assortment` — возит ли станция эту позицию.

Умолчания, когда правила нет (решение МАГа 30.08.2026):

  · применение — доступна всем: привезли товар, можно продавать, решения центра
    ждать не нужно. Правило нужно, чтобы ИСКЛЮЧИТЬ;
  · цена — сетевая: право назначается явно, с причиной. Забыть выдать право
    заметно сразу (звонок со станции), забыть отобрать — не заметно никогда.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PRICE = "price"
ASSORTMENT = "assortment"

# Что происходит, когда ни одно правило не подошло.
УМОЛЧАНИЯ = {PRICE: False, ASSORTMENT: True}

# Разделитель веток в `edge.item_group.path` («Табак / Сигареты»). Правило
# группы действует на всю ветку, но «Табак» не должен накрывать «Табакерку» —
# поэтому сравнение идёт либо по равенству, либо по префиксу вместе с
# разделителем.
РАЗДЕЛИТЕЛЬ = " / "


@dataclass
class Правило:
    id: str
    subject: str
    station_id: int | None
    group_id: int | None
    group_path: str
    item_id: int | None
    allow: bool
    hard: bool
    reason: str
    valid_from: str | None
    valid_to: str | None
    created_at: str | None

    @property
    def область(self) -> str:
        return f"АЗС {self.station_id}" if self.station_id else "вся сеть"

    @property
    def предмет_правила(self) -> str:
        if self.item_id:
            return "позиция"
        if self.group_id:
            return f"группа «{self.group_path}»"
        return "все позиции"

    def как_текст(self) -> str:
        знак = "разрешение" if self.allow else ("жёсткий запрет" if self.hard else "запрет")
        return f"{self.область} · {self.предмет_правила} · {знак}"


@dataclass
class Решение:
    """Ответ и его обоснование — вместе, потому что порознь бесполезны."""
    allow: bool
    subject: str
    station_id: int
    item_id: int
    # Правило, которое решило. None — сработало умолчание.
    сработало: Правило | None = None
    # Правила, которые подошли, но проиграли по конкретности. Порядок — от
    # ближайшего проигравшего к самому общему: так человек читает «а почему
    # не сработало вот это».
    перебиты: list[Правило] = field(default_factory=list)

    @property
    def по_умолчанию(self) -> bool:
        return self.сработало is None

    def объяснение(self) -> str:
        if self.сработало is None:
            return ("умолчание компании: "
                    + ("цена сетевая" if self.subject == PRICE
                       else "позиция доступна всем станциям"))
        return f"{self.сработало.как_текст()} — «{self.сработало.reason}»"


# Порядок конкретности. Побеждает первое правило этого порядка:
#
#   1. жёсткий запрет (бьёт всё, включая станционные разрешения);
#   2. правило про конкретную станцию — всегда сильнее общесетевого;
#   3. правило про карточку — сильнее правила про группу;
#   4. глубокая группа — сильнее вышестоящей («Табак / Стики» бьёт «Табак»).
#
# Станция стоит выше товара осознанно: настройка АЗС — осмысленное исключение,
# сделанное человеком под точку, а сетевое правило — фон. Иначе одно сетевое
# правило по карточке отменяло бы разрешение, выданное конкретной станции,
# и товаровед не понимал бы, почему выданное им право не работает.
_ЗАПРОС = """
    WITH цель AS (
        SELECT i.id AS item_id, coalesce(g.path, '') AS path
        FROM edge.item i
        LEFT JOIN edge.item_group g ON g.id = i.group_id
        WHERE i.id = :item
    )
    SELECT r.id::text AS id, r.subject, r.station_id, r.group_id,
           coalesce(rg.path, '') AS group_path, r.item_id,
           r.allow, r.hard, r.reason,
           r.valid_from, r.valid_to, r.created_at
    FROM edge.matrix_rule r
    LEFT JOIN edge.item_group rg ON rg.id = r.group_id
    CROSS JOIN цель c
    WHERE r.company_id = :company
      AND r.subject = :subject
      AND r.closed_at IS NULL
      AND (r.valid_from IS NULL OR r.valid_from <= now())
      AND (r.valid_to   IS NULL OR r.valid_to   >= now())
      AND (r.station_id IS NULL OR r.station_id = :station)
      AND (r.item_id    IS NULL OR r.item_id    = c.item_id)
      AND (r.group_id   IS NULL
           OR c.path = rg.path
           OR c.path LIKE rg.path || :разделитель || '%')
    ORDER BY r.hard DESC,
             (r.station_id IS NOT NULL) DESC,
             (r.item_id IS NOT NULL) DESC,
             length(coalesce(rg.path, '')) DESC,
             r.created_at DESC
"""


def _правило(row) -> Правило:
    def момент(v):
        return v.isoformat() if v is not None else None
    return Правило(
        id=row["id"], subject=row["subject"], station_id=row["station_id"],
        group_id=row["group_id"], group_path=row["group_path"], item_id=row["item_id"],
        allow=bool(row["allow"]), hard=bool(row["hard"]), reason=row["reason"],
        valid_from=момент(row["valid_from"]), valid_to=момент(row["valid_to"]),
        created_at=момент(row["created_at"]),
    )


async def разрешить(db: AsyncSession, company_id, subject: str,
                    station_id: int, item_id: int) -> Решение:
    """Что можно на этой станции с этой позицией — и почему именно так."""
    if subject not in УМОЛЧАНИЯ:
        raise ValueError(f"неизвестный предмет правила: {subject}")

    строки = (await db.execute(text(_ЗАПРОС), {
        "company": company_id, "subject": subject,
        "station": station_id, "item": item_id, "разделитель": РАЗДЕЛИТЕЛЬ,
    })).mappings().all()

    if not строки:
        return Решение(allow=УМОЛЧАНИЯ[subject], subject=subject,
                       station_id=station_id, item_id=item_id)

    правила = [_правило(r) for r in строки]
    return Решение(allow=правила[0].allow, subject=subject,
                   station_id=station_id, item_id=item_id,
                   сработало=правила[0], перебиты=правила[1:])


async def цену_ведёт_станция(db: AsyncSession, company_id,
                             station_id: int, item_id: int) -> bool:
    """Короткий ответ там, где объяснение не нужно."""
    return (await разрешить(db, company_id, PRICE, station_id, item_id)).allow


async def позиция_в_матрице(db: AsyncSession, company_id,
                            station_id: int, item_id: int) -> bool:
    """Возит ли станция эту позицию."""
    return (await разрешить(db, company_id, ASSORTMENT, station_id, item_id)).allow


async def правила_компании(db: AsyncSession, company_id,
                           subject: str | None = None,
                           включая_закрытые: bool = False) -> list[dict]:
    """Все правила — для экрана «Матрица» и для отправки на станцию.

    Станция получает правила целиком и считает право сама: правил десятки,
    карточек тысячи, и смена одного правила не должна гнать по каналу весь
    справочник.
    """
    условия = ["r.company_id = :company"]
    параметры: dict = {"company": company_id}
    if subject:
        условия.append("r.subject = :subject")
        параметры["subject"] = subject
    if not включая_закрытые:
        условия.append("r.closed_at IS NULL")

    строки = (await db.execute(text(f"""
        SELECT r.id::text AS id, r.subject, r.station_id, r.group_id,
               coalesce(rg.path,'') AS group_path, r.item_id,
               coalesce(i.sku,'') AS item_sku, coalesce(i.name,'') AS item_name,
               r.allow, r.hard, r.reason, r.valid_from, r.valid_to,
               r.created_by::text AS created_by, r.created_at, r.closed_at
        FROM edge.matrix_rule r
        LEFT JOIN edge.item_group rg ON rg.id = r.group_id
        LEFT JOIN edge.item i ON i.id = r.item_id
        WHERE {' AND '.join(условия)}
        ORDER BY r.subject, r.station_id NULLS LAST, rg.path NULLS FIRST, r.created_at DESC
    """), параметры)).mappings().all()

    def момент(v):
        return v.isoformat() if v is not None else None

    return [{
        "id": r["id"], "subject": r["subject"], "station_id": r["station_id"],
        "group_id": r["group_id"], "group_path": r["group_path"],
        "item_id": r["item_id"], "item_sku": r["item_sku"], "item_name": r["item_name"],
        "allow": bool(r["allow"]), "hard": bool(r["hard"]), "reason": r["reason"],
        "valid_from": момент(r["valid_from"]), "valid_to": момент(r["valid_to"]),
        "created_by": r["created_by"], "created_at": момент(r["created_at"]),
        "closed_at": момент(r["closed_at"]),
    } for r in строки]


async def завести_правило(db: AsyncSession, company_id, *, subject: str,
                          allow: bool, reason: str,
                          station_id: int | None = None,
                          group_id: int | None = None,
                          item_id: int | None = None,
                          hard: bool = False,
                          valid_from=None, valid_to=None,
                          author_id=None) -> dict:
    """Новое правило. Существующее на ту же четвёрку — закрывается, не правится.

    История прав — такой же документ, как история цен: «почему в июле было
    иначе» обязано иметь ответ. Поэтому правило никогда не редактируется на
    месте; в интерфейсе это выглядит обычным изменением, в базе — новой
    записью со ссылкой на предыдущую.
    """
    import uuid as _uuid

    reason = (reason or "").strip()
    if not reason:
        raise ValueError("правило без причины не заводится: "
                         "через полгода «почему так» спросят обязательно")
    if subject not in УМОЛЧАНИЯ:
        raise ValueError(f"неизвестный предмет правила: {subject}")
    if group_id and item_id:
        raise ValueError("правило указывает либо группу, либо позицию: "
                         "позиция уже определяет свою группу")
    if hard and station_id:
        raise ValueError("жёсткий запрет ставится только сетевым правилом: "
                         "он и нужен, чтобы станция не могла его перебить")

    прежнее = (await db.execute(text("""
        SELECT id::text AS id FROM edge.matrix_rule
        WHERE company_id = :c AND subject = :s AND closed_at IS NULL
          AND station_id IS NOT DISTINCT FROM :st
          AND group_id   IS NOT DISTINCT FROM :g
          AND item_id    IS NOT DISTINCT FROM :i
    """), {"c": company_id, "s": subject, "st": station_id,
           "g": group_id, "i": item_id})).mappings().first()

    новое = _uuid.uuid4()
    if прежнее is not None:
        await db.execute(text("""
            UPDATE edge.matrix_rule
               SET closed_at = now(), closed_by = :by, replaced_by = :new
             WHERE id = :id
        """), {"id": прежнее["id"], "by": author_id, "new": новое})

    await db.execute(text("""
        INSERT INTO edge.matrix_rule
               (id, company_id, subject, station_id, group_id, item_id,
                allow, hard, valid_from, valid_to, reason, created_by)
        VALUES (:id, :c, :s, :st, :g, :i, :a, :h, :vf, :vt, :r, :by)
    """), {"id": новое, "c": company_id, "s": subject, "st": station_id,
           "g": group_id, "i": item_id, "a": allow, "h": hard,
           "vf": valid_from, "vt": valid_to, "r": reason, "by": author_id})

    return {"id": str(новое), "replaced": прежнее["id"] if прежнее else None}


async def закрыть_правило(db: AsyncSession, company_id, rule_id, author_id=None) -> bool:
    """Снять правило. Оно не удаляется — перестаёт действовать и остаётся в истории."""
    res = await db.execute(text("""
        UPDATE edge.matrix_rule SET closed_at = now(), closed_by = :by
        WHERE id = :id AND company_id = :c AND closed_at IS NULL
    """), {"id": rule_id, "c": company_id, "by": author_id})
    return bool(res.rowcount)


async def решения(db: AsyncSession, company_id, station_id: int,
                  позиции: list[tuple[int, str]], subject: str) -> dict[int, bool]:
    """Решение матрицы по каждой позиции станции для одного предмета.

    Нужна там, где карточки уезжают вниз ПАЧКОЙ: справочник станции — это
    тысяча с лишним позиций, и спрашивать `разрешить` по каждой значит послать
    тысячу запросов ради десятка правил.

    Правила загружаются один раз, лестница конкретности применяется в памяти —
    тот же порядок, что в `_ЗАПРОС`: жёсткий запрет → правило станции →
    правило карточки → более глубокая группа → сеть.

    `позиции` — пары «идентификатор карточки, путь её группы»; путь уже есть в
    выборке, ради которой всё и затевается.
    """
    строки = (await db.execute(text("""
        SELECT r.station_id, r.item_id, coalesce(rg.path, '') AS group_path,
               r.allow, r.hard
          FROM edge.matrix_rule r
          LEFT JOIN edge.item_group rg ON rg.id = r.group_id
         WHERE r.company_id = :company AND r.subject = :subject
           AND r.closed_at IS NULL
           AND (r.valid_from IS NULL OR r.valid_from <= now())
           AND (r.valid_to   IS NULL OR r.valid_to   >= now())
           AND (r.station_id IS NULL OR r.station_id = :station)
         ORDER BY r.hard DESC,
                  (r.station_id IS NOT NULL) DESC,
                  (r.item_id IS NOT NULL) DESC,
                  length(coalesce(rg.path, '')) DESC,
                  r.created_at DESC
    """), {"company": company_id, "subject": subject, "station": station_id})).mappings().all()

    def подходит(r, item_id: int, path: str) -> bool:
        if r["item_id"] is not None and r["item_id"] != item_id:
            return False
        путь = r["group_path"]
        if путь:
            return path == путь or path.startswith(путь + РАЗДЕЛИТЕЛЬ)
        return True

    ответ: dict[int, bool] = {}
    for item_id, path in позиции:
        решение = УМОЛЧАНИЯ[subject]
        for r in строки:                     # уже в порядке конкретности
            if подходит(r, item_id, path or ""):
                решение = bool(r["allow"])
                break
        ответ[item_id] = решение
    return ответ


async def владельцы_цены(db: AsyncSession, company_id, station_id: int,
                         позиции: list[tuple[int, str]]) -> dict[int, bool]:
    """Кому принадлежит цена: True — станции. Пачкой, для выгрузки справочника."""
    return await решения(db, company_id, station_id, позиции, PRICE)


async def применение(db: AsyncSession, company_id, station_id: int,
                     позиции: list[tuple[int, str]]) -> dict[int, bool]:
    """Применяется ли позиция на станции: True — да (умолчание — применяется).

    Отраслевой аналог — листинг: у SAP Retail площадка не может ни продать, ни
    принять артикул без действующего условия листинга. У нас запрет мягче:
    карточка на станцию всё равно едет (она встречается в сменах прошлых дней,
    и ставку по ней брать неоткуда), но БЕЗ ЦЕНЫ — а без цены станция не
    отправит её в кассу. 31.08.2026 без этого 20 блюд АЗС 8, закрытых
    товароведом за отсутствием продаж, уехали бы в кассу как ни в чём не бывало:
    правило было, и не значило ничего.
    """
    return await решения(db, company_id, station_id, позиции, ASSORTMENT)
