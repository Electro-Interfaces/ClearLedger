"""Что можно передавать наружу и какие объекты вообще публикуются.

СТО раздел 12 ставит два ограничения на выгрузку сведений об объектах:

* **п. 12.1–12.2 — состав.** Наружу не передаются технический ключ, инвентарный
  номер, сведения о стоимости, адреса и параметры подключения оборудования,
  пароли и ключи. Разрешённый состав ведётся перечнем, а не «всем, что есть в
  ответе»: иначе новая графа паспорта уезжает наружу молча, самим фактом
  появления.
* **п. 12.4 — признак публикации.** Объект без разрешения не публикуется вовсе.
  Признак ведётся на уровне точки обслуживания.

Внутренний обмен между системами организации под эти ограничения не подпадает
(п. 7.6 разделяет их прямо): Поддержка получает полный состав, иначе она не
сможет вести заявку по объекту. Поэтому политика применяется по признаку
`external`, а не ко всякой выгрузке подряд.
"""
from __future__ import annotations

from typing import Any

# Разрешённый состав при передаче ВОВНЕ. Перечень, а не исключения: добавленная
# завтра графа паспорта не уедет наружу, пока её сюда не впишут осознанно.
PUBLIC_FIELDS: frozenset[str] = frozenset({
    "code", "name", "type", "status", "operationalStatus", "address",
})

# Разрешённый состав паспорта — то, что видит потребитель услуги: где станция,
# какая у неё мощность и какие разъёмы. Ни заводского номера, ни инвентарного.
PUBLIC_PASSPORT_FIELDS: frozenset[str] = frozenset({
    "stationNumber", "city", "street", "house", "latitude", "longitude",
    "powerKwt", "connectorsCount", "connectorTypes", "brand", "speedClass",
})

# Графы, которые норма называет поимённо как непередаваемые. Держим отдельно от
# перечня разрешённых, чтобы правило было видно, а не выводилось вычитанием.
NEVER_EXPORTED: frozenset[str] = frozenset({
    "id", "stationId", "inventoryNumber", "serialNumber", "hubexAssetId",
    "ocppProtocol", "firmware", "sourceBindings", "metadata",
})


def is_publishable(location) -> bool:
    """Разрешена ли публикация объекта (п. 12.4).

    Признак трёхзначен: `True` — разрешено, `False` — запрещено явно, `None` —
    не задан. Не задан означает «нет разрешения»: публикация по умолчанию — это
    решение за владельца объекта, принятое молчанием.
    """
    return getattr(location, "is_published", None) is True


def filter_for_export(item: dict[str, Any]) -> dict[str, Any]:
    """Оставить только разрешённый к передаче состав."""
    out = {k: v for k, v in item.items() if k in PUBLIC_FIELDS}
    passport = item.get("passport") or {}
    if isinstance(passport, dict):
        clean = {k: v for k, v in passport.items()
                 if k in PUBLIC_PASSPORT_FIELDS and k not in NEVER_EXPORTED}
        if clean:
            out["passport"] = clean
    return out
