"""Канал ОРП в бухгалтерию: расширение TradeLedger забирает пакеты у нас.

Раньше отчёты о розничных продажах приезжали в БП ГИГ из центральной базы 1С —
файлами через каталог обмена на сервере 1С (`КаталогOwnCloud_ЦБ`, по умолчанию
`C:\\TL_BP_Export\\`). Центральной базы в пространстве больше нет, а каталог
на чужом сервере — лишнее звено, которое молчит при сбое и перезаливает старьё
кнопкой «Перезагрузить период».

Здесь то же самое сделано так, как уже работает канал нефтепродуктов: расширение
ходит по HTTP прямо к источнику. Две ручки, зеркало STS-контракта
(`/v1/shifts` → `/v1/report/shift_report`):

* `GET /tl/shifts?from=&to=&station=` — какие смены есть за период;
* `GET /tl/package?shift=` — пакет одной смены, формат v2.

Сам пакет собирает `BpPackageEmitter` — тот же, что отдаёт предпросмотр в
интерфейсе. Формат менять не пришлось: приёмник `TL_СопуткаСервис` читает
`Документы[].Товары` с полями Номенклатура/Количество/Цена/Сумма/СтавкаНДС, а
шапку — `ВерсияФормата`, `ИдентификаторПакета`, `Смена{}`, `НСИ[]`; наш агент
писался по этому же контракту.

Вход — Basic auth поверх того же реестра ключей, что и у edge-агентов
(`SpaceInboundKey`): второй механизм доступа заводить незачем. Логин расширение
шлёт любой, значение имеет пароль — он и есть ключ.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Company, DataEntry, SpaceInboundKey

router = APIRouter(prefix="/tl", tags=["Канал ОРП → бухгалтерия"])

_basic = HTTPBasic(auto_error=False)

#: Смена в ответе списка. Имена полей русские — их читает 1С, и латиница в
#: пакете смотрелась бы чужеродно рядом с «Документы» и «НСИ».
_ПОЛЕ_КЛЮЧ = "КлючСмены"


async def канал_компании(
    creds: HTTPBasicCredentials | None = Depends(_basic),
    db: AsyncSession = Depends(get_db),
) -> Company:
    """Компания, чьим ключом пришли. Пароль Basic-авторизации — сам ключ.

    Сравнение хеша идёт через `compare_digest`: обычное `==` на строках
    завершается на первом несовпавшем байте, и по времени ответа ключ
    подбирается посимвольно.
    """
    if creds is None or not creds.password:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Нужна Basic-авторизация: пароль — ключ пространства",
            headers={"WWW-Authenticate": "Basic"},
        )
    предъявленный = hashlib.sha256(creds.password.encode()).hexdigest()
    ключи = (await db.execute(select(SpaceInboundKey).where(
        SpaceInboundKey.revoked_at.is_(None),
    ))).scalars().all()
    ключ = next(
        (k for k in ключи if secrets.compare_digest(k.key_hash, предъявленный)), None)
    if ключ is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Ключ не опознан или отозван",
            headers={"WWW-Authenticate": "Basic"},
        )
    company = await db.get(Company, ключ.company_id)
    if company is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ключ не привязан к пространству")
    ключ.last_used_at = datetime.now(timezone.utc)
    return company


def _день_смены(смена: dict) -> str:
    """Дата смены по её закрытию, а при отсутствии — по открытию.

    Смена закрывается за полночь, и брать день от открытия значит развести две
    ревизии одной смены по разным дням.
    """
    for поле in ("Закрытие", "Открытие"):
        значение = str(смена.get(поле) or "")
        if len(значение) >= 10:
            return значение[:10]
    return ""


def _ключ_смены(запись: DataEntry) -> str:
    """Тот же ключ, которым смену находит BpPackageEmitter."""
    смена = (запись.meta or {}).get("Смена") or {}
    return str(смена.get("Смена") or f"{_день_смены(смена)}|{смена.get('КодАЗС') or '—'}")


@router.get("/shifts", summary="Смены за период (что можно забрать)")
async def смены_за_период(
    from_: date = Query(..., alias="from", description="с даты включительно"),
    to: date = Query(..., description="по дату включительно"),
    station: int | None = Query(None, description="код АЗС; пусто — все станции"),
    company: Company = Depends(канал_компании),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Список смен, за которые есть отчёт о розничных продажах.

    Зеркало `/v1/shifts` у STS: расширение сначала спрашивает, что есть, и лишь
    затем забирает пакеты по одному. Без этой ручки от файлового каталога не
    отвязаться — HTTP-режим умеет взять пакет, но не умеет узнать, какие смены
    существуют.
    """
    # ТОЛЬКО наши смены. Записи с `source='oneC'` — наследие канала центральной
    # базы 1С, которой в пространстве больше нет; в бухгалтерию они уже уезжали
    # своим путём, и отдать их второй раз значит завести документ дважды: у
    # приёмника идемпотентность по `ИсточникUUID`, а он у станции и у ЦБ разный.
    rows = (await db.execute(select(DataEntry).where(
        DataEntry.company_id == company.id,
        DataEntry.source == "edge",
        DataEntry.doc_type_id == "retail_sale_sidegoods",
    ))).scalars().all()

    # В сутках смен НЕСКОЛЬКО, и каждая — свой документ: ключом служит GUID
    # смены, а не день. Схлопывать их по дате нельзя — 11.06.2026 на 208 таких
    # две (7008 и 7009), 19.08 — три.
    #
    # Схлопываем только РЕВИЗИИ одной смены (переоткрытие, перевыгрузка): наверх
    # идёт одна строка на ключ, с самым поздним закрытием — пакет соберётся
    # именно из неё, и список обязан говорить то же, что отдаст /package.
    лучшие: dict[tuple[str, str], tuple[DataEntry, dict, str]] = {}
    for row in rows:
        смена = (row.meta or {}).get("Смена") or {}
        день = _день_смены(смена)
        if not день:
            continue
        if not (from_.isoformat() <= день <= to.isoformat()):
            continue
        if station is not None and str(смена.get("КодАЗС") or "") != str(station):
            continue
        # Смена без внутреннего номера — не смена. Пока агент его не слал (июнь
        # 2026), одна и та же смена приезжала повторно под ключом пакета: в
        # реестре такие дубли гасятся, и канал обязан вести себя так же, иначе
        # бухгалтерия получит 11.06.2026 лишний отчёт на 897 ₽. Ноль стоит у
        # служебных пакетов — это тоже не смена.
        if str(смена.get("НомерСменыВнутр") or "") in ("", "0"):
            continue
        # Схлопываем по ФИЗИЧЕСКОЙ смене — паре (АЗС, внутренний номер), а не по
        # GUID пакета.
        #
        # Одна и та же смена приезжает под РАЗНЫМИ GUID: станция шлёт свой
        # (версия 1, из 1С), центр вычисляет свой (версия 5, детерминированный).
        # 04.09.2026 таких смен оказалось 58 из 92, и список отдавал 132 ключа
        # вместо 92 — расширение запросило бы одну смену дважды и завело в
        # бухгалтерии два отчёта. Так в начале сентября и появились 44 дубля
        # поверх проведённых документов.
        #
        # Внутренний номер уникален в пределах станции и не зависит от того,
        # кто и когда пересобрал пакет; GUID зависит.
        группа = (str(смена.get("КодАЗС") or ""),
                  str(смена.get("НомерСменыВнутр") or ""))
        прежний = лучшие.get(группа)
        if прежний is None or str(смена.get("Закрытие") or "") > str(
                прежний[1].get("Закрытие") or ""):
            лучшие[группа] = (row, смена, день)

    ответ = [
        {
            _ПОЛЕ_КЛЮЧ: _ключ_смены(row),
            "КодАЗС": смена.get("КодАЗС"),
            "Дата": день,
            "НомерСмены": смена.get("НомерСмены") or смена.get("ОСЭНомер"),
            "Открытие": смена.get("Открытие"),
            "Закрытие": смена.get("Закрытие"),
            "ВнутреннийНомер": смена.get("НомерСменыВнутр"),
        }
        for row, смена, день in лучшие.values()
    ]
    # Внутри суток порядок задаёт ОТКРЫТИЕ, а не печатный номер: он строится из
    # даты открытия и у всех смен одного дня одинаков (11.06.2026 обе смены
    # называются «2082081106202601»).
    ответ.sort(key=lambda с: (с["Дата"], str(с["КодАЗС"]), str(с["Открытие"] or "")))
    return ответ


