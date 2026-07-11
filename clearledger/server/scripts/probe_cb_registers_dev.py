"""
DEV Этап-1 probe: структура регистров остатков/партий ЦБ ЭЛСИ.АЗК (для pull остатка).
describe_entity → измерения/ресурсы/реквизиты. Read-only. Запуск (из server/):
  py -3.13 scripts/probe_cb_registers_dev.py
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

REGISTERS = [
    "AccumulationRegister_ТоварыНаСкладах",
    "AccumulationRegister_ТоварыОрганизаций",
    "AccumulationRegister_ПартииТоваровНаСкладах",
    "AccumulationRegister_НДСПартииТоваров",
    "AccumulationRegister_ТоварыНаАЗК",
]
# Документы движения — состав табличных частей (для маппинга колонок ТЧ).
DOC_TABULARS = {
    "Document_ПоступлениеТоваровУслугНаАЗК": "Товары",
    "Document_ПеремещениеТоваров": "Товары",
    "Document_ИнвентаризацияТоваровНаСкладе": "Товары",
    "Document_СписаниеТоваров": "Товары",
    "Document_ОприходованиеТоваров": "Товары",
    "Document_ПереоценкаТоваровАЗК": "Товары",
}


async def main() -> None:
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'
    print("= Структура регистров остатков/партий =\n")

    async with OneCComClient(conn) as client:
        for reg in REGISTERS:
            try:
                st = await client.describe_entity(reg)
                print(f"▸ {reg[len('AccumulationRegister_'):]}")
                print(f"   измерения: {', '.join(st.get('dimensions') or []) or '—'}")
                print(f"   ресурсы:   {', '.join(st.get('resources') or []) or '—'}")
                print(f"   реквизиты: {', '.join(st.get('attributes') or []) or '—'}\n")
            except Exception as e:  # noqa: BLE001
                print(f"▸ {reg}: ошибка — {type(e).__name__}: {e}\n")

        print("= Реквизиты шапки документов движения (для доп. полей) =")
        for doc in DOC_TABULARS:
            try:
                st = await client.describe_entity(doc)
                print(f"\n▸ {doc[len('Document_'):]}  реквизиты: {', '.join(st.get('attributes') or []) or '—'}")
            except Exception as e:  # noqa: BLE001
                print(f"\n▸ {doc}: ошибка — {type(e).__name__}: {e}")

    print("\n= probe завершён =")


if __name__ == "__main__":
    asyncio.run(main())
