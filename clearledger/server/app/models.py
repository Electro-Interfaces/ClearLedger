"""
SQLAlchemy 2.0 ORM модели TradeLedger.
Все первичные ключи — UUID (хранятся как PostgreSQL UUID).
"""

import uuid
from datetime import date as date_type, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------
class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    profile_id: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cloud_api_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Кастомизация профиля (JSONB)
    customization: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Связи
    users: Mapped[list["User"]] = relationship(back_populates="company")
    # Члены компании (M2M через user_companies) — источник истины прав доступа.
    members: Mapped[list["User"]] = relationship(
        secondary="user_companies", back_populates="companies", viewonly=False
    )
    entries: Mapped[list["DataEntry"]] = relationship(back_populates="company")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="company")
    connectors: Mapped[list["Connector"]] = relationship(back_populates="company")


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Компания по умолчанию (какую показать первой). Источник истины ПРАВ —
    # user_companies. Nullable: суперадмин может не иметь дефолтной компании.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    # Суперадмин видит и переключает ВСЕ компании без записей в user_companies.
    is_superadmin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Восстановление пароля по email: одноразовый токен (SHA256-хеш) + срок действия.
    reset_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reset_token_expires: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Presence чата: время последнего отключения WS (для «был(а) N мин назад»).
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Связи
    company: Mapped["Company | None"] = relationship(back_populates="users")
    # Доступные компании (M2M через user_companies).
    companies: Mapped[list["Company"]] = relationship(
        secondary="user_companies", back_populates="members", viewonly=False
    )


# ---------------------------------------------------------------------------
# UserCompany — членство пользователя в компании (M2M, источник истины прав)
# ---------------------------------------------------------------------------
class UserCompany(Base):
    __tablename__ = "user_companies"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Роль пользователя В ЭТОЙ компании: user | admin (роль-на-компанию).
    # server_default обязателен: backfill-INSERT миграции v2.0 не указывает role.
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user", server_default=text("'user'")
    )
    # RBAC: разрешённые модули доступа (ключи из access_catalog.ACCESS_KEYS).
    # NULL = полный доступ (admin, суперадмин, старые члены до миграции).
    # Список = доступны только перечисленные модули. Legacy-fallback, если role_id пуст.
    modules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Назначенная именованная роль доступа (company_roles). Приоритетнее modules.
    # NULL = ad-hoc (см. modules) или admin (полный доступ).
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company_roles.id", ondelete="SET NULL"), nullable=True
    )
    # Должность сотрудника в этой компании (per-company).
    position: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # КТО этот человек для пространства. Права даёт role/role_id, а это — принадлежность:
    # в чатах, заявках и справочнике людей должно быть видно, с кем разговариваешь.
    #   internal — свой сотрудник компании;
    #   partner  — внешний участник (подрядчик, поставщик, представитель заказчика);
    #   vendor   — инженер разработчика платформы: поддержка самого пространства.
    party_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", server_default=text("'internal'")
    )
    # Какую организацию представляет внешний участник (карточка юрлица пространства).
    # Для своих сотрудников NULL — их организация и есть компания пространства.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True
    )
    # СКОУП ДАННЫХ: объекты пространства (`service_locations.id`), которые человек видит.
    # NULL = вся сеть компании; список = только эти объекты и всё, что к ним привязано
    # (сессии, оборудование, заявки). Права (`modules`) отвечают на вопрос «какие
    # экраны», скоуп — «по каким объектам»: подрядчику нужен «Парк оборудования», но
    # только на своих пяти станциях. Механика — `app/scope.py`.
    object_scope: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # ОСНОВАНИЕ: договоры (`contracts.id`), по которым человек допущен в пространство.
    # Это справка, а не права — доступ даёт роль, а здесь видно, ЧЕМ он обоснован:
    # у подрядчика это его договор обслуживания. Список, потому что оснований бывает
    # несколько (рамочный плюс на объект); NULL или пусто — основание не указано.
    contract_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# CompanyRole — именованная роль доступа per-компания (hybrid RBAC)
# ---------------------------------------------------------------------------
class CompanyRole(Base):
    __tablename__ = "company_roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Набор модулей доступа. NULL = все модули (полный доступ).
    modules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Системная роль (сид из пресетов): нельзя удалять/переименовывать.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Invitation — приглашение сотрудника в компанию по email
# ---------------------------------------------------------------------------
class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user", server_default=text("'user'")
    )
    position: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Кем человек войдёт в пространство: свой сотрудник, представитель компании-партнёра
    # или инженер поддержки платформы. Принадлежность хранится В ПРИГЛАШЕНИИ, а не
    # ставится потом: партнёр, принявший приглашение, иначе попадал бы в список своих
    # сотрудников заказчика и терялся там до ручной пометки.
    party_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", server_default=text("'internal'")
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True
    )
    # SHA256 от сырого токена (сырой токен только в письме, в БД не хранится).
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # pending | accepted | revoked
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# DataEntry
# ---------------------------------------------------------------------------
class DataEntry(Base):
    __tablename__ = "data_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category_id: Mapped[str] = mapped_column(String(100), nullable=False)
    subcategory_id: Mapped[str] = mapped_column(String(100), nullable=False)
    doc_type_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    # Статус: new, recognized, verified, transferred, error, archived
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="new")

    # Источник: upload, photo, manual, api, email, oneC, whatsapp, telegram, paste
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    source_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # JSONB для произвольных метаданных (атрибут "meta" → колонка "metadata")
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # OCR данные (JSONB)
    ocr_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Слой данных (см. docs/sverka-spec.md §0):
    # 'raw' (L1) — сырьё из внешнего источника как пришло (status='new'|'recognized')
    # 'clean' (L2) — нормализовано бухгалтером/AI, готово к выгрузке (status='verified')
    # Поле упрощает фильтрацию вместо производной по status.
    layer: Mapped[str] = mapped_column(String(10), nullable=False, default="raw")

    # Lineage: какой raw-Entry породил этот clean-Entry (для diff L1↔L2).
    # NULL для raw-entries и для clean-entries без явной raw-предтечи.
    derived_from_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Связи
    company: Mapped["Company"] = relationship(back_populates="entries")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="entry")


# ---------------------------------------------------------------------------
# CbNomenclature — кеш НСИ номенклатуры ЦБ ЭЛСИ.АЗК (GUID → имя/атрибуты).
# GUID (Ref) из ЦБ ≠ external_ref зеркала БП, поэтому отдельная таблица.
# Наполняется скриптом enrich_cb_nomenclature_dev.py (fetch Catalog.Номенклатура).
# Джойнится по external_ref с GUID номенклатуры в продажах/закупках сопутки.
# ---------------------------------------------------------------------------
class CbNomenclature(Base):
    __tablename__ = "cb_nomenclature"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    external_ref: Mapped[str] = mapped_column(String(36), nullable=False)  # Ref (GUID) из ЦБ
    name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    article: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vat: Mapped[str | None] = mapped_column(String(20), nullable=True)        # «22%» / «10%» / …
    marked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    weighed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    group_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)  # НоменклатурнаяГруппа GUID
    kind_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)   # ВидНоменклатуры GUID
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)       # БазоваяЕдиницаИзмерения (шт/г/л)
    full_name: Mapped[str | None] = mapped_column(String(700), nullable=True) # НаименованиеПолное
    main_supplier: Mapped[str | None] = mapped_column(String(300), nullable=True)  # ОсновнойПоставщик (имя)
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)       # Код ЦБ (КодЦБ пакета, soft-match приёмника)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("uq_cb_nom_company_ref", "company_id", "external_ref", unique=True),)


# ---------------------------------------------------------------------------
# CbRef — универсальный кеш ссылок ЦБ (контрагенты, номенклатурные группы, …):
# GUID → имя. kind разделяет справочники. Для Приёмки/Поставщиков/Категорий.
# ---------------------------------------------------------------------------
class CbRef(Base):
    __tablename__ = "cb_ref"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # counterparty | nom_group | nom_kind | organization | warehouse
    external_ref: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # реквизиты для НСИ-секции пакета БП: organization → {full_name,inn,kpp,ogrn,okpo,jur_fiz};
    # warehouse → {code, kind_name}. Для остальных kind — NULL.
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (Index("uq_cb_ref_ck", "company_id", "kind", "external_ref", unique=True),)


# ---------------------------------------------------------------------------
# CbBarcode — штрихкоды/EAN из РегистрСведений.Штрихкоды ЦБ (Штрихкод → товар).
# ---------------------------------------------------------------------------
class CbBarcode(Base):
    __tablename__ = "cb_barcode"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    barcode: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")  # имя товара
    owner_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)          # GUID (если извлечён)
    btype: Mapped[str | None] = mapped_column(String(30), nullable=True)              # EAN13 / EAN8 / Ручной
    main: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    __table_args__ = (Index("ix_cb_barcode_company", "company_id", "barcode"),)


# ---------------------------------------------------------------------------
# StockOnHand — достоверный остаток товара из регистров ЦБ ЭЛСИ.АЗК (снимок).
# Заменяет грубую оценку stock_est (закупка − продажи). Источник:
#   qty/retail_price/barcode — РегистрНакопления.ТоварыНаАЗК.Остатки (розничный зал);
#   cost_amount             — РегистрНакопления.ПартииТоваровНаСкладах.Остатки (Σ Стоимость).
# Грейн = склад × номенклатура. Наполняется скриптом pull_cb_stock_dev.py.
# Отрицательные остатки — норма для розничных АЗС (учёт по средней) → флаг negative.
# ---------------------------------------------------------------------------
class StockOnHand(Base):
    __tablename__ = "stock_on_hand"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    warehouse_code: Mapped[str] = mapped_column(String(20), nullable=False)   # код склада (208, 20800002)
    warehouse_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    nomenclature_ref: Mapped[str] = mapped_column(String(36), nullable=False)  # GUID номенклатуры ЦБ
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    retail_price: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)   # ЦенаВРознице
    cost_amount: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)    # (не используется)
    # Удельная себестоимость (закуп.) за БАЗОВУЮ единицу = ПартииТоваровНаСкладах
    # Стоимость/Количество — в тех же единицах, что и остаток (сигареты/блоки, весовые).
    cost_unit: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_stock_on_hand", "company_id", "warehouse_code", "nomenclature_ref", unique=True),
    )


# ---------------------------------------------------------------------------
# CbInventoryDoc — документы инвентаризации из ЦБ ЭЛСИ.АЗК (снимок, режим A).
# Реестр Document.ИнвентаризацияТоваровНаСкладе + агрегаты отклонений факт↔учёт
# (недостачи/излишки, shrinkage). Строки-отклонения — в lines (JSONB) для drill.
# Наполняется скриптом pull_cb_inventory_dev.py.
# ---------------------------------------------------------------------------
class CbInventoryDoc(Base):
    __tablename__ = "cb_inventory_doc"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    external_ref: Mapped[str] = mapped_column(String(36), nullable=False)  # GUID документа
    number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    doc_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ISO дата
    posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    fill_date: Mapped[str | None] = mapped_column(String(30), nullable=True)  # ДатаЗаполнения ISO (пакет БП)
    warehouse_code: Mapped[str] = mapped_column(String(20), nullable=False)
    warehouse_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Агрегаты отклонений (факт − учёт)
    dev_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shortage_qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)      # недостача, ед. (<0)
    shortage_amount: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)   # недостача, ₽ (<0)
    surplus_qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)       # излишки, ед. (>0)
    surplus_amount: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)    # излишки, ₽ (>0)
    net_amount: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)        # чистое отклонение, ₽
    # ВСЕ строки ТЧ Товары в порядке НомерСтроки (эмиттер БП: носитель факта, эталон
    # отдаёт полную ТЧ). [{n,ref,name,fact,uchet,price,amount,amount_uchet,dev,amount_dev}].
    # UI-дриллы отклонений фильтруют dev≠0 сами.
    lines: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_cb_inventory_doc", "company_id", "external_ref", unique=True),
    )


# ---------------------------------------------------------------------------
# CbMovementDoc — обобщённый документ товародвижения из ЦБ (снимок, режим A).
# kind: writeoff (СписаниеТоваров) | transfer (ПеремещениеТоваров) | …
# Реестр + строки (lines JSONB). Для списаний: reason/from_inventory; для
# перемещений: warehouse_to_*. Наполняется скриптами pull_cb_<kind>_dev.py.
# ---------------------------------------------------------------------------
class CbMovementDoc(Base):
    __tablename__ = "cb_movement_doc"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # writeoff | transfer
    external_ref: Mapped[str] = mapped_column(String(36), nullable=False)
    number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    doc_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    inventory_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)  # writeoff: GUID инвентаризации-основания
    warehouse_code: Mapped[str] = mapped_column(String(20), nullable=False)
    warehouse_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    warehouse_to_code: Mapped[str | None] = mapped_column(String(20), nullable=True)     # перемещение → получатель
    warehouse_to_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(60), nullable=True)                 # классификация (списания)
    from_inventory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_qty: Mapped[float] = mapped_column(Numeric(16, 3), nullable=False, default=0)
    total_amount: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    lines: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [{ref,name,qty,amount,price}]
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_cb_movement_doc", "company_id", "kind", "external_ref", unique=True),
        Index("ix_cb_movement_kind", "company_id", "kind"),
    )


# ---------------------------------------------------------------------------
# StorePlan — план продаж магазина (слой политик, О-1 план-факт-светофор).
# Ручной ввод руководителя в UI (дефолт по плану модернизации; альтернативы —
# импорт из БП / экстраполяция — задел на будущее). Гранулярность: период (месяц
# YYYY-MM) × разрез (scope_kind: total|category|station) × ключ (scope_key: имя
# категории / код АЗС / '*') × метрика (metric: revenue|margin|qty). Факт-сторона
# считается из продаж на лету; здесь хранится только план. Уникальность —
# на (company, period, scope_kind, scope_key, metric).
# ---------------------------------------------------------------------------
class StorePlan(Base):
    __tablename__ = "store_plan"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    period_ym: Mapped[str] = mapped_column(String(7), nullable=False)          # 'YYYY-MM'
    scope_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="total")  # total|category|station
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False, default="*")      # имя категории / код АЗС / '*'
    metric: Mapped[str] = mapped_column(String(20), nullable=False, default="revenue")    # revenue|margin|qty
    plan_value: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_store_plan", "company_id", "period_ym", "scope_kind", "scope_key", "metric", unique=True),
    )


# ---------------------------------------------------------------------------
# TobaccoMrc — справочник максимальных розничных цен (МРЦ) табака (О-3,
# регуляторный контроль: продажа выше МРЦ = нарушение). Источник — ручной
# CSV-импорт (дефолт по плану; ключ CSV — штрихкод GTIN → nomenclature_ref
# через CbBarcode, fallback артикул/имя). Далее — ЧЗ-фид. Одна строка =
# текущая МРЦ на SKU; valid_from — задел под историю.
# ---------------------------------------------------------------------------
class TobaccoMrc(Base):
    __tablename__ = "tobacco_mrc"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    nomenclature_ref: Mapped[str] = mapped_column(String(36), nullable=False)  # GUID номенклатуры ЦБ
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)       # имя из CSV (для сверки)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)     # GTIN, по которому смэтчили
    mrc: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)         # максимальная розничная цена
    valid_from: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ISO дата (задел под историю)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_tobacco_mrc", "company_id", "nomenclature_ref", unique=True),
    )


