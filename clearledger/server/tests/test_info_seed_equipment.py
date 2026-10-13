"""Пакет справки по разделу «Эксплуатация → Оборудование».

Ловим то, что иначе всплывёт только на стенде: статья с разделом, которого нет в
пакете, роняет сид ВСЕХ пакетов (KeyError в `_seed_pack`); одинаковый заголовок
заводит одну статью вместо двух; привязка к несуществующей вкладке оставляет правую
панель пустой.
"""
import re
from pathlib import Path

from app.services.info_center import KIND_LABELS
from app.services.info_seed import APP_CATEGORIES, ARTICLES as ENERGY, CATEGORIES as ENERGY_CATEGORIES
from app.services.info_seed_equipment import ARTICLES, CATEGORIES, CATEGORY, SECTION_KEYS

MENUS = Path(__file__).resolve().parents[2] / "src" / "config" / "workspaceMenus.ts"


def test_заголовки_уникальны_во_всём_пакете_энергетики():
    titles = [a["title"] for a in ENERGY]
    twins = sorted({t for t in titles if titles.count(t) > 1})
    assert not twins, f"одинаковые заголовки: {twins}"
    assert all(a in ENERGY for a in ARTICLES), "пакет оборудования не подключён к энергетике"


def test_разделы_статей_объявлены_и_вложены_в_эксплуатацию():
    declared = {c["title"] for c in ENERGY_CATEGORIES}
    for a in ENERGY:
        assert a["category"] in declared, f"«{a['title']}»: раздела {a['category']} нет в пакете"
    apps = {c["title"] for c in APP_CATEGORIES}
    for c in CATEGORIES:
        assert c["parent"] in apps, f"у раздела «{c['title']}» нет приложения-родителя"
    assert all(a["category"] == CATEGORY and a["kind"] in KIND_LABELS for a in ARTICLES)


def test_привязки_ведут_на_вкладки_раздела():
    for a in ARTICLES:
        assert a["bindings"], f"«{a['title']}»: без привязок статья не всплывёт"
        for app_code, section, weight in a["bindings"]:
            assert app_code == "ops" and isinstance(weight, int), a["title"]
            assert section is None or section in SECTION_KEYS, f"«{a['title']}»: вкладки {section} нет"
    covered = {s for a in ARTICLES for _, s, _ in a["bindings"]}
    assert covered >= set(SECTION_KEYS), f"вкладки без статьи: {set(SECTION_KEYS) - covered}"
    if MENUS.exists():  # в прогоне против одного server/ дерева фронта нет
        block = MENUS.read_text(encoding="utf-8").split("export const EQUIPMENT_MENU", 1)[1].split("EQUIPMENT_KEYS", 1)[0]
        assert set(re.findall(r"key: '([^']+)'", block)) == set(SECTION_KEYS)


def test_обзор_раздела_стоит_выше_прочих_статей_без_вкладки():
    """Экран без своей статьи показывает привязки к `ops` без раздела - первой идёт обзорная."""
    loose = sorted(((w, a["title"]) for a in ENERGY for app, s, w in a["bindings"] if app == "ops" and s is None),
                   reverse=True)
    assert loose[0][1] == ARTICLES[0]["title"], loose
    assert len(loose) == 1 or loose[0][0] > loose[1][0], loose


def test_текст_вычитан_и_держит_границу_учёта():
    for a in ARTICLES:
        text = " ".join((a["title"], a["summary"], a["body"]))
        assert len(a["body"].strip()) > 400, f"«{a['title']}»: тело слишком короткое"
        assert "—" not in text and "–" not in text, f"«{a['title']}»: длинное тире"
        # Раздел ведёт складские предметы: слова «локация» и «площадка» в справке не живут.
        assert not re.search(r"локаци|площадк", text, re.I), f"«{a['title']}»: слово не из складского учёта"
        assert not re.search(r"\bявляется\b|\bданн(ый|ая|ое|ого|ом)\b|стоит отметить", text, re.I), a["title"]
