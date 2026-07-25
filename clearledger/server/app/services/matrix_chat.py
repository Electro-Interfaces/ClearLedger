"""Доменный слой чата экосистемы (модель Ангара: плоская, провижининг Admin API).

Группы = именованные приватные комнаты + `MatrixGroupRoom`; личка = упорядоченная пара
пользователей → 1 комната (`MatrixDmRoom`); папки = клиентская группировка (`MatrixChatFolder`).
Всё, кроме идентичности user→mxid, скоупится по компании (Ур. 2). Темы (threads) — на
клиенте через `m.thread`, отдельной серверной сущности не требуют.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (Counterparty, MatrixChatFolder, MatrixDmRoom, MatrixGroupRoom,
                        MatrixIdentity, User, UserCompany)
from app.services import matrix_admin as ma


# ── идентичность и сессия ──

async def ensure_matrix_account(db: AsyncSession, user: User) -> str:
    """Идемпотентно завести Matrix-аккаунт пользователя, вернуть mxid (фиксируется навсегда)."""
    rec = (await db.execute(select(MatrixIdentity).where(
        MatrixIdentity.user_id == user.id))).scalar_one_or_none()
    if rec is not None:
        return rec.mxid
    mxid = ma.mxid_for(user.id)
    await ma.admin_upsert_user(mxid, getattr(user, "name", None))
    db.add(MatrixIdentity(user_id=user.id, mxid=mxid))
    try:
        await db.commit()
    except Exception:  # noqa: BLE001 — гонка: перечитать существующую привязку
        await db.rollback()
        rec = (await db.execute(select(MatrixIdentity).where(
            MatrixIdentity.user_id == user.id))).scalar_one_or_none()
        if rec is not None:
            return rec.mxid
        raise
    return mxid


async def issue_session(db: AsyncSession, user: User) -> dict[str, str]:
    """Сессия для браузерного matrix-js-sdk: публичный homeserver + mxid + свежий токен."""
    mxid = await ensure_matrix_account(db, user)
    token = await ma.get_user_login_token(mxid)
    return {"homeserver": ma.public_homeserver(), "userId": mxid, "accessToken": token}


async def _mxid_of(db: AsyncSession, user_id) -> str | None:
    rec = (await db.execute(select(MatrixIdentity).where(
        MatrixIdentity.user_id == user_id))).scalar_one_or_none()
    return rec.mxid if rec else None


# ── группы ──

async def create_group_room(db: AsyncSession, company_id, owner: User,
                            title: str, participant_ids: list, is_public: bool = False) -> dict[str, Any]:
    """Создать групповой чат: комната + владелец PL100 + участники force-join."""
    owner_mxid = await ensure_matrix_account(db, owner)
    final_title = (title or "").strip()[:120] or "Группа"
    room_id = await ma.create_room(name=final_title, topic="Групповой чат", is_public=is_public)
    await ma.force_join(room_id, owner_mxid)
    await ma.set_user_power(room_id, owner_mxid, 100)
    for uid in participant_ids:
        u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if u is None or u.id == owner.id:
            continue
        mxid = await ensure_matrix_account(db, u)
        await ma.force_join(room_id, mxid)
    db.add(MatrixGroupRoom(company_id=company_id, room_id=room_id, owner_id=owner.id,
                           title=final_title, is_public=is_public))
    await db.commit()
    return {"roomId": room_id, "title": final_title, "isPublic": is_public}


async def list_my_group_rooms(db: AsyncSession, company_id, user: User) -> list[dict[str, Any]]:
    """Группы пользователя в компании (владелец или участник по mxid)."""
    rooms = (await db.execute(select(MatrixGroupRoom).where(
        MatrixGroupRoom.company_id == company_id).order_by(MatrixGroupRoom.created_at.desc()))).scalars().all()
    mxid = await _mxid_of(db, user.id)
    out: list[dict[str, Any]] = []
    for g in rooms:
        if g.owner_id == user.id:
            out.append(_group_dto(g))
            continue
        if mxid:
            try:
                if mxid in await ma.get_joined_members(g.room_id):
                    out.append(_group_dto(g))
            except Exception:  # noqa: BLE001 — комната недоступна, пропускаем
                pass
    return out


def _group_dto(g: MatrixGroupRoom) -> dict[str, Any]:
    return {"roomId": g.room_id, "title": g.title, "ownerId": str(g.owner_id), "isPublic": g.is_public}


async def list_public_rooms(db: AsyncSession, company_id) -> list[dict[str, Any]]:
    rooms = (await db.execute(select(MatrixGroupRoom).where(
        MatrixGroupRoom.company_id == company_id, MatrixGroupRoom.is_public.is_(True))
        .order_by(MatrixGroupRoom.created_at.desc()).limit(100))).scalars().all()
    return [_group_dto(g) for g in rooms]


async def join_public_room(db: AsyncSession, company_id, user: User, room_id: str) -> None:
    g = (await db.execute(select(MatrixGroupRoom).where(
        MatrixGroupRoom.company_id == company_id, MatrixGroupRoom.room_id == room_id,
        MatrixGroupRoom.is_public.is_(True)))).scalar_one_or_none()
    if g is None:
        raise ValueError("Публичная комната не найдена")
    mxid = await ensure_matrix_account(db, user)
    await ma.force_join(room_id, mxid)


# ── личные сообщения ──

async def ensure_dm_room(db: AsyncSession, company_id, me: User, other_id) -> str:
    """Одна комната на упорядоченную пару пользователей в компании."""
    a, b = sorted([str(me.id), str(other_id)])
    rec = (await db.execute(select(MatrixDmRoom).where(
        MatrixDmRoom.company_id == company_id,
        MatrixDmRoom.user_a_id == a, MatrixDmRoom.user_b_id == b))).scalar_one_or_none()
    if rec is not None:
        return rec.room_id
    other = (await db.execute(select(User).where(User.id == other_id))).scalar_one_or_none()
    if other is None:
        raise ValueError("Пользователь не найден")
    me_mx = await ensure_matrix_account(db, me)
    other_mx = await ensure_matrix_account(db, other)
    room_id = await ma.create_room(topic="Личные сообщения", is_direct=True)
    await ma.force_join(room_id, me_mx)
    await ma.force_join(room_id, other_mx)
    db.add(MatrixDmRoom(company_id=company_id, user_a_id=a, user_b_id=b, room_id=room_id))
    await db.commit()
    return room_id


# ── папки ──

async def list_folders(db: AsyncSession, company_id, user: User) -> list[dict[str, Any]]:
    rows = (await db.execute(select(MatrixChatFolder).where(
        MatrixChatFolder.company_id == company_id, MatrixChatFolder.user_id == user.id)
        .order_by(MatrixChatFolder.sort))).scalars().all()
    return [{"id": str(f.id), "name": f.name, "roomIds": list(f.room_ids or []), "order": f.sort} for f in rows]


async def create_folder(db: AsyncSession, company_id, user: User, name: str, room_ids: list) -> dict[str, Any]:
    cnt = len(await list_folders(db, company_id, user))
    f = MatrixChatFolder(company_id=company_id, user_id=user.id, name=(name or "").strip()[:40] or "Папка",
                   room_ids=list(room_ids or [])[:200], sort=cnt)
    db.add(f)
    await db.commit()
    return {"id": str(f.id), "name": f.name, "roomIds": list(f.room_ids or []), "order": f.sort}


async def update_folder(db: AsyncSession, company_id, user: User, folder_id,
                        name: str | None = None, room_ids: list | None = None) -> bool:
    f = (await db.execute(select(MatrixChatFolder).where(
        MatrixChatFolder.id == folder_id, MatrixChatFolder.company_id == company_id,
        MatrixChatFolder.user_id == user.id))).scalar_one_or_none()
    if f is None:
        return False
    if name is not None:
        f.name = name.strip()[:40] or f.name
    if room_ids is not None:
        f.room_ids = list(room_ids)[:200]
    await db.commit()
    return True


async def delete_folder(db: AsyncSession, company_id, user: User, folder_id) -> bool:
    f = (await db.execute(select(MatrixChatFolder).where(
        MatrixChatFolder.id == folder_id, MatrixChatFolder.company_id == company_id,
        MatrixChatFolder.user_id == user.id))).scalar_one_or_none()
    if f is None:
        return False
    await db.delete(f)
    await db.commit()
    return True


async def reorder_folders(db: AsyncSession, company_id, user: User, ordered_ids: list) -> None:
    rows = {str(f.id): f for f in (await db.execute(select(MatrixChatFolder).where(
        MatrixChatFolder.company_id == company_id, MatrixChatFolder.user_id == user.id))).scalars().all()}
    for i, fid in enumerate(ordered_ids):
        f = rows.get(str(fid))
        if f is not None:
            f.sort = i
    await db.commit()


# ── люди (для выбора участников) ──

async def search_people(db: AsyncSession, company_id, q: str, me_id, limit: int = 30) -> list[dict[str, Any]]:
    """Люди пространства для добавления в чаты (кроме себя).

    Отдаём не только имя: в чате должно быть видно, КТО собеседник — свой сотрудник или
    внешний участник (подрядчик, поставщик) и от какой организации. Иначе в общей комнате
    сотрудник и подрядчик выглядят одинаково, хотя разговор с ними разный.
    """
    stmt = (select(User, UserCompany, Counterparty)
            .join(UserCompany, UserCompany.user_id == User.id)
            .outerjoin(Counterparty, Counterparty.id == UserCompany.organization_id)
            .where(UserCompany.company_id == company_id, User.id != me_id))
    ql = (q or "").strip()
    if ql:
        like = f"%{ql}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.email.ilike(like)))
    rows = (await db.execute(stmt.order_by(User.name).limit(limit))).all()
    return [_person_card(u, uc, org) for u, uc, org in rows]


def _person_card(user: User, membership: UserCompany, org: Counterparty | None) -> dict[str, Any]:
    """Карточка человека для чата: имя + принадлежность («кто это»)."""
    party = getattr(membership, "party_type", None) or "internal"
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        # internal — свой сотрудник компании; partner — внешний участник пространства.
        "partyType": party,
        "role": membership.role,
        "position": membership.position,
        "orgName": (org.short_name or org.name) if org is not None else None,
    }


SUPPORT_CHANNEL_TITLE = "Поддержка платформы"


async def ensure_support_channel(db: AsyncSession, company_id, requester: User) -> dict[str, Any]:
    """Канал связи с разработчиком платформы — теми же средствами, что и остальные чаты.

    У заказчика должен быть штатный способ дойти до тех, кто эту экосистему делает, не
    выходя из неё: не почта и не мессенджер снаружи, а обычная комната пространства. В неё
    входят инициатор и все участники с принадлежностью `vendor` (инженеры разработчика).

    Идемпотентно: комната одна на компанию (`MatrixGroupRoom` с этим названием). Повторный
    вызов добавляет в неё тех, кого там ещё нет, — состав поддержки со временем меняется.
    """
    room = (await db.execute(select(MatrixGroupRoom).where(
        MatrixGroupRoom.company_id == company_id,
        MatrixGroupRoom.title == SUPPORT_CHANNEL_TITLE))).scalar_one_or_none()

    vendors = (await db.execute(
        select(User).join(UserCompany, UserCompany.user_id == User.id)
        .where(UserCompany.company_id == company_id, UserCompany.party_type == "vendor")
    )).scalars().all()

    if room is None:
        created = await create_group_room(
            db, company_id, requester, SUPPORT_CHANNEL_TITLE,
            [v.id for v in vendors], is_public=False)
        return {**created, "vendors": len(vendors), "created": True}

    # Комната есть — досыпаем участников (инициатора и инженеров поддержки).
    joined = set()
    try:
        joined = set(await ma.get_joined_members(room.room_id))
    except Exception:  # noqa: BLE001 — комната недоступна: пусть решает вызывающий
        pass
    for person in [requester, *vendors]:
        mxid = await ensure_matrix_account(db, person)
        if mxid not in joined:
            await ma.force_join(room.room_id, mxid)
    return {"roomId": room.room_id, "title": room.title, "isPublic": room.is_public,
            "vendors": len(vendors), "created": False}


async def chat_directory(db: AsyncSession, company_id) -> list[dict[str, Any]]:
    """Справочник участников чата по Matrix-идентификаторам.

    В сообщениях Matrix автор приходит как mxid, поэтому подписи «свой/внешний» UI рисует
    по этой карте: mxid → карточка человека пространства. Кого нет в карте (гость, бот) —
    UI подписывает нейтрально, а не выдумывает принадлежность.
    """
    rows = (await db.execute(
        select(User, UserCompany, MatrixIdentity, Counterparty)
        .join(UserCompany, UserCompany.user_id == User.id)
        .join(MatrixIdentity, MatrixIdentity.user_id == User.id)
        .outerjoin(Counterparty, Counterparty.id == UserCompany.organization_id)
        .where(UserCompany.company_id == company_id)
    )).all()
    out = []
    for user, membership, identity, org in rows:
        card = _person_card(user, membership, org)
        card["mxid"] = identity.mxid
        out.append(card)
    return out
