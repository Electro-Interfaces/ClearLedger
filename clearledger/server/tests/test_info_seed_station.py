"""Пакет справки по рабочему месту АЗС: привязки, разделы и скриншоты.

Ловим три молчаливые поломки: раздел меню, которого нет в `storeCatalog.STORE_VIEWS`
(статья не всплывёт подсказкой), раздел «Инфо», которого нет в `helpSlices` (пункт
помощи опустеет), и картинку, которой нет на диске (в статье будет битый значок).
"""
import re
from pathlib import Path

import pytest

from app.services.app_registry import _APPS
from app.services.info_center import KIND_LABELS
from app.services.info_seed_station import ARTICLES, CATEGORIES, IMG

APP_CODES = {a["code"] for a in _APPS}
FRONT = Path(__file__).resolve().parents[2]
STORE_CATALOG = FRONT / "src" / "config" / "storeCatalog.ts"
HELP_SLICES = FRONT / "src" / "components" / "workspace" / "helpSlices.ts"
SHOTS = FRONT / "public" / "help" / "station"

# Проверка сверяет справку с деревом ФРОНТА. В прогоне против одного `server/`
# (так тесты гоняют в контейнере стенда) этого дерева нет — и падение означало
# бы «не туда посмотрели», а не поломку. В CI и на машине разработчика дерево
# полное, там проверка работает.
pytestmark = pytest.mark.skipif(
    not STORE_CATALOG.exists(),
    reason="дерево фронта недоступно: прогон идёт против одного server/")


def _store_view_keys() -> set[str]:
    src = STORE_CATALOG.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*key: '([^']+)'", src, re.M))


def test_привязки_ведут_в_существующие_разделы_магазина():
    keys = _store_view_keys()
    assert "station_console" in keys, "пункт «Рабочее место АЗС» пропал из меню продукта"
    for a in ARTICLES:
        assert a["bindings"], f"«{a['title']}»: без привязок статья не всплывёт"
        for app_code, section, weight in a["bindings"]:
            assert app_code in APP_CODES, f"«{a['title']}»: продукта {app_code} нет в реестре"
            assert section is None or section in keys, \
                f"«{a['title']}»: раздела {section} нет в STORE_VIEWS"
            assert isinstance(weight, int)


def test_каждая_статья_привязана_к_рабочему_месту_азс():
    for a in ARTICLES:
        assert any(s == "station_console" for _c, s, _w in a["bindings"]), \
            f"«{a['title']}»: не всплывёт на экране, ради которого написана"


def test_разделы_объявлены_и_попадают_в_помощь_продукта():
    titles = {c["title"] for c in CATEGORIES}
    slices = HELP_SLICES.read_text(encoding="utf-8")
    for a in ARTICLES:
        assert a["category"] in titles, f"«{a['title']}»: раздела {a['category']} нет"
        assert a["kind"] in KIND_LABELS
    for t in titles:
        assert f"'{t}'" in slices, f"раздел «{t}» не разложен в helpSlices - пункт помощи пуст"


def test_скриншоты_лежат_на_диске_и_стоят_отдельной_строкой():
    for a in ARTICLES:
        for line in a["body"].splitlines():
            if "![" not in line:
                continue
            assert line.strip().startswith("!["), \
                f"«{a['title']}»: картинка внутри абзаца не отрендерится"
            url = re.search(r"\]\(([^)]+)\)", line).group(1)
            assert url.startswith(IMG), f"«{a['title']}»: чужой путь к картинке {url}"
            assert (SHOTS / Path(url).name).exists(), f"«{a['title']}»: нет файла {url}"


def test_у_каждой_статьи_есть_тело_и_описание():
    for a in ARTICLES:
        assert len(a["body"].strip()) > 400, f"«{a['title']}»: тело слишком короткое"
        assert a.get("summary"), f"«{a['title']}»: без описания панель покажет один заголовок"
        assert "—" not in a["body"] and "–" not in a["body"], \
            f"«{a['title']}»: длинное тире, текст не вычитан"
