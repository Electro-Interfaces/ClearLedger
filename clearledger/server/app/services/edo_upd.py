"""Разбор входящего УПД (универсального передаточного документа).

Формат ФНС — XML с латинскими именами элементов и русскими атрибутами:
`Документ` → `СвСчФакт` (шапка: продавец, номер, дата) → `ТаблСчФакт` →
`СведТов` (строки: наименование, количество, цена, сумма, НДС). Коды маркировки
живут в `НомСредИдентТов` внутри строки — либо поштучно (`КИЗ`), либо
агрегатами (`НомУпак`).

Разбор намеренно снисходительный: операторы ЭДО и учётные системы поставщиков
кладут одни и те же данные в разные места, и падать на первом неожиданном теге
нельзя — приёмка встанет. Чего не поняли, отдаём человеку в исходном виде.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET


def _text(el, *names: str) -> str:
    """Первый непустой атрибут из перечисленных."""
    for n in names:
        v = (el.get(n) or "").strip()
        if v:
            return v
    return ""


def _num(v: str) -> float:
    try:
        return float(v.replace(",", ".").replace(" ", ""))
    except (ValueError, AttributeError):
        return 0.0


def _find_all(root, tag: str):
    """Поиск по имени тега без учёта пространства имён.

    В боевых файлах namespace то есть, то нет, и жёсткий путь ломается на
    первом же поставщике с другой учётной системой.
    """
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag:
            yield el


def parse_upd(raw: bytes) -> dict:
    """Разобрать XML УПД в заготовку приёмки.

    Возвращает шапку и строки в терминах нашего документа приёмки: заявленное
    количество, цена, штрихкод, коды маркировки. Фактическое количество не
    заполняется никогда — его ставит приёмщик, пересчитав товар.
    """
    # Кодировка объявлена в самом файле; windows-1251 в УПД встречается чаще,
    # чем хотелось бы, и ElementTree разбирает её сам по декларации.
    root = ET.fromstring(raw)

    seller = ""
    for el in _find_all(root, "СвПрод"):
        for org in el.iter():
            name = _text(org, "НаимОрг", "Наим")
            if name:
                seller = name
                break
        if seller:
            break

    number, date = "", ""
    for el in _find_all(root, "СвСчФакт"):
        number = _text(el, "НомерСчФ", "НомерДок")
        date = _text(el, "ДатаСчФ", "ДатаДок")
        break

    lines: list[dict] = []
    for tov in _find_all(root, "СведТов"):
        name = _text(tov, "НаимТов")
        qty = _num(_text(tov, "КолТов"))
        price = _num(_text(tov, "ЦенаТов"))
        amount = _num(_text(tov, "СтТовБезНДС", "СтТовУчНал"))
        vat = ""
        for nds in tov.iter():
            if nds.tag.rsplit("}", 1)[-1] == "СумНал":
                continue
            v = _text(nds, "НалСт")
            if v:
                vat = v
                break

        # Коды маркировки: поштучные КИЗ и агрегаты (короба). Агрегат — это не
        # экземпляр, а упаковка; принимать по нему поштучно нельзя, поэтому
        # держим отдельно и честно показываем приёмщику.
        codes: list[str] = []
        packs: list[str] = []
        for ident in tov.iter():
            tag = ident.tag.rsplit("}", 1)[-1]
            if tag == "КИЗ":
                val = (ident.text or "").strip() or _text(ident, "КИЗ")
                if val:
                    codes.append(val)
            elif tag == "НомУпак":
                val = (ident.text or "").strip() or _text(ident, "НомУпак")
                if val:
                    packs.append(val)

        barcode = _text(tov, "ШтрихКод", "Артикул")
        if name or qty:
            lines.append({
                "name": name,
                "barcode": barcode,
                "qty_expected": qty,
                "qty_fact": 0,          # ставит приёмщик, пересчитав товар
                "price": price,
                "amount": amount,
                "vat_rate": vat,
                "mark_codes": codes,
                "pack_codes": packs,
            })

    return {
        "supplier": seller,
        "incoming_number": number,
        "incoming_date": date,
        "lines": lines,
        "marked_lines": sum(1 for l in lines if l["mark_codes"]),
        "total_codes": sum(len(l["mark_codes"]) for l in lines),
    }
