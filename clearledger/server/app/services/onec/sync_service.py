from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingDoc,
    Counterparty,
    InventoryBatch,
    NomenclatureItem,
    NomenclaturePrice,
    OneCConnection,
    OneCPolicy,
    OneCSyncLog,
    Organization,
    Period,
    Warehouse,
)
from app.services.onec.com_client import OneCComClient
from app.services.onec.crypto import decrypt_password
from app.services.onec.exceptions import OneCError
from app.services.onec.odata_client import (
    ENTITY_COUNTERPARTIES,
    ENTITY_DOC_CORRECTION,
    ENTITY_DOC_OPZS,
    ENTITY_DOC_ORP,
    ENTITY_DOC_PTU,
    ENTITY_DOC_TRANSFER,
    ENTITY_DOC_WRITEOFF,
    ENTITY_NOMENCLATURE,
    ENTITY_ORGANIZATIONS,
    ENTITY_WAREHOUSES,
    OneCODataClient,
)


# Тип объединения — формальная аннотация интерфейса. OneCComClient и
# OneCODataClient имеют одинаковый публичный API (metadata_catalogs,
# fetch_entity, iter_entity, count_entity, aclose, __aenter__/__aexit__),
# поэтому sync_service работает с любым из них.
OneCClient = OneCODataClient | OneCComClient

logger = logging.getLogger("clearledger.onec.sync")


# Поля справочников 1С, которые тянем в локальную нормализованную БД.
# Только то, что есть в существующих моделях ClearLedger — без расширения схемы.
COUNTERPARTY_SELECT = ["Ref_Key", "DeletionMark", "Description", "ИНН", "КПП"]
NOMENCLATURE_SELECT = ["Ref_Key", "DeletionMark", "Description", "Артикул", "Код"]
ORGANIZATION_SELECT = ["Ref_Key", "DeletionMark", "Description", "ИНН", "КПП"]
WAREHOUSE_SELECT    = ["Ref_Key", "DeletionMark", "Description", "Код"]