# ---------------------------------------------------------------------------
# AuditEvent
# ---------------------------------------------------------------------------
class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="SET NULL"), nullable=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    user_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Действие: created, verified, rejected, transferred, archived, restored,
    #   excluded, included, updated, version_created, exported,
    #   bulk_archived, bulk_excluded, connector_synced
    action: Mapped[str] = mapped_column(String(50), nullable=False)

    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Связи
    entry: Mapped["DataEntry | None"] = relationship(back_populates="audit_events")
    company: Mapped["Company"] = relationship(back_populates="audit_events")


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------
class Connector(Base):
    __tablename__ = "connectors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    # Статус: active, error, disabled
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")

    last_sync: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="idle"
    )

    records_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category_id: Mapped[str] = mapped_column(String(100), nullable=False)
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)

    # Произвольная конфигурация (JSONB)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Связи
    company: Mapped["Company"] = relationship(back_populates="connectors")


# ---------------------------------------------------------------------------
# SourceFile (uploaded files)
# ---------------------------------------------------------------------------
class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# DocumentLink
# ---------------------------------------------------------------------------
class DocumentLink(Base):
    __tablename__ = "document_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="CASCADE"), nullable=False
    )
    target_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="CASCADE"), nullable=False
    )
    link_type: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: Counterparty (Контрагенты)
# ---------------------------------------------------------------------------
class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    inn: Mapped[str] = mapped_column(String(20), nullable=False)
    kpp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False, default="ЮЛ")
    aliases: Mapped[list] = mapped_column(ARRAY(String), nullable=False, default=list)
    # Ref_Key из БП ГИГ (OData) — связка записей справочника с источником
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # v2.5: универсальный снимок ВСЕХ реквизитов источника (L1 RAW) + промо-колонки.
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    okpo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Полная карточка контрагента (ручной ввод для компаний без 1С + промо из raw)
    ogrn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    okved: Mapped[str | None] = mapped_column(String(20), nullable=True)
    legal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    director_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    director_position: Mapped[str | None] = mapped_column(String(150), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bank_bik: Mapped[str | None] = mapped_column(String(12), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Ref_Key головного контрагента (иерархия), если задан
    head_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Ось контрагента: external (внешний) | retail (служебный розничный) |
    # internal (наша организация для внутренних движений). См. TRADELEDGER_COUNTERPARTY_AXIS §6.
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="external", server_default=text("'external'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: Organization (Организации / Юрлица)
# ---------------------------------------------------------------------------
class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    inn: Mapped[str] = mapped_column(String(20), nullable=False)
    kpp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ogrn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    bank_account: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bank_bik: Mapped[str | None] = mapped_column(String(12), nullable=True)
    # Расширенные реквизиты — полная карточка организации БП 3.0
    # (заполняются вручную или из 1С). Группы: идентификация, гос.регистрация,
    # налоговая/фонды, адреса, контакты, ответственные лица.
    vid: Mapped[str | None] = mapped_column(String(40), nullable=True)            # ЮЛ / ИП / ОП / ФЛ
    full_name: Mapped[str | None] = mapped_column(String(500), nullable=True)     # полное наименование
    prefix: Mapped[str | None] = mapped_column(String(10), nullable=True)         # префикс
    okpo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Государственная регистрация
    reg_date: Mapped[str | None] = mapped_column(String(20), nullable=True)       # дата регистрации
    okved: Mapped[str | None] = mapped_column(String(20), nullable=True)
    oktmo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    okato: Mapped[str | None] = mapped_column(String(20), nullable=True)
    okopf: Mapped[str | None] = mapped_column(String(20), nullable=True)
    okfs: Mapped[str | None] = mapped_column(String(20), nullable=True)
    registration_cert: Mapped[str | None] = mapped_column(String(300), nullable=True)  # свидетельство о гос.рег.
    # Налоговый орган и фонды
    ifns_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ifns_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pfr_reg_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fss_reg_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fss_subordination: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Адреса и контакты
    legal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    postal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fax: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Ответственные лица
    director_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    director_position: Mapped[str | None] = mapped_column(String(150), nullable=True)
    accountant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cashier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: Nomenclature (Номенклатура)
# ---------------------------------------------------------------------------
class NomenclatureItem(Base):
    __tablename__ = "nomenclature"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_label: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    vat_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: Contract (Договоры)
# ---------------------------------------------------------------------------
class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[str] = mapped_column(String(20), nullable=False)
    counterparty_id: Mapped[str] = mapped_column(String(100), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    amount_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # v2.5: универсальный снимок ВСЕХ реквизитов 1С (L1 RAW) + промо-колонки.
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # ВидДоговора 1С: СПокупателем | СПоставщиком | СКомитентом | ... (см. SCHEMA_REFS_GIG §2)
    kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Полная карточка договора (ручной ввод + промо из raw)
    vat_rate: Mapped[str | None] = mapped_column(String(20), nullable=True)        # ставка НДС
    amount_incl_vat: Mapped[bool | None] = mapped_column(Boolean, nullable=True)   # сумма включает НДС
    settlement_kind: Mapped[str | None] = mapped_column(String(150), nullable=True)  # вид взаиморасчётов
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Основание обязательства (НАШ слой, v2.8): договор | разрешение | постановление |
    # приказ | сервитут. Для энергоснабжения/аренды РусГидро часть объектов стоит на
    # муниципальной земле по разрешению, а не по договору аренды. См.
    # SOURCE_CONTRACTS_PAYMENTS_RUSHYDRO.md §6.
    basis: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # СрокДействия (ISO-дата строкой) и ДоговорЗакрыт
    valid_until: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Охват договора по торговым точкам (НАШ слой, не из 1С):
    # company (вся компания) | locations (набор contract_locations) | unassigned (дефолт).
    # См. TRADELEDGER_COUNTERPARTY_AXIS §5, SCHEMA_REFS_GIG §2a.
    scope_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unassigned", server_default=text("'unassigned'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# ContractLocation (связь договор ↔ торговая точка — НАШ слой охвата)
# ---------------------------------------------------------------------------
# Заполняется только при Contract.scope_type='locations' (ad-hoc набор точек).
# Для 'company' (вся компания) и 'unassigned' — пусто. Точки контрагента =
# производное (объединение охватов его договоров). См.
# TRADELEDGER_COUNTERPARTY_AXIS §5, SCHEMA_REFS_GIG §2a.
# ---------------------------------------------------------------------------
class ContractLocation(Base):
    __tablename__ = "contract_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    location_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_contract_locations", "contract_id", "location_id", unique=True),
    )


# ---------------------------------------------------------------------------
# StationContractSettlement (платёжная дисциплина по станции × роль — v2.8)
# ---------------------------------------------------------------------------
# Платёжно-договорный слой реестра «Договоры и оплаты ЭЗС» (energy/РусГидро).
# Оплата фиксируется по СТРОКЕ реестра (станция × роль), т.к. один договор может
# покрывать несколько ЭЗС с разным статусом оплаты — поэтому статус живёт на
# связке станция↔роль, а не на договоре глобально. contract_id — мягкая ссылка
# (best-effort резолв; NULL если договор не сопоставлен). См.
# SOURCE_CONTRACTS_PAYMENTS_RUSHYDRO.md §5.
# ---------------------------------------------------------------------------
class StationContractSettlement(Base):
    __tablename__ = "station_contract_settlements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    location_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Роль контура обязательства: energy (энергоснабжение/закупка) | rent (аренда
    # земли/площадки) | service (сервисный договор на обслуживание ЭЗС).
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # Мягкая ссылка на договор (резолв по контрагент+номер+тип); NULL если не сопоставлен.
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # Контрагент строки (GUID 1С или наш UUID) — для отображения даже без договора.
    counterparty_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # «Оплачено по» — ISO-дата (метка 1-го числа месяца включительно), либо NULL.
    paid_through: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Статус оплаты: paid | unpaid | unknown | special (% от выручки/фикс/сервитут).
    payment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default=text("'unknown'")
    )
    # Основание (дублирует Contract.basis для отображения без джойна): договор|разрешение|...
    basis: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Проблемный комментарий реестра (не поступают документы, банкротство, демонтаж...).
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Снимок периода реестра (напр. '2026-06-01') — для будущей истории.
    period: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # v2.9 (реестры РусГидро): ежемесячная плата по договору (постоянная часть).
    amount_gross: Mapped[float | None] = mapped_column(Float, nullable=True)   # с НДС, руб/мес
    amount_net: Mapped[float | None] = mapped_column(Float, nullable=True)     # без НДС, руб/мес
    vat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)        # ставка НДС, %
    contract_start: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ISO-дата
    contract_end: Mapped[str | None] = mapped_column(String(20), nullable=True)    # ISO-дата
    # Прочие атрибуты источника (переменная часть, сроки оплаты, ср. тариф э/э,
    # единовременный платёж, вид деятельности, способ обмена...) — без жёстких колонок.
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Один текущий статус на станцию×роль (идемпотентный upsert реестра).
        Index("uq_station_settlement", "company_id", "location_id", "role", unique=True),
        Index("idx_station_settlement_status", "company_id", "role", "payment_status"),
    )


# ---------------------------------------------------------------------------
# StationEnergyPeriod (входящая э/э по станции × месяц — v2.9, РусГидро)
# ---------------------------------------------------------------------------
# Помесячный факт входящей электроэнергии по объекту: объём, который выставляют
# контрагенты (из «Сводной» реестра договоров), и входящий тариф руб/кВт·ч с НДС
# (из «Тарифы Электроэнергия_Входящие»). Слои приходят из РАЗНЫХ файлов канала
# reestr_contracts_payments — upsert по (company, location, period) не затирает
# чужое поле. Стоимость = intake_kwh × tariff_rub_kwh (считается на чтении).
# ---------------------------------------------------------------------------
class StationEnergyPeriod(Base):
    __tablename__ = "station_energy_periods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    location_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Первое число месяца ISO: '2026-06-01'.
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    # Объём входящей э/э за месяц, кВт·ч (выставлено контрагентом).
    intake_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Входящий тариф, руб/кВт·ч с НДС (помесячный, ведётся с июня 2026).
    tariff_rub_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_station_energy_period", "company_id", "location_id", "period", unique=True),
        Index("idx_station_energy_period", "company_id", "period"),
    )


# ---------------------------------------------------------------------------
# StationDispensePeriod (L2: ОТПУСК э/э станции помесячно — из сводной выработки)
# ---------------------------------------------------------------------------
# Симметрия StationEnergyPeriod (вход): помесячный отпуск кВт·ч и выручка ₽ по
# станции из ручной сводной контрагента («ОБЩАЯ_2024-2026», слот obshaya канала
# реестров). Гранулярность — тип коннектора; connector_type IS NULL = станционная
# строка (для станций без коннекторной детализации в файле). Сумма по станции =
# SUM всех её строк: коннекторные и станционные строки НЕ пересекаются (см.
# ingest_obshaya). Транзакционный отпуск 2026+ — charge_sessions; этот ряд даёт
# историю 2024–2025 и базу сверки на пересечении периодов.
# ---------------------------------------------------------------------------
class StationDispensePeriod(Base):
    __tablename__ = "station_dispense_periods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    location_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Первое число месяца ISO: '2024-03-01'.
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    # Тип коннектора (CCS2/CHADEMO/GBT_DC/...); NULL — станционная строка.
    connector_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Отпуск за месяц, кВт·ч (кВтч-листы ведутся с 03.2024).
    dispense_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Выручка за месяц, ₽ (₽-лист ведётся 01.2024–07.2025; дальше — сессии).
    amount_rub: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # '' вместо NULL в connector_type не используем: уникальность через COALESCE
        # не выразить штатным Index — ключ включает connector_type, NULL-строки
        # дедуплицируются в ingest (upsert через префетч-кеш).
        Index("idx_station_dispense_loc", "company_id", "location_id", "period"),
        Index("idx_station_dispense_period", "company_id", "period"),
    )


# ---------------------------------------------------------------------------
# ContractDimension (обобщённая грань ограничения договора по разрезу — Фаза 3)
# ---------------------------------------------------------------------------
# Договор может ограничиваться не только торговыми точками, но и другими
# разрезами учёта: номенклатура, канал/источник, статья ДДС и т.п. (план §5).
# Точки — отдельная типизированная грань (ContractLocation, строгий FK); прочие
# разрезы — здесь, полиморфно: dim_type + dim_ref (id/код/external_ref элемента).
# Семантика: есть записи для (договор, dim_type) → ограничен этим набором; нет
# записей → не ограничен по этому разрезу (= весь разрез). dim_ref мягкая ссылка
# (без FK на конкретную сущность — полиморфизм). См. TRADELEDGER_COUNTERPARTY_AXIS §5.
# ---------------------------------------------------------------------------
class ContractDimension(Base):
    __tablename__ = "contract_dimensions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # nomenclature | channel | dds_article | ... (location — отдельной таблицей)
    dim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # id / код / external_ref элемента разреза (Nomenclature.external_ref, Channel.id, …)
    dim_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_contract_dimensions", "contract_id", "dim_type", "dim_ref", unique=True),
        Index("idx_contract_dimensions_lookup", "company_id", "dim_type", "dim_ref"),
    )


# ---------------------------------------------------------------------------
# AccountingDoc (Учётные документы 1С)
# ---------------------------------------------------------------------------
class AccountingDoc(Base):
    __tablename__ = "accounting_docs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)  # GUID 1С
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    number: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[str] = mapped_column(String(20), nullable=False)
    counterparty_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    counterparty_inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    organization_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    vat_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status_1c: Mapped[str] = mapped_column(String(50), nullable=False, default="Проведён")
    lines: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    matched_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="SET NULL"), nullable=True
    )
    match_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    match_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warehouse_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Реквизиты входящего документа поставщика (ТТН №+дата).
    # Композитный ключ сверки ТТН-файл ↔ ПТУ —
    # (counterparty_inn + external_number + external_date + amount).
    external_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # ВидОперации из 1С — критичен для интерпретации проводок ОРП:
    # ОтчетККМОПродажах vs НТТО дают разные формулы НДС/выручки.
    operation_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Статус периода — кэш от Period.status на момент загрузки документа.
    # open | closed. В closed-периоде любое расхождение подсвечивается строже
    # (требование МАГ — см. docs/sverka-spec.md §7a).
    period_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="open"
    )
    # Состояние сверки этого документа с парной TradeLedger.DataEntry.
    # pending | none | rounding | minor | material | critical | unmatched
    discrepancy_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    # Короткая свёртка расхождений для строки таблицы UI.
    discrepancy_summary: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    # Полный список расхождений с формулами (см. §7a.3 спецификации).
    discrepancy_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# ReconcileMapping (маппинг внешний ключ → запись в БП ГИГ)
