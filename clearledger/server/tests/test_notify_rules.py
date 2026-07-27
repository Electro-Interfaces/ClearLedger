"""Категории оповещений: событие журнала должно попадать в ту подписку, которую ждут.

Ломается это тихо: подписан на «Доступы и роли», а письма приходят про добавленных людей —
или наоборот, не приходят вовсе. Поэтому разбор действий проверяем отдельно от доставки,
которой нужны и БД, и Matrix, и SMTP.
"""
from app.notify_catalog import CATEGORIES, category_for, is_known, label_of


def test_люди_и_доступы_не_путаются():
    # `member.` — общий префикс двух разных категорий: роль это про человека,
    # а выданный доступ — про права. Один общий префикс схлопнул бы их в одну.
    assert category_for("user.create") == "people"
    assert category_for("user.remove") == "people"
    assert category_for("member.role") == "people"
    assert category_for("member.party") == "people"
    assert category_for("member.access") == "access"
    assert category_for("member.scope") == "access"
    assert category_for("role.create") == "access"
    assert category_for("role.delete") == "access"


def test_объекты_пространства_и_неизвестное():
    assert category_for("space.object.create") == "space"
    assert category_for("space.object.update") == "space"
    # Незнакомое действие не теряется: попадает в «Прочие события», а не проваливается.
    assert category_for("fuel.shift.import") == "other"
    assert category_for("") == "other"
    assert category_for(None) == "other"


def test_каталог_согласован():
    codes = [c.code for c in CATEGORIES]
    assert len(codes) == len(set(codes))            # дублей категорий нет
    assert all(is_known(c) for c in codes)
    assert label_of("people") and label_of("нет-такой") == "нет-такой"
    # Ровно одна категория без префиксов — та, что ловит остальное. Две такие означали бы,
    # что часть событий уходит в случайную из них.
    assert sum(1 for c in CATEGORIES if not c.prefixes) == 1
