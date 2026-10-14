"""Документы ЗИП: расчёт остатков при проведении, инвентаризации и отмене."""
import asyncio
import uuid
from decimal import Decimal as Dec

import pytest
from fastapi import HTTPException

from app.services import ezs_spare_docs as S

CID = uuid.uuid4()
P1, P2 = str(uuid.uuid4()), str(uuid.uuid4())
A, B = "wh-a", "wh-b"
NAMES = {P1: "Силовой модуль 30 кВт", P2: "Кабель CCS2"}


class FakeDB:
    async def get(self, model, key, **kw):
        return None


def run(coro):
    return asyncio.run(coro)


def negate(effects):
    return [(p, loc, -x) for p, loc, x in effects if x]


def test_у_каждого_вида_документа_свой_префикс():
    assert {op: p for op, (p, _) in S.SPARE_DOC_KINDS.items()} == {
        "receipt": "ПЗ", "issue": "РЗП", "transfer": "ПЗП", "write_off": "СЗП", "inventory": "ИНВ"}
    assert set(S.SPARE_DOC_LABELS) == set(S.SPARE_DOC_KINDS)
    from app.services.ezs_equipment_docs import DOC_KINDS
    assert not {p for p, _ in S.SPARE_DOC_KINDS.values()} & {p for p, _ in DOC_KINDS.values()}


@pytest.mark.parametrize("op", ["issue", "write_off", "transfer"])
def test_расход_больше_остатка_отклоняется(op):
    lines = S.norm_lines(op, [{"partId": P1, "qty": 5}, {"partId": P2, "qty": 1}])
    stock = {(P1, A): Dec(3), (P2, A): Dec(10)}
    with pytest.raises(HTTPException, match="Недостаточно остатка «Силовой модуль 30 кВт»: есть 3, нужно 5") as e:
        S.apply_effects(stock, S.doc_effects(op, lines, A, B), NAMES)
    assert e.value.status_code == 409
    assert stock == {(P1, A): Dec(3), (P2, A): Dec(10)}  # отказ ничего не меняет


def test_перемещение_переносит_остаток_между_складами():
    lines = S.norm_lines("transfer", [{"partId": P1, "qty": "2.5"}])
    new = S.apply_effects({(P1, A): Dec(3)}, S.doc_effects("transfer", lines, A, B))
    assert new == {(P1, A): Dec("0.5"), (P1, B): Dec("2.5")}


def test_инвентаризация_даёт_отклонение_факт_минус_учёт():
    lines = S.norm_lines("inventory", [{"partId": P1, "fact": 0}, {"partId": P2, "fact": "12"}])
    assert lines[0] == {"partId": P1, "fact": "0"}  # обнуление допустимо
    stock = {(P1, A): Dec(4), (P2, A): Dec(10)}
    for ln in lines:
        ln["book"] = S.fmt(stock[(ln["partId"], A)])
    effects = S.doc_effects("inventory", lines, None, A)
    assert effects == [(P1, A, Dec(-4)), (P2, A, Dec(2))]  # недостача и излишек
    assert S.apply_effects(stock, effects) == {(P1, A): Dec(0), (P2, A): Dec(12)}


@pytest.mark.parametrize("op,lines,start", [
    ("receipt", [{"partId": P1, "qty": 7}], {}),
    ("issue", [{"partId": P1, "qty": 2}], {(P1, A): Dec(5)}),
    ("transfer", [{"partId": P1, "qty": 2}, {"partId": P2, "qty": 1}], {(P1, A): Dec(5), (P2, A): Dec(1)}),
    ("write_off", [{"partId": P2, "qty": 1}], {(P2, A): Dec(1)}),
])
def test_отмена_возвращает_остаток(op, lines, start):
    effects = S.doc_effects(op, S.norm_lines(op, lines), A, B)
    posted = S.apply_effects(start, effects)
    back = S.apply_effects(posted, negate(effects), NAMES, cancel=True)
    assert {k: v for k, v in back.items() if v} == {k: v for k, v in start.items() if v}


def test_отмена_описи_возвращает_учётный_остаток():
    lines = [{"partId": P1, "book": "4", "fact": "0"}, {"partId": P2, "book": "3", "fact": "3"}]
    effects = S.doc_effects("inventory", lines, None, A)
    assert negate(effects) == [(P1, A, Dec(4))]  # строка без расхождения сторно не даёт
    assert S.apply_effects({(P1, A): Dec(0), (P2, A): Dec(3)}, negate(effects))[(P1, A)] == Dec(4)


def test_отмена_уводящая_в_минус_отклоняется():
    effects = S.doc_effects("receipt", S.norm_lines("receipt", [{"partId": P1, "qty": 10}]), None, A)
    after_issue = {(P1, A): Dec(4)}  # из прихода уже израсходовано 6
    with pytest.raises(HTTPException, match="Сначала отмените более поздние расходы") as e:
        S.apply_effects(after_issue, negate(effects), NAMES, cancel=True)
    assert e.value.status_code == 409


@pytest.mark.parametrize("op,raw,msg", [
    ("receipt", [], "хотя бы одну строку"),
    ("receipt", [{"partId": P1, "qty": 0}], "больше нуля"),
    ("issue", [{"partId": P1, "qty": -1}], "больше нуля"),
    ("issue", [{"partId": P1}], "количество"),
    ("issue", [{"partId": "не-ссылка", "qty": 1}], "номенклатура"),
    ("receipt", [{"partId": P1, "qty": "NaN"}], "количество"),
    ("receipt", [{"partId": P1, "qty": 1}, {"partId": P1, "qty": 2}], "дважды"),
    ("inventory", [{"partId": P1, "fact": -1}], "не может быть отрицательным"),
])
def test_строки_проверяются(op, raw, msg):
    with pytest.raises(HTTPException, match=msg):
        S.norm_lines(op, raw)


@pytest.mark.parametrize("payload,msg", [
    ({"op": "correction", "doc_date": "2026-10-13", "lines": [{"partId": P1, "qty": 1}]}, "Неизвестный вид"),
    ({"op": "receipt", "doc_date": "13.10.2026", "lines": [{"partId": P1, "qty": 1}]}, "дату документа"),
    ({"op": "receipt", "doc_date": "2026-10-13", "lines": []}, "хотя бы одну строку"),
])
def test_документ_проверяется_до_проведения(payload, msg):
    with pytest.raises(HTTPException, match=msg):
        run(S.post_document(FakeDB(), CID, None, payload))


def test_количество_без_экспоненты_и_хвостовых_нулей():
    assert [S.fmt(Dec(x)) for x in ("1E+2", "2.500", "0.000", "10")] == ["100", "2.5", "0", "10"]