# ---------------------------------------------------------------------------
# Соответствия между ключами источников TradeLedger (station_id из STS,
# артикул топлива, код вида оплаты, артикул номенклатуры из ТТН-файла)
# и записями в Catalog.Склады / Catalog.Номенклатура / Catalog.ВидыОплат БП.
# Используется reconciliation_service для построчного матчинга
# (см. docs/sverka-spec.md §2.5 — каскад артикул → код → имя → AI).

# ---------------------------------------------------------------------------
# ExportPacket (L3 — что мы выгружаем в 1С)
# ---------------------------------------------------------------------------
# Пакет данных, подготовленный для загрузки в БП ГИГ через её расширение
# (TradeLedger.cfe тянет через HTTP API TradeLedger). Один пакет = один или
# несколько target-документов в 1С (агрегация смен в один ОРП, разделение
# ТТН на ПТУ+ПКО и т.п.). См. docs/sverka-spec.md §0.

class ExportPacket(Base):
    __tablename__ = "export_packets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Тип пакета — определяет какой документ ожидается в 1С на выходе.
    # 'shift_orp'   — смена АЗС → ОРП
    # 'purchase_ttn' — ТТН поставщика → ПТУ
    # 'cash_pko'    — кассовая операция → ПКО
    # 'production'  — общепит → ОПЗС
    # 'correction'  — корректировка поступления
    kind: Mapped[str] = mapped_column(String(30), nullable=False)

    # Натуральный ключ идемпотентности = КлючЗагрузки нативного пути .cfe
    # (например TL|СМЕНА|{system}|{station}|{shift}). Частичный UNIQUE-индекс
    # (company_id, idem_key) WHERE status<>'rejected' не даёт задвоить смену
    # при пере-источивании на живой бухгалтерии (блокер №1, см. database.py).
    idem_key: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Какие clean-DataEntry (L2) пошли в пакет. Один пакет = одна смена
    # (натуральный ключ); JSONB-массив UUID.
    source_entry_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Жизненный цикл пакета:
    # 'draft'    — подготовлен в TradeLedger, не отправлен
    # 'queued'   — поставлен в очередь HTTP-обмена (TradeLedger ещё не забрал)
    # 'sent'     — отдан расширению 1С (получен запросом extension'а)
    # 'acked'    — 1С квитировала: пакет загружен, ссылка на документ известна
    # 'rejected' — 1С отвергла (с указанием причины в reject_reason)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    # Полезная нагрузка, что мы реально отправили (JSON, сериализация L3).
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Когда 1С квитировала — сюда ставится id AccountingDoc, который
    # представляет L4-snapshot этого пакета. Связь L3↔L4.
    target_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_docs.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# OneCPolicy — учётная политика организации (срез из РегС.УчетнаяПолитика БП 3.0)
# ---------------------------------------------------------------------------
# Хранит последнюю запись УчетнаяПолитики на организацию. Используется для:
# - Понимания метода оценки МПЗ (FIFO/Средняя) при сверке ОРП/Списания.
# - Режима налогообложения (ОСН/УСН), ставки НДС.
# - Раздельного учёта НДС.

class OneCPolicy(Base):
    __tablename__ = "onec_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_external_ref: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
    )
    organization_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    # Произвольные поля среза учётной политики из БП (PBU/НДС/ставки/раздельный учёт).
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Отдельные часто используемые поля для быстрого SQL-фильтра в UI.
    mpz_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_system: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vat_rate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pbu_18_02: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    separate_vat_accounting: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# PostingTemplate — справочник ожидаемых проводок по ВидОперации
# ---------------------------------------------------------------------------
# При проведении документа определённого ВидОперации 1С формирует
# характерный набор проводок (например ОРП ВидОп=ОтчетККМОПродажах →
# 90.02.1/41.02 + 62.Р/90.01.1 + 50.01/62.Р + 90.03/68.02).
# Этот шаблон храним локально для подсветки соответствия факт vs ожидание
# в UI Sheet документа.

class PostingTemplate(Base):
    __tablename__ = "posting_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    operation_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Массив объектов {dt, kt, formula, comment} — что ожидаем.
    expected: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NomenclaturePrice(Base):
    """Срез РегС.ЦеныНоменклатуры из БП ГИГ — оптовые/розничные/закупочные
    цены номенклатуры на дату. Используем для:
      - проверки входной цены ТТН против актуальной закупочной цены
      - сверки розничной выручки против актуальной розничной цены
      - подсветки отклонений в DocumentsPage.
    Уникальность по (company_id, nomenclature_ref, price_type, period)."""
    __tablename__ = "nomenclature_prices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # GUID Catalog.Номенклатура — джойнится с NomenclatureItem.external_ref.
    nomenclature_ref: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    nomenclature_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # GUID Catalog.ВидыЦен (Оптовая, Розничная, Закупочная и т.п.)
    price_type_ref: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    price_type_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True, default="RUB")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InventoryBatch(Base):
    """Партия товара (FIFO) — остаток по регистратору-документу.

    В БП 3.0 ред.3 источник:
      1) РегистрНакопления.ПартииТоваровНаСкладах (виртуальная Остатки) —
         основной канал. Если регистр пуст (часто на розничных АЗС с
         учётом по средней) — пробуем второй вариант.
      2) Аналитика по счёту 41.01 через СубконтоДт2 (партии-документы)
         регистра РегистрБухгалтерии.Хозрасчетный.

    Регистратор-партия — обычно ПТУ или ВводОстатков.
    """
    __tablename__ = "inventory_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Документ-регистратор партии (ПТУ/ВводОстатков/Корректировка)
    batch_doc_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    batch_doc_ref: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    batch_doc_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    batch_doc_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Аналитика
    nomenclature_ref: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    nomenclature_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    warehouse_ref: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    organization_ref: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Остатки на момент среза
    quantity_remaining: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    amount_remaining: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    unit_price: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    # Источник данных: 'register' (РегистрНакопления) | 'postings' (бухсчёт)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="register")
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReconcileMapping(Base):
    __tablename__ = "reconcile_mappings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Маппинг уровня КАНАЛА (override) — значения в STS/TradeCorp/MSTO/ЦБ
    # называются по-разному. NULL = дефолт компании (общий для всех каналов).
    # Резолв: channel_id-specific → company-default(NULL) → канон-сид.
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    # Тип маппинга: 'station' | 'fuel' | 'paytype' | 'nomenclature' | 'counterparty'
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Ключ во внешнем источнике (station_id STS, артикул поставщика, pay_type STS).
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # external_ref записи в Catalog (GUID в БП) — JOIN на Counterparty/Warehouse/...
    target_ref: Mapped[str] = mapped_column(String(36), nullable=False)
    # Имя цели для UI (кеш — обновляется при sync_catalogs)
    target_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 0..100, насколько уверены в маппинге
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Как создан: 'manual' | 'auto' | 'ai' | 'imported_from_bp'
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    # Комментарий пользователя
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: Warehouse (Склады / АЗС)
# ---------------------------------------------------------------------------
class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False, default="warehouse")
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: BankAccount (Банковские счета)
# ---------------------------------------------------------------------------
class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    bik: Mapped[str] = mapped_column(String(12), nullable=False)
    corr_account: Mapped[str | None] = mapped_column(String(30), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="RUB")
    organization_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ===========================================================================
# FUEL: Топливный учёт (GIG Fuel Ledger)
# ===========================================================================


# ---------------------------------------------------------------------------
# FuelStation (АЗС)
# ---------------------------------------------------------------------------
class FuelStation(Base):
    __tablename__ = "fuel_stations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    code: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sts_system_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Гео-паспорт (координаты/адрес из STS /v1/points) — для Карты АЗС.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# FuelTransaction (пооперационный налив — STS /v2/transactions)
# ---------------------------------------------------------------------------
class FuelTransaction(Base):
    """Пооперационная транзакция отпуска топлива (налив) из STS /v2/transactions.

    Грейн = одна операция на ТРК (в отличие от FuelShiftSale = агрегат смена×канал×
    топливо). Даёт счётчик наливов (как в эталонной системе), реестр операций и
    точные метрики (по часам/картам/ТРК). Дедуп по STS `id` в скоупе компания+станция.
    """
    __tablename__ = "fuel_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id", ondelete="SET NULL"), nullable=True
    )
    station_code: Mapped[int] = mapped_column(Integer, nullable=False)
    ext_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # STS transaction id (дедуп)

    dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shift_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nozzle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    fuel_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pay_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pay_type_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    card: Mapped[str | None] = mapped_column(String(64), nullable=True)

    liters: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)   # quantity
    price: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)          # ₽/л
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)    # ₽ (STS cost)
    density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_fuel_transactions", "company_id", "station_code", "ext_id", unique=True),
        Index("idx_ftx_company_dt", "company_id", "dt"),
    )


# ---------------------------------------------------------------------------
# FuelShift (Сменный отчёт — нормализованный)
# ---------------------------------------------------------------------------
class FuelShift(Base):
    __tablename__ = "fuel_shifts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id"), nullable=False
    )
    shift_number: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    operator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="new"
    )  # new|verified|exported|posted

    total_liters: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )
    total_amount: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False, default=0
    )
    cash: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    card: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    voucher: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    # Ссылка на сырой документ
    raw_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="SET NULL"),
        nullable=True
    )

    # Сырой сменный отчёт STS как есть ({psm, release, sales, receipt, money}) —
    # вход для эталонного просмотрщика TradeFrame (адаптер ShiftReportAdapterV2).
    # Хранится для побайтовой верности формы детали смены; продажи по pay_type
    # (купон/МобилПр и т.п.) не теряются, в отличие от FuelShiftSale.
    raw_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Источник не отдаёт детализацию продаж по этой смене (psm/sales пусты при
    # живой кассе): НЕ ноль выручки, а пробел в данных. У АЗС 205/207/208/209/
    # 210/9008 так выглядит период до подключения к контуру STS (до янв–фев 2026).
    # Аналитика обязана исключать такие смены из средних, иначе они занижают
    # выручку/смену и среднюю цену молча. Ставится приёмом и переигровкой
    # (fuel_shift_refresh), снимается автоматически, как только STS отдал продажи.
    sales_missing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Учётный период (Шаг 1) — определяется по closed_at смены
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"),
        nullable=True
    )
    # Период закрыт в БП — запись read-only
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Уникальный UUID для pull-расширения БП (идемпотентность)
    source_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Связи
    station: Mapped["FuelStation"] = relationship()
    tanks: Mapped[list["FuelTank"]] = relationship(back_populates="shift")
    pumps: Mapped[list["FuelPump"]] = relationship(back_populates="shift")
    cash_movements: Mapped[list["FuelCashMovement"]] = relationship(back_populates="shift")


# ---------------------------------------------------------------------------
# FuelTank (Резервуар — по смене)
# ---------------------------------------------------------------------------
class FuelTank(Base):
    __tablename__ = "fuel_tanks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_shifts.id", ondelete="CASCADE"),
        nullable=False
    )
    tank_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fuel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    fuel_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ── КНИГА (документальный остаток): doc_beg + приход − отпуск = doc_end ──
    volume_start: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    volume_end: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    sales: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)  # отпуск
    volume_received: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)  # поступление

    # ── ФАКТ (замер уровнемером на конец смены; секция `rest` отчёта STS) ──
    # Книга и факт — разные величины: книга считается от прошлого остатка
    # арифметикой, факт меряется в резервуаре. Их разница и есть излишек или
    # недостача, ради которой бухгалтер проводит инвентаризацию. Раньше факт
    # не сохранялся вовсе, и сравнивать было не с чем.
    fact_volume: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    fact_mass: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)  # кг

    # ── МАССА (кг) по тем же четырём точкам ──
    # Учёт ГСМ в бухгалтерии ведётся в тоннах, а не в литрах: объём «дышит» с
    # температурой, масса — нет. Без массы сверка с 1С неполная.
    mass_start: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    mass_end: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    mass_sales: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    mass_received: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)

    density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)  # плотность конца
    density_beg: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    temp_beg: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    temp_end: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    level_end: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    water_level: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    water_volume: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Связи
    shift: Mapped["FuelShift"] = relationship(back_populates="tanks")


# ---------------------------------------------------------------------------
# FuelPump (ТРК/колонка — по смене)
# ---------------------------------------------------------------------------
class FuelPump(Base):
    __tablename__ = "fuel_pumps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_shifts.id", ondelete="CASCADE"),
        nullable=False
    )
    pump_number: Mapped[int] = mapped_column(Integer, nullable=False)
    nozzle: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fuel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    fuel_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tank_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sales_volume: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)  # отпуск, л
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)  # сумма, ₽
    psm_beg: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)  # счётчик начало
    psm_end: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)  # счётчик конец
    price: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    # Связи
    shift: Mapped["FuelShift"] = relationship(back_populates="pumps")


# ---------------------------------------------------------------------------
# FuelCashMovement (Движение наличных — секция money сменного отчёта)
# ---------------------------------------------------------------------------
class FuelCashMovement(Base):
    __tablename__ = "fuel_cash_movements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_shifts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    operation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    pos_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    shift: Mapped["FuelShift"] = relationship(back_populates="cash_movements")


# ---------------------------------------------------------------------------
# FuelReceipt (ТТН / Поступление)
# ---------------------------------------------------------------------------
class FuelReceipt(Base):
    __tablename__ = "fuel_receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id"), nullable=False
    )
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_shifts.id", ondelete="SET NULL"),
        nullable=True
    )
    ttn: Mapped[str] = mapped_column(String(100), nullable=False)
    fuel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    fuel_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(500), nullable=True)

    doc_volume_liters: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    doc_mass_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    doc_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    fact_volume_liters: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    fact_mass_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    fact_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    diff_volume: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    diff_mass: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    # Реквизиты для журнала/деталей поступления (как TradePoint): номер смены STS,
    # резервуар, температуры и фактическая плотность.
    shift_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doc_temp: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    fact_temp: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    fact_density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="new"
    )

    raw_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="SET NULL"),
        nullable=True
    )

    # Учётный период (Шаг 1) — определяется по received_at
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"),
        nullable=True
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # ИсточникUUID для pull-расширения БП
    source_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# OnlineOrder (Онлайн-заказы агрегаторов из MSTO IntegratorService —
# внешний источник для сверки онлайн-канала смены: Я.Заправки/Benzuber/FuelUp).
# ---------------------------------------------------------------------------
class OnlineOrder(Base):
    __tablename__ = "online_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Станция — best-effort: маппинг MSTO servicePointId → точка может отсутствовать.
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id", ondelete="SET NULL"),
        nullable=True
    )

    # MSTO-идентификаторы
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)  # sessionId MSTO
    service_point_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_point_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    post_number: Mapped[int | None] = mapped_column(Integer, nullable=True)  # № ТРК

    # Агрегатор (тариф) и топливо
    aggregator: Mapped[str | None] = mapped_column(String(100), nullable=True)  # Яндекс/FuelUp/Benzuber
    fuel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)   # как в MSTO
    fuel_code: Mapped[int | None] = mapped_column(Integer, nullable=True)       # канон эталона (1-7), резолв по имени

    order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Заказано (план) vs исполнено (факт на ТРК)
    ordered_sum: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    ordered_volume: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    actual_sum: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    actual_volume: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)

    operation_result: Mapped[str | None] = mapped_column(String(20), nullable=True)  # success|wait|error|cancel

    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_online_orders_ext", "company_id", "external_id", unique=True),
        Index("idx_online_orders_company_date", "company_id", "order_date"),
        Index("idx_online_orders_station_date", "company_id", "station_id", "order_date"),
    )


