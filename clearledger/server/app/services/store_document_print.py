"""Печатные формы документов магазина.

Бланки те же, что человек видит в 1С: ТОРГ-12, ТОРГ-13, ИНВ-3, ТОРГ-16, М-4.
Ничего своего не изобретаем — сотрудник и бухгалтер должны узнать лист с
первого взгляда, иначе печатная форма это распечатка экрана, а не документ.

Формы Госкомстата с 2013 года необязательны, но остались отраслевым языком: по
ним ищут графы и спорят с поставщиком. Поэтому сохраняем номер формы, код ОКУД
и нумерацию граф — те детали, по которым бланк узнают.

Печатает браузер: своего PDF-движка здесь нет и не нужно.
"""
from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.models import StoreDocumentProjection


ЕДИНИЦЫ = ("", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь",
           "девять", "десять", "одиннадцать", "двенадцать", "тринадцать",
           "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать",
           "восемнадцать", "девятнадцать")
ЕДИНИЦЫ_Ж = {1: "одна", 2: "две"}
ДЕСЯТКИ = ("", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят",
           "семьдесят", "восемьдесят", "девяносто")
СОТНИ = ("", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот",
         "семьсот", "восемьсот", "девятьсот")


def _тройка(n: int, женский: bool) -> list[str]:
    out: list[str] = []
    if n >= 100:
        out.append(СОТНИ[n // 100])
        n %= 100
    if n >= 20:
        out.append(ДЕСЯТКИ[n // 10])
        n %= 10
    if n > 0:
        # женский род нужен тысячам: «одна тысяча», но «один рубль»
        out.append(ЕДИНИЦЫ_Ж[n] if женский and n in ЕДИНИЦЫ_Ж else ЕДИНИЦЫ[n])
    return out


def _окончание(n: int, формы: tuple[str, str, str]) -> str:
    n %= 100
    if 11 <= n <= 14:
        return формы[2]
    return {1: формы[0], 2: формы[1], 3: формы[1], 4: формы[1]}.get(n % 10, формы[2])


def сумма_прописью(сумма: object) -> str:
    """«Одна тысяча двести тридцать четыре рубля 56 копеек» — реквизит бланка."""
    try:
        значение = Decimal(str(сумма or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        значение = Decimal("0.00")
    if значение < 0:
        return "минус " + сумма_прописью(-значение)
    целых = int(значение)
    копеек = int((значение - целых) * 100)
    слова: list[str] = []
    миллионы, тысячи, остаток = целых // 1000000, (целых // 1000) % 1000, целых % 1000
    if миллионы:
        слова += _тройка(миллионы, False)
        слова.append(_окончание(миллионы, ("миллион", "миллиона", "миллионов")))
    if тысячи:
        слова += _тройка(тысячи, True)
        слова.append(_окончание(тысячи, ("тысяча", "тысячи", "тысяч")))
    if остаток or not слова:
        слова += _тройка(остаток, False)
    фраза = " ".join(word for word in слова if word) or "ноль"
    return (f"{фраза[0].upper()}{фраза[1:]} "
            f"{_окончание(целых, ('рубль', 'рубля', 'рублей'))} "
            f"{копеек:02d} {_окончание(копеек, ('копейка', 'копейки', 'копеек'))}")


# бланк вида документа: номер формы, ОКУД, название и подписи под листом
БЛАНКИ = {
    "purchase": ("ТОРГ-12", "0330212", "Товарная накладная",
                 ("Отпуск разрешил", "Товар принял", "Главный (старший) бухгалтер")),
    "return_purchase": ("ТОРГ-12", "0330212", "Товарная накладная на возврат поставщику",
                        ("Отпустил", "Принял")),
    "return_sale": ("ТОРГ-12", "0330212", "Накладная на возврат товара от покупателя",
                    ("Отпустил", "Принял")),
    "transfer": ("ТОРГ-13", "0330213",
                 "Накладная на внутреннее перемещение, передачу товаров",
                 ("Отпустил", "Получил")),
    "inventory": ("ИНВ-3", "0317004",
                  "Инвентаризационная опись товарно-материальных ценностей",
                  ("Председатель комиссии", "Член комиссии",
                   "Материально ответственное лицо")),
    "writeoff": ("ТОРГ-16", "0330216", "Акт о списании товаров",
                 ("Председатель комиссии", "Член комиссии", "Утверждаю: руководитель")),
    "gain": ("М-4", "0315003", "Приходный ордер", ("Принял (кладовщик)", "Сдал")),
    "retail_sale_sidegoods": ("—", "", "Отчёт о розничных продажах",
                              ("Составил", "Главный (старший) бухгалтер")),
    "production_release": ("—", "", "Отчёт производства за смену",
                           ("Составил", "Проверил")),
    "recipe": ("ОП-1", "0330501", "Калькуляционная карточка",
               ("Заведующий производством", "Калькуляцию составил", "Утверждаю: руководитель")),
}

# у чеков, смен и переоценки унифицированного бланка нет: чек печатает касса,
# смена это архив, переоценка — внутренний приказ по ценам
БЕЗ_БЛАНКА = {"fiscal_receipt", "store_shift", "revaluation"}

КОЛОНКИ = ("№", "Наименование", "Штрихкод", "Ед. изм.", "Количество",
           "Цена, руб. коп.", "Сумма, руб. коп.", "Ставка НДС", "Сумма НДС")


def _текст(row: dict, *ключи: str) -> str:
    for ключ in ключи:
        значение = row.get(ключ)
        if значение not in (None, ""):
            return str(значение)
    return ""


def _число(row: dict, *ключи: str) -> str:
    сырое = _текст(row, *ключи)
    if not сырое:
        return ""
    try:
        значение = Decimal(str(сырое))
    except (InvalidOperation, ValueError):
        return сырое
    return f"{значение.normalize():f}" if значение == значение.to_integral() else f"{значение}"


def _деньги(row: dict, *ключи: str) -> str:
    сырое = _текст(row, *ключи)
    if not сырое:
        return ""
    try:
        return f"{Decimal(str(сырое)).quantize(Decimal('0.01'))}"
    except (InvalidOperation, ValueError):
        return сырое


def строки_бланка(payload: dict) -> tuple[list[list[str]], Decimal]:
    строки: list[list[str]] = []
    итог = Decimal("0.00")
    источник = [*(payload.get("lines") or []), *(payload.get("services") or [])]
    for индекс, row in enumerate(источник, 1):
        if not isinstance(row, dict):
            continue
        сумма = _деньги(row, "amount", "Сумма")
        try:
            итог += Decimal(сумма or "0")
        except (InvalidOperation, ValueError):
            pass
        строки.append([
            str(индекс),
            _текст(row, "name", "Наименование", "НоменклатураНаименование"),
            _текст(row, "barcode", "ШтрихКод"),
            _текст(row, "unit", "Единица") or "шт",
            _число(row, "qty", "Количество", "qty_fact"),
            _деньги(row, "price", "Цена"),
            сумма,
            _текст(row, "vat_rate", "СтавкаНДС"),
            _деньги(row, "vat_amount", "СуммаНДС"),
        ])
    return строки, итог


def _ячейка(значение: str, число: bool) -> str:
    класс = ' class="num"' if число else ""
    return f"<td{класс}>{html.escape(значение)}</td>"


# бланки расхождения: по ним предъявляют претензию поставщику и проводят
# результат пересчёта. Пустыми не печатаются — пустой акт хуже отсутствующего.
БЛАНКИ_РАСХОЖДЕНИЯ = {
    "purchase": ("ТОРГ-2", "0330202",
                 "Акт об установленном расхождении по количеству и качеству "
                 "при приёмке товарно-материальных ценностей",
                 ("Председатель комиссии", "Член комиссии", "Представитель поставщика")),
    "inventory": ("ИНВ-19", "0317017",
                  "Сличительная ведомость результатов инвентаризации "
                  "товарно-материальных ценностей",
                  ("Главный (старший) бухгалтер", "Материально ответственное лицо")),
}

КОЛОНКИ_РАСХОЖДЕНИЯ = ("№", "Наименование", "Штрихкод", "Ед. изм.",
                       "Цена, руб. коп.", "По документу / по учёту",
                       "Фактически", "Отклонение", "Отклонение, сумма")


def _decimal(значение: object) -> Decimal:
    try:
        return Decimal(str(значение or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def строки_расхождения(payload: dict) -> tuple[list[list[str]], Decimal]:
    """Только позиции, где ожидание разошлось с фактом."""
    строки: list[list[str]] = []
    итог = Decimal("0.00")
    номер = 0
    for row in payload.get("lines") or []:
        if not isinstance(row, dict):
            continue
        ожидалось = _decimal(_текст(row, "qty_expected", "КоличествоЗаявлено",
                                    "КоличествоУчет"))
        факт = _decimal(_текст(row, "qty", "Количество", "qty_fact"))
        if ожидалось == факт:
            continue
        номер += 1
        цена = _decimal(_текст(row, "price", "Цена"))
        отклонение = факт - ожидалось
        сумма = (отклонение * цена).quantize(Decimal("0.01"))
        итог += сумма
        строки.append([
            str(номер),
            _текст(row, "name", "Наименование"),
            _текст(row, "barcode", "ШтрихКод"),
            _текст(row, "unit", "Единица") or "шт",
            f"{цена.quantize(Decimal('0.01'))}",
            f"{ожидалось.normalize():f}",
            f"{факт.normalize():f}",
            f"{отклонение.normalize():f}",
            f"{сумма}",
        ])
    return строки, итог


def _форма_расхождения(
    row: StoreDocumentProjection, payload: dict, *, компания: str = "",
) -> str | None:
    """ТОРГ-2 для приёмки и ИНВ-19 для пересчёта — только по расходящимся строкам."""
    if row.document_kind not in БЛАНКИ_РАСХОЖДЕНИЯ:
        return None
    строки, итог = строки_расхождения(payload)
    if not строки:
        return None
    бланк, окуд, название, подписи = БЛАНКИ_РАСХОЖДЕНИЯ[row.document_kind]
    основание = ("Акт является основанием для предъявления претензии поставщику."
                 if row.document_kind == "purchase"
                 else "Ведомость составляется только по позициям с расхождением.")
    return _рендер_бланка(
        row, бланк=бланк, окуд=окуд, название=название, подписи=подписи,
        колонки=КОЛОНКИ_РАСХОЖДЕНИЯ, строки=строки, итог=итог,
        итог_подпись="Итого отклонение", компания=компания, основание=основание,
        текстовые=(1, 2, 3),
    )


def печатная_форма(
    row: StoreDocumentProjection, payload: dict, *, компания: str = "",
    вариант: str = "main",
) -> str | None:
    """HTML печатной формы или None, если у вида бланка нет."""
    if вариант == "diff":
        return _форма_расхождения(row, payload, компания=компания)
    if row.document_kind in БЕЗ_БЛАНКА or row.document_kind not in БЛАНКИ:
        return None
    бланк, окуд, название, подписи = БЛАНКИ[row.document_kind]
    строки, итог_строк = строки_бланка(payload)
    итог = Decimal(str(row.amount or 0)).quantize(Decimal("0.01"))
    if not итог and итог_строк:
        итог = итог_строк
    return _рендер_бланка(
        row, бланк=бланк, окуд=окуд, название=название, подписи=подписи,
        колонки=КОЛОНКИ, строки=строки, итог=итог,
        итог_подпись="Всего по документу", компания=компания,
        текстовые=(1, 2, 3, 7),
    )


def _рендер_бланка(
    row: StoreDocumentProjection, *, бланк: str, окуд: str, название: str,
    подписи: tuple[str, ...], колонки: tuple[str, ...], строки: list[list[str]],
    итог: Decimal, итог_подпись: str, компания: str, текстовые: tuple[int, ...],
    основание: str = "",
) -> str:
    заголовок = "".join(
        f'<th{" class=\"num\"" if index not in текстовые and index else ""}>'
        f"{html.escape(колонка)}</th>"
        for index, колонка in enumerate(колонки)
    )
    графы = "".join(f"<td>{index}</td>" for index in range(1, len(колонки) + 1))
    тело = "".join(
        "<tr>" + "".join(
            _ячейка(значение, индекс not in текстовые)
            for индекс, значение in enumerate(ячейки)
        ) + "</tr>"
        for ячейки in строки
    ) or f'<tr><td colspan="{len(колонки)}">Строк нет</td></tr>'
    реквизиты = [
        ("Станция", f"АЗС {row.station_id}" if row.station_id else "Центральный склад"),
        ("Контрагент", row.counterparty_name or "—"),
        ("ИНН", row.counterparty_inn or "—"),
        ("Склад / направление", str((row.header or {}).get("warehouse") or "—")),
    ]
    if (row.header or {}).get("incoming_number"):
        реквизиты.append(("Документ поставщика", str(row.header["incoming_number"])))
    мета = "".join(
        f"<dt>{html.escape(подпись)}:</dt><dd>{html.escape(str(значение))}</dd>"
        for подпись, значение in реквизиты
    )
    подписи_html = "".join(
        f'<div><div class="line"></div><small>{html.escape(роль)} — подпись, '
        "расшифровка</small></div>" for роль in подписи
    )
    дата = row.document_at.strftime("%d.%m.%Y") if isinstance(
        row.document_at, datetime) else ""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>{html.escape(бланк)} № {html.escape(row.number or "")}</title>
<style>
body{{font:12px/1.4 Arial,sans-serif;color:#000;background:#fff;margin:20px}}
.blank{{display:flex;justify-content:flex-end;font-size:10px}}
.blank td{{border:1px solid #000;padding:2px 6px}}
h1{{font-size:16px;margin:10px 0 2px;text-align:center}}
.sub{{text-align:center;margin-bottom:12px}}
.org div{{border-bottom:1px solid #000;padding:2px 0;margin-bottom:2px}}
.org small{{color:#444;font-size:10px}}
dl.meta{{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:10px 0 12px}}
dl.meta dd{{margin:0;font-weight:bold}}
table.doc{{border-collapse:collapse;width:100%;font-size:11px}}
table.doc th,table.doc td{{border:1px solid #000;padding:4px 6px;vertical-align:top}}
table.doc th{{background:#f0f0f0;text-align:left}}
table.doc tr.graphs td{{text-align:center;font-size:9px;color:#555;padding:1px}}
table.doc td.num,table.doc th.num{{text-align:right;white-space:nowrap}}
tfoot td{{font-weight:bold;background:#f6f6f6}}
.words{{margin:10px 0;border-bottom:1px solid #000;padding-bottom:2px}}
.words small{{display:block;color:#444;font-size:10px;font-weight:normal}}
.note{{margin:10px 0;padding:6px 8px;border:1px solid #999;background:#fafafa}}
.signs{{margin-top:26px;display:flex;flex-wrap:wrap;gap:26px}}
.signs div{{flex:1 1 30%;min-width:190px}}
.signs .line{{border-bottom:1px solid #000;height:20px;margin-bottom:2px}}
.signs small{{font-size:10px}}
@media print{{body{{margin:8mm}}.noprint{{display:none}}}}
</style></head><body>
<div class="noprint" style="margin-bottom:12px">
  <button onclick="window.print()" style="font:13px Arial;padding:6px 14px">Печать</button>
</div>
<div class="blank"><table>
  <tr><td>Форма по ОКУД</td><td>{html.escape(окуд)}</td></tr>
  <tr><td>Унифицированная форма</td><td>{html.escape(бланк)}</td></tr>
</table></div>
<div class="org">
  <div>{html.escape(компания)}<small> — организация</small></div>
</div>
<h1>{html.escape(название)}</h1>
<div class="sub">№ {html.escape(row.number or "б/н")} от {дата}</div>
<dl class="meta">{мета}</dl>
<table class="doc">
  <thead><tr>{заголовок}</tr><tr class="graphs">{графы}</tr></thead>
  <tbody>{тело}</tbody>
  <tfoot><tr><td colspan="{len(колонки) - 1}">{html.escape(итог_подпись)}</td>
    <td class="num">{итог}</td></tr></tfoot>
</table>
<p class="words">{html.escape(сумма_прописью(итог))}<small>сумма прописью</small></p>
{f'<div class="note">{html.escape(основание)}</div>' if основание else ""}
<div class="signs">{подписи_html}</div>
</body></html>"""
