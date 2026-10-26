"""Телефон в E.164 — один разбор для базы и для кода (Я-3, «Телефония»).

Телефоны в справочниках Ядра — свободный текст: «8 (495) 123-45-67, доб. 12»,
«+7(999) 999 99-95», два номера через запятую. Сравнивать такое с номером
звонящего нельзя: узел присылает `+74951234567`, и совпадение по строке не
находит почти никого (E.164 был у 1 номера контрагента из 106, отчёт
ContactHub research/02 §1.2).

Поэтому у `counterparties`, `counterparty_contacts` и `users` есть
нормализованные колонки, которые считает сама база: генерируемые колонки на
функции `phone_to_e164(text)`. Так их нельзя забыть пересчитать — кто бы ни
писал телефон (сведение из 1С пачкой, экран, импорт), колонка следует за ним, и
отдельной разовой миграции данных не нужно: `ALTER TABLE … ADD COLUMN …
GENERATED` заполняет её сразу для всех строк.

Правило (то же в `to_e164` ниже — для входящих номеров и тестов):
  * добавочный номер отрезается («доб.», «ext», «вн.» — отдельным словом, чтобы
    «Главный: 8 495…» не потерял номер), из нескольких номеров
    берётся первый, который разобрался (разделители «,», «;», «/»);
  * 11 цифр с 7 или 8 впереди → `+7` и последние десять;
  * 10 цифр без «+» → `+7` и они (номер РФ без кода страны);
  * «+» и 11–15 цифр → как есть (зарубежный);
  * иначе — нет номера (короткий внутренний, мусор).
"""
from __future__ import annotations

import re

# Функция для генерируемых колонок. IMMUTABLE обязательна: без неё PostgreSQL не
# даст построить на ней ни колонку, ни индекс. Имя не совпадает с колонками,
# чтобы в выражениях было видно, где функция, а где поле.
PHONE_FUNCTION_DDL = r"""
CREATE OR REPLACE FUNCTION phone_to_e164(raw text) RETURNS varchar
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $fn$
DECLARE
  part text;
  d text;
BEGIN
  IF raw IS NULL THEN
    RETURN NULL;
  END IF;
  FOREACH part IN ARRAY regexp_split_to_array(raw, '[,;/]') LOOP
    part := regexp_replace(part, '(^|[^а-яёa-z])(доб|ext|вн).*$', '\1', 'i');
    d := regexp_replace(part, '[^0-9]', '', 'g');
    IF length(d) = 11 AND left(d, 1) IN ('7', '8') THEN
      RETURN '+7' || right(d, 10);
    ELSIF length(d) = 10 AND position('+' IN part) = 0 THEN
      RETURN '+7' || d;
    ELSIF position('+' IN part) > 0 AND length(d) BETWEEN 11 AND 15 THEN
      RETURN '+' || d;
    END IF;
  END LOOP;
  RETURN NULL;
END
$fn$
"""

# Выражение генерируемой колонки — общее для модели и миграции.
def generated(column: str) -> str:
    return f"phone_to_e164({column})"


_EXT = re.compile(r"(^|[^а-яёa-z])(доб|ext|вн).*$", re.IGNORECASE | re.DOTALL)


def to_e164(raw: str | None) -> str | None:
    """Тот же разбор, что `phone_to_e164` в базе. Расхождение ловит тест."""
    if raw is None:
        return None
    for part in re.split(r"[,;/]", raw):
        part = _EXT.sub(r"\1", part)
        d = re.sub(r"[^0-9]", "", part)
        if len(d) == 11 and d[0] in "78":
            return "+7" + d[-10:]
        if len(d) == 10 and "+" not in part:
            return "+7" + d
        if "+" in part and 11 <= len(d) <= 15:
            return "+" + d
    return None


# Добавочный человек дописывает к городскому номеру, и терять его нельзя:
# «доб. 123» — это то, по чему до него дозвонятся.
_EXT_VALUE = re.compile(r"(?:доб|ext|вн)[.\s]*([0-9]{1,6})", re.IGNORECASE)


def pretty(raw: str | None) -> str | None:
    """Номер в едином виде: «+7 900 123-45-67», добавочный сохраняется.

    Человек пишет как привык — «89001234567», «8 (812) 000-00-00 доб 123», — и
    в карточке соседа рядом оказывались три разных написания одного формата.
    Нормализованные колонки в базе решают поиск, но не решают чтение: единый
    вид нужен глазам. Нераспознанное возвращаем как есть — решает вызывающий.
    """
    if raw is None:
        return None
    текст = raw.strip()
    if not текст:
        return None
    e164 = to_e164(текст)
    if e164 is None:
        return текст
    d = e164.lstrip("+")
    если_рф = len(d) == 11 and d[0] == "7"
    основной = f"+7 {d[1:4]} {d[4:7]}-{d[7:9]}-{d[9:]}" if если_рф else f"+{d}"
    доб = _EXT_VALUE.search(текст)
    return f"{основной}, доб. {доб.group(1)}" if доб else основной


def mask(e164: str | None) -> str:
    """Номер для ответа и журнала: `+7 900 ***-**-67`; сырой номер наружу не идёт."""
    if not e164:
        return "—"
    d = e164.lstrip("+")
    if len(d) == 11 and d[0] == "7":
        return f"+7 {d[1:4]} ***-**-{d[-2:]}"
    return f"+{d[:2]}***{d[-2:]}" if len(d) > 4 else "***"