class OnlineReconciliationDecision(Base):
    """Решение оператора по расхождению онлайн-заказов и корректировка L2."""
    __tablename__ = "online_reconciliation_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    case_key: Mapped[str] = mapped_column(String(180), nullable=False)
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id", ondelete="SET NULL"), nullable=True
    )
    shift_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    online_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("online_orders.id", ondelete="SET NULL"), nullable=True
    )
    fuel_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_transactions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolution: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_system: Mapped[str | None] = mapped_column(String(30), nullable=True)
    canonical_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    canonical_volume: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_online_recon_decision", "company_id", "case_key", unique=True),
        Index("idx_online_recon_status", "company_id", "status"),
        Index(
            "idx_online_recon_shift", "company_id", "station_id", "shift_number"
        ),
    )


# ---------------------------------------------------------------------------
# FuelExportDoc (Документ для выгрузки в 1С)
# ---------------------------------------------------------------------------
class FuelExportDoc(Base):
    __tablename__ = "fuel_export_docs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # receipt|transfer|assembly|retail_sales
    label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_shifts.id", ondelete="SET NULL"),
        nullable=True
    )
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft"
    )  # draft|confirmed|exported|posted
    export_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    export_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Учётный период (Шаг 1)
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"),
        nullable=True
    )

    # Подтверждение от расширения БП (ack от GIG_Ledger.cfe)
    bp_doc_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bp_acked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    exported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# FuelValidationResult (Результат проверки по эталону)
# ---------------------------------------------------------------------------
class FuelValidationResult(Base):
    __tablename__ = "fuel_validation_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # shift|receipt
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_code: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # counterparty_inn, nomenclature, vat_rate
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="warning"
    )  # info|warning|error|block
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ===========================================================================
# ACCOUNTING PERIODS — цикл «симбиоз с бухгалтерией» (Шаг 1)
# ===========================================================================
# Период — первичная сущность нормализованной БД. Каждый рабочий объект
# (FuelShift, FuelReceipt, DataEntry, AccountingDoc) привязан к Period
# и наследует флаг is_locked, если период закрыт.
#
# Закрытие происходит ВНЕ TradeLedger (в БП ГИГ через УстановкуДатЗапрета
# или аналогичный механизм). TradeLedger детектирует закрытие при
# репликации и проставляет Period.status='closed' + is_locked=true
# на привязанные сущности.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Period (Учётный период)
# ---------------------------------------------------------------------------
class Period(Base):
    __tablename__ = "periods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..12

    # open|closed — закрыт ли период в бухгалтерии-эталоне
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Источник установки статуса: manual (вручную в UI TradeLedger)
    # или from_bp (репликация из БП через OData / явный признак закрытия)
    closure_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="from_bp"
    )

    # Связь с записью в БП: «дата запрета изменений до X числа» либо
    # явная регистровая запись. JSONB для гибкости.
    bp_closure_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# ReferenceSnapshot (Снимок эталона из БП по периоду)
# ---------------------------------------------------------------------------
# Хранит «срез знаний» из БП на момент закрытия периода — для
# воспроизводимости проверок незакрытого периода. Не дублирует
# справочники (они в Counterparty/Nomenclature/...), а фиксирует
# *версию* справочников и список документов с проводками.
# ---------------------------------------------------------------------------
class ReferenceSnapshot(Base):
    __tablename__ = "reference_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("periods.id", ondelete="CASCADE"),
        nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Сводка снимка: сколько документов, контрагентов, проводок и т.д.
    # Структура: {"counterparties_count": N, "documents_count": M,
    #             "postings_count": K, "checksum": "sha256:..."}
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Полный список Ref_Key документов БП в этом периоде —
    # для быстрого «список финализированных документов периода».
    document_refs: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )


# ---------------------------------------------------------------------------
# SourceSync (Лог репликации из БП через OData)
# ---------------------------------------------------------------------------
class SourceSync(Base):
    __tablename__ = "source_syncs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    # Тип репликации: catalogs (справочники) | closed_periods (документы и
    # проводки за закрытые периоды) | period_closure (детект закрытия) |
    # full (полная синхронизация)
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # success|partial|error
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    # Время начала и завершения
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Счётчики
    items_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Детали ошибок и метаданные
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# ---------------------------------------------------------------------------
# PullCheckpoint (Точка чтения для расширения БП — pull-расширение)
# ---------------------------------------------------------------------------
# Хранит «что уже забрало расширение БП» для идемпотентности.
# При повторном опросе расширение присылает свой extension_id и last_seen,
# TradeLedger отдаёт только дельту с этого момента.
# ---------------------------------------------------------------------------
class PullCheckpoint(Base):
    __tablename__ = "pull_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    # Идентификатор расширения-потребителя (например, "gig_ledger_cfe@bp_gig")
    extension_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Тип забираемых документов: fuel_shift | fuel_receipt | ...
    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Что забирали — за какой период
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"),
        nullable=True
    )

    # Последняя отметка времени, на которую расширение получило документы
    last_pulled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Список ИсточникUUID документов, которые расширение подтвердило загруженными
    acknowledged_uuids: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )

    # Сколько документов в последнем pull-вызове
    last_pulled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ===========================================================================
# CHANNEL SUBSYSTEM — подсистема входных каналов (Шаг 1.5)
# ===========================================================================
# Source         — настроенное подключение (STS, ОФД, OData 1С, ...).
# SourceCredentials — зашифрованные креды (Fernet, отдельная таблица).
# Channel        — pipeline обработки: 1+ Source → stages → результат.
# ChannelStream  — что забираем из каждого источника канала.
# ChannelStage   — этап pipeline (fetch / normalize / reconcile / ...).
# ReconcileRule  — правила сверки между потоками.
# ChannelTemplate — шаблон pipeline для типовой задачи.
# SyncLog        — журнал прогонов канала.
# RawBatchRecord — сырой ответ источника (для дебага и переигрывания).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Source (Настроенное подключение)
# ---------------------------------------------------------------------------
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    # Тип источника — соответствует SourceAdapter.source_type
    # ("sts", "onec_odata", "ofd_platforma", "acquiring_sber", ...)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Имя, заданное пользователем («STS ГИГ (65)», «1С Бухгалтерия ГИГ»)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # connected | disconnected | error | draft
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")

    # Не-секретные настройки (URL, login, system_ids — без пароля)
    connection_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# SourceCredentials (Секреты — отдельная таблица, Fernet)
# ---------------------------------------------------------------------------
# Хранение паролей / токенов отдельно от Source — чтобы дамп-эндпоинты
# CRUD случайно не вернули секреты, и чтобы можно было ротировать
# Fernet-ключ без переписывания Source.
# ---------------------------------------------------------------------------
class SourceCredentials(Base):
    __tablename__ = "source_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )

    # Ключ → зашифрованное значение Fernet (base64)
    # Например: {"password": "gAAAAA..."}
    encrypted_values: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    # Версия шифрования (для будущих миграций ключа)
    cipher_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Channel (Pipeline обработки)
# ---------------------------------------------------------------------------
class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # active | paused | error | draft
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")

    # ID шаблона, из которого канал создан (опционально)
    template_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Расписание: { mode: 'manual'|'interval'|'cron', interval_minutes, cron, ... }
    schedule: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        default=lambda: {"mode": "manual", "pause_on_error": True, "max_retries": 3}
    )

    # skip | warn | overwrite
    duplicate_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="skip"
    )

    # Период загрузки (дней назад) — для каналов с дельтой по дате
    period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    # Произвольная конфигурация (специфика канала)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Каталог хранения сырых файлов (если канал работает с файлами)
    root_catalog: Mapped[str | None] = mapped_column(String(500), nullable=True)

    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    docs_loaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# ChannelStream (Поток данных канала — что из какого Source забираем)
# ---------------------------------------------------------------------------
class ChannelStream(Base):
    __tablename__ = "channel_streams"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False
    )
    # null = разрез предустановлен шаблоном, но источник ещё не подключён.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )

    # ID типа документа в Source.adapter.available_doc_types
    # (например, "shift_report" / "receipt" / "transactions")
    doc_type_id: Mapped[str] = mapped_column(String(100), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    catalog_template: Mapped[str | None] = mapped_column(String(500), nullable=True)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Роль разреза учёта в канале: anchor (опорный) | control (сверяемый со
    # смежными разрезами) | reference (справочный) | external (внешний).
    # Задаётся шаблоном канала; определяет, какие разрезы можно дополнительно сверять.
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="control")


# ---------------------------------------------------------------------------
# ChannelStage (Этап pipeline канала)
# ---------------------------------------------------------------------------
class ChannelStage(Base):
    __tablename__ = "channel_stages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False
    )

    # fetch | normalize | reconcile | validate | transform | save
    stage_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Для fetch — из какого Source через какой поток
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True
    )
    # Для reconcile — массив stream id
    reconcile_stream_ids: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )

    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# ReconcileRule (Правило сверки между потоками канала)
# ---------------------------------------------------------------------------
class ReconcileRule(Base):
    __tablename__ = "reconcile_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Минимум 2 stream-id для сверки
    stream_ids: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )

    # По какому полю сопоставлять записи между потоками
    match_field: Mapped[str] = mapped_column(String(100), nullable=False)
    # Какие поля сравнивать
    compare_fields: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )
    # Допустимое расхождение (%)
    tolerance: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=0
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# ChannelTemplate (Пользовательский шаблон канала)
# ---------------------------------------------------------------------------
# Шаблоны хранятся также в коде (clearledger/src/templates/), но если
# пользователь модифицировал шаблон — сохраняется в БД компании.
# ---------------------------------------------------------------------------
class ChannelTemplate(Base):
    __tablename__ = "channel_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )

    # Если NULL company_id — это «системный» шаблон из кода
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    source_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Полный JSON шаблона: streams, stages, schedule, default_connection
    template_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# ChannelSyncLog (Журнал прогона канала)
# ---------------------------------------------------------------------------
class ChannelSyncLog(Base):
    __tablename__ = "channel_sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # success | partial | error | running
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")

    # Период прогона (ISO yyyy-mm-dd). NULL = весь период / прогон до фичи кокпита.
    date_from: Mapped[str | None] = mapped_column(String(10), nullable=True)
    date_to: Mapped[str | None] = mapped_column(String(10), nullable=True)

    loaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Подробный лог: список событий [{ts, level, event, message}]
    events: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


# ---------------------------------------------------------------------------
# RawBatchRecord (Сырой ответ источника — для дебага и переигрывания)
# ---------------------------------------------------------------------------
# Каждый fetch_delta пишет сюда RawBatch. Полезно когда нормализация
# упадёт на странных данных — можно посмотреть исходник и переиграть.
# ---------------------------------------------------------------------------
class RawBatchRecord(Base):
    __tablename__ = "raw_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True
    )
    sync_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel_sync_logs.id", ondelete="SET NULL"),
        nullable=True
    )

    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Сырая полезная нагрузка
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    items_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


# ---------------------------------------------------------------------------
# Интеграция 1С: подключения и журнал синхронизации
# ---------------------------------------------------------------------------
class OneCConnection(Base):
    __tablename__ = "onec_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # mode='odata' — HTTP-публикация, odata_url хранит URL.
    # mode='com'  — V83.COMConnector, odata_url хранит строку соединения
    # (File=... или Srvr=...;Ref=...). См. services/onec/com_client.py.
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="odata")
    odata_url: Mapped[str] = mapped_column(String(500), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False)
    exchange_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="inactive"
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_interval_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    sync_logs: Mapped[list["OneCSyncLog"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class OneCSyncLog(Base):
    __tablename__ = "onec_sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("onec_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    items_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    connection: Mapped["OneCConnection"] = relationship(back_populates="sync_logs")


# ---------------------------------------------------------------------------
# ServiceLocation (Точки обслуживания — АЗС/магазины/офисы)
# ---------------------------------------------------------------------------
# Перенесено из localStorage в бэкенд: точки должны быть общими для всех
# браузеров/пользователей и совпадать с конфигом каналов. id — клиентский
# nanoid (String), чтобы фронт и бэк совпадали без доп. резолва.
# ---------------------------------------------------------------------------
class ServiceLocation(Base):
    __tablename__ = "service_locations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # fuel_station | retail | office | warehouse | other
    type: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    # active | closed | planned (жизненный цикл точки)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # Операционный статус: working|not_working|on_repair|maintenance|unknown
    operational_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default=text("'unknown'")
    )
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Привязки к источникам: [{sourceId, config:{system_id,station}, label}]
    source_bindings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Произвольные метаданные (в API — поле metadata)
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Нормализованный регион (производный от extra_metadata.federalSubject). NULL
    # пока не размечен; источник-сырьё остаётся в metadata. См. Region.
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # ── Паспорт ЭЗС-станции (нормализованный L2 из справочника станций; заполнен
    #    для type='ev_charging', иначе NULL). Полный сырой паспорт — в extra_metadata.
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    station_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    street: Mapped[str | None] = mapped_column(String(200), nullable=True)
    house: Mapped[str | None] = mapped_column(String(40), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_kwt: Mapped[float | None] = mapped_column(Float, nullable=True)
    connectors_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    connector_types: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ocpp_protocol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    firmware: Mapped[str | None] = mapped_column(String(80), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    access_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_published: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_test: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"))
    hubex_asset_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    hubex_link_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    success_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ── Атрибуты из сводной выработки контрагента (слот obshaya, v2.14):
    # размещение city|highway (их «трасса/город») — субсидийный разрез;
    location_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # класс скорости fast|slow (их «Быстрая/Медленная»);
    speed_class: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # даты жизненного цикла ISO 'YYYY-MM-DD' (вывод: дата распознана из «Дата
    # вывода из эксплуатации»; текст без даты — в extra_metadata.decommissionNote);
    installed_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    decommissioned_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # инвентарный номер ОС (мост к бухучёту; «НЕТ НА 01»/«не известно» → NULL);
    inventory_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # станция закреплена за корп-контуром (каршеринг) — их «статус корп».
    is_corp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# LocationTypeDef (Каталог типов точек обслуживания — редактируемый)
# ---------------------------------------------------------------------------
# Тип точки = код + единица + набор полей (схема). Встроенные типы:
# company_id IS NULL (доступны всем, is_builtin=true, не удаляются); кастомные
# типы компании: company_id задан. Значения полей конкретной точки хранятся в
# ServiceLocation.extra_metadata. Нижестоящий код опирается на стабильный `code`
# (например 'fuel_station'), а не на лейбл.
# ---------------------------------------------------------------------------
class LocationTypeDef(Base):
    __tablename__ = "location_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # NULL = встроенный (системный) тип; задан = кастомный тип компании
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="MapPin")
    # Единица измерения по умолчанию: л / кВт·ч / шт / "" (нет)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("''"))
    # fuel | energy | goods | food | none — задел под единицы/сверку
    nomenclature_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none", server_default=text("'none'")
    )
    # Схема полей типа: [{key,label,type,options?,unit?,required?}] (форма MetadataField)
    fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Код уникален среди встроенных типов (company_id IS NULL)
        Index(
            "uq_location_types_builtin_code", "code",
            unique=True, postgresql_where=text("company_id IS NULL"),
        ),
        # Код уникален в пределах компании (кастомные типы)
        Index(
            "uq_location_types_company_code", "company_id", "code",
            unique=True, postgresql_where=text("company_id IS NOT NULL"),
        ),
    )


