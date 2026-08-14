"""Резолв организации 1С в `organization_id` слоя.

Каждый запрос коннектора тащит `Организация1С` — представление юрлица, от имени
которого сделана запись. В слое ось хранится ссылкой, поэтому имя надо превратить в
`organizations.id` ОДИН раз при загрузке, а не сравнивать строки в каждом отчёте.

Сопоставление по имени намеренно грубое: 1С отдаёт «ПРОМИЗОЛ СПБ ООО», а в карточке
организации записано «ООО «ПРОМИЗОЛ СПБ»» — разный порядок слов, кавычки-ёлочки и
пробелы. Поэтому сравниваем по «скелету»: только буквы и цифры в нижнем регистре,
отсортированные по словам. ИНН точнее, но его в представлении нет.

Использование в загрузчике:

    from resolve_org import org_map, org_id
    m = org_map(rows_of_organizations)         # [(id, name, inn), ...] из слоя
    oid = org_id(m, "ПРОМИЗОЛ СПБ ООО")        # → uuid или None
"""
from __future__ import annotations

import re


def _skeleton(name: str) -> str:
    """Имя без кавычек, форм собственности по краям и порядка слов."""
    words = re.findall(r"[0-9a-zA-Zа-яёА-ЯЁ]+", (name or "").lower())
    # Форма собственности стоит то спереди, то сзади — на опознание она не влияет.
    forms = {"ооо", "оао", "зао", "пао", "ао", "ип", "нко", "ано", "муп", "гуп"}
    core = [w for w in words if w not in forms]
    return " ".join(sorted(core or words))


def org_map(rows) -> dict[str, str]:
    """`[(id, name, inn), …]` → скелет имени и ИНН → id."""
    out: dict[str, str] = {}
    for oid, name, inn in rows:
        out[_skeleton(name)] = str(oid)
        if inn:
            out[str(inn).strip()] = str(oid)
    return out


def org_id(mapping: dict[str, str], name_or_inn: str | None) -> str | None:
    """Организация по представлению 1С или по ИНН. None — если не опознана.

    None здесь законен: запись без организации (общий справочник, служебный регистр)
    видна в любом разрезе. Придумывать ей юрлицо нельзя — это молча припишет чужие
    цифры одному из налогоплательщиков.
    """
    if not name_or_inn:
        return None
    key = str(name_or_inn).strip()
    return mapping.get(key) or mapping.get(_skeleton(key))


def demo() -> None:
    """Самопроверка: разное написание одного юрлица опознаётся одинаково."""
    rows = [("11111111-1111-1111-1111-111111111111", 'ООО «ПРОМИЗОЛ СПБ»', "7811760132")]
    m = org_map(rows)
    same = ["ПРОМИЗОЛ СПБ ООО", 'ООО "ПРОМИЗОЛ СПБ"', "  промизол спб  ", "7811760132"]
    for name in same:
        assert org_id(m, name) == rows[0][0], name
    assert org_id(m, "ООО Ромашка") is None
    assert org_id(m, "") is None
    assert org_id(m, None) is None
    print("resolve_org: ок —", len(same), "написаний сведены к одному юрлицу")


if __name__ == "__main__":
    demo()
