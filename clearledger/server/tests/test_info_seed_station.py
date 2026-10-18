"""Пакет справки по рабочему месту АЗС: привязки, разделы и скриншоты.

Ловим разрыв привязок продукта, разделов «Инфо» и меню помощи, а также картинки,
которых нет на диске. Ключи экранов станции отличаются от меню центра:
пакет используется и автономной справкой агента.
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


def test_привязки_ведут_в_существующий_продукт():
    for a in ARTICLES:
        assert a["bindings"], f"«{a['title']}»: без привязок статья не всплывёт"
        for app_code, section, weight in a["bindings"]:
            assert app_code in APP_CODES, f"«{a['title']}»: продукта {app_code} нет в реестре"
            assert section is None or (isinstance(section, str) and section.strip()), a["title"]
            assert isinstance(weight, int)


def test_каждая_статья_доступна_в_помощи_магазина():
    for a in ARTICLES:
        # Дерево /info?app=shop отбирает по продукту, а не по конкретному экрану.
        assert any(c == "shop" for c, _s, _w in a["bindings"]), \
            f"«{a['title']}»: не попадёт в помощь «Магазина»"


def test_разделы_объявлены_и_попадают_в_помощь_продукта():
    titles = {c["title"] for c in CATEGORIES}
    assert len(titles) == len(CATEGORIES)
    assert {a["category"] for a in ARTICLES} == titles
    slices = HELP_SLICES.read_text(encoding="utf-8").split(
        "export const STORE_HELP_SLICES", 1)[1].split("\n}", 1)[0]
    menu = STORE_CATALOG.read_text(encoding="utf-8").split(
        "export const STORE_HELP_MENU", 1)[1].split("\n]", 1)[0]
    menu_keys = set(re.findall(r"key: '([^']+)'", menu))
    covered = set()
    for key, block in re.findall(r"'(help-[^']+)': \{(.*?)\n  \}", slices, re.S):
        assert key in menu_keys, f"помощь {key} отсутствует в меню «Магазина»"
        categories = re.search(r"categories: \[([^]]+)\]", block)
        if categories:
            covered.update(re.findall(r"'([^']+)'", categories.group(1)))
    for a in ARTICLES:
        assert a["category"] in titles, f"«{a['title']}»: раздела {a['category']} нет"
        assert a["kind"] in KIND_LABELS
    for t in titles:
        assert t in covered, f"раздел «{t}» не разложен в помощь «Магазина»"


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