# ===========================================================================
# Сервисный центр (netservice) — управление сервисом сети.
# MVP: 3-я линия (HubEx FSM). L1 заявок/объектов/справочников raw+промо +
# нормализация региона. Унифицированный SupportCase и др. источники — Фаза 2+.
# ===========================================================================

# ---------------------------------------------------------------------------
# Region — нормализованный справочник регионов (производный от
# ServiceLocation.extra_metadata.federalSubject). Сырьё остаётся в metadata,
# region_id — быстрый разрез для аналитики.
# ---------------------------------------------------------------------------
class Region(Base):
    __tablename__ = "regions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Сырое значение federalSubject для матчинга при бэкфилле/синке.
    federal_subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Смещение часового пояса от Москвы, часов (для анализа сессий по местному
    # времени). Заполняется tz_offsets.backfill_region_offsets; NULL → МСК.
    msk_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_regions_company_name", "company_id", "name", unique=True),
    )


# ---------------------------------------------------------------------------
# HubexTask — L1 заявок HubEx FSM (raw + промо-колонки). Натуральный ключ
# идемпотентности (company_id, hubex_id). Вся SLA-математика — по 6 timestamp
# полям timesheet. asset_id → ServiceLocation.extra_metadata.hubexAssetId.
# ---------------------------------------------------------------------------
class HubexTask(Base):
    __tablename__ = "hubex_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # id заявки в HubEx (ключ словаря ответа /WORK/Tasks)
    hubex_id: Mapped[str] = mapped_column(String(64), nullable=False)
    number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Промо
    task_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    work_type: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # workType.erpID — мост к 1С/ERP (финансовый мост, Фаза 3)
    work_type_erp_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(200), nullable=True)
    criticality: Mapped[str | None] = mapped_column(String(200), nullable=True)
    criticality_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asset_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contractor_company: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contractor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(300), nullable=True)
    assignee_is_tech: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Наш слой: резолв объекта в нашу точку и регион
    location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True
    )
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL"), nullable=True
    )
    # timesheet — вся SLA-математика
    ts_created: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ts_requested: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ts_assigned: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ts_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ts_completed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ts_closed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_overdue: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_rated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    child_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_hubex_tasks", "company_id", "hubex_id", unique=True),
        Index("idx_hubex_tasks_asset", "company_id", "asset_id"),
        Index("idx_hubex_tasks_lastmod", "company_id", "last_modified"),
        Index("idx_hubex_tasks_stage", "company_id", "stage"),
        Index("idx_hubex_tasks_region", "company_id", "region_id"),
        Index(
            "idx_hubex_tasks_open", "company_id",
            postgresql_where=text("ts_closed IS NULL"),
        ),
    )


# ---------------------------------------------------------------------------
# HubexAsset — справочник объектов HubEx (/ES/Assets). Ключ (company_id, hubex_id).
# ---------------------------------------------------------------------------
class HubexAsset(Base):
    __tablename__ = "hubex_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    hubex_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True
    )
    serial_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_hubex_assets", "company_id", "hubex_id", unique=True),
    )


# ---------------------------------------------------------------------------
# HubexRef — полиморфный справочник HubEx (статусы/типы/виды работ/критичность/
# подрядчики). Ключ (company_id, ref_kind, hubex_id).
# ---------------------------------------------------------------------------
class HubexRef(Base):
    __tablename__ = "hubex_refs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # status | task_type | work_type | criticality | company
    ref_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    hubex_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    erp_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_hubex_refs", "company_id", "ref_kind", "hubex_id", unique=True),
    )


# ---------------------------------------------------------------------------
# SupportSyncCursor — курсор инкрементального синка источников Сервисного центра.
# Ключ (company_id, source_type, doc_kind).
# ---------------------------------------------------------------------------
class SupportSyncCursor(Base):
    __tablename__ = "support_sync_cursors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)  # hubex_fsm | ...
    doc_kind: Mapped[str] = mapped_column(String(40), nullable=False)     # tasks | refs | ...
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_support_sync_cursors", "company_id", "source_type", "doc_kind", unique=True),
    )


# ---------------------------------------------------------------------------
# Маппинги топливных каналов STS → документы 1С:БП (профиль fuel, ГИГ).
# Воспроизводят настраиваемые справочники расширения TradeLedger.cfe:
#   PaymentChannel  ← каналы оплаты (Оплата_<канал>_*: склад, требует перемещения)
#   PaymentMapping  ← регистр TL_МаппингОплат (образец имени STS → канал)
#   FuelMapping     ← Топливо_<N>_* (service_code → номенклатура тонны/литры + плотность)
# Источник истины маппингов — приложение (решение 28.06.2026).
# Контракт: docs/CHANNEL_STS_FUEL_SHIFT_TTN.md.
# ---------------------------------------------------------------------------
class PaymentChannel(Base):
    __tablename__ = "payment_channels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # retail | retail_cash | retail_card | cards | online | voucher | ledger | writeoff_fuel
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Склад БП (имя; GUID после репликации НСИ). NULL/"" — без виртуального склада.
    warehouse_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Создаётся ли Перемещение 41.02→41.01 на склад канала.
    requires_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    counterparty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_payment_channels", "company_id", "code", unique=True),
    )


class PaymentMapping(Base):
    __tablename__ = "payment_mappings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Образец имени pay_type из STS (нижний регистр). Матчинг — подстрока.
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    # Код канала (PaymentChannel.code). "" — игнорировать (купоны/прокачка).
    channel_code: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # Переопределение склада на уровне строки (приоритет над складом канала).
    warehouse_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_payment_mappings", "company_id", "pattern", unique=True),
    )


class FuelMapping(Base):
    __tablename__ = "fuel_mappings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # service_code из STS (1=АИ-100 2=АИ-92 3=АИ-95 4=АИ-98 5=ДТ 6=ДТ зим 7=СУГ)
    service_code: Mapped[int] = mapped_column(Integer, nullable=False)
    fuel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Номенклатура БП: имя (отображение/документы) + GUID 1С (единый источник
    # правды, согласовано с бухгалтерией — имя выбирается из каталога 1С по GUID).
    nomenclature_tonnes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nomenclature_liters: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nomenclature_t_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    nomenclature_l_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Справочная плотность (т/м³); фактическая берётся из ТТН.
    density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_fuel_mappings", "company_id", "service_code", unique=True),
    )


# ---------------------------------------------------------------------------
# FuelShiftSale — разбивка продаж смены по КАНАЛУ ОПЛАТЫ × виду топлива.
# L2-проекция секции STS sales после применения PaymentMapping. Основа для
# построения документов 1С (ОРП/ПКО/Перемещения/Списание). Один ряд = один
# (канал оплаты, код топлива) в смене.
# ---------------------------------------------------------------------------
class FuelShiftSale(Base):
    __tablename__ = "fuel_shift_sales"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_shifts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Код канала оплаты (PaymentChannel.code): retail_cash/retail_card/cards/...
    payment_channel: Mapped[str] = mapped_column(String(40), nullable=False)
    fuel_code: Mapped[int] = mapped_column(Integer, nullable=False)
    liters: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    discount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    # Склад БП для этого канала (имя; из mapping.override или channel).
    warehouse_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_fuel_shift_sales", "shift_id", "payment_channel", "fuel_code", unique=True),
    )


# ---------------------------------------------------------------------------
# FuelShiftSaleOverride — РУЧНАЯ КОРРЕКТИРОВКА строки продаж смены (слой L2 CLEAN).
# Правка человеком поверх FuelShiftSale (raw-проекция STS). Ключуется НАТУРАЛЬНЫМ
# ключом смены (station_id + shift_number), а НЕ shift_id — чтобы пережить
# «Обновить период» (delete+reingest с CASCADE пересоздаёт смену с новым UUID).
# Накладывается при построении документов 1С (_build_shift_docs) и в get_shift.
# ---------------------------------------------------------------------------
class FuelShiftSaleOverride(Base):
    __tablename__ = "fuel_shift_sale_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Натуральный ключ смены (станция стабильна между reingest; shift_id — нет).
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shift_number: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_channel: Mapped[str] = mapped_column(String(40), nullable=False)
    fuel_code: Mapped[int] = mapped_column(Integer, nullable=False)
    # Скорректированные значения (NULL → показатель не правился, берётся из FuelShiftSale).
    liters: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    discount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Снимок исходных STS-значений на момент первой правки (для diff/аудита/отката).
    src_liters: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    src_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    src_discount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "uq_fuel_sale_override", "company_id", "station_id", "shift_number",
            "payment_channel", "fuel_code", unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# FuelTankInventory — ИНВЕНТАРИЗАЦИЯ РЕЗЕРВУАРА (корректировка книги на факт).
# Замер уровнемера (факт) и документальный остаток (книга) расходятся, и это
# расхождение само не списывается — копится, пока инвентаризация не оформит
# корректировку. Одна строка = один резервуар на дату инвентаризации: книжный
# остаток на момент, фактический замер и разница (излишек к оприходованию /
# недостача к списанию). После подтверждения книга считается приведённой к
# факту — расхождение на этот момент закрыто.
#
# Ключуется НАТУРАЛЬНЫМ ключом резервуара (station_id + tank_number + дата), а не
# shift_id — чтобы пережить «Обновить период» (переигровка пересоздаёт смены с
# новыми UUID). Слой L2, поверх raw-данных смен, как FuelShiftSaleOverride.
# ---------------------------------------------------------------------------
class FuelTankInventory(Base):
    __tablename__ = "fuel_tank_inventories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tank_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fuel_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Дата инвентаризации (момент замера).
    inventory_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    # Смена, чей замер взят как факт (для ссылки на первоисточник).
    shift_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Книга (документальный остаток на момент) и факт (замер уровнемера).
    book_volume: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    fact_volume: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # Корректировка = факт − книга: плюс — оприходование излишка, минус — списание.
    adjustment_volume: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    book_mass: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    fact_mass: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    adjustment_mass: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)

    # draft — черновик ведомости; confirmed — проведено (книга приведена к факту).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_fuel_tank_inventory", "company_id", "station_id", "tank_number",
            "inventory_date", unique=True,
        ),
    )


class FuelShiftCorrectionNote(Base):
    """Комментарий менеджера по корректировке смены — один на документ (смену).

    Ключуется натуральным ключом смены (company_id + station_id + shift_number),
    как FuelShiftSaleOverride — переживает delete+reingest STS.
    """
    __tablename__ = "fuel_shift_correction_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shift_number: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "uq_fuel_shift_corr_note", "company_id", "station_id", "shift_number",
            unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# FuelReceiptOverride — РУЧНАЯ КОРРЕКТИРОВКА ТТН перед выгрузкой в 1С (L2 CLEAN).
# Правка объёма/массы/плотности документа поверх FuelReceipt (raw из STS).
# Ключуется натуральным ключом ТТН (station_id + ttn + fuel_code, -1 для NULL),
# а НЕ id — чтобы пережить delete+reingest. Накладывается в _build_receipt_docs
# (→ документы 1С: Перемещение тонн + Комплектация) и в списке ТТН.
# ---------------------------------------------------------------------------
class FuelReceiptOverride(Base):
    __tablename__ = "fuel_receipt_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ttn: Mapped[str] = mapped_column(String(100), nullable=False)
    fuel_code: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    # Скорректированные значения документа (NULL → не правился, берётся из FuelReceipt).
    doc_volume_liters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    doc_mass_kg: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    # Снимок исходных STS-значений на момент первой правки (для diff/отката).
    src_volume: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    src_mass: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    src_density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "uq_fuel_receipt_override", "company_id", "station_id", "ttn",
            "fuel_code", unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# FuelReceiptCost — СЕБЕСТОИМОСТЬ ПАРТИИ (ТТН-слива), задаётся менеджером (L2).
# Партия = ТТН × вид топлива; менеджер вводит ₽/л ИЛИ ₽/кг, вторая единица
# считается через плотность. Для FIFO-списания на продажи (в литрах) храним
# нормализованный `cost_per_liter`. Натуральный ключ (station_id + ttn + fuel_code,
# -1 для NULL) — переживает delete+reingest ТТН. Основа расчёта маржи по разрезам.
# ---------------------------------------------------------------------------
class FuelReceiptCost(Base):
    __tablename__ = "fuel_receipt_costs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ttn: Mapped[str] = mapped_column(String(100), nullable=False)
    fuel_code: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    # Что ввёл менеджер: единица и цена за единицу.
    unit: Mapped[str] = mapped_column(String(10), nullable=False, default="liter")  # 'liter' | 'kg'
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    # Плотность, использованная для пересчёта л↔кг (из ТТН или введённая).
    density_used: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    # Нормализовано в ₽/л для FIFO (продажи считаются в литрах).
    cost_per_liter: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    # Происхождение: ручной ввод / из закупочной партии (Шаг 2).
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    purchase_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "uq_fuel_receipt_cost", "company_id", "station_id", "ttn",
            "fuel_code", unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# FuelOpeningBalance — ВХОДЯЩИЙ ОСТАТОК топлива до начала загруженной истории.
# Это не ТТН: отдельная учётная партия по АЗС × виду топлива, которая закрывает
# продажи до первого доступного поступления и участвует в FIFO первой.
# ---------------------------------------------------------------------------
class FuelOpeningBalance(Base):
    __tablename__ = "fuel_opening_balances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    fuel_code: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    liters: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    cost_per_liter: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "uq_fuel_opening_balance", "company_id", "station_id", "fuel_code",
            unique=True,
        ),
        Index("idx_fuel_opening_balance_fifo", "company_id", "station_id", "fuel_code", "as_of"),
    )