class OneCSyncService:
    """Pull-синхронизация НСИ из БП ГИГ в локальную нормализованную БД.

    Логика:
    - На каждый запрос создаётся OneCSyncLog со статусом 'running'.
    - По окончании — finished_at, status='completed' либо 'error', details.
    - Записи с DeletionMark=True пропускаются (мягкое удаление обновлений).
    - external_ref = Ref_Key (UUID 1С) — ключ дедупликации.
    - company_id берётся из OneCConnection.company_id.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _open_client(self, connection: OneCConnection) -> OneCClient:
        password = decrypt_password(connection.password_encrypted)
        mode = (connection.mode or "odata").lower()
        if mode == "com":
            # odata_url для COM хранит либо путь к файловой БД, либо ConnString.
            url = connection.odata_url.strip()
            if "=" not in url:
                conn_string = (
                    f'File="{url}";'
                    f'Usr="{connection.username}";'
                    f'Pwd="{password}";'
                )
            else:
                conn_string = url
            # Если задан COM_AGENT_URL — идём через удалённого агента (production deploy
            # на Linux/Miran). Иначе локальный subprocess (dev на Windows).
            import os
            if os.environ.get("COM_AGENT_URL"):
                from app.services.onec.http_agent_client import OneCHttpAgentClient
                client_http = OneCHttpAgentClient(conn_string)
                await client_http._ensure_started()  # noqa: SLF001
                return client_http
            client = OneCComClient(conn_string)
            await client._ensure_started()  # noqa: SLF001
            return client
        return OneCODataClient(
            base_url=connection.odata_url,
            username=connection.username,
            password=password,
        )

    async def _start_log(
        self,
        connection: OneCConnection,
        sync_type: str,
        direction: str = "in",
    ) -> OneCSyncLog:
        log = OneCSyncLog(
            id=uuid.uuid4(),
            connection_id=connection.id,
            direction=direction,
            sync_type=sync_type,
            status="running",
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def _finish_log(
        self,
        log: OneCSyncLog,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        log.status = status
        log.finished_at = datetime.now(tz=timezone.utc)
        if details:
            log.details = {**(log.details or {}), **details}

    # ─── публичные операции ─────────────────────────────────────────

    async def test_connection(self, connection: OneCConnection) -> dict[str, Any]:
        try:
            async with await self._open_client(connection) as client:
                catalogs = await client.metadata_catalogs()
            return {"available": True, "catalogs": catalogs, "error": None}
        except OneCError as exc:
            return {"available": False, "catalogs": [], "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — точка контакта с внешним миром, ловим всё
            logger.exception("Unexpected error during test_connection")
            return {"available": False, "catalogs": [], "error": f"{type(exc).__name__}: {exc}"}

    async def sync_catalogs(self, connection: OneCConnection) -> OneCSyncLog:
        log = await self._start_log(connection, sync_type="catalogs")
        details: dict[str, Any] = {}
        try:
            async with await self._open_client(connection) as client:
                details["organizations"] = await self._sync_organizations(client, connection, log)
                details["counterparties"] = await self._sync_counterparties(client, connection, log)
                details["warehouses"] = await self._sync_warehouses(client, connection, log)
                details["nomenclature"] = await self._sync_nomenclature(client, connection, log)
            await self._finish_log(log, "completed", details)
        except Exception as exc:
            await self._finish_log(log, "error", {"error": f"{type(exc).__name__}: {exc}", **details})
            raise
        return log

    async def sync_policy(self, connection: OneCConnection) -> OneCSyncLog:
        """Pull всех регистров УчетнойПолитики из БП ГИГ.

        В БП 3.0 настройки разнесены по 8+ регистрам:
          УчетнаяПолитика, УчетнаяПолитикаНалоговогоУчета,
          УчетнаяПолитикаНДС, СпособыОценкиМПЗ, ПорядокУчетаНДСНаСчете_19,
          УчетнаяПолитикаПоНалогуНаПрибыль и т.д.

        Через metadata_registers находим все регистры с "УчетнаяПолитика"
        либо "СпособыОценки" в имени и тянем каждый.
        Результат — один OneCPolicy на организацию с settings[register_name] =
        {fields}."""
        log = await self._start_log(connection, sync_type="policy")
        details: dict[str, Any] = {"organizations": 0, "policies": 0, "registers": []}
        try:
            async with await self._open_client(connection) as client:
                # 1) Находим все регистры по подстрокам (case-insensitive)
                # В БП 3.0.194 реальные настройки лежат в:
                #   - УчетнаяПолитика (общий)
                #   - НастройкиСистемыНалогообложения (ОСН/УСН/ЕНВД)
                #   - НастройкиУчетаНДС, НастройкиРасчетаНДС
                #   - НастройкиУчетаНалогаНаПрибыль (+ Постоянные)
                #   - НастройкиУчетаУСН, НастройкиУчетаЕНС
                #   - МетодыОпределенияПрямыхРасходовПроизводстваВНУ
                #   - ПорядокОтраженияЗарплатыВБухУчете
                #   - и ~15 других НастройкиУчета*
                candidates: set[str] = set()
                # Берём только регистры по подстрокам, исключая "Удалить*" и "Версия*"
                for substr in (
                    "учетнаяполитика", "учётнаяполитика",
                    "настройкисистемы", "настройкирасчетандс",
                    "настройкиучета", "настройкиучёта",
                    "методыопределения", "порядокотражения",
                    "способоценки",
                ):
                    try:
                        for r in await client.metadata_registers(substr):
                            short = r.replace("InformationRegister_", "")
                            if short.startswith("Удалить") or "Версия" in short:
                                continue
                            candidates.add(r)
                    except Exception:
                        continue
                if not candidates:
                    raise OneCError("Регистры учётной политики не найдены в БП")
                details["registers"] = sorted(candidates)

                # 2) Для каждого регистра — describe → fetch с реальными полями
                # Накопитель: {org_ref: {register_name: {field: value, ...}}}
                per_org: dict[str, dict[str, dict[str, Any]]] = {}
                # Накопитель самой ранней/последней даты для отображения
                per_org_period: dict[str, str] = {}

                policy_entity_main = None  # для совместимости с UI

                for reg in sorted(candidates):
                    try:
                        d = await client.describe_entity(reg)
                    except Exception:
                        continue
                    avail = set(d.get("dimensions", []) + d.get("resources", []) + d.get("attributes", []))
                    org_field = next((x for x in ("Организация", "Контрагент") if x in avail), None)
                    if not org_field:
                        continue
                    # Поля: Period + Организация + всё остальное что в регистре есть.
                    # Берём ВСЕ реквизиты — это и есть «снимок настроек».
                    OPTIONAL_ALL = sorted(avail - {org_field, "Период", "Регистратор"})
                    fields = ["Period", f"{org_field}_Key"] + OPTIONAL_ALL
                    try:
                        rows = await client.fetch_entity(reg, select=fields, orderby="Period")
                    except Exception as exc:
                        # Если регистр непригоден (например, измерение не Организация) — пропускаем.
                        details.setdefault("skipped_registers", []).append(f"{reg}: {type(exc).__name__}")
                        continue
                    # Накопление по хронологии: для каждого поля ОТДЕЛЬНО
                    # берём ПОСЛЕДНЕЕ не-null значение по всем периодам.
                    # У периодического РС: позднее не-null перекрывает раннее.
                    # Это даёт «действующую» политику с учётом всех изменений.
                    org_key = f"{org_field}_Key"
                    # сортируем по Period ASC
                    rows_sorted = sorted(rows, key=lambda r: str(r.get("Period") or ""))
                    accumulated: dict[str, dict[str, Any]] = {}  # org → merged record
                    latest_period: dict[str, str] = {}
                    for r in rows_sorted:
                        org = str(r.get(org_key) or "")
                        if not org:
                            continue
                        bucket = accumulated.setdefault(org, {})
                        bucket[org_key] = org
                        for k, v in r.items():
                            if k in (org_key,):
                                continue
                            # Перекрываем только если новое значение НЕ null/пусто.
                            # False допускаем — это значимое значение для bool флагов
                            # (например ПлательщикНДС=False), но GUID-нули пропускаем.
                            if v is None or v == "" or v == "00000000-0000-0000-0000-000000000000":
                                continue
                            bucket[k] = v
                        pd = str(r.get("Period") or "")
                        if pd > latest_period.get(org, ""):
                            latest_period[org] = pd
                        bucket["Period"] = latest_period[org]
                    short_name = reg.replace("InformationRegister_", "")
                    for org_ref, raw in accumulated.items():
                        per_org.setdefault(org_ref, {})[short_name] = raw
                        pd = str(raw.get("Period") or "")[:19]
                        if pd:
                            cur_p = per_org_period.get(org_ref, "")
                            if not cur_p or pd > cur_p:
                                per_org_period[org_ref] = pd
                    if not policy_entity_main and short_name == "УчетнаяПолитика":
                        policy_entity_main = reg

                details["raw_rows"] = sum(len(v) for v in per_org.values())
                details["policy_entity"] = policy_entity_main or sorted(candidates)[0]
                # Для нижестоящего кода: latest = per_org, поля плоские извлекутся
                # из «главной» УчетнаяПолитика или из любого регистра, где найдём
                # ключевые поля.
                latest = {org: {"_per_register": regs, "Period": per_org_period.get(org, "")}
                          for org, regs in per_org.items()}

                # Подтянем имена организаций из локальной БД
                local_orgs = {
                    o.external_ref: o.name
                    for o in (await self.session.execute(
                        select(Organization).where(
                            Organization.company_id == connection.company_id,
                            Organization.external_ref.is_not(None),
                        )
                    )).scalars().all()
                    if o.external_ref
                }

                # ── Чистка старых снимков политики (одна запись на организацию)
                from sqlalchemy import delete
                if latest:
                    await self.session.execute(
                        delete(OneCPolicy).where(
                            OneCPolicy.company_id == connection.company_id,
                            OneCPolicy.organization_external_ref.in_(list(latest.keys())),
                        )
                    )

                for org_ref, raw in latest.items():
                    period_iso = str(raw.get("Period") or "")[:19]
                    # Достаём плоские поля из всех регистров — _find() сканирует
                    # все регистры и возвращает первое значимое значение по списку имён.
                    regs_data: dict[str, dict[str, Any]] = raw.get("_per_register") or {}
                    def _find(*field_names: str, allow_false: bool = False) -> Any:
                        for r in regs_data.values():
                            for fn in field_names:
                                v = r.get(fn)
                                if v is None or v == "":
                                    continue
                                if not allow_false and v is False:
                                    continue
                                return v
                        return None
                    # МПЗ (Способ оценки) — нет в БП ГИГ, default null
                    mpz_val = _find("СпособОценкиМПЗ", "СпособОценкиЗапасов", "СпособОценкиМПЗПостроки")
                    # Система налогообложения: в БП 3.0.194 определяется по флагам
                    # НастройкиСистемыНалогообложения.{ПлательщикНДС, ПлательщикНалогаНаПрибыль, ПрименяетсяУСН}
                    plat_nds = _find("ПлательщикНДС")
                    plat_pribyl = _find("ПлательщикНалогаНаПрибыль")
                    primen_usn = _find("ПрименяетсяУСН", "ПрименяетсяУпрощеннаяСистемаНалогообложения")
                    primen_osn = _find("ПрименяетсяОбщаяСистемаНалогообложения", "ПрименяетсяОСН")
                    sys_enum = _find("СистемаНалогообложения", "ТипНалогообложения")
                    tax_system = (
                        "УСН" if primen_usn else
                        "ОСН" if (primen_osn or (plat_nds and plat_pribyl)) else
                        (str(sys_enum) if sys_enum else None)
                    )
                    # Ставка налога на прибыль = СтавкаФБ + СтавкаСубъектРФ
                    stavka_fb = _find("СтавкаФБ", "СтавкаНалогаНаПрибыльФБ")
                    stavka_sub = _find("СтавкаСубъектРФ", "СтавкаНалогаНаПрибыльСубъектРФ")
                    profit_rate = None
                    if stavka_fb is not None or stavka_sub is not None:
                        try:
                            profit_rate = f"{float(stavka_fb or 0) + float(stavka_sub or 0):.0f}%"
                        except (TypeError, ValueError):
                            pass
                    # Ставка НДС: явная или 22% дефолт для ОСН с НДС
                    vat = _find("СтавкаНДС", "ОсновнаяСтавкаНДС", "СтавкаНДСОсновная")
                    vat_rate = str(vat) if vat else (
                        f"НДС 22% / Прибыль {profit_rate}" if profit_rate and plat_nds else
                        (profit_rate if profit_rate else None)
                    )
                    flat = {
                        "mpz_method": str(mpz_val) if mpz_val else None,
                        "tax_system": tax_system,
                        "vat_rate": vat_rate,
                        # bool флаги — пробуем найти ИСТИНУ в любой записи
                        "pbu_18_02": bool(_find("ПоддержкаПБУ18", "ПрименяетсяПБУ18", "ПрименяетсяПБУ_18_02", "ПрименяетсяПБУ18_02", "УчитыватьРазницыПБУ18")),
                        "separate_vat_accounting": bool(_find("ВедетсяРаздельныйУчетНДС", "РаздельныйУчетНДС", "ВестиРаздельныйУчетНДС", "ВедетсяРаздельныйУчет")),
                    }
                    self.session.add(OneCPolicy(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        organization_external_ref=org_ref,
                        organization_name=local_orgs.get(org_ref),
                        period=period_iso,
                        settings=raw,
                        **flat,
                    ))
                    details["policies"] += 1
                details["organizations"] = len(latest)
            await self._finish_log(log, "completed", details)
        except Exception as exc:
            await self._finish_log(log, "error", {"error": f"{type(exc).__name__}: {exc}", **details})
            raise
        return log

    async def sync_prices(self, connection: OneCConnection) -> OneCSyncLog:
        """Pull цен номенклатуры из БП ГИГ.

        Источники (БП 3.0):
          1. РегС.ЦеныНоменклатуры — справочные цены (измерения ТипЦен+Номенклатура)
             Часто пуст или содержит мало записей — используется опционально.
          2. РегС.ЦеныНоменклатурыДокументов — ФАКТИЧЕСКИЕ цены из ПТУ.
             Каждое поступление пишет сюда цену → история закупочных цен.
        """
        log = await self._start_log(connection, sync_type="prices")
        details: dict[str, Any] = {"prices": 0, "skipped": 0, "from_catalog": 0, "from_documents": 0}
        try:
            async with await self._open_client(connection) as client:
                # ── чистим старые цены этой компании
                from sqlalchemy import delete
                await self.session.execute(
                    delete(NomenclaturePrice).where(NomenclaturePrice.company_id == connection.company_id)
                )

                nom_names = {
                    n.external_ref: n.name
                    for n in (await self.session.execute(
                        select(NomenclatureItem).where(
                            NomenclatureItem.company_id == connection.company_id,
                            NomenclatureItem.external_ref.is_not(None),
                        )
                    )).scalars().all()
                    if n.external_ref
                }
                # дедуп: (nom, price_type) → latest row
                latest: dict[tuple[str, str], dict[str, Any]] = {}

                # ── 1. РегС.ЦеныНоменклатуры (справочные)
                try:
                    d1 = await client.describe_entity("InformationRegister_ЦеныНоменклатуры")
                    avail = set(d1.get("dimensions", []) + d1.get("resources", []) + d1.get("attributes", []))
                    # В БП 3.0 измерение называется ТипЦен (НЕ ВидЦены)
                    type_field = next((x for x in ("ТипЦен", "ВидЦены") if x in avail), None)
                    fields = ["Period", "Номенклатура_Key"]
                    if type_field:
                        fields.append(f"{type_field}_Key")
                    if "Цена" in avail:
                        fields.append("Цена")
                    if "Валюта" in avail:
                        fields.append("Валюта_Key")
                    rows = await client.fetch_entity("InformationRegister_ЦеныНоменклатуры", select=fields, orderby="Period")
                    for r in rows:
                        nom = str(r.get("Номенклатура_Key") or "")
                        if not nom:
                            details["skipped"] += 1
                            continue
                        pt = str(r.get(f"{type_field}_Key") or "") if type_field else "catalog"
                        if not pt:
                            pt = "catalog"
                        key = (nom, f"catalog:{pt}")
                        cur = latest.get(key)
                        if cur is None or str(r.get("Period") or "") > str(cur.get("Period") or ""):
                            r["_source"] = "catalog"
                            r["_pt_name"] = "Справочная"
                            latest[key] = r
                    details["from_catalog"] = sum(1 for k in latest if k[1].startswith("catalog"))
                except Exception as e:
                    details.setdefault("warnings", []).append(f"ЦеныНоменклатуры: {type(e).__name__}: {e}")

                # ── 2. РегС.ЦеныНоменклатурыДокументов (фактические цены)
                # НЕЗАВИСИМЫЙ регистр в БП 3.0 — без Period/Recorder.
                # Измерения: Номенклатура + СпособЗаполненияЦены.
                # Это закупочные цены из ПТУ + установленные вручную.
                try:
                    d2 = await client.describe_entity("InformationRegister_ЦеныНоменклатурыДокументов")
                    avail2 = set(d2.get("dimensions", []) + d2.get("resources", []) + d2.get("attributes", []))
                    fields2 = []
                    nom_dim = next((x for x in ("Номенклатура",) if x in avail2), None)
                    if not nom_dim:
                        raise OneCError("Нет измерения Номенклатура")
                    fields2.append(f"{nom_dim}_Key")
                    sposob_dim = next((x for x in ("СпособЗаполненияЦены",) if x in avail2), None)
                    if sposob_dim:
                        fields2.append(f"{sposob_dim}_Key")
                    for f in ("Цена", "ЦенаВключаетНДС", "Стоимость"):
                        if f in avail2:
                            fields2.append(f)
                    if "Валюта" in avail2:
                        fields2.append("Валюта_Key")
                    rows2 = await client.fetch_entity(
                        "InformationRegister_ЦеныНоменклатурыДокументов",
                        select=fields2,
                    )
                    # Дедуп по (nom, sposob) — последняя запись (нет даты, перекрытие любое)
                    for r in rows2:
                        nom = str(r.get("Номенклатура_Key") or "")
                        if not nom:
                            details["skipped"] += 1
                            continue
                        sposob = str(r.get("СпособЗаполненияЦены_Key") or "default") if sposob_dim else "default"
                        key = (nom, f"documents:{sposob}")
                        r["_source"] = "documents"
                        r["_pt_name"] = "Закупочная (документы)"
                        latest[key] = r  # перекрываем — берём последнее
                    details["from_documents"] = sum(1 for k in latest if k[1].startswith("documents"))
                except Exception as e:
                    details.setdefault("warnings", []).append(f"ЦеныНоменклатурыДокументов: {type(e).__name__}: {str(e)[:200]}")

                # ── INSERT
                for (nom, pt), raw in latest.items():
                    period_iso = str(raw.get("Period") or "")[:19]
                    price_val = float(raw.get("Цена") or raw.get("Стоимость") or 0.0)
                    self.session.add(NomenclaturePrice(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        nomenclature_ref=nom,
                        nomenclature_name=nom_names.get(nom),
                        price_type_ref=pt,
                        price_type_name=raw.get("_pt_name"),
                        period=period_iso,
                        price=price_val,
                        currency="RUB",
                    ))
                    details["prices"] += 1
            await self._finish_log(log, "completed", details)
        except Exception as exc:
            await self._finish_log(log, "error", {"error": f"{type(exc).__name__}: {exc}", **details})
            raise
        return log

    async def sync_batches(self, connection: OneCConnection) -> OneCSyncLog:
        """Pull остатков партий товаров (FIFO) из БП ГИГ.

        Источник — РегистрНакопления.ПартииТоваровНаСкладах. Берём всё
        активные движения (Период не фильтруем — текущая суммарная позиция).
        Берём НЕ виртуальную «Остатки» (её COM-доступ требует параметров),
        а сами движения и суммируем приход − расход в Python."""
        log = await self._start_log(connection, sync_type="batches")
        details: dict[str, Any] = {"raw_movements": 0, "batches": 0, "skipped_empty": 0}
        try:
            async with await self._open_client(connection) as client:
                # Для РегистраНакопления Period это поле документа, а ВидДвижения —
                # перечисление {Приход, Расход}. Берём количество и сумму со знаком.
                # Поиск регистра партий. В БП 3.0 партионный учёт ОПЦИОНАЛЕН
                # и в дефолтной конфигурации (ГИГ-стиль) обычно ВЫКЛЮЧЕН.
                # Если регистра партий нет — fallback на ТоварыНаСкладах (остатки без FIFO).
                batch_entity = None
                describe: dict[str, list[str]] = {}
                fallback_source = None
                for cand in (
                    "AccumulationRegister_ПартииТоваровНаСкладах",
                    "AccumulationRegister_ПартииТоваров",
                    "AccumulationRegister_ПартииТоваровБухгалтерскийУчет",
                ):
                    try:
                        describe = await client.describe_entity(cand)
                        batch_entity = cand
                        break
                    except Exception:
                        continue
                if not batch_entity:
                    # Fallback: ТоварыНаСкладах — остатки без партий
                    for cand in (
                        "AccumulationRegister_ТоварыНаСкладах",
                        "AccumulationRegister_ТоварыОрганизаций",
                    ):
                        try:
                            describe = await client.describe_entity(cand)
                            batch_entity = cand
                            fallback_source = cand.replace("AccumulationRegister_", "")
                            break
                        except Exception:
                            continue
                if not batch_entity:
                    details["info"] = (
                        "Партионный учёт в БП ГИГ не ведётся, и регистр ТоварыНаСкладах недоступен. "
                        "Для ГИГ типична работа без партий (БП 3.0 базовая поставка, не Управление торговлей). "
                        "Раздел остаётся пустым — это нормальное состояние."
                    )
                    await self._finish_log(log, "completed", details)
                    return log
                details["fallback_source"] = fallback_source
                avail = set(describe.get("dimensions", []) + describe.get("resources", []) + describe.get("attributes", []))
                details["batch_entity"] = batch_entity
                # Минимум: Period, Recorder, Номенклатура. Остальное — что есть.
                fields = ["Period", "Recorder_Key", "Номенклатура_Key", "ВидДвижения"]
                for f in ("Склад", "Организация"):
                    if f in avail:
                        fields.append(f + "_Key")
                for f in ("Количество", "Стоимость", "Сумма"):
                    if f in avail:
                        fields.append(f)
                rows = await client.fetch_entity(batch_entity, select=fields)
                details["raw_movements"] = len(rows)

                # Группировка: (батч, ном, склад) → накопленный остаток.
                agg: dict[tuple, dict[str, Any]] = {}
                for r in rows:
                    batch_ref = str(r.get("Recorder_Key") or "")
                    nom = str(r.get("Номенклатура_Key") or "")
                    wh = str(r.get("Склад_Key") or "")
                    org = str(r.get("Организация_Key") or "")
                    if not batch_ref or not nom:
                        continue
                    key = (batch_ref, nom, wh)
                    qty = float(r.get("Количество") or 0.0)
                    # Стоимость / Сумма — в разных версиях именуется по-разному
                    amt = float(r.get("Стоимость") or r.get("Сумма") or 0.0)
                    # ВидДвижения: 'Приход' (+) / 'Расход' (−).
                    vd = str(r.get("ВидДвижения") or "")
                    sign = -1.0 if "Расход" in vd else 1.0
                    bucket = agg.setdefault(key, {
                        "batch_doc_ref": batch_ref,
                        "nomenclature_ref": nom,
                        "warehouse_ref": wh or None,
                        "organization_ref": org or None,
                        "qty": 0.0,
                        "amt": 0.0,
                    })
                    bucket["qty"] += sign * qty
                    bucket["amt"] += sign * amt

                # Имена номенклатуры и складов из локальной БД.
                nom_names = {
                    n.external_ref: n.name
                    for n in (await self.session.execute(
                        select(NomenclatureItem).where(
                            NomenclatureItem.company_id == connection.company_id,
                            NomenclatureItem.external_ref.is_not(None),
                        )
                    )).scalars().all()
                    if n.external_ref
                }
                wh_names = {
                    w.external_ref: w.name
                    for w in (await self.session.execute(
                        select(Warehouse).where(
                            Warehouse.company_id == connection.company_id,
                            Warehouse.external_ref.is_not(None),
                        )
                    )).scalars().all()
                    if w.external_ref
                }

                # Чистка предыдущего среза перед перезаписью (все источники).
                from sqlalchemy import delete
                await self.session.execute(
                    delete(InventoryBatch).where(
                        InventoryBatch.company_id == connection.company_id,
                    )
                )

                source_label = "register" if not fallback_source else f"fallback:{fallback_source}"
                for bucket in agg.values():
                    qty = round(bucket["qty"], 4)
                    if abs(qty) < 1e-4:
                        details["skipped_empty"] += 1
                        continue
                    amt = round(bucket["amt"], 2)
                    self.session.add(InventoryBatch(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        batch_doc_type=None,
                        batch_doc_ref=bucket["batch_doc_ref"],
                        nomenclature_ref=bucket["nomenclature_ref"],
                        nomenclature_name=nom_names.get(bucket["nomenclature_ref"]),
                        warehouse_ref=bucket["warehouse_ref"],
                        warehouse_name=wh_names.get(bucket["warehouse_ref"]) if bucket["warehouse_ref"] else None,
                        organization_ref=bucket["organization_ref"],
                        quantity_remaining=qty,
                        amount_remaining=amt,
                        unit_price=round(amt / qty, 4) if abs(qty) > 1e-4 else None,
                        source=source_label,
                    ))
                    details["batches"] += 1
            await self._finish_log(log, "completed", details)
        except Exception as exc:
            await self._finish_log(log, "error", {"error": f"{type(exc).__name__}: {exc}", **details})
            raise
        return log

    async def sync_documents(self, connection: OneCConnection) -> OneCSyncLog:
        """Pull шапок документов БП ГИГ в AccountingDoc.

        Покрывает четыре ключевых типа для GIG Ledger:
        - ПТУ (поступление от поставщиков)
        - ОРП (отчёт о розничных продажах)
        - ОПЗС (отчёт производства за смену — общепит)
        - КорректировкаПоступления (возвраты/правки в БП 3.0)

        Идемпотентно: upsert по external_id = Ref_Key. Имена контрагента
        и организации подтягиваются из локальной БД по external_ref
        (по дизайну, сначала надо запустить sync_catalogs).
        Фильтр по checkpoint появится в следующем шаге — пока берём
        ограниченное окно от last_sync_at (если задано) или 100 свежих.
        """
        log = await self._start_log(connection, sync_type="documents")
        details: dict[str, Any] = {}
        try:
            async with await self._open_client(connection) as client:
                # Прежде чем грузить документы — построим карту GUID→имя из локальной БД.
                local_cp = await self._build_local_index(Counterparty, connection.company_id)
                local_org = await self._build_local_index(Organization, connection.company_id)
                # Для склада берём code (≤ 20 символов в БД), не name.
                local_wh = await self._build_local_index(Warehouse, connection.company_id, by="code")

                for entity, doc_type in [
                    (ENTITY_DOC_PTU,        "ПТУ"),
                    (ENTITY_DOC_ORP,        "ОРП"),
                    (ENTITY_DOC_OPZS,       "ОПЗС"),
                    (ENTITY_DOC_CORRECTION, "КорректировкаПоступления"),
                    # Связанные с ОРП документы — перемещения на виртуальные
                    # склады (Талоны/Карты/Ведомости/Яндекс) и списания
                    # «по прочие». Регистратором ОРП они не являются, но
                    # привязаны к нему через Склад+Дата (один день).
                    (ENTITY_DOC_TRANSFER,   "ПеремещениеТоваров"),
                    (ENTITY_DOC_WRITEOFF,   "СписаниеТоваров"),
                ]:
                    details[doc_type] = await self._sync_doc_type(
                        client=client,
                        connection=connection,
                        log=log,
                        entity=entity,
                        doc_type=doc_type,
                        local_cp=local_cp,
                        local_org=local_org,
                        local_wh=local_wh,
                    )
            # Auto-link L3↔L4: после sync пытаемся связать acked-пакеты без
            # target_doc_id с только что обновлёнными AccountingDoc.
            linked = await self._autolink_acked_packets(connection.company_id)
            if linked:
                details["autolink_l3_l4"] = linked

            await self._finish_log(log, "completed", details)
        except Exception as exc:
            await self._finish_log(log, "error", {"error": f"{type(exc).__name__}: {exc}", **details})
            raise
        return log

    async def _autolink_acked_packets(self, company_id: Any) -> dict[str, int]:
        """Acked ExportPackets без target_doc_id ищут себе AccountingDoc по
        composite key из payload.marker.

        Соответствие kind → правило поиска:
          shift_orp:   AccountingDoc.date startswith payload.date AND
                       warehouse_code == payload.station_code AND
                       abs(amount - payload.total_amount) < 0.05 AND
                       doc_type='ОРП'
          purchase_ttn: external_number == payload.ttn_number AND
                        external_date startswith payload.ttn_date AND
                        doc_type='ПТУ'"""
        from app.models import AccountingDoc, ExportPacket
        stats = {"matched": 0, "skipped": 0}
        packets = (await self.session.execute(
            select(ExportPacket).where(
                ExportPacket.company_id == company_id,
                ExportPacket.status == "acked",
                ExportPacket.target_doc_id.is_(None),
            )
        )).scalars().all()
        for p in packets:
            payload = p.payload or {}
            doc = None
            if p.kind == "shift_orp":
                date = payload.get("date") or ""
                station = payload.get("station_code") or ""
                total = float(payload.get("total_amount") or 0)
                if date and station:
                    candidates = (await self.session.execute(
                        select(AccountingDoc).where(
                            AccountingDoc.company_id == company_id,
                            AccountingDoc.doc_type == "ОРП",
                            AccountingDoc.date == date,
                            AccountingDoc.warehouse_code == station,
                        )
                    )).scalars().all()
                    # Выбираем по близости суммы
                    if candidates:
                        candidates.sort(key=lambda c: abs((c.amount or 0) - total))
                        if abs((candidates[0].amount or 0) - total) < 0.05:
                            doc = candidates[0]
            elif p.kind == "purchase_ttn":
                ttn_no = payload.get("ttn_number") or ""
                ttn_date = (payload.get("ttn_date") or "")[:10]
                if ttn_no:
                    doc = (await self.session.execute(
                        select(AccountingDoc).where(
                            AccountingDoc.company_id == company_id,
                            AccountingDoc.doc_type == "ПТУ",
                            AccountingDoc.external_number == ttn_no,
                            *([AccountingDoc.external_date == ttn_date] if ttn_date else []),
                        ).limit(1)
                    )).scalar_one_or_none()
            if doc is not None:
                p.target_doc_id = doc.id
                stats["matched"] += 1
            else:
                stats["skipped"] += 1
        if stats["matched"]:
            await self.session.flush()
        return stats

    async def _build_local_index(
        self, model: type, company_id: Any, *, by: str = "name"
    ) -> dict[str, str]:
        """{external_ref → attribute} для подстановки имени или кода."""
        rows = (await self.session.execute(
            select(model).where(
                model.company_id == company_id,
                model.external_ref.is_not(None),
            )
        )).scalars().all()
        return {r.external_ref: getattr(r, by) for r in rows if r.external_ref}

    async def _build_inn_index(self, model: type, company_id: Any) -> dict[str, str]:
        """{external_ref → ИНН} для подстановки в counterparty_inn AccountingDoc.
        Нужен для композитного ключа сверки ТТН-файл ↔ ПТУ."""
        rows = (await self.session.execute(
            select(model).where(
                model.company_id == company_id,
                model.external_ref.is_not(None),
            )
        )).scalars().all()
        return {r.external_ref: (r.inn or "").strip() for r in rows if r.external_ref and (r.inn or "").strip()}

    async def _build_period_index(self, company_id: Any) -> dict[tuple[int, int], str]:
        """{(year, month) → status} — кэш статусов периодов для компании.
        Используется при sync_documents чтобы проставить period_status каждому
        AccountingDoc одним запросом, а не N+1."""
        rows = (await self.session.execute(
            select(Period.year, Period.month, Period.status).where(
                Period.company_id == company_id,
            )
        )).all()
        return {(int(y), int(m)): (s or "open") for y, m, s in rows}

    @staticmethod
    def _lookup_period_status(
        period_index: dict[tuple[int, int], str], date_str: str,
    ) -> str:
        """Период не заведён в БД ⇒ считаем открытым. Это безопасный дефолт —
        бухгалтер заведёт периоды через UI /1c/periods, и тогда статус
        пересчитается в фоне (см. §7a.5 спецификации)."""
        if not date_str or len(date_str) < 7:
            return "open"
        try:
            y, m = int(date_str[:4]), int(date_str[5:7])
        except ValueError:
            return "open"
        return period_index.get((y, m), "open")

    async def _sync_doc_type(
        self,
        *,
        client: Any,
        connection: OneCConnection,
        log: OneCSyncLog,
        entity: str,
        doc_type: str,
        local_cp: dict[str, str],
        local_org: dict[str, str],
        local_wh: dict[str, str],
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}

        # Локальный индекс периодов (year,month) → status. Заполняется один раз
        # на компанию и используется для проставления period_status каждому
        # документу без N+1 запросов.
        period_index = await self._build_period_index(connection.company_id)

        # Локальный индекс ИНН контрагентов для заполнения counterparty_inn
        # без дополнительного round-trip (нужен для композитного ключа сверки ТТН).
        local_cp_inn = await self._build_inn_index(Counterparty, connection.company_id)

        # Шапки документов БП 3.0 — поля заметно различаются между типами.
        # СуммаДокумента — у ПТУ/ОРП/КП/Списание; ОПЗС (производство) и
        # ПеремещениеТоваров её не имеют (расчёт идёт из ТЧ).
        # СуммаНДС в шапке ПТУ ОТСУТСТВУЕТ (только в ТЧ Товары/Услуги).
        select_fields = ["Ref_Key", "DeletionMark", "Posted", "Number", "Date"]
        has_amount = entity in (
            ENTITY_DOC_PTU, ENTITY_DOC_ORP, ENTITY_DOC_CORRECTION,
            ENTITY_DOC_WRITEOFF,
        )
        if has_amount:
            select_fields.append("СуммаДокумента")
        if entity in (ENTITY_DOC_PTU, ENTITY_DOC_CORRECTION):
            select_fields.extend([
                "Контрагент_Key",
                "Договор_Key",
                "НомерВходящегоДокумента",
                "ДатаВходящегоДокумента",
                "СуммаВключаетНДС",
            ])
        # ВидОперации есть у всех типов — критичен для интерпретации проводок.
        select_fields.append("ВидОперации")
        select_fields.append("Организация_Key")
        if entity in (ENTITY_DOC_PTU, ENTITY_DOC_ORP, ENTITY_DOC_WRITEOFF):
            select_fields.append("Склад_Key")
        # У ПеремещениеТоваров склад зовётся СкладОтправитель — пока не тянем
        # (нет соответствующего поля в AccountingDoc; для UI «связанные доки»
        # склад берётся из шапки ОРП, а перемещение приземляется по дате+док-типу).

        filter_expr: str | None = None
        if connection.last_sync_at:
            ts = connection.last_sync_at.strftime("%Y-%m-%dT%H:%M:%S")
            filter_expr = f"Date ge datetime'{ts}'"

        async for item in client.iter_entity(entity, select=select_fields, filter_expr=filter_expr, orderby="Ref_Key", page_size=500):
            stats["processed"] += 1
            if item.get("DeletionMark"):
                stats["skipped"] += 1
                continue
            ref_key = item.get("Ref_Key")
            if not ref_key:
                stats["errors"] += 1
                continue
            try:
                existing = (await self.session.execute(
                    select(AccountingDoc).where(
                        AccountingDoc.company_id == connection.company_id,
                        AccountingDoc.external_id == ref_key,
                    )
                )).scalar_one_or_none()

                cp_key = item.get("Контрагент_Key")
                org_key = item.get("Организация_Key")
                wh_key = item.get("Склад_Key")
                cp_name = local_cp.get(cp_key, "") if cp_key else ""
                org_name = local_org.get(org_key, "") if org_key else ""
                wh_code = (local_wh.get(wh_key, "") or "")[:20] if wh_key else None

                number = str(item.get("Number") or "").strip() or ref_key[:8]
                # AccountingDoc.date — VARCHAR(20). ISO-datetime занимает 25
                # символов, обрезаем до даты "YYYY-MM-DD" (10 символов).
                date_str = str(item.get("Date") or "").strip()[:10]
                amount = float(item.get("СуммаДокумента") or 0) if has_amount else 0.0
                # vat_amount берётся через ТЧ/проводки на следующем шаге
                # (см. docs/sverka-spec.md §3.2 — ленивая загрузка ТЧ).
                vat_amount = None
                status_1c = "Проведён" if item.get("Posted") else "Записан"

                # Новые поля шапки для сверки (см. docs/sverka-spec.md):
                op_type = (item.get("ВидОперации") or "").strip()[:100] or None
                ext_number = (item.get("НомерВходящегоДокумента") or "").strip()[:200] or None
                ext_date = (item.get("ДатаВходящегоДокумента") or "").strip()[:10] or None
                cp_inn = local_cp_inn.get(cp_key) if cp_key else None

                # period_status — статус месяца этого документа.
                p_status = self._lookup_period_status(period_index, date_str)

                if existing is None:
                    self.session.add(AccountingDoc(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        external_id=ref_key,
                        doc_type=doc_type,
                        number=number,
                        date=date_str,
                        counterparty_name=cp_name,
                        counterparty_inn=cp_inn,
                        organization_name=org_name or None,
                        amount=amount,
                        vat_amount=vat_amount,
                        status_1c=status_1c,
                        warehouse_code=wh_code,
                        lines=[],
                        external_number=ext_number,
                        external_date=ext_date,
                        operation_type=op_type,
                        period_status=p_status,
                        discrepancy_status="pending",
                    ))
                    stats["created"] += 1
                else:
                    existing.number = number
                    existing.date = date_str
                    existing.counterparty_name = cp_name or existing.counterparty_name
                    existing.counterparty_inn = cp_inn or existing.counterparty_inn
                    existing.organization_name = org_name or existing.organization_name
                    existing.amount = amount
                    if vat_amount is not None:
                        existing.vat_amount = vat_amount
                    existing.external_number = ext_number or existing.external_number
                    existing.external_date = ext_date or existing.external_date
                    existing.operation_type = op_type or existing.operation_type
                    existing.period_status = p_status
                    existing.status_1c = status_1c
                    if wh_code:
                        existing.warehouse_code = wh_code
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                logger.warning("Doc %s upsert failed (Ref_Key=%s): %s", doc_type, ref_key, exc)

        self._merge_log_stats(log, stats)
        return stats

    # ─── upsert по каждой сущности ──────────────────────────────────

    async def _sync_counterparties(
        self,
        client: OneCODataClient,
        connection: OneCConnection,
        log: OneCSyncLog,
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
        async for item in client.iter_entity(ENTITY_COUNTERPARTIES, select=COUNTERPARTY_SELECT, orderby="Ref_Key", page_size=500):
            stats["processed"] += 1
            if item.get("DeletionMark"):
                stats["skipped"] += 1
                continue
            ref_key = item.get("Ref_Key")
            if not ref_key:
                stats["errors"] += 1
                continue
            try:
                existing = (await self.session.execute(
                    select(Counterparty).where(
                        Counterparty.company_id == connection.company_id,
                        Counterparty.external_ref == ref_key,
                    )
                )).scalar_one_or_none()
                if existing is None:
                    self.session.add(Counterparty(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        external_ref=ref_key,
                        name=(item.get("Description") or "").strip() or "(без названия)",
                        inn=(item.get("ИНН") or "").strip(),
                        kpp=((item.get("КПП") or "").strip() or None),
                    ))
                    stats["created"] += 1
                else:
                    existing.name = (item.get("Description") or existing.name).strip() or existing.name
                    existing.inn = (item.get("ИНН") or existing.inn or "").strip()
                    existing.kpp = ((item.get("КПП") or "").strip() or None) or existing.kpp
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                logger.warning("Counterparty upsert failed (Ref_Key=%s): %s", ref_key, exc)

        self._merge_log_stats(log, stats)
        return stats

    async def _sync_organizations(
        self,
        client: OneCODataClient,
        connection: OneCConnection,
        log: OneCSyncLog,
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
        async for item in client.iter_entity(ENTITY_ORGANIZATIONS, select=ORGANIZATION_SELECT, orderby="Ref_Key", page_size=500):
            stats["processed"] += 1
            if item.get("DeletionMark"):
                stats["skipped"] += 1
                continue
            ref_key = item.get("Ref_Key")
            if not ref_key:
                stats["errors"] += 1
                continue
            try:
                existing = (await self.session.execute(
                    select(Organization).where(
                        Organization.company_id == connection.company_id,
                        Organization.external_ref == ref_key,
                    )
                )).scalar_one_or_none()
                if existing is None:
                    self.session.add(Organization(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        external_ref=ref_key,
                        name=(item.get("Description") or "").strip() or "(без названия)",
                        inn=(item.get("ИНН") or "").strip(),
                        kpp=((item.get("КПП") or "").strip() or None),
                    ))
                    stats["created"] += 1
                else:
                    existing.name = (item.get("Description") or existing.name).strip() or existing.name
                    existing.inn = (item.get("ИНН") or existing.inn or "").strip()
                    existing.kpp = ((item.get("КПП") or "").strip() or None) or existing.kpp
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                logger.warning("Organization upsert failed (Ref_Key=%s): %s", ref_key, exc)

        self._merge_log_stats(log, stats)
        return stats

    async def _sync_warehouses(
        self,
        client: OneCODataClient,
        connection: OneCConnection,
        log: OneCSyncLog,
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
        async for item in client.iter_entity(ENTITY_WAREHOUSES, select=WAREHOUSE_SELECT, orderby="Ref_Key", page_size=500):
            stats["processed"] += 1
            if item.get("DeletionMark"):
                stats["skipped"] += 1
                continue
            ref_key = item.get("Ref_Key")
            if not ref_key:
                stats["errors"] += 1
                continue
            try:
                existing = (await self.session.execute(
                    select(Warehouse).where(
                        Warehouse.company_id == connection.company_id,
                        Warehouse.external_ref == ref_key,
                    )
                )).scalar_one_or_none()
                code = (item.get("Код") or "").strip() or ref_key[:8]
                name = (item.get("Description") or "").strip() or code
                if existing is None:
                    self.session.add(Warehouse(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        external_ref=ref_key,
                        code=code,
                        name=name,
                    ))
                    stats["created"] += 1
                else:
                    existing.code = code
                    existing.name = name
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                logger.warning("Warehouse upsert failed (Ref_Key=%s): %s", ref_key, exc)

        self._merge_log_stats(log, stats)
        return stats

    async def _sync_nomenclature(
        self,
        client: OneCODataClient,
        connection: OneCConnection,
        log: OneCSyncLog,
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
        async for item in client.iter_entity(ENTITY_NOMENCLATURE, select=NOMENCLATURE_SELECT, orderby="Ref_Key", page_size=500):
            stats["processed"] += 1
            if item.get("DeletionMark"):
                stats["skipped"] += 1
                continue
            ref_key = item.get("Ref_Key")
            if not ref_key:
                stats["errors"] += 1
                continue
            try:
                existing = (await self.session.execute(
                    select(NomenclatureItem).where(
                        NomenclatureItem.company_id == connection.company_id,
                        NomenclatureItem.external_ref == ref_key,
                    )
                )).scalar_one_or_none()
                code = (item.get("Артикул") or item.get("Код") or "").strip() or ref_key[:8]
                name = (item.get("Description") or "").strip() or code
                if existing is None:
                    self.session.add(NomenclatureItem(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        external_ref=ref_key,
                        code=code,
                        name=name,
                        unit="шт",
                        unit_label="штука",
                    ))
                    stats["created"] += 1
                else:
                    existing.code = code
                    existing.name = name
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                logger.warning("Nomenclature upsert failed (Ref_Key=%s): %s", ref_key, exc)

        self._merge_log_stats(log, stats)
        return stats

    @staticmethod
    def _merge_log_stats(log: OneCSyncLog, stats: dict[str, int]) -> None:
        log.items_processed += stats["processed"]
        log.items_created += stats["created"]
        log.items_updated += stats["updated"]
        log.items_errors += stats["errors"]
