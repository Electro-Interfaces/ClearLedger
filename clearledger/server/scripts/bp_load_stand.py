# -*- coding: utf-8 -*-
"""
Ф4/приёмка — загрузить пакет Ledger в БП-стенд GIG Base2 через COM
(TL_СопуткаСервис.ОбработатьПакетИзСтроки) и показать результат: статус,
созданные документы, ошибки, идемпотентность. Опция --provodki проводит
созданные ОРП+ПТУ и печатает проводки для сверки с эталонной моделью БП.

⚠ Запуск ТОЛЬКО в 32-битном Python (COM-коннектор 1С):
  py -3.13-32 scripts/bp_load_stand.py <пакет.json> [--provodki]

Пакет — из scripts/emit_shift_package_dev.py. Стенд непроведён (Проводить=Ложь),
проведение проводок — только по --provodki (spot-check на стенде).
Креды стенда — ext-cb-msn/scripts/secrets.json (bpgig_stand_*), НЕ в коде.
"""
import glob
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import win32com.client  # noqa: E402

SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")


def _conn_string():
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    return (f'File="{s["bpgig_stand_base"]}";'
            f'Usr="{s["bpgig_stand_user"]}";Pwd="{s["bpgig_stand_pwd"]}";')


def _проводки(v8, ссыл):
    q = v8.NewObject("Запрос")
    q.Текст = ("ВЫБРАТЬ Т.СчетДт.Код КАК Дт, Т.СчетКт.Код КАК Кт, Т.Сумма КАК Сум "
               "ИЗ РегистрБухгалтерии.Хозрасчетный КАК Т ГДЕ Т.Регистратор=&Р")
    q.УстановитьПараметр("Р", ссыл)
    r = q.Выполнить().Выбрать()
    ит = {}
    while r.Следующий():
        k = f"Дт {r.Дт or '—':<9} Кт {r.Кт or '—'}"
        ит[k] = ит.get(k, 0) + float(r.Сум or 0)
    return ит


def main():
    args = sys.argv[1:]
    провести = "--provodki" in args
    paths = [a for a in args if not a.startswith("--")]
    pattern = paths[0] if paths else "*.json"
    files = glob.glob(pattern)
    if not files:
        print(f"Не найден пакет по маске: {pattern}")
        return
    path = files[0]
    txt = Path(path).read_text(encoding="utf-8")
    J = json.loads(txt)
    pid = J.get("ИдентификаторПакета", "")
    print(f"Файл: {Path(path).name}\nИдентификаторПакета: {pid}  ХешПакета: {J.get('ХешПакета','')[:16]}…")

    v8 = win32com.client.Dispatch("V83.COMConnector").Connect(_conn_string())
    print("Коннект OK:", v8.Метаданные.Синоним)

    res = v8.TL_СопуткаСервис.ОбработатьПакетИзСтроки(txt, False)
    try:
        st = v8.XMLСтрока(res.Статус)
    except Exception:
        st = str(res.Статус)
    print(f"── Статус: {st} | ВсегоДокументов: {res.ВсегоДокументов} | ВсегоНСИ: {res.ВсегоНСИ}")
    if res.Ошибки.Количество():
        print(f"── Ошибок: {res.Ошибки.Количество()}")
        for i in range(min(res.Ошибки.Количество(), 30)):
            print("   ✗", res.Ошибки.Получить(i))

    # созданные документы по регистру идемпотентности
    q = v8.NewObject("Запрос")
    q.Текст = ("ВЫБРАТЬ Т.Тип КАК Тип, Т.СсылкаОбъект КАК С ИЗ РегистрСведений.TL_СоответствиеИсточников "
               "КАК Т ГДЕ Т.ИдентификаторПоследнегоПакета=&П")
    q.УстановитьПараметр("П", pid)
    s = q.Выполнить().Выбрать()
    ретейл = приход = None
    print("── Созданные документы:")
    while s.Следующий():
        имя = s.С.Метаданные().Имя
        print(f"   {str(s.Тип):26} → {имя} №{s.С.Номер}  проведён={s.С.Проведен}  сумма={getattr(s.С,'СуммаДокумента','?')}")
        if имя == "ОтчетОРозничныхПродажах" and not ретейл:
            ретейл = s.С
        if имя == "ПоступлениеТоваровУслуг" and not приход:
            приход = s.С

    if провести:
        ПР = v8.РежимЗаписиДокумента.Проведение
        for ссыл, метка in [(ретейл, "ОРП"), (приход, "ПТУ")]:
            if not ссыл:
                continue
            try:
                ссыл.ПолучитьОбъект().Записать(ПР)
                print(f"\n══ {метка} {ссыл.Номер} ПРОВЕДЁН, СуммаДок={ссыл.СуммаДокумента} ══")
                for k, v in sorted(_проводки(v8, ссыл).items(), key=lambda x: -abs(x[1])):
                    print(f"   {k}: {round(v, 2)}")
            except Exception as e:
                print(f"\n══ {метка} {ссыл.Номер}: НЕ проведён — {str(e)[:160]}")


if __name__ == "__main__":
    main()