# ---------------------------------------------------------------------------
# FuelPurchaseBatch — КРУПНАЯ ЗАКУПОЧНАЯ ПАРТИЯ топлива (Шаг 2). Менеджер вводит
# закупку у поставщика (объём + себестоимость), выбирает целевые АЗС; аллокатор
# распределяет объём на ТТН этих АЗС по ФИФО (по дате поступления), создавая
# FuelReceiptCost(source='purchase_batch') на покрытые ТТН.
# ---------------------------------------------------------------------------
class FuelPurchaseBatch(Base):
    __tablename__ = "fuel_purchase_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fuel_code: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    fuel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Объём закупки и себестоимость (unit — как ввёл менеджер; cost_per_liter норм.).
    total_liters: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_mass_kg: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    unit: Mapped[str] = mapped_column(String(10), nullable=False, default="liter")
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    cost_per_liter: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    purchase_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Целевые АЗС (список UUID станций строками) для распределения по ФИФО.
    target_station_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")  # draft | allocated
    allocated_liters: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChargeSession(Base):
    """Зарядная сессия ЭЗС (energy-профиль, РусГидро). Источник — Excel-выгрузка
    ChargeTransactions. Дедуп по (company_id, session_ext_id)."""
    __tablename__ = "charge_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # Канал-обработчик (цепочка Источник→Канал→Разрез); NULL — прямой импорт (legacy).
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    session_ext_id: Mapped[str] = mapped_column(String(64), nullable=False)  # «ID сессии»

    # Станция/объект
    station_code: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)   # «Номер станции» (65.245)
    # Материализованная связь с объектом-станцией (конформная размерность): резолв
    # station_code → ServiceLocation по № при загрузке/бэкфилле. NULL = станция-сирота.
    location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True, index=True)
    station_name: Mapped[str | None] = mapped_column(String(160), nullable=True)              # «Наименование станции» (СНК)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)        # «Регион станции»
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)                   # «Адрес станции»

    # Коннектор
    connector_no: Mapped[str | None] = mapped_column(String(20), nullable=True)               # «Номер коннектора»
    connector_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True) # TYPE2/CHADEMO/GBT_DC

    # Время
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, index=True)  # «Начало сессии по МСК»
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)             # «Завершение сессии по МСК»
    duration_min: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)     # завершение − начало, мин

    # Классификация
    result: Mapped[str | None] = mapped_column(String(40), nullable=True)                     # «Результат зарядки» (Complete/…)
    charge_type: Mapped[str | None] = mapped_column(String(40), nullable=True)                # «Тип зарядки» (USER)
    user_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)      # «Тип пользователя» (ФЛ/ЮЛ)
    user_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)       # «Пользователь» (телефон)
    rfid: Mapped[str | None] = mapped_column(String(120), nullable=True)                      # «RFID-карта»
    # Обогащение: наименование корпоративного клиента (ЮЛ) — джойн справочника
    # «Организации» по телефону (user_id). NULL для ФЛ/несопоставленных.
    client_name: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    # Договорной тариф корп-клиента (₽/кВтч) и вычисленная корп-выручка
    # (energy_kwh × client_tariff). У ЮЛ session.amount=0 (постоплата) — реальная
    # выручка считается тут по тарифной модели (матрица/плоский/розница).
    client_tariff: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    client_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # Показатели
    energy_kwh: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)       # «Энергия», кВтч
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)           # «Итоговая сумма списания», ₽
    tariff: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)           # «Цена тарифа», ₽/кВтч

    # Оплата
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)  # «Дата и время оплаты»
    payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)                 # «ID платежа»

    # Разрез учёта (placeholder — привяжем к разрезам сверки позже)
    cut_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    # --- ВИЗИТ: склейка смежных попыток одного клиента на одной станции ---------
    # CPO пишет каждую попытку подключения отдельной сессией. Клиент, у которого
    # разъём схватился с третьего раза, даёт 3 строки: две «CompleteError» и одну
    # рабочую — по сырым сессиям это «67% брака», по факту человек зарядился.
    # Визит = (company, user_id, station_code) + разрыв со следующей ≤ порога
    # (по умолчанию 15 мин, см. charge_visits.VISIT_GAP_MIN). Поля проставляет
    # recompute_visits() после каждой загрузки — вручную не заполнять.
    visit_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    visit_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)    # № попытки в визите, 1..N
    visit_size: Mapped[int | None] = mapped_column(Integer, nullable=True)   # всего попыток в визите
    # Визит завершился отпуском энергии (по любой из своих сессий). Именно это, а
    # не result='Complete': 12 749 сессий Complete отпустили 0 кВтч, а 5 768
    # CompleteError — отпустили. Флаг CPO отвечает на другой вопрос.
    visit_charged: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_charge_sessions", "company_id", "session_ext_id", unique=True),
    )


class AnalyticsCacheVersion(Base):
    """Версия агрегатных данных компании — для инвалидации кеша раздела «Продажи».
    Инкрементируется при ingest/обогащении сессий: все прежние кеш-ключи
    (содержащие версию) становятся недостижимы. См. services/analytics_cache.py."""
    __tablename__ = "analytics_cache_version"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CorporateClient(Base):
    """Реестр корпоративных клиентов (ЮЛ) ЭЗС — из справочника «Организации».
    Ключ джойна с сессиями — phone (= charge_sessions.user_id). Договорной тариф:
    mode matrix/flat/retail (+ rate для flat, matrix регион×коннектор для matrix)."""
    __tablename__ = "corporate_clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)          # ключ = user_id сессии
    ext_id: Mapped[str | None] = mapped_column(String(40), nullable=True)   # «ID организации» из файла
    inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Та же организация, что платит по договору корпзарядки: без ссылки клиента с
    # контрагентом сводили по имени, и первое же переименование рвало связь.
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="retail")  # matrix|flat|retail
    rate: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)         # для flat
    matrix: Mapped[dict | None] = mapped_column(JSONB, nullable=True)       # {region: {CCS2,TYPE2,TYPE1}} — РОЗНИЦА
    # Скидка клиента к рознице, % (напр. каршеринг = 25). Применяется к матрице:
    # цена = розница_матрицы × (1 − discount_pct/100). Регионы вне матрицы = розница.
    discount_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0, server_default=text("0"))
    contract_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    users: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_corporate_clients", "company_id", "phone", unique=True),
    )


class MetrikaConnection(Base):
    """Подключение к Яндекс.Метрике (per-company): счётчик + OAuth-токен (шифрован
    через onec.crypto). Живой fetch аналитики через Reporting API — НЕ ingest в L2.
    Токен фронту не отдаётся (только статус configured/enabled)."""
    __tablename__ = "metrika_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    counter_id: Mapped[str] = mapped_column(String(40), nullable=False)      # № счётчика Метрики
    token_encrypted: Mapped[str] = mapped_column(String(2048), nullable=False)  # OAuth-токен (Fernet)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")  # ok|error|unknown
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    counter_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("uq_metrika_company", "company_id", unique=True),)


# ═══════════════════════════════════════════════════════════════════════════
# Складской учёт оборудования ЭЗС (energy): единицы, движения, ЗИП.
#
# «Железка» отделена от «места»: EzsEquipmentUnit — учётная карточка станции
# (серийник/вендор/паспорт), её местонахождение — ссылка на ServiceLocation
# (склад type=warehouse ЛИБО площадка ev_charging) или внешний держатель
# (подрядчик/производитель — custodian + custodian_name). Первая реализованная
# фаза схемы модернизации справочника (Станция ≠ Площадка, 13.07.2026).
#
# Карточки НЕ создаются массово для работающего парка — рождаются при закупке,
# демонтаже, Excel-импорте складского реестра или ручном вводе; после монтажа
# карточка живёт дальше (state='in_operation').
# Префикс Ezs*/ezs_* — имена Warehouse/StockOnHand заняты магазином (сопутка).
# ═══════════════════════════════════════════════════════════════════════════


class EzsEquipmentUnit(Base):
    """Единица оборудования ЭЗС (станция-железка складского контура)."""
    __tablename__ = "ezs_equipment_units"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="station")  # задел: module|...
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)     # trim при записи
    vendor: Mapped[str | None] = mapped_column(String(120), nullable=True)            # канон (canon_vendor)
    vendor_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)        # как пришло
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    station_type: Mapped[str | None] = mapped_column(String(40), nullable=True)       # DC/AC/…
    power_kwt: Mapped[float | None] = mapped_column(Float, nullable=True)
    connectors_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    connector_types: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inventory_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(300), nullable=True)
    purchase_doc: Mapped[str | None] = mapped_column(String(200), nullable=True)
    purchase_date: Mapped[str | None] = mapped_column(String(10), nullable=True)      # ISO YYYY-MM-DD
    warranty_until: Mapped[str | None] = mapped_column(String(10), nullable=True)     # ISO
    # Привязка к документу поставки (слой оснований) + денежная оценка ОС:
    # supply_id/supply_line_id — из какой поставки пришла единица (мягкие ссылки,
    # без FK — как counterparty у движения); purchase_amount/vat_amount —
    # первоначальная стоимость (счёт 07/08), нужна для выгрузки станции как ОС в БП.
    supply_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    supply_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    purchase_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    vat_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Жизненный цикл: in_stock_new | in_stock_used | reserved | in_installation |
    # in_operation | in_repair | returned_to_vendor | written_off (терминальные два).
    # Переходы — словарь TRANSITIONS в services/ezs_equipment.py (валидация на бэке).
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="in_stock_new")
    # Грейд «б/у» — атрибут единицы, НЕЗАВИСИМЫЙ от state: определяет, в какое
    # складское состояние возвращаться из reserved/in_repair (new или used).
    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    # Держатель: warehouse|site — наши локации; contractor|vendor — внешний
    # (custodian_name), current_location_id тогда NULL; none — списана/утиль.
    custodian: Mapped[str] = mapped_column(String(20), nullable=False, default="warehouse")
    custodian_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    origin_location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    reserved_for_location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_ezs_unit_company_state", "company_id", "state"),
        Index("ix_ezs_unit_company_loc", "company_id", "current_location_id"),
        Index("ix_ezs_unit_supply", "company_id", "supply_id"),
        # Частично-уникальный индекс по lower(serial_number) — в миграции v2.15
        # (функциональный, декларативно не выразить).
    )


class EzsEquipmentMovement(Base):
    """Движение единицы оборудования: полный журнал судьбы железки.

    Каждое движение атомарно меняет unit (state/current_location/custodian) —
    текущее состояние единицы всегда выводимо из последнего движения."""
    __tablename__ = "ezs_equipment_movements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_equipment_units.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # receipt|transfer|reserve|unreserve|to_installation|commissioning|dismantle|
    # to_repair|from_repair|to_vendor|write_off|correction
    op: Mapped[str] = mapped_column(String(20), nullable=False)
    from_location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    to_location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    from_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    counterparty: Mapped[str | None] = mapped_column(String(300), nullable=True)  # кому передано
    occurred_on: Mapped[str] = mapped_column(String(10), nullable=False)          # ISO дата операции
    basis: Mapped[str | None] = mapped_column(String(300), nullable=True)         # документ-основание (текст)
    # Структурная привязка движения к документу поставки/возврата (receipt/to_vendor).
    # Мягкие ссылки без FK; basis остаётся человекочитаемым дублем.
    supply_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    supply_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ezs_move_company_date", "company_id", "occurred_on"),
        Index("ix_ezs_move_unit_created", "unit_id", "created_at"),
    )


class EzsSparePart(Base):
    """Номенклатура ЗИП (запчасти) — количественный учёт, без серийников."""
    __tablename__ = "ezs_spare_parts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # power_module|controller|connector|cable|display|board|other
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    vendor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    article: Mapped[str | None] = mapped_column(String(100), nullable=True)         # артикул
    compatible_models: Mapped[str | None] = mapped_column(String(300), nullable=True)
    unit_label: Mapped[str] = mapped_column(String(20), nullable=False, default="шт")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Удаление при наличии движений запрещено — архив (скрытие из подбора).
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Уникальность (company_id, lower(name)) — функциональный индекс в v2.15.


class EzsSparePartStock(Base):
    """Материализованный остаток ЗИП: (номенклатура × склад) → количество.

    Паттерн StockOnHand: снимок, корректируется движениями транзакционно
    (with_for_update), отрицательный остаток запрещён сервисом."""
    __tablename__ = "ezs_spare_part_stock"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    part_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_spare_parts.id", ondelete="CASCADE"), nullable=False)
    location_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="CASCADE"), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_ezs_spare_stock", "company_id", "part_id", "location_id", unique=True),
    )


class EzsSparePartMovement(Base):
    """Движение ЗИП: приход/расход/перемещение/списание/корректировка.

    Расход (issue) может быть привязан к станции-единице (target_unit_id)
    и/или площадке (target_location_id) — на что потрачена запчасть."""
    __tablename__ = "ezs_spare_part_movements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    part_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_spare_parts.id", ondelete="CASCADE"),
        nullable=False, index=True)
    op: Mapped[str] = mapped_column(String(20), nullable=False)  # receipt|issue|transfer|write_off|correction
    qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)  # > 0 (семантику даёт op)
    from_location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    to_location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    target_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_equipment_units.id", ondelete="SET NULL"), nullable=True)
    target_location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    occurred_on: Mapped[str] = mapped_column(String(10), nullable=False)
    basis: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Привязка движения ЗИП к документу поставки/возврата (мягкие ссылки, без FK).
    supply_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    supply_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ezs_spmove_company_date", "company_id", "occurred_on"),
        Index("ix_ezs_spmove_part_created", "part_id", "created_at"),
    )


# ===========================================================================
# Документы складского учёта оборудования (слой оснований поверх движений).
# Документ поставки/возврата не заменяет поток движений железа — он его
# ГРУППИРУЕТ и ОБОСНОВЫВАЕТ, храня план (спецификацию), против которого
# сверяется факт. Факт (принято) — производное от привязанных единиц/движений
# (COUNT единиц / SUM движений по supply_line_id), не хранимое поле.
# Поставщик = существующий Counterparty (kind='external'); ссылка мягкая +
# снимок имени (переживает пересинк/удаление справочника).
# Модель сверена с 1С: станция = ОС (07→08→01), ЗИП = материалы (10.05).
# ===========================================================================
class EzsSupplyDocument(Base):
    """Шапка документа поставки/возврата оборудования и ЗИП."""
    __tablename__ = "ezs_supply_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    # supply — поступление от поставщика (приход); return — возврат поставщику.
    # Задел на transfer|writeoff|inventory (обёртки над существующими движениями).
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False, default="supply")
    number: Mapped[str] = mapped_column(String(100), nullable=False)
    doc_date: Mapped[str] = mapped_column(String(10), nullable=False)              # ISO YYYY-MM-DD
    # Поставщик — мягкая ссылка на counterparties.id (без FK, как Contract.counterparty_id)
    # + снимок имени (устойчив к пересинку/удалению справочника, как movement.counterparty).
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Рамочный договор (мягкая ссылка): «поставка по договору №…».
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # draft → ordered → partially_received/received (производные) → closed | cancelled.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Склад-получатель по умолчанию для приёмки.
    warehouse_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="RUB")
    amount_total: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    vat_total: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_ezs_supply_company_status", "company_id", "status"),
        Index("ix_ezs_supply_company_date", "company_id", "doc_date"),
    )


