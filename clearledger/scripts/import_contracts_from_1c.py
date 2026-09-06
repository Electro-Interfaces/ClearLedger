# -*- coding: utf-8 -*-
"""Разовый импорт договоров с поставщиками из ЦБ ЭЛСИ.АЗК в центр.

Договор — основание прихода: по нему бухгалтерия ведёт расчёты с поставщиком.
В центре он живёт в канонической таблице `contracts` — той самой, из которой его
берёт выгрузка в бухгалтерию (`services/bp_export.py`): у документа стоит UUID
договора, и если канонической записи нет, документ в БП не уходит вовсе.
Отсюда правило: второй, «станционной», таблицы договоров быть не должно.

Два шага, потому что 1С и база пространства стоят в разных местах:

    py -3.13-32 import_contracts_from_1c.py dump --pwd ... --out contracts.json
    py          import_contracts_from_1c.py sql  --in contracts.json
                --company <uuid> --out contracts.sql

`dump` читает боевую ЦБ через V83.COMConnector — только чтение и только
32-битным Python: коннектор зарегистрирован как x86. `sql` собирает
идемпотентный INSERT: контрагент ищется по ИНН, организация — по ИНН
организации. Не нашлись — строка пропускается и попадает в отчёт: договор без
контрагента станции всё равно не показать.

⚠ Сопоставление по ИНН, а не по имени: в ЦБ справочник контрагентов «грязный»,
одно юрлицо встречается под несколькими написаниями.

⚠ Это разовый перенос истории. Постоянный источник договоров — 1С:Бухгалтерия,
там их ведут; импорт оттуда делается отдельно.
"""
from __future__ import annotations

import argparse
import io
import json
import sys

ЦБ = 'Srvr="SQL1";Ref="azs_centre";Usr="Elsy";Pwd="{pwd}";'

ЗАПРОС = """
ВЫБРАТЬ Д.Ссылка КАК Ссылка, Д.Наименование КАК Имя, Д.Номер КАК Номер,
        Д.Дата КАК Дата, Д.Владелец.Наименование КАК Контрагент,
        Д.Владелец.ИНН КАК ИНН, Д.Владелец.КПП КАК КПП,
        Д.Организация.Наименование КАК Орг, Д.Организация.ИНН КАК ОргИНН
  ИЗ Справочник.ДоговорыКонтрагентов КАК Д
 ГДЕ Д.ВидДоговора = ЗНАЧЕНИЕ(Перечисление.ВидыДоговоровКонтрагентов.СПоставщиком)
   И НЕ Д.ПометкаУдаления
 УПОРЯДОЧИТЬ ПО Контрагент, Имя
"""


