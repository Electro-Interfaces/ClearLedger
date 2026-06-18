"""
Выдать / отозвать доступ пользователя к компании (членство user_companies)
и/или назначить суперадмина.

Запуск (из каталога server):
    py -3 scripts/grant_company_access.py <email> <company_slug|uuid>
    py -3 scripts/grant_company_access.py <email> <company_slug|uuid> --revoke
    py -3 scripts/grant_company_access.py <email> --superadmin
    py -3 scripts/grant_company_access.py <email> <company> --superadmin

Примеры:
    py -3 scripts/grant_company_access.py ivan@gig.ru gig
    py -3 scripts/grant_company_access.py ivan@gig.ru rti --revoke
    py -3 scripts/grant_company_access.py admin@clearledger.ru --superadmin
"""
import argparse
import asyncio
import sys
from pathlib import Path

# консоль Windows = cp1251; принудительно UTF-8 для вывода с кириллицей
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# чтобы `import app...` работал при запуске из server/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import Company, User, UserCompany  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402


async def main(email: str, company_ref: str | None, revoke: bool, make_super: bool) -> int:
    async with async_session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            print(f"✗ Пользователь не найден: {email}")
            return 1

        if make_super:
            user.is_superadmin = True
            print(f"✓ {email} → суперадмин (доступ ко всем компаниям)")

        if company_ref:
            cid = await resolve_company_id(company_ref, db)
            comp = await db.get(Company, cid)
            label = f"{comp.name} ({comp.slug})" if comp else str(cid)
            existing = await db.get(UserCompany, (user.id, cid))
            if revoke:
                if existing:
                    await db.execute(
                        delete(UserCompany).where(
                            UserCompany.user_id == user.id,
                            UserCompany.company_id == cid,
                        )
                    )
                    print(f"✓ Доступ отозван: {email} ✗ {label}")
                else:
                    print(f"· Членства не было: {email} / {label}")
            else:
                if existing:
                    print(f"· Доступ уже есть: {email} / {label}")
                else:
                    db.add(UserCompany(user_id=user.id, company_id=cid))
                    print(f"✓ Доступ выдан: {email} → {label}")

        await db.commit()

        # Итог: текущие компании пользователя.
        rows = (
            await db.execute(
                select(Company.slug)
                .join(UserCompany, UserCompany.company_id == Company.id)
                .where(UserCompany.user_id == user.id)
                .order_by(Company.slug)
            )
        ).scalars().all()
        super_note = " + суперадмин (все)" if user.is_superadmin else ""
        print(f"  Членство {email}: {', '.join(rows) or '—'}{super_note}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Выдать/отозвать доступ к компании")
    ap.add_argument("email")
    ap.add_argument("company", nargs="?", default=None, help="slug или UUID компании")
    ap.add_argument("--revoke", action="store_true", help="отозвать доступ")
    ap.add_argument("--superadmin", action="store_true", help="назначить суперадмином")
    args = ap.parse_args()
    if not args.company and not args.superadmin:
        ap.error("укажите компанию или --superadmin")
    raise SystemExit(asyncio.run(main(args.email, args.company, args.revoke, args.superadmin)))