@router.get("/package", summary="Пакет одной смены (формат v2)")
async def пакет_смены(
    shift: str = Query(..., description="КлючСмены из /tl/shifts"),
    company: Company = Depends(канал_компании),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Пакет для приёмника TL: шапка, НСИ и документы смены.

    Собирается тем же эмиттером, что и предпросмотр в интерфейсе, — чтобы
    человек на экране и бухгалтерия видели ровно один и тот же пакет.
    """
    from app.services.bp_export import BpPackageEmitter

    try:
        return await BpPackageEmitter(db, company.id).build_shift_package(shift)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Сборка пакета: {e}")


@router.get("/packages", summary="Пакеты всех смен периода — одним ответом")
async def пакеты_периода(
    from_: date = Query(..., alias="from", description="с даты включительно"),
    to: date = Query(..., description="по дату включительно"),
    station: int | None = Query(None, description="код АЗС; пусто — все станции"),
    limit: int = Query(30, ge=1, le=200, description="сколько смен отдать за раз"),
    offset: int = Query(0, ge=0, description="сколько смен пропустить"),
    company: Company = Depends(канал_компании),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Все пакеты периода за один запрос — вместо «список, потом по одному».

    Поштучная выдача обходилась дорого с обеих сторон: 1С поднимала новое
    TLS-соединение на каждую смену, а эмиттер на каждый пакет перечитывал
    записи компании целиком — 2 739 строк, по секунде на пакет, сто семнадцать
    раз подряд. Здесь эмиттер один на весь период: выборки читаются однажды и
    переиспользуются, а соединение нужно одно.

    Смена, которая не собралась, не роняет ответ: она попадает в «Ошибки»
    поимённо, остальные приезжают. Так же ведёт себя поштучный путь, и терять
    период целиком из-за одной смены нельзя.
    """
    from app.services.bp_export import BpPackageEmitter

    смены = await смены_за_период(
        from_=from_, to=to, station=station, company=company, db=db)
    emitter = BpPackageEmitter(db, company.id)

    # Ответ на весь период — 17,7 МБ: 1С такой объём принимает тяжело, поэтому
    # период отдаётся окнами. Порядок смен устойчивый (дата, станция, открытие),
    # так что окна не пересекаются и ничего не теряют.
    окно = смены[offset:offset + limit]

    пакеты: list[dict] = []
    ошибки: list[dict] = []
    for смена in окно:
        ключ = смена[_ПОЛЕ_КЛЮЧ]
        try:
            пакеты.append(await emitter.build_shift_package(ключ))
        except Exception as e:  # noqa: BLE001
            ошибки.append({
                _ПОЛЕ_КЛЮЧ: ключ,
                "Дата": смена.get("Дата"),
                "ВнутреннийНомер": смена.get("ВнутреннийНомер"),
                "Ошибка": str(e)[:400],
            })
    return {
        "СменВПериоде": len(смены),
        "Отступ": offset,
        "Отдано": len(пакеты),
        "Пакеты": пакеты,
        "Ошибки": ошибки,
        "ЕстьЕщё": offset + len(окно) < len(смены),
    }
