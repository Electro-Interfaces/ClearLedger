"""Автопризнание заявок станций на карточки: товароведа в центре нет.

Пока заявку разбирал человек, она ждала в среднем три дня (208, 40 дней до
04.10.2026: 76 ч в среднем, 267 ч самое долгое), и всё это время станция жила
черновиком с нулевым GUID — смена не собиралась, остаток жил не на той
карточке. Решение МАГа 04.10.2026: признавать автоматически по тем же правилам,
по которым признавал человек, а человеку оставлять только спорное.

Правила проверены на 173 разобранных заявках за 40 дней:

  · штрихкод заявки есть у одной карточки сети → привязать. GTIN один на товар:
    станция завела черновик, потому что карточку не видела, а не потому, что
    это другой товар (названия у станций расходятся, «LD Blue» = «LD Autograph»);
  · исключение — карточка «в ассортименте»: станция завела отдельный вкус, а
    штрихкод этого вкуса висел на общей карточке. Человек в таких случаях
    заводил карточку вкуса и передавал ей штрихкод (18 из 18). Делаем так же,
    но только если у общей карточки по этому штрихкоду на станциях нет остатка:
    иначе остаток останется висеть на старой карточке (Ирис Меллер, −1);
  · штрихкода в сети нет → завести карточку в группе, которую выбрала станция
    (по названию группа угадывалась неверно или никак в 33 случаях из 165);
  · несколько владельцев штрихкода, нет годного штрихкода, нет группы, остаток
    на общей карточке → человеку. Отказ — никогда автоматически.

Признание идёт той же функцией и той же транзакцией, что ручное
(`edge_nsi.resolve_item_draft` + `_queue_nsi_delta`): иначе карточка завелась бы
в центре, а станции о ней не узнали бы (ловушка 04.09.2026).
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.database import async_session_factory
from app.services import edge_nsi, item_group_guess

log = logging.getLogger("clearledger.store.item_draft_auto")

TICK_SECONDS = 300
LOCK_NAMESPACE = 0x1D7A0
# Заявку не трогаем первые минуты: администратор мог поправить черновик сразу
# после заведения (имя, штрихкод), и правка ещё едет наверх.
ВЫДЕРЖКА_МИНУТ = 10
ПОМЕТКА = "авто"
# Признаём только ночью по Москве. Признанная карточка, приехав на станцию,
# переклеивает черновик во ВСЕХ документах, в том числе в накладной, которую
# администратор ещё заполняет: версия документа меняется, и сохранение её формы
# отклоняется «документ изменил кто-то ещё» (208, 05.10.2026: два отказа подряд,
# работа после последнего сохранения терялась). Днём черновик подождёт до ночи.
МСК = timezone(timedelta(hours=3))
НОЧЬ_С, НОЧЬ_ДО = 2, 5


def ночное_окно(момент: datetime) -> bool:
    return НОЧЬ_С <= момент.astimezone(МСК).hour < НОЧЬ_ДО


def штрихкод_годен(код: str) -> bool:
    """GTIN с верной контрольной цифрой и не внутренний код магазина.

    Короткие номера (кухня, внутренние коды станции) и коды на «2» (RCN,
    канон п. 3: не привязываются никогда) остаются человеку: по ним нельзя
    сказать, что два разных места имеют в виду один товар.
    """
    цифры = re.sub(r"[^0-9]", "", код or "")
    if len(цифры) not in (8, 12, 13, 14) or цифры != (код or "").strip():
        return False
    if (len(цифры) in (8, 13) and цифры[0] == "2") or (len(цифры) == 12 and цифры[0] == "2"):
        return False
    тело, контроль = цифры[:-1], int(цифры[-1])
    сумма = sum(int(ц) * (3 if i % 2 == 0 else 1) for i, ц in enumerate(reversed(тело)))
    return (10 - сумма % 10) % 10 == контроль


def слова(имя: str) -> set[str]:
    """Значимые слова названия: буквы и числа в нижнем регистре."""
    return {с for с in re.findall(r"[a-zа-яё0-9]+", (имя or "").lower().replace("ё", "е"))
            if len(с) > 1 or с.isdigit()}


def похожи(а: str, б: str) -> bool:
    """Тот же товар другими словами: доля общих слов не меньше 0,6.

    Новый штрихкод того же товара (новая упаковка, другой поставщик) человек
    привязывал к старой карточке по названию — «Святой Источник негаз. 1,5».
    Останавливать признание по сходству нельзя: на истории 40 дней такое правило
    задержало бы 27 настоящих новых товаров (масло 10W40 рядом с 5W40, вкусы
    Philip Morris) и поймало бы один дубль, а задержанная заявка без товароведа
    висит и держит станцию на черновике. Дубль потом сливается штатно, поэтому
    сходство только пишется в пометку — для разбора задним числом.
    """
    х, у = слова(а), слова(б)
    if not х or not у:
        return False
    return len(х & у) / len(х | у) >= 0.6


def ассортимент(имя: str) -> bool:
    """Общая карточка «в ассортименте»: «в ассорт.», «асс.», «асср.», «Ассорти»."""
    return re.search(r"(^|[\s(])асс", (имя or "").lower()) is not None


@dataclass
class Держатель:
    item_id: int
    name: str
    остаток: float  # сумма |остатка| по штрихкодам заявки на всех станциях


@dataclass
class Решение:
    действие: str  # link | create | split | human
    почему: str
    item_id: int | None = None
    group_id: int | None = None
    передать_от: int | None = None  # карточка «в ассортименте», у которой забираем штрихкод


def решить(имя: str, коды: list[str], держатели: list[Держатель],
           группа_станции: int | None, группа_по_имени: int | None,
           похожие: list[str] | None = None) -> Решение:
    """Чистое решение по одной заявке — без базы, проверяется тестами.

    `похожие` — названия карточек сети, похожих на заявку (без общего штрихкода).
    """
    if not коды:
        return Решение("human", "у заявки нет штрихкода")
    негодные = [к for к in коды if not штрихкод_годен(к)]
    if негодные:
        return Решение("human", "штрихкод не GTIN или внутренний: " + ", ".join(негодные))
    if len(держатели) > 1:
        return Решение("human", "штрихкод у нескольких карточек сети")
    группа = группа_станции if группа_станции is not None else группа_по_имени
    откуда = "группа станции" if группа_станции is not None else "группа по названию"
    if len(держатели) == 1:
        д = держатели[0]
        if ассортимент(д.name) and not ассортимент(имя):
            if д.остаток > 0.0005:
                return Решение("human", f"вкус из «{д.name}», но у неё по этому штрихкоду есть остаток")
            if группа is None:
                return Решение("human", "вкус из карточки «в ассортименте», а группа не определена")
            return Решение("split", f"вкус отделён от «{д.name}», {откуда}",
                           group_id=группа, передать_от=д.item_id)
        return Решение("link", f"штрихкод уже у карточки «{д.name}»", item_id=д.item_id)
    if группа is None:
        return Решение("human", "новой карточке не определить группу")
    почему = f"новая карточка, {откуда}"
    if похожие:
        почему += f"; похожа на «{похожие[0]}» — проверить, не дубль ли"
    return Решение("create", почему, group_id=группа)


async def _держатели(db, коды: list[str]) -> list[Держатель]:
    строки = (await db.execute(text("""
        SELECT i.id, i.name, i.external_uuid::text AS uuid
          FROM edge.barcode b JOIN edge.item i ON i.id = b.item_id
         WHERE b.code = ANY(:c) AND b.status = 'active' AND NOT coalesce(i.deleted, false)
         GROUP BY i.id, i.name, i.external_uuid
    """), {"c": коды})).mappings().all()
    out = []
    for с in строки:
        остаток = (await db.execute(text("""
            SELECT coalesce(sum(abs(quantity)), 0) FROM store_stock_balances
             WHERE item_uuid = :u AND barcode = ANY(:c)
        """), {"u": с["uuid"], "c": коды})).scalar() or 0
        out.append(Держатель(с["id"], с["name"], float(остаток)))
    return out


async def _похожие(db, имя: str) -> list[str]:
    """Карточки сети с почти тем же названием. Около трёх тысяч строк — дёшево."""
    имена = (await db.execute(text(
        "SELECT name FROM edge.item WHERE NOT coalesce(deleted, false)"))).scalars().all()
    return [и for и in имена if похожи(имя, и)][:3]


async def _группа_по_пути(db, путь: str | None) -> int | None:
    if not (путь or "").strip():
        return None
    return (await db.execute(text("SELECT id FROM edge.item_group WHERE path = :p"),
                             {"p": путь.strip()})).scalar()


async def _передать_штрихкоды(db, новая: int, прежняя: int, коды: list[str]) -> None:
    """То же, что «передать код» на экране коллизий: прежний владелец — historical."""
    for код in коды:
        претензия = (await db.execute(text("""
            SELECT id FROM edge.barcode WHERE item_id = :n AND code = :c AND status = 'rejected'
        """), {"n": новая, "c": код})).scalar()
        if претензия is None:
            continue
        await db.execute(text("""
            UPDATE edge.barcode SET status = 'historical',
                   note = coalesce(note || ' · ', '') || 'вкус отделён автопризнанием'
             WHERE item_id = :p AND code = :c AND status = 'active'
        """), {"p": прежняя, "c": код})
        await db.execute(text("""
            UPDATE edge.barcode SET status = 'active', note = 'передан автопризнанием'
             WHERE id = :id
        """), {"id": претензия})


async def разобрать_заявку(db, cid, заявка) -> Решение:
    """Одна заявка — одна транзакция: решение, перенос штрихкода, задания станциям."""
    from app.routers.store_router import _queue_nsi_delta  # ручка ручного признания

    коды = [str(к).strip() for к in (заявка["barcodes"] or []) if str(к).strip()]
    держатели = await _держатели(db, коды) if коды else []
    по_имени = await item_group_guess.предложить(db, заявка["name"] or "")
    решение = решить(заявка["name"] or "", коды, держатели,
                     await _группа_по_пути(db, заявка["group_path"]),
                     по_имени["group_id"] if по_имени else None,
                     [] if держатели else await _похожие(db, заявка["name"] or ""))
    if решение.действие == "human":
        return решение
    пометка = f"{ПОМЕТКА}: {решение.почему}"
    действие = "link" if решение.действие == "link" else "create"
    итог = await edge_nsi.resolve_item_draft(
        db, cid, заявка["id"], действие, решение.item_id, пометка,
        group_id=решение.group_id)
    if решение.действие == "split":
        await _передать_штрихкоды(db, итог["item_id"], решение.передать_от, коды)
        await _queue_nsi_delta(db, cid, решение.передать_от)
    await _queue_nsi_delta(db, cid, итог["item_id"])
    await db.commit()
    return решение


async def tick() -> dict[str, int]:
    счёт = {"link": 0, "create": 0, "split": 0, "human": 0, "error": 0}
    async with async_session_factory() as db:
        заявки = (await db.execute(text(f"""
            SELECT id, company_id, name, barcodes, group_path
              FROM edge.item_draft
             WHERE resolved_at IS NULL AND NOT rejected
               AND created_at < now() - interval '{ВЫДЕРЖКА_МИНУТ} minutes'
             ORDER BY company_id, created_at
        """))).mappings().all()
        компании = {з["company_id"] for з in заявки}
        for cid in компании:
            # Один разборщик на компанию во всём кластере: две реплики завели бы
            # одну карточку дважды.
            занято = await db.scalar(text("SELECT pg_try_advisory_lock(:ns, :k)"),
                                     {"ns": LOCK_NAMESPACE, "k": cid.int % (2 ** 31)})
            if not занято:
                continue
            try:
                for з in [з for з in заявки if з["company_id"] == cid]:
                    try:
                        р = await разобрать_заявку(db, cid, з)
                        счёт[р.действие] += 1
                        if р.действие != "human":
                            log.info("автопризнание #%s «%s»: %s — %s",
                                     з["id"], з["name"], р.действие, р.почему)
                    except Exception:  # noqa: BLE001 — одна заявка не валит разбор
                        await db.rollback()
                        счёт["error"] += 1
                        log.exception("автопризнание #%s «%s» не удалось", з["id"], з["name"])
            finally:
                await db.execute(text("SELECT pg_advisory_unlock(:ns, :k)"),
                                 {"ns": LOCK_NAMESPACE, "k": cid.int % (2 ** 31)})
                await db.commit()
    return счёт


async def run_forever() -> None:
    """Фоновый цикл — поднимается из lifespan приложения."""
    log.info("Автопризнание заявок на карточки запущено (тик %d с)", TICK_SECONDS)
    while True:
        if not ночное_окно(datetime.now(timezone.utc)):
            await asyncio.sleep(TICK_SECONDS)
            continue
        try:
            счёт = await tick()
            if any(счёт[k] for k in ("link", "create", "split", "error")):
                log.info("автопризнание: %s", счёт)
        except Exception:  # noqa: BLE001 — разбор не критичен для API
            log.exception("Сбой такта автопризнания")
        await asyncio.sleep(TICK_SECONDS)
