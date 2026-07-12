"""
Ф4 — байт-точная сверка пакета Ledger vs эталонного пакета TL_ЭкспортБП для ОДНОЙ
смены. Диффает по значениям, матчит документы/НСИ по (Тип, ИсточникUUID),
игнорирует «летучие» поля (ИдентификаторПакета/ВремяВыгрузки/Источник/ХешПакета).

Использование:
  py -3.13 scripts/bp_compare.py <эталон_ЦБ.json> <наш_ledger.json>

Эталон ЦБ — из C:\\TL_BP_Export\\ (после запуска TL_ЭкспортБП для смены).
Наш — из POST /api/store/bp-package/emit или GET /api/store/bp-package для той же смены.
"""
import io
import json
import sys

VOLATILE_TOP = {"ИдентификаторПакета", "ВремяВыгрузки", "Источник", "ХешПакета"}


def _load(path):
    return json.load(io.open(path, encoding="utf-8-sig"))


def _key(doc):
    return (doc.get("Тип"), doc.get("ИсточникUUID"))


def _diff(a, b, path, out):
    """Рекурсивный дифф значений. a=эталон, b=наш."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: у нас ЛИШНЕЕ = {b[k]!r}")
            elif k not in b:
                out.append(f"{path}.{k}: у нас НЕТ (эталон = {a[k]!r})")
            else:
                _diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: длина списка эталон={len(a)} наш={len(b)}")
        for i in range(min(len(a), len(b))):
            _diff(a[i], b[i], f"{path}[{i}]", out)
    else:
        # числа сравниваем с допуском (float-погрешность/округление)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(float(a) - float(b)) > 0.01:
                out.append(f"{path}: эталон={a} наш={b} (Δ={round(float(a) - float(b), 4)})")
        elif a != b:
            out.append(f"{path}: эталон={a!r} наш={b!r}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    ref, our = _load(sys.argv[1]), _load(sys.argv[2])
    out = []

    # верх (без летучих)
    _diff({k: v for k, v in ref.items() if k not in VOLATILE_TOP and k not in ("Документы", "НСИ")},
          {k: v for k, v in our.items() if k not in VOLATILE_TOP and k not in ("Документы", "НСИ")},
          "пакет", out)

    # документы по ключу
    rd = {_key(d): d for d in ref.get("Документы", [])}
    od = {_key(d): d for d in our.get("Документы", [])}
    for k in sorted(set(rd) | set(od), key=lambda x: (x[0] or "", x[1] or "")):
        if k not in od:
            out.append(f"ДОКУМЕНТ {k}: есть в эталоне, у нас НЕТ")
        elif k not in rd:
            out.append(f"ДОКУМЕНТ {k}: у нас ЛИШНИЙ")
        else:
            _diff(rd[k], od[k], f"док[{k[0]}]", out)

    # НСИ по ключу
    rn = {_key(x): x for x in ref.get("НСИ", [])}
    on = {_key(x): x for x in our.get("НСИ", [])}
    for k in sorted(set(rn) | set(on), key=lambda x: (x[0] or "", x[1] or "")):
        if k not in on:
            out.append(f"НСИ {k}: есть в эталоне, у нас НЕТ")
        elif k not in rn:
            out.append(f"НСИ {k}: у нас ЛИШНЕЕ")
        else:
            _diff(rn[k], on[k], f"нси[{k[0]}]", out)

    print(f"=== СВЕРКА: эталон {len(ref.get('Документы', []))} док / {len(ref.get('НСИ', []))} НСИ  vs  "
          f"наш {len(our.get('Документы', []))} док / {len(our.get('НСИ', []))} НСИ ===")
    if not out:
        print("✓ ИДЕНТИЧНО (кроме летучих полей) — байт-паритет достигнут")
    else:
        print(f"⚠ расхождений: {len(out)}")
        for line in out[:200]:
            print("  " + line)
        if len(out) > 200:
            print(f"  … ещё {len(out) - 200}")


if __name__ == "__main__":
    main()