class EzsSupplyLine(Base):
    """Строка спецификации документа: план (что и сколько заказано/возвращается).

    line_kind=station — шаблон единицы (при приёмке копируется в N карточек);
    line_kind=spare — количественная позиция ЗИП (part_id). qty_received НЕ
    хранится — считается из привязанных единиц/движений по id строки."""
    __tablename__ = "ezs_supply_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    supply_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_supply_documents.id", ondelete="CASCADE"),
        nullable=False, index=True)
    line_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="station")  # station|spare
    part_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_spare_parts.id", ondelete="SET NULL"), nullable=True)
    # Шаблон станции (для line_kind=station) — копируется в единицы при приёмке.
    vendor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    station_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    power_kwt: Mapped[float | None] = mapped_column(Float, nullable=True)
    connectors_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    connector_types: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)          # свободная метка позиции
    qty_planned: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    vat_rate: Mapped[str | None] = mapped_column(String(20), nullable=True)       # канон bp_export._nds
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ezs_supply_line_doc", "supply_id"),
    )


# ===========================================================================
# Банк ЗУ — площадки (земельные участки) под установку ЭЗС: девелоперский
# пайплайн развития сети. НЕ путать с EzsEquipmentUnit (склад железа): здесь
# учёт МЕСТ, где сеть строится, на стадиях проработки → работы → архива.
# Источник — сводный Excel «Банк данных ЗУ» (3 листа = стадии). Ключевые поля —
# в колонках (фильтры/агрегаты), полный ряд (55 колонок) — в raw JSONB.
# ===========================================================================
class EzsSite(Base):
    """Площадка (ЗУ) под установку ЭЗС — запись девелоперского пайплайна.

    Стадии — воронка подбора недвижимости с гейтами (см.
    `docs/SITES_LAND_BANK_BLUEPRINT.md`): lead → screening → negotiation → dd →
    decision → contracting → construction → live, плюс on_hold и archive.
    Дешёвые проверки идут раньше дорогих, стадия двигается по закрытию гейта.
    """
    __tablename__ = "ezs_sites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    # Человекочитаемый номер проекта (ЭЗС-2026-0042) — им называют проект в
    # переписке и на совещании; UUID для этого не годится.
    project_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)   # имя проекта
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="lead")
    stage_since: Mapped[str | None] = mapped_column(String(10), nullable=True)   # ISO-дата входа в стадию
    prev_stage: Mapped[str | None] = mapped_column(String(16), nullable=True)    # откуда пришла
    archive_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)  # почему отклонена
    status_raw: Mapped[str | None] = mapped_column(String(80), nullable=True)   # исходный «Статус»
    received_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ISO, «Дата поступления»
    # ── идентичность площадки (иначе повторный импорт плодит дубли) ──
    # Ключ по приоритету: кадастровый № → координаты (радиус ~50 м) → адрес+город.
    cadastral_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ── география ──
    region: Mapped[str | None] = mapped_column(String(160), nullable=True)       # как в файле
    region_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)  # канон справочника regions
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL"), nullable=True)
    city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    place_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)   # город|трасса
    install_place: Mapped[str | None] = mapped_column(String(300), nullable=True)
    route: Mapped[str | None] = mapped_column(String(80), nullable=True)        # трасса (Е-30, М-5…)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)             # распарсено из «Координаты»
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    coords_raw: Mapped[str | None] = mapped_column(String(120), nullable=True)
    map_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ── участок ──
    owner: Mapped[str | None] = mapped_column(String(400), nullable=True)       # собственник
    brand: Mapped[str | None] = mapped_column(String(160), nullable=True)       # бренд площадки (АЗС и т.п.)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    ownership: Mapped[str | None] = mapped_column(String(60), nullable=True)    # собственность|аренда
    free_power_kwt: Mapped[str | None] = mapped_column(String(80), nullable=True)  # часто текст («по запросу»)
    # ── экономика подключения (парсинг best-effort; NULL если не распознано) ──
    connection_cost: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    rent_cost_month: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # ── план ЭЗС ──
    planned_power_kwt: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_ezs_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ports_gbt: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ports_ccs: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ports_chademo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ports_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # ── участники и техприсоединение ──
    supplier: Mapped[str | None] = mapped_column(String(300), nullable=True)    # поставщик ЭЗС
    contractor: Mapped[str | None] = mapped_column(String(400), nullable=True)  # подрядчик
    # Роль участника — ссылкой на карточку контрагента; текст выше остаётся исходником
    # (в файле пишут «ООО «Ромашка» (аренда)», а карточка одна на все роли и продукты).
    # Без этого собственник площадки и арендодатель в договорах — два разных мира.
    owner_counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    supplier_counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    contractor_counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    tu_status: Mapped[str | None] = mapped_column(Text, nullable=True)          # статус согласования / ТУ
    tech_conn_type: Mapped[str | None] = mapped_column(String(300), nullable=True)
    dop_service: Mapped[str | None] = mapped_column(String(300), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ── ведение площадки (кто, что дальше, до какого срока) ──
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(300), nullable=True)
    next_action_due: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ISO
    last_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hold_until: Mapped[str | None] = mapped_column(String(10), nullable=True)       # для on_hold
    # Чек-листы гейтов: {ключ пункта: {"done": bool, "at": iso, "by": uuid}}.
    gates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Поля, изменённые руками, — импорт из файла их не трогает.
    manual_fields: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # ── права на землю (гейт «право») ──
    control_form: Mapped[str | None] = mapped_column(String(40), nullable=True)   # аренда|сервитут|размещение|собственность
    land_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    permitted_use: Mapped[str | None] = mapped_column(String(200), nullable=True)  # ВРИ
    encumbrances: Mapped[str | None] = mapped_column(Text, nullable=True)
    rent_rate: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    contract_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    contract_end: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # ── техприсоединение (гейт «техника») ──
    free_power_num: Mapped[float | None] = mapped_column(Float, nullable=True)     # кВт числом
    distance_to_tp_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp_cost: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    tp_term_months: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ── графы банка ЗУ, обязательные по чек-листу согласования (docx РусГидро) ──
    # Экономика этапа 3: входная цена электроэнергии и стоимость строймонтажа —
    # без них «Итого затраты на подключение» нечем разложить.
    input_price_kwth: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)  # R
    smr_cost: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)          # T
    # Условия площадки, которые проверяет отдел развития глазами (этап 2/3).
    long_term_contract: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # Y
    has_video: Mapped[bool | None] = mapped_column(Boolean, nullable=True)           # Z
    has_mobile: Mapped[bool | None] = mapped_column(Boolean, nullable=True)          # AB
    # Контакты этапа 3. Держим текстом: в файле это «Иванов 8-900-…, ТЦ Маяк» —
    # разбирать на карточки нечего, но без контакта переговоры вести некому.
    owner_contact: Mapped[str | None] = mapped_column(Text, nullable=True)           # AC
    source_company: Mapped[str | None] = mapped_column(String(300), nullable=True)   # AD
    source_person: Mapped[str | None] = mapped_column(Text, nullable=True)           # AE
    # ── субсидия: требования программы = обязательные параметры проекта ──
    # Мощность от 149 кВт, круглосуточный доступ, минимум два машино-места,
    # обязательство эксплуатировать 5 лет (см. docs/SITES_PROJECT_LIFECYCLE.md).
    subsidy_planned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    parking_spots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    access_24x7: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_lighting: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_internet: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    subsidy_amount: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    commissioned_on: Mapped[str | None] = mapped_column(String(10), nullable=True)  # дата ввода
    # ── замыкание цикла: построенная площадка = объект сети + договор в учёте ──
    # ⚠ `service_locations.id` — строковый nanoid, а не UUID. Колонка была объявлена
    # UUID, и связь физически не записывалась: `link_location` падал на типе, а
    # обязательный пункт регламента 8.8 «Объект заведён в реестре сети» закрыть
    # было нечем. Тип исправлен миграцией v2.27.
    location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    # Договор на землю в учёте. Через contract_locations связать нельзя: там ключ
    # на станцию, которой у проекта ещё нет.
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True)
    # Полный исходный ряд (заголовок → значение) — ничего не теряем при импорте.
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_sheet: Mapped[str | None] = mapped_column(String(80), nullable=True)  # лист-источник
    row_no: Mapped[int | None] = mapped_column(Integer, nullable=True)           # № строки в листе
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ezs_site_company_stage", "company_id", "stage"),
        Index("ix_ezs_site_company_region", "company_id", "region"),
        Index("ix_ezs_site_company_dedup", "company_id", "dedup_key"),
        Index("ix_ezs_site_company_owner", "company_id", "owner_user_id"),
    )


class EzsProject(Base):
    """Проект на площадке — временное предприятие с началом и концом.

    Разделение трёх сущностей (решение 28.07.2026): **площадка** (`ezs_sites`)
    это место и живёт всегда; **проект** — то, что на ней делают, и он
    закрывается; **объект** (`service_locations`) — актив, который переживает
    свои проекты и принимает новые.

    Зачем: пока проект был той же строкой, что и площадка, станцию нельзя было
    вернуть из эксплуатации на доработку — только откатить стадию назад, стирая
    историю ввода. По ФСБУ 26/2020 модернизация действующего объекта — это новое
    капвложение со своей датой решения, а не продолжение старого; по FERC замена
    узла = списание старой единицы плюс капитализация новой. Поэтому ретрофит,
    релокация и демонтаж — НОВЫЙ проект со ссылкой на тот же объект.

    Первый проект площадки создаётся из неё самой (миграция v2.27 завела по
    проекту на каждую существующую запись), поэтому `site_id` обязателен, а
    `location_id` появляется при вводе в эксплуатацию.
    """
    __tablename__ = "ezs_projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_sites.id", ondelete="CASCADE"), nullable=False, index=True)
    # Объект сети: у стройки появляется в конце, у ретрофита известен с начала.
    location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    # new_build | retrofit | relocation | decommission
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="new_build")
    project_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="lead")
    stage_since: Mapped[str | None] = mapped_column(String(10), nullable=True)
    prev_stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Причина, по которой проект остановлен. Для «отменён» это основание списания
    # капвложений (Дт 91.02 Кт 08), поэтому дату решения храним отдельно.
    closed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(300), nullable=True)
    next_action_due: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hold_until: Mapped[str | None] = mapped_column(String(10), nullable=True)
    gates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    commissioned_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_ezs_project_company_stage", "company_id", "stage"),
        Index("ix_ezs_project_site", "site_id"),
        Index("ix_ezs_project_location", "location_id"),
    )


class EzsSiteEvent(Base):
    """Событие площадки: смена стадии, касание, заметка, правка, импорт.

    История нужна не для аудита ради аудита: без даты входа в стадию нельзя
    сказать, что зависло, а без касаний — кто последний разговаривал с
    собственником и когда.
    """
    __tablename__ = "ezs_site_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_sites.id", ondelete="CASCADE"), nullable=False, index=True)
    # Проект, к которому относится запись. Через площадку связывать нельзя:
    # второй проект на том же месте (ретрофит) склеился бы с первым.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_projects.id", ondelete="CASCADE"), nullable=True, index=True)
    # stage | touch | note | edit | import | gate
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="note")
    from_stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ezs_site_event_site", "site_id", "created_at"),
    )


class EzsSiteDoc(Base):
    """Документ проекта: ЕГРН, ТУ, договор, схема, фото, акт.

    Файл лежит в общем хранилище (`source_files`), здесь — смысл: к какому
    проекту относится, какого типа и на каком этапе появился. Тип важен не для
    красоты: часть пунктов гейта закрывается именно приложенным документом
    («Договор подписан» — это скан договора, а не галочка).
    """
    __tablename__ = "ezs_site_docs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_sites.id", ondelete="CASCADE"), nullable=False, index=True)
    # Проект, к которому относится запись. Через площадку связывать нельзя:
    # второй проект на том же месте (ретрофит) склеился бы с первым.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_projects.id", ondelete="CASCADE"), nullable=True, index=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True)
    # egrn | site_plan | photo | offer | contract | tu | tp_contract | project | act_mount | act | other
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="other")
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True)   # на какой стадии приложен
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ezs_site_doc_site", "site_id", "kind"),
    )


class EzsTechConnection(Base):
    """Техприсоединение проекта — со своим жизненным циклом и сроками.

    Отдельная сущность, а не поля площадки: срок проекта определяется именно
    присоединением (от 60 дней без реконструкции до полутора лет с усилением
    сети), у него свои даты «план/факт» и своя переписка с сетевой организацией.
    """
    __tablename__ = "ezs_tech_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_sites.id", ondelete="CASCADE"), nullable=False, index=True)
    # Проект, к которому относится запись. Через площадку связывать нельзя:
    # второй проект на том же месте (ретрофит) склеился бы с первым.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_projects.id", ondelete="CASCADE"), nullable=True, index=True)
    # draft | applied | specs (ТУ получены) | contract | in_progress | done | rejected
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    grid_operator: Mapped[str | None] = mapped_column(String(300), nullable=True)  # сетевая организация
    grid_operator_counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    application_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    application_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    specs_no: Mapped[str | None] = mapped_column(String(80), nullable=True)        # № ТУ
    specs_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    contract_no: Mapped[str | None] = mapped_column(String(80), nullable=True)     # договор ТП
    contract_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    power_kwt: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    # Срок мероприятий сетевой организации: план и факт — из этой пары берётся просрочка.
    due_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    done_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    needs_reconstruction: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ── паспорт питающей сети (графы AQ–AV банка ЗУ, этап 2 чек-листа) ──
    # Отдел развития снимает эти параметры на осмотре: от них зависит, хватит ли
    # мощности без реконструкции и во что обойдётся присоединение.
    substation_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)   # AQ
    line_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)         # AR
    transformer_kva: Mapped[str | None] = mapped_column(String(80), nullable=True)     # AS (в файле «63 кВА»)
    line_type: Mapped[str | None] = mapped_column(String(120), nullable=True)          # AT
    extra_power_possible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # AU
    transformer_swap_possible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # AV
    # ── стоимость и сроки мероприятий ТУ (AX–BA, этап 5) ──
    # `cost` = договор с сетевой организацией (AW), это её часть работ.
    works_cost: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)    # AX
    total_cost: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)    # AY
    applicant_term_months: Mapped[float | None] = mapped_column(Float, nullable=True)  # BA
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_ezs_tc_company_status", "company_id", "status"),
    )


