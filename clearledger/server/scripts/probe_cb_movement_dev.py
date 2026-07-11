"""
DEV Этап-0 probe: инвентаризация складского контура ЦБ ЭЛСИ.АЗК (локальная копия, COM).

Цель — заменить «❓» в STORE_MOVEMENT_BLUEPRINT (gap 208) фактами:
  - какие ДОКУМЕНТЫ товародвижения реально существуют в конфигурации;
  - какие РЕГИСТРЫ НАКОПЛЕНИЯ товара (остатки/партии) и РЕГИСТРЫ СВЕДЕНИЙ цен есть;
  - сколько записей у документов-кандидатов (движение реально ведётся или пусто);
  - структура шапки найденных документов движения (реквизиты).

Ничего не пишет в 1С (read-only). Пароль/база — из ext-cb-msn/scripts/secrets.json.
Запуск (из server/):  py -3.13 scripts/probe_cb_movement_dev.py
Внешний скрипт — любой Python; COM-воркер сам поднимается в 32-бит (py -3.13-32).
"""
import asyncio
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.onec.com_client import OneCComClient  # noqa: E402

SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")

# Ключевые слова товародвижения — по ним раскладываем полный список документов.
MOVE_KEYWORDS = [
    "Поступлен", "Перемещен", "Инвентаризац", "Списан", "Оприходован",
    "Возврат", "Переоценк", "УстановкаЦен", "Розничн", "ОтчетОРозничных",
    "Комплектац", "Выпуск", "Производств", "ВводОстатк", "Реализац", "Корректировк",
]


def _bucket(name: str) -> str | None:
    low = name.lower()
    for kw in MOVE_KEYWORDS:
        if kw.lower() in low:
            return kw
    return None


async def main() -> None:
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'
    print(f"= ЦБ ЭЛСИ.АЗК probe (склад/движение) =\nБаза: {s['tsb_base']}\n")

    async with OneCComClient(conn) as client:
        # ── Регистры накопления (остатки/партии товара) ──
        accum = await client.metadata_accum_registers()
        tovar_accum = [r for r in accum if any(k in r for k in ("Товар", "Партии", "Остатк", "Склад"))]
        print(f"РЕГИСТРЫ НАКОПЛЕНИЯ: всего {len(accum)}; товарные ({len(tovar_accum)}):")
        for r in tovar_accum:
            print(f"   • {r}")
        print()

        # ── Регистры сведений (цены) ──
        price_ir = await client.metadata_registers("Цен")
        print(f"РЕГИСТРЫ СВЕДЕНИЙ (цены), найдено {len(price_ir)}:")
        for r in price_ir:
            print(f"   • {r}")
        print()

        # ── Документы: полный список → раскладка по товародвижению ──
        docs = await client.metadata_documents()
        print(f"ДОКУМЕНТЫ: всего в конфигурации {len(docs)}")
        move_docs = [d for d in docs if _bucket(d[len("Document_"):])]
        print(f"кандидаты товародвижения ({len(move_docs)}):\n")

        # ── По каждому кандидату: количество + шапка ──
        print(f"{'ДОКУМЕНТ':52} {'ЗАПИСЕЙ':>9}")
        print("-" * 64)
        found: list[dict] = []
        for d in sorted(move_docs):
            short = d[len("Document_"):]
            try:
                cnt = await client.count_entity(d)
            except Exception as e:  # noqa: BLE001
                print(f"{short:52} {'ошибка':>9}  ({type(e).__name__})")
                continue
            mark = "" if cnt else "  — пусто"
            print(f"{short:52} {cnt:>9}{mark}")
            if cnt:
                found.append({"entity": d, "name": short, "count": cnt})

        # ── Структура шапки непустых документов движения ──
        print("\n= СТРУКТУРА ШАПКИ НЕПУСТЫХ ДОКУМЕНТОВ =")
        for f in found:
            try:
                st = await client.describe_entity(f["entity"])
                attrs = ", ".join(st.get("attributes") or []) or "—"
                print(f"\n▸ {f['name']}  ({f['count']} зап.)\n   реквизиты: {attrs}")
            except Exception as e:  # noqa: BLE001
                print(f"\n▸ {f['name']}: describe ошибка — {type(e).__name__}: {e}")

    print("\n= probe завершён =")


if __name__ == "__main__":
    asyncio.run(main())
