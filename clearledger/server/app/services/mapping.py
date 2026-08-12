"""
Резолвер МАППИНГА значений между системами — конфигурация уровня КАНАЛА.

Виды (kind): fuel | paytype | station | nomenclature | counterparty.
Значения топлива/оплат/станций называются по-РАЗНОМУ в STS / TradeCorp / MSTO /
ЦБ ЭЛСИ.АЗК, поэтому маппинг — ДАННЫЕ (`ReconcileMapping`), а не хардкод.

Приоритет резолва:
  1. channel-specific (ReconcileMapping.channel_id = канал) — оптимизация под канал;
  2. company-default (channel_id IS NULL) — общий для компании;
  3. канонический СИД (ниже) — дефолт «из коробки».

Сиды перекрываются маппингом канала/компании. resolve() — рантайм (БД+сид);
normalize_default() — только сид (без БД, для стадии нормализации потока).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReconcileMapping

# ── Канонические СИДЫ (дефолты; перекрываются ReconcileMapping) ──────────────
_FUEL_SEED = {
    "бензин аи-92": "АИ-92", "аи-92": "АИ-92", "92": "АИ-92", "regular": "АИ-92",
    "бензин аи-95": "АИ-95", "аи-95": "АИ-95", "95": "АИ-95", "premium": "АИ-95",
    "бензин аи-98": "АИ-98", "аи-98": "АИ-98", "98": "АИ-98", "super": "АИ-98",
    "бензин аи-100": "АИ-100", "аи-100": "АИ-100", "100": "АИ-100", "ultimate": "АИ-100",
    "дизельное топливо": "ДТ", "дизель": "ДТ", "дт": "ДТ", "diesel": "ДТ",
    "дт зимнее": "ДТ", "дт летнее": "ДТ", "дт-к5": "ДТ", "дт-премиум": "ДТ",
    "дт к5": "ДТ", "дт премиум": "ДТ",
    "пропан": "Пропан", "propane": "Пропан", "газ": "Пропан", "спбт": "Пропан",
    "метан": "Метан", "methane": "Метан", "cng": "Метан",
}
# Способы оплаты: STS pay_type.id / названия форм (ОРП/эквайринг) → канон
_PAYTYPE_SEED = {
    "1": "Наличные", "наличные": "Наличные",
    "2": "Банковская карта", "карты мпс": "Банковская карта",
    "банковские карты": "Банковская карта", "retail_card": "Банковская карта",
    "cards": "Топливная карта", "топливные карты": "Топливная карта",
    "online": "Онлайн", "онлайн": "Онлайн", "online (яндекс, мобилпр.)": "Онлайн",
    "voucher": "Талоны", "талоны": "Талоны",
    "ledger": "Ведомости", "ведомости": "Ведомости",
    "retail_cash": "Наличные",
}
# Типы коннекторов ЭЗС → канон. Один словарь на три потока: сессии, паспорт
# станции (`connectors_ru` витрины) и прайс (`tariffs_ru`). До 09.08.2026 канон
# применялся только к сессиям, поэтому один разъём назывался «CCS Combo 2» в
# сессии и «CCS2» в паспорте — сопоставить факт с прайсом по типу было нельзя.
# Написания ниже сняты с фактических данных пилота (11 вариантов на 7 типов).
_CONNECTOR_SEED = {
    "type2": "Type 2", "type 2": "Type 2", "тип2": "Type 2", "тип 2": "Type 2",
    "type1": "Type 1", "type 1": "Type 1", "тип1": "Type 1", "тип 1": "Type 1",
    # Переходник Type 2 → Type 1: разъём со стороны машины остаётся Type 1.
    "переходник t2-t1": "Type 1",
    "ccs": "CCS Combo 2", "ccs2": "CCS Combo 2", "combo2": "CCS Combo 2",
    "chademo": "CHAdeMO", "чадемо": "CHAdeMO",
    "gbt_dc": "GB/T DC", "gbt dc": "GB/T DC", "gbt/dc": "GB/T DC", "gb/t dc": "GB/T DC",
    "gbt_ac": "GB/T AC", "gbt ac": "GB/T AC", "gbt/ac": "GB/T AC", "gb/t ac": "GB/T AC",
    # Голое «GB/T» правила намеренно не имеет: DC и AC — разные разъёмы и разные
    # деньги, а строка не говорит какой именно. Пусть остаётся видимой в разрезе.
    "shuko": "SHUKO", "шуко": "SHUKO", "schuko": "SHUKO",
    "ac": "AC (переменный ток)", "dc": "DC (постоянный ток)",
}
# Тип пользователя ЭЗС → канон
_USER_TYPE_SEED = {
    "фл": "ФЛ", "физическое лицо": "ФЛ", "individual": "ФЛ", "b2c": "ФЛ",
    "юл": "ЮЛ", "юридическое лицо": "ЮЛ", "legal": "ЮЛ", "b2b": "ЮЛ",
}
_SEEDS: dict[str, dict[str, str]] = {
    "fuel": _FUEL_SEED,
    "paytype": _PAYTYPE_SEED,
    "connector": _CONNECTOR_SEED,
    "user_type": _USER_TYPE_SEED,
}


def normalize_default(kind: str, source_key) -> str:
    """Канон-сид (без БД): нормализовать значение по дефолтной карте вида."""
    raw = str(source_key or "").strip()
    return _SEEDS.get(kind, {}).get(raw.lower(), raw)


# Регион ЭЗС → канон. Данные приходят в 2–3 написаниях («Приморский» / «Приморский
# край», «Сахалинская» / «обл» / «область», «Башкортостан» / «Республика ...»).
# Ключ = ПЕРВОЕ слово (после снятия префикса «Республика», в нижнем регистре) —
# одно правило покрывает все варианты субъекта.
_REGION_CANON = {
    "алтайский": "Алтайский край", "амурская": "Амурская область",
    "башкортостан": "Республика Башкортостан", "брянская": "Брянская область",
    "бурятия": "Республика Бурятия", "владимирская": "Владимирская область",
    "еврейская": "Еврейская автономная область", "забайкальский": "Забайкальский край",
    "иркутская": "Иркутская область", "камчатский": "Камчатский край",
    "кемеровская": "Кемеровская область", "краснодарский": "Краснодарский край",
    "красноярский": "Красноярский край", "курганская": "Курганская область",
    "ленинградская": "Ленинградская область", "липецкая": "Липецкая область",
    "магаданская": "Магаданская область", "москва": "Москва",
    "московская": "Московская область", "нижегородская": "Нижегородская область",
    "новосибирская": "Новосибирская область", "омская": "Омская область",
    "оренбургская": "Оренбургская область", "пензенская": "Пензенская область",
    "пермский": "Пермский край", "приморский": "Приморский край",
    "рязанская": "Рязанская область", "самарская": "Самарская область",
    "саратовская": "Саратовская область", "сахалинская": "Сахалинская область",
    "татарстан": "Республика Татарстан", "свердловская": "Свердловская область",
    "тверская": "Тверская область", "тульская": "Тульская область",
    "тюменская": "Тюменская область", "удмуртская": "Удмуртская Республика",
    "хабаровский": "Хабаровский край", "хакасия": "Республика Хакасия",
    "челябинская": "Челябинская область", "чувашская": "Чувашская Республика",
    # Субъекты, встретившиеся в паспортах станций пилота и не опознававшиеся:
    "смоленская": "Смоленская область", "марий": "Республика Марий Эл",
    "чувашия": "Чувашская Республика", "мордовия": "Республика Мордовия",
    "карелия": "Республика Карелия", "коми": "Республика Коми",
    "саха": "Республика Саха (Якутия)", "якутия": "Республика Саха (Якутия)",
    "алтай": "Республика Алтай", "адыгея": "Республика Адыгея",
    "ставропольский": "Ставропольский край", "ростовская": "Ростовская область",
    "воронежская": "Воронежская область", "ярославская": "Ярославская область",
    "ленинградская": "Ленинградская область", "калужская": "Калужская область",
}


def canon_region(raw) -> str | None:
    """Нормализовать регион ЭЗС к канону по первому слову. Неизвестный — как есть."""
    s = str(raw or "").strip()
    if not s:
        return None
    low = s.lower().replace("ё", "е")
    # Сокращённая форма встречается наравне с полной («Респ Хакасия», «Смоленская
    # обл»): без снятия префикса первым словом оказывается «респ», и субъект не
    # опознаётся — в паспортах станций так разъехались 87 написаний на 48 субъектов.
    for prefix in ("республика ", "респ. ", "респ "):
        if low.startswith(prefix):
            low = low[len(prefix):].strip()
            break
    low = low.removeprefix("г.").removeprefix("г ").strip()
    first = low.replace("-", " ").split()[0] if low.split() else ""
    return _REGION_CANON.get(first, s)


# Приставки населённого пункта: витрина пишет «г.Красноярск», HubEx — «Красноярск».
# Из-за одной этой разницы 260 карточек пилота считались расходящимися с витриной,
# а группировка по городу давала два «Красноярска».
_CITY_PREFIX = ("г.", "г ", "город ", "с.", "с ", "село ", "п.", "п ", "пос.", "пос ",
                "посёлок ", "поселок ", "д.", "д ", "деревня ", "ст.", "станица ",
                "пгт.", "пгт ", "рп.", "рп ", "с/п ")


def canon_city(raw) -> str | None:
    """Название населённого пункта без приставки типа («г.Красноярск» → «Красноярск»)."""
    s = " ".join(str(raw or "").split())
    if not s:
        return None
    low = s.lower()
    for prefix in _CITY_PREFIX:
        if low.startswith(prefix):
            s = s[len(prefix):].strip()
            break
    return s or None


# Кириллические двойники латиницы: в паспорте станции 227 бренд записан как
# «StarСharge» с кириллической «С» — глазами не отличить, а в справочнике это
# отдельный бренд с одной станцией.
_HOMOGLYPH = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P",
    "С": "C", "Т": "T", "Х": "X", "У": "Y",
    "а": "a", "е": "e", "к": "k", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
})
# Ключ (без регистра, пробелов и дефисов) → каноническое написание.
_BRAND_CANON = {
    "fora": "FORA", "фора": "FORA",
    "псс": "ПСС", "pss": "ПСС",
    "kostad": "Kostad", "костад": "Kostad",
    "rewatt": "REWATT", "реватт": "REWATT",
    "eprom": "EPROM", "епром": "EPROM",
    "starcharge": "StarCharge", "старчардж": "StarCharge",
    "onder": "ONDER", "ондер": "ONDER",
    "parus": "Парус", "парус": "Парус",
    "svetozar": "Светозар", "светозар": "Светозар",
    "nsp": "NSP", "abb": "ABB", "setec": "Setec", "touch": "Touch",
    "nartis": "Нартис", "нартис": "Нартис", "enel": "Enel",
}


def canon_brand(raw) -> str | None:
    """Каноническое написание бренда станции; неизвестный — как пришёл (без хвостов).

    Витрина пишет «ПСС (Россия)», HubEx — «ПСС». Ключ ищется дважды: как есть и
    после замены кириллических двойников латиницей — так «StarСharge» с
    кириллической «С» опознаётся как «StarCharge», а «Фора» и «FORA» сходятся."""
    s = " ".join(str(raw or "").split())
    if not s:
        return None
    s = s.split(" (")[0].strip() or s
    plain = s.lower().replace("-", "").replace(" ", "")
    latin = s.translate(_HOMOGLYPH).lower().replace("-", "").replace(" ", "")
    return _BRAND_CANON.get(plain) or _BRAND_CANON.get(latin) or s


_OWNER_FORMS = ("ооо", "оао", "пао", "зао", "ао", "ип", "нао")


def owner_key(raw) -> str:
    """Ключ сравнения владельцев: «ООО СНК» и «СНК» — один и тот же контрагент.

    Хранение не трогаем (юрлицо пишется как в документах), но сверять реестр с
    витриной по строке нельзя: 130 из 134 «расхождений» — это правовая форма."""
    s = " ".join(str(raw or "").replace('"', " ").replace("«", " ").replace("»", " ").split())
    low = s.lower()
    for form in _OWNER_FORMS:
        if low.startswith(f"{form} "):
            low = low[len(form) + 1:]
            break
        if low.endswith(f" {form}"):
            low = low[: -len(form) - 1]
            break
    return low.strip()


# Границы РФ с запасом: всё, что вне, — мусор источника (три тестовые карточки
# пилота стоят в Гренландии и в Арктике).
def geo_in_russia(lat, lon) -> bool:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return 41.0 <= la <= 82.0 and 19.0 <= lo <= 191.0


async def load_kind_map(
    db: AsyncSession,
    company_id: uuid.UUID,
    kind: str,
    channel_id: uuid.UUID | None = None,
) -> dict[str, str]:
    """Карта {source_key.lower(): target} для вида — ОДНИМ запросом на прогон.

    channel-override поверх company-default (channel выигрывает). Применять через
    apply(); чего нет в карте — фолбэк на канон-сид (normalize_default).
    """
    rows = (
        await db.execute(
            select(ReconcileMapping).where(
                ReconcileMapping.company_id == company_id,
                ReconcileMapping.kind == kind,
            )
        )
    ).scalars().all()
    company_map: dict[str, str] = {}
    channel_map: dict[str, str] = {}
    for m in rows:
        tgt = m.target_name or m.target_ref
        if not tgt:
            continue
        key = str(m.source_key or "").strip().lower()
        if m.channel_id is None:
            company_map[key] = tgt
        elif channel_id is not None and m.channel_id == channel_id:
            channel_map[key] = tgt
    return {**company_map, **channel_map}


def apply(kind: str, value, kind_map: dict[str, str]) -> str:
    """Применить загруженную карту: override → канон-сид → как есть."""
    raw = str(value or "").strip()
    return kind_map.get(raw.lower()) or normalize_default(kind, raw)


async def resolve(
    db: AsyncSession,
    company_id: uuid.UUID,
    kind: str,
    source_key,
    channel_id: uuid.UUID | None = None,
) -> str:
    """Резолв значения: channel-override → company-default → канон-сид.

    Возвращает target_name/target_ref маппинга, иначе — нормализованный сид.
    """
    sk = str(source_key or "").strip()
    rows = (
        await db.execute(
            select(ReconcileMapping).where(
                ReconcileMapping.company_id == company_id,
                ReconcileMapping.kind == kind,
                ReconcileMapping.source_key == sk,
            )
        )
    ).scalars().all()
    if rows:
        chosen = None
        if channel_id is not None:
            chosen = next((m for m in rows if m.channel_id == channel_id), None)
        chosen = chosen or next((m for m in rows if m.channel_id is None), None) or rows[0]
        return chosen.target_name or chosen.target_ref or normalize_default(kind, sk)
    return normalize_default(kind, sk)