def dump(args) -> int:
    import win32com.client

    conn = win32com.client.Dispatch("V83.COMConnector").Connect(ЦБ.format(pwd=args.pwd))
    выборка = conn.NewObject("Запрос", ЗАПРОС).Выполнить().Выбрать()
    out = []
    while выборка.Следующий():
        дата = выборка.Дата
        out.append({
            # UUID берём через conn.String: str() над COM-значением отдаёт
            # «<COMObject <unknown>>» и молча портит весь импорт.
            "uuid": conn.String(выборка.Ссылка.УникальныйИдентификатор()),
            "name": (выборка.Имя or "").strip(),
            "number": (выборка.Номер or "").strip(),
            "signed_on": дата.strftime("%Y-%m-%d") if дата and дата.year > 1900 else "",
            "partner_name": (выборка.Контрагент or "").strip(),
            "partner_inn": только_цифры(выборка.ИНН),
            "partner_kpp": (выборка.КПП or "").strip(),
            "org_name": (выборка.Орг or "").strip(),
            "org_inn": только_цифры(выборка.ОргИНН),
        })
    io.open(args.out, "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print("выгружено договоров: %d -> %s" % (len(out), args.out))
    орг: dict[str, int] = {}
    for c in out:
        орг[c["org_name"]] = орг.get(c["org_name"], 0) + 1
    for имя, n in sorted(орг.items(), key=lambda kv: -kv[1]):
        print("  %s: %d" % (имя or "<без организации>", n))
    return 0


def sql(args) -> int:
    данные = json.loads(io.open(args.inp, encoding="utf-8").read())
    if getattr(args, "org_inn", ""):
        # Организация-владелец решает, чей это договор: у одного поставщика в ЦБ
        # живут договоры на старое юрлицо (Норд-Лайн) и на новое (ГИГ), и брать
        # чужие нельзя — приход уедет в расчёты не с тем.
        данные = [c for c in данные if c["org_inn"] == args.org_inn]
    строки: list[str] = []
    пропущено = 0
    for c in данные:
        if not c["name"] or not c["partner_inn"]:
            пропущено += 1
            continue
        # Контрагента и организацию ищем по ИНН прямо в запросе: импорт остаётся
        # одним файлом и переживает повторный запуск. Договор либо привяжется,
        # либо тихо пропустится — кривой строки в справочнике не появится.
        строки.append("\n".join([
            "INSERT INTO core.contracts",
            "  (id, company_id, number, date, title, counterparty_id, organization_id,",
            "   type, kind, currency, external_ref, raw)",
            "SELECT %s::uuid, %s::uuid," % (кав(c["uuid"]), кав(args.company)),
            "       %s, %s, %s," % (кав(c["number"] or c["name"]),
                                    кав(c["signed_on"]), кав(c["name"])),
            "       cp.id, o.id, 'поставка', 'СПоставщиком', 'RUB', %s," % кав(c["uuid"]),
            "       jsonb_build_object('source','1c_cb','name',%s)" % кав(c["name"]),
            "  FROM core.counterparties cp",
            "  LEFT JOIN core.organizations o",
            "         ON o.company_id = cp.company_id",
            "        AND %s = %s" % (цифры("o.inn"), кав(c["org_inn"])),
            " WHERE cp.company_id = %s::uuid" % кав(args.company),
            "   AND %s = %s" % (цифры("cp.inn"), кав(c["partner_inn"])),
            # Повторный запуск не должен плодить двойников. Ключ узнавания —
            # external_ref (UUID договора в 1С), а НЕ id: часть договоров была
            # заведена в центре раньше, своими идентификаторами, и «ON CONFLICT
            # (id)» их не видел — импорт создал бы вторые экземпляры тех же
            # договоров у тех же поставщиков.
            "   AND NOT EXISTS (SELECT 1 FROM core.contracts x",
            "                    WHERE x.company_id = %s::uuid" % кав(args.company),
            "                      AND x.external_ref = %s)" % кав(c["uuid"]),
            "   AND NOT EXISTS (SELECT 1 FROM core.contracts y",
            "                    WHERE y.company_id = %s::uuid" % кав(args.company),
            "                      AND y.counterparty_id = cp.id",
            "                      AND y.organization_id = o.id",
            "                      AND y.number = %s);" % кав(c["number"] or c["name"]),
        ]))
    io.open(args.out, "w", encoding="utf-8").write("\n\n".join(строки) + "\n")
    print("договоров в SQL: %d из %d -> %s" % (len(строки), len(данные), args.out))
    if пропущено:
        print("пропущено без ИНН контрагента: %d — сопоставлять нечем" % пропущено)
    print("выполнить в базе пространства: psql -f %s" % args.out)
    return 0


def только_цифры(v) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def кав(v: str) -> str:
    return "'" + (v or "").replace("'", "''") + "'"


def цифры(поле: str) -> str:
    """Только цифры ИНН: в 1С он встречается с пробелами и дефисами."""
    return "regexp_replace(coalesce(%s,''), '[^0-9]', '', 'g')" % поле


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump", help="прочитать договоры из ЦБ (32-битный Python)")
    d.add_argument("--out", default="contracts.json")
    d.add_argument("--pwd", required=True, help="пароль учётки чтения ЦБ")
    d.set_defaults(func=dump)
    q = sub.add_parser("sql", help="собрать SQL для базы пространства")
    q.add_argument("--in", dest="inp", default="contracts.json")
    q.add_argument("--out", default="contracts.sql")
    q.add_argument("--company", required=True, help="UUID компании в центре")
    q.add_argument("--org-inn", default="", help="брать только договоры этой организации (ИНН)")
    q.set_defaults(func=sql)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(main())
