"""
DEV: настроить подключение Source `onec_operational` (ЦБ ЭЛСИ.АЗК) компании gig
на ЛОКАЛЬНУЮ копию ЦБ `TsB_Live_20260429` (файловая база, COM-subprocess 32-бит),
чтобы каналы sidegoods/food читали сопутку/общепит по ст. 208.

Пароль АдминистраторАЗК читается из ext-cb-msn/scripts/secrets.json (gitignored) —
в этот скрипт не хардкодится. Шифруется Fernet-ключом backend (SECRET_KEY из .env),
чтобы orchestrator._decrypt_pwd мог его расшифровать.

Запуск (из каталога server/):  py -3 scripts/configure_cb_source_dev.py
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

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import Source, SourceCredentials  # noqa: E402
from app.services.onec.crypto import encrypt_password  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")


async def main() -> None:
    if not SECRETS.exists():
        print(f"НЕТ secrets: {SECRETS}")
        return
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    base, user, pwd = s.get("tsb_base"), s.get("tsb_user"), s.get("tsb_pwd")
    if not (base and user and pwd) or "ВСТАВИТЬ" in str(pwd):
        print("secrets.json: заполните tsb_base/tsb_user/tsb_pwd")
        return
    conn_str = f'File="{base}"'

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        src = (await db.execute(select(Source).where(
            Source.company_id == cid, Source.source_type == "onec_operational",
        ))).scalar_one_or_none()
        if not src:
            print("НЕТ Source onec_operational — сначала запусти seed_gig_connections.py")
            return

        src.connection_config = {
            "configuration": "elsi_azk",
            "mode": "com",
            "connection_string": conn_str,
            "login": user,
            "default_station": "208",
        }
        src.status = "connected"
        await db.flush()

        cr = (await db.execute(select(SourceCredentials).where(
            SourceCredentials.source_id == src.id,
        ))).scalar_one_or_none()
        enc = {"password": encrypt_password(pwd)}
        if cr:
            cr.encrypted_values = enc
        else:
            db.add(SourceCredentials(source_id=src.id, encrypted_values=enc))

        await db.commit()
        print(f"OK: Source onec_operational [{src.id}]")
        print(f"    connection_string = {conn_str}")
        print(f"    login = {user}  ·  default_station = 208  ·  mode = com")
        print("    пароль зашифрован в SourceCredentials")


if __name__ == "__main__":
    asyncio.run(main())
