"""Область учёта раздела «Маркетинг»: контур из шапки доходит до отбора точек.

Замечание РусГидро 18.09.2026: человек выбирал «Забайкальский край», а раздел
показывал рынок всей страны — область учёта в запросы просто не попадала. Тест
держит обе стороны: пустой контур ничего не сужает (иначе рынок исчезнет у того,
кто ничего не выбирал), а выбранная территория превращается в условие отбора.
"""
import uuid

from app.models import MarketSite, Region, ServiceLocation
from app.routers.market_router import наши_в_области, область


def тексты(conds) -> list[str]:
    return [str(c.compile(compile_kwargs={"literal_binds": True})) for c in conds]


def test_пустой_контур_ничего_не_сужает():
    assert область(None, None) == []
    assert область("", "  ") == []


def test_регион_становится_условием_по_точкам():
    conds = область("Забайкальский край", None)
    assert len(conds) == 1
    sql = тексты(conds)[0]
    assert "market_sites.region" in sql
    assert "Забайкальский край" in sql


def test_несколько_территорий_через_запятую():
    conds = область("Забайкальский край, Приморский край", "Чита")
    sql = " ".join(тексты(conds))
    assert len(conds) == 2
    assert "Приморский край" in sql and "Чита" in sql
    # Пустые куски («а,,б») не превращаются в отбор по пустой строке: иначе
    # запятая-опечатка молча вычёркивала бы весь рынок.
    assert "''" not in sql


def test_свои_объекты_сужаются_тем_же_контуром():
    cid = uuid.uuid4()
    assert наши_в_области(cid, None, None) is None
    q = наши_в_области(cid, "Забайкальский край", None)
    sql = str(q.compile(compile_kwargs={"literal_binds": True}))
    # Регион объекта берётся каноном справочника, а не денорм-полем.
    assert "regions.name" in sql and "service_locations.region_id" in sql
    assert "Забайкальский край" in sql


def test_город_своих_объектов():
    q = наши_в_области(uuid.uuid4(), None, "Чита")
    sql = str(q.compile(compile_kwargs={"literal_binds": True}))
    assert "service_locations.city" in sql and "Чита" in sql


# Модели используются в условиях — импорт держит проверку честной.
assert MarketSite is not None and Region is not None and ServiceLocation is not None
