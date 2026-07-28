"""Знание пространства: привязки к рабочим областям и состав сида.

Ловим то, что иначе всплывёт только у пользователя: статья привязана к продукту,
которого нет в реестре, или к разделу, которого нет в меню, — тогда правая панель
молча пуста, и понять почему нельзя.
"""
from app.routers.sso_router import INTERNAL_ROUTES
from app.services.app_registry import _APPS
from app.services.info_center import KINDS, KIND_LABELS
from app.services.info_seed import ARTICLES, CATEGORIES, PROFILE

APP_CODES = {a["code"] for a in _APPS}


def test_инфо_есть_в_реестре_и_имеет_маршрут():
    assert "info" in APP_CODES
    assert INTERNAL_ROUTES.get("info") == "/info"


def test_статьи_привязаны_к_существующим_продуктам():
    for a in ARTICLES:
        assert a["bindings"], f"«{a['title']}»: нет привязок — статья не появится в панели"
        for app_code, _section, weight in a["bindings"]:
            assert app_code in APP_CODES, f"«{a['title']}»: продукта {app_code} нет в реестре"
            assert isinstance(weight, int)


def test_разделы_и_пласты_согласованы():
    titles = {c["title"] for c in CATEGORIES}
    for a in ARTICLES:
        assert a["category"] in titles, f"«{a['title']}»: раздела {a['category']} нет"
        assert a["kind"] in KIND_LABELS, f"«{a['title']}»: пласт {a['kind']} неизвестен"
    assert {k["key"] for k in KINDS} == {"guide", "norm", "lnd", "faq"}


def test_сид_только_платформенный_и_отраслевой():
    # Документы компании в сид не попадают: у каждой компании они свои.
    assert PROFILE == "energy"
    assert all(a["kind"] != "lnd" for a in ARTICLES), "ЛНД заводится в пространстве, не в коде"


def test_у_каждой_статьи_есть_тело_и_описание():
    for a in ARTICLES:
        assert len(a["body"].strip()) > 200, f"«{a['title']}»: тело слишком короткое"
        assert a.get("summary"), f"«{a['title']}»: без описания панель покажет один заголовок"