class EzsSiteEquipment(Base):
    """Потребность проекта в оборудовании и её исполнение.

    Отдельно от склада (`ezs_equipment_units`): склад отвечает на вопрос «что у
    нас есть и где лежит», а проект — «что этой площадке нужно и на каком этапе
    закупка». Пока железо не приехало, единицы склада ещё не существует, но
    потребность уже влияет на сроки и бюджет проекта.

    Когда оборудование поступает, строка связывается с единицей склада
    (`unit_id`) и документом поставки (`supply_id`) — так план сходится с фактом.
    """
    __tablename__ = "ezs_site_equipment"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_sites.id", ondelete="CASCADE"), nullable=False, index=True)
    # Проект, к которому относится запись. Через площадку связывать нельзя:
    # второй проект на том же месте (ретрофит) склеился бы с первым.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_projects.id", ondelete="CASCADE"), nullable=True, index=True)
    # planned | ordered | supplied | installed | cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)      # что именно
    manufacturer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    power_kwt: Mapped[float | None] = mapped_column(Float, nullable=True)
    connectors: Mapped[str | None] = mapped_column(String(120), nullable=True)  # GB/T, CCS2, CHAdeMO…
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supplier: Mapped[str | None] = mapped_column(String(300), nullable=True)
    supplier_counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    order_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    due_date: Mapped[str | None] = mapped_column(String(10), nullable=True)     # плановая поставка
    supplied_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    installed_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Связь с фактом на складе — появляется, когда железо приехало.
    unit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    supply_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_ezs_site_equipment_status", "company_id", "status"),
    )


class EzsSiteCost(Base):
    """Статья бюджета проекта: план и факт. Факт может ссылаться на документ."""
    __tablename__ = "ezs_site_costs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_sites.id", ondelete="CASCADE"), nullable=False, index=True)
    # Проект, к которому относится запись. Через площадку связывать нельзя:
    # второй проект на том же месте (ретрофит) склеился бы с первым.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_projects.id", ondelete="CASCADE"), nullable=True, index=True)
    # tp | equipment | smr | design | rent | other
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    plan_amount: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    fact_amount: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    doc_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)  # основание факта
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ===========================================================================
# Чат (внутренний мессенджер, Telegram-подобный) — порт ядра из TSupport.
# Комнаты компании (Общий/Объявления) + личные + группы; company-scoped.
# ===========================================================================
class ChatRoom(Base):
    """Комната чата: company (kind general/news), direct (личный), group."""
    __tablename__ = "chat_rooms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # type: company | direct | group. kind (только для company): general | news.
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="direct")
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)  # NULL у direct → имя собеседника
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)      # false = soft-delete
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Закреплённое сообщение (одно на комнату). Мягкая ссылка (без FK — избегаем
    # цикла chat_rooms↔chat_messages); валидность проверяет роут.
    pinned_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # updated_at = время последней активности (сортировка списка комнат)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_chat_rooms_company", "company_id"),
        Index("idx_chat_rooms_type", "type"),
        # Одна системная комната каждого вида (general/news) на компанию среди активных.
        Index("uq_chat_rooms_company_kind", "company_id", "kind",
              unique=True, postgresql_where=text("kind IS NOT NULL AND is_active = true")),
    )


class ChatParticipant(Base):
    """Участник комнаты + курсор непрочитанного (last_read_at)."""
    __tablename__ = "chat_participants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")  # member | admin
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_chat_participants", "room_id", "user_id", unique=True),
        Index("idx_chat_participants_user", "user_id"),
    )


class ChatMessage(Base):
    """Сообщение комнаты. user_name денормализован (история). Soft-delete."""
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")  # text|image|video|file|system
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Вложение (одиночный файл на сообщение; серия изображений = серия сообщений-«альбом»).
    file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reply_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    is_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_chat_messages_room_created", "room_id", "created_at"),
    )


class ChatMessageReaction(Base):
    """Реакция-эмодзи на сообщение. Одна на пользователя (UNIQUE)."""
    __tablename__ = "chat_message_reactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_chat_reaction", "message_id", "user_id", unique=True),
        Index("idx_chat_reaction_message", "message_id"),
    )


class ChatFolder(Base):
    """Персональная папка чатов (Telegram-стиль): набор комнат + порядок."""
    __tablename__ = "chat_folders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    room_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_chat_folders_user", "user_id", "sort_order"),
    )


# ===========================================================================
# Контроль дублей номенклатуры по цепочке Нефтосервер → локальная 1С 208 → ЦБ.
# Кеш карточек + привязок кассы (КодНефтосервера) + статусы/трекинг правок.
# Ключ склейки уровней — GUID карточки (lowercase-дефис, совпадает у 208 и ЦБ).
# ===========================================================================
class DedupCard(Base):
    """Карточка номенклатуры для анализа дублей. source='local208' (живой pull
    станции) или 'cb' (снимок ЦБ). Ключ склейки уровней — guid."""
    __tablename__ = "dedup_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)   # local208 | cb
    guid: Mapped[str] = mapped_column(String(40), nullable=False)     # UUID карточки (склейка)
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    code_prefix: Mapped[str | None] = mapped_column(String(8), nullable=True)  # 008|208|ЦБ0|000|...
    name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    name_norm: Mapped[str] = mapped_column(String(500), nullable=False, default="")  # ключ группировки
    marked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_assortment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # «в ассортименте» — НЕ дубль
    group_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # розн. цена (РС.ЦеныНоменклатуры «Розничная 208»)
    sold_qty: Mapped[float | None] = mapped_column(Float, nullable=True)  # продано за 30 дн (ОРП) — «продаётся сейчас»
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_dedup_cards", "company_id", "source", "guid", unique=True),
        Index("idx_dedup_cards_norm", "company_id", "name_norm"),
    )


class DedupNsBinding(Base):
    """Привязка кода кассы (КодНефтосервера) → карточка. Мост Нефтосервер↔1С:
    какой код на какую карточку бьёт, активна ли, розн.цена, помечена ли цель."""
    __tablename__ = "dedup_ns_bindings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    warehouse: Mapped[str | None] = mapped_column(String(20), nullable=True)   # код склада (208)
    ns_code: Mapped[str] = mapped_column(String(40), nullable=False)           # КодНС (ProdCode кассы)
    card_guid: Mapped[str | None] = mapped_column(String(40), nullable=True)   # карточка-цель
    card_marked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # цель помечена → касса бьёт дубль
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # Актуальность
    retail_price: Mapped[float | None] = mapped_column(Float, nullable=True)   # ЦенаВРознице
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_dedup_ns", "company_id", "warehouse", "ns_code", unique=True),
        Index("idx_dedup_ns_card", "company_id", "card_guid"),
    )


class DedupStatus(Base):
    """Отметка статуса дедупа (ручной трекинг). entity_type: 'group' (по
    нормализованному имени) или 'card' (по guid). Хранит статус + канон + заметку
    + историю изменений — чтобы отмечать что исправлено (скриптом/руками) и видеть прогресс."""
    __tablename__ = "dedup_statuses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(10), nullable=False)   # group | card
    entity_key: Mapped[str] = mapped_column(String(500), nullable=False)   # name_norm | guid
    # pending | not_duplicate | not_used | in_progress | repointed | merged | done
    # not_used — оператор пометил позицию «не используется / убрать» (вывод из НСИ,
    # не слияние: в export_plan / merge_map такие группы не попадают)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    canon_guid: Mapped[str | None] = mapped_column(String(40), nullable=True)  # выбранный хозяин группы
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{at,by,from,to,note}]
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_dedup_status", "company_id", "entity_type", "entity_key", unique=True),
    )


class DedupCorrectionJob(Base):
    """Задание на корректировку по команде менеджера. kind='repoint' — перецеп
    кодов НС на канон (Документ.УстановкаКодовНС на станции, авто через ноду).
    Слияние ЗаменитьСсылки НЕ автоматизируем (виснет) — отдаётся .epf-картой.
    Нода 208 забирает pending по ключу, выполняет, репортит результат."""
    __tablename__ = "dedup_correction_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="repoint")
    # pending | running | done | error | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # пробный прогон (план без записи)
    # {warehouse, groups:[{groupKey,title,canonGuid,canonCode,nsCodes:[...]}]}
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # отчёт ноды
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_dedup_jobs_company", "company_id", "status"),
    )


# ===========================================================================
# ElsyPlus Core — реестр приложений и модулей (app-измерение экосистемы).
# Заменяет клиентский localStorage-демо (moduleConnectionService): «что подключено
# компании» и «кто к чему допущен» — теперь СЕРВЕРНАЯ конфигурация, единый источник.
# Приложение = самоописываемый модуль экосистемы (Ledger, Support/Координатор, …);
# модуль = подраздел приложения (обобщение moduleComponents). Таблицы eco_* создаёт
# create_all при старте; сид каталога — services/app_registry.seed_apps (идемпотентно).
# ===========================================================================
class App(Base):
    """Каталог приложений экосистемы ElsyPlus."""
    __tablename__ = "eco_apps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)   # 'ledger','support',…
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(300), nullable=True)     # для лаунчера/SSO handoff
    icon: Mapped[str | None] = mapped_column(String(60), nullable=True)          # lucide-имя
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="app")
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Конфигурация приложения на уровне экосистемы (настройка при подключении):
    # свободный JSON (адреса, ключи-ссылки, параметры интеграции). Секреты — НЕ сюда.
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppModule(Base):
    """Модуль, который предоставляет приложение (обобщение moduleComponents фронта)."""
    __tablename__ = "eco_app_modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eco_apps.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)                # уникален в рамках приложения
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # is_core — не отключается (ядро приложения); default_on — включён по умолчанию новой компании.
    is_core: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    __table_args__ = (Index("uq_eco_app_module", "app_id", "code", unique=True),)


class CompanyApp(Base):
    """Подключение приложения компании (серверная замена localStorage-демо)."""
    __tablename__ = "eco_company_apps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eco_apps.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)            # per-company настройки приложения
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("uq_eco_company_app", "company_id", "app_id", unique=True),)


class CompanyAppModule(Base):
    """Включение конкретного модуля приложения на компанию."""
    __tablename__ = "eco_company_app_modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eco_apps.id", ondelete="CASCADE"), nullable=False)
    module_code: Mapped[str] = mapped_column(String(60), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("uq_eco_company_app_module", "company_id", "app_id", "module_code", unique=True),)


class AppCompanyLink(Base):
    """Карта соответствия компаний: компания пространства ↔ её идентификатор в приложении.

    Приложение-разрез ведёт СВОИ компании (у Координатора это собственная таблица
    `companies`), поэтому проекция общих сущностей обязана знать пару «наша компания —
    его компания». Без карты в мультикомпанийном контейнере объекты одной компании
    попадут другой — это нарушение изоляции уровня 2 (docs/SPACE.md §2, §6).

    Заполняется при онбординге приложения компании (Центр управления). `external_code` —
    человеческий ключ (slug/код) для сверки глазами и в логах.
    """
    __tablename__ = "eco_app_company_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eco_apps.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    # Идентификатор компании НА СТОРОНЕ приложения (строкой: у разных приложений разный тип).
    external_company_id: Mapped[str] = mapped_column(String(120), nullable=False)
    external_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Одна компания пространства ↔ одна компания приложения, в обе стороны.
        Index("uq_eco_app_company_link", "app_id", "company_id", unique=True),
        Index("uq_eco_app_company_link_ext", "app_id", "external_company_id", unique=True),
    )


# ===========================================================================
# Чат экосистемы (Matrix) — модель «как в Ангаре»: плоская. Группы = именованные
# приватные Matrix-комнаты + своя таблица; папки = клиентская группировка. Провижининг
# через Synapse Admin API сервисным аккаунтом. Скоуп по компании (Ур. 2): группы/личка/
# папки принадлежат компании; идентичность user→mxid — глобальная на пользователя.
# Темы (Matrix threads) живут В комнатах (m.thread) — отдельной таблицы не требуют.
# ===========================================================================
class MatrixIdentity(Base):
    """Привязка пользователя Ledger к Matrix-пользователю (mxid). Токен НЕ храним — минтим на сессию."""
    __tablename__ = "chat_matrix_identity"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    mxid: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationRule(Base):
    """О чём и куда оповещать в пространстве компании: категория событий × каналы.

    Каналы — те, что у пространства уже есть: чат (служебная комната «Оповещения», куда
    пишет сервисный аккаунт) и почта. Внешних сервисов рассылки не завожу: сообщение
    должно приходить туда, где человек и так работает.

    Получатели: `recipients = NULL` — администраторы организации (состав меняется сам,
    список не надо поддерживать руками); иначе перечисленные участники.
    """
    __tablename__ = "notification_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    # Код категории из `notify_catalog.CATEGORIES` (people | access | space | other).
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                          server_default=text("true"))
    via_chat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                           server_default=text("true"))
    via_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                            server_default=text("false"))
    recipients: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_notification_rule", "company_id", "category", unique=True),
    )


class MatrixGroupRoom(Base):
    """Групповой чат = именованная приватная Matrix-комната + метаданные (скоуп компании)."""
    __tablename__ = "chat_group_room"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    room_id: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MatrixDmRoom(Base):
    """Личный чат: упорядоченная пара пользователей → одна комната (скоуп компании)."""
    __tablename__ = "chat_dm_room"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    room_id: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)

    __table_args__ = (Index("uq_chat_dm_pair", "company_id", "user_a_id", "user_b_id", unique=True),)


class MatrixChatFolder(Base):
    """Папка чатов Matrix (Telegram-style) — клиентская группировка комнат, per-user×компания.
    Отдельно от TSupport-ChatFolder (другой чат): таблица chat_mx_folder."""
    __tablename__ = "chat_mx_folder"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    room_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ===========================================================================
# «Инфо» — знание пространства: инструкции, отраслевые нормы, ЛНД компании.
# Отдельное приложение уровня Ядра (docs/INFO.md): одно на всё пространство,
# открывается контекстно из любого рабочего места.
# ===========================================================================
class InfoCategory(Base):
    """Раздел дерева знаний.

    `company_id IS NULL` — раздел платформы (ведёт поставщик, виден всем
    пространствам); заполнен — раздел этого пространства. `profile_id` сужает
    платформенный раздел до отрасли: нормы по нефтепродуктам не нужны сети ЭЗС.
    """
    __tablename__ = "info_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    profile_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("info_categories.id", ondelete="CASCADE"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InfoArticle(Base):
    """Статья знания: инструкция, норма или локальный документ компании.

    Один текст живёт в одном месте, а появляется там, где нужен, — через привязки
    к продуктам и разделам (`InfoBinding`). Отдельного конфига «что показывать в
    каком приложении» нет: набор привязок и есть эта настройка.
    """
    __tablename__ = "info_articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    profile_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("info_categories.id", ondelete="SET NULL"), nullable=True)
    # guide (инструкция) | norm (отраслевая норма) | lnd (документ компании) | faq
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="guide")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="published")
    doc_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    effective_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Документ, который ведёт процесс в приложении: «Чек-лист согласования ЗУ»
    # стал гейтами в «Проектах». Пока значение одно — `ezs_checklist`.
    process_ref: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_info_article_company_kind", "company_id", "kind"),
        Index("ix_info_article_profile", "profile_id"),
    )


class InfoBinding(Base):
    """Где показывать статью: продукт и раздел его рабочей области.

    `section_key` пуст — статья относится ко всему продукту. `weight` решает, что
    подставить первым, когда контексту подходит несколько статей.
    """
    __tablename__ = "info_bindings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("info_articles.id", ondelete="CASCADE"), nullable=False, index=True)
    app_code: Mapped[str] = mapped_column(String(30), nullable=False)
    section_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_info_binding_ctx", "app_code", "section_key"),
    )
