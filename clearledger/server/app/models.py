"""
SQLAlchemy 2.0 ORM модели TradeLedger.
Все первичные ключи — UUID (хранятся как PostgreSQL UUID).
"""

import uuid
from datetime import date as date_type, datetime, time as time_type

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Sequence,
    String,
    Text,
    Time,
    UniqueConstraint,
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
    # Пояс организации. Срок «до 20-го» — обязательство перед компанией, и день
    # у него один на всех: считай его по получателю, и Владивосток просрочен за
    # семь часов до Москвы, работая по тому же договору.
    tz: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Europe/Moscow",
        server_default=text("'Europe/Moscow'")
    )
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
    # PIN станции: bcrypt-хеш короткого кода для входа на рабочем месте АЗС (edge).
    # Отдельно от password_hash: PIN едет вниз в ростере станции и разблокирует
    # профиль локально, а пароль экосистемы наружу не выходит. NULL — PIN не
    # задан, быстрый вход на станции недоступен (остаётся вход по паролю).
    station_pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    # Фотография человека (/api/files/<id>). Пространство — рабочее место, а не
    # реестр: в списке участников и у сообщений должно быть лицо, а не буква в
    # кружке. Генеративный кружок остаётся, пока фото не загружено.
    avatar_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Как с человеком связаться помимо пространства. Заполняет он сам: в рабочем
    # разговоре сплошь и рядом нужно позвонить, а искать телефон приходится по
    # переписке годичной давности. Городской — там, где мобильный не отвечает
    # (диспетчерская, приёмная), поэтому это два разных поля, а не одно.
    phone_mobile: Mapped[str | None] = mapped_column(String(40), nullable=True)
    phone_office: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Человек живёт в своей почте и в пространство не заходит: сообщения чатов
    # уходят ему письмом, а ответ возвращается в ленту. Учётка нужна только чтобы
    # он был участником комнаты и автором сообщений — вход ею невозможен
    # (пароля нет, `login` такие учётки отклоняет).
    mail_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Когда человека можно трогать. Пространство растянуто от Владивостока до
    # Москвы, и регламентное напоминание не бывает срочнее сна: в тишину оно не
    # пропускается, а сдвигается на начало ближайшего окна. Пояс — имя IANA, а
    # не смещение: «каждый понедельник в 10:00» иначе уедет на час при переводе
    # часов. Расчёты — `services/space_time.py`.
    tz: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Europe/Moscow",
        server_default=text("'Europe/Moscow'")
    )
    work_start: Mapped[time_type] = mapped_column(
        Time, nullable=False, default=lambda: time_type(9, 0),
        server_default=text("'09:00'")
    )
    work_end: Mapped[time_type] = mapped_column(
        Time, nullable=False, default=lambda: time_type(18, 0),
        server_default=text("'18:00'")
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
    # ЮРЛИЦО, которое участник ведёт. Не путать с `organization_id` выше: та про
    # внешнего подрядчика и ссылается на контрагента, а это — своя организация
    # компании (юрлицо её учёта). NULL = человек видит все юрлица клиента.
    #
    # Одно юрлицо, а не список: реальный случай — «бухгалтер ИП» и «бухгалтер ООО»,
    # и набор из нескольких потребует `= ANY(...)` во всех выборках. Заведём, когда
    # появится человек, ведущий два юрлица из трёх.
    own_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    # СКОУП ДАННЫХ: объекты пространства (`service_locations.id`), которые человек видит.
    # NULL = вся сеть компании; список = только эти объекты и всё, что к ним привязано
    # (сессии, оборудование, заявки). Права (`modules`) отвечают на вопрос «какие
    # экраны», скоуп — «по каким объектам»: подрядчику нужен «Парк оборудования», но
    # только на своих пяти станциях. Механика — `app/scope.py`.
    object_scope: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Бизнес-полномочия «Магазина». Не смешиваются с role/modules: один человек
    # может быть товароведом сети и администратором нескольких конкретных АЗС.
    # [{role, scope_type, scope_id}]
    business_grants: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # ОСНОВАНИЕ: договоры (`contracts.id`), по которым человек допущен в пространство.
    # Это справка, а не права — доступ даёт роль, а здесь видно, ЧЕМ он обоснован:
    # у подрядчика это его договор обслуживания. Список, потому что оснований бывает
    # несколько (рамочный плюс на объект); NULL или пусто — основание не указано.
    contract_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Подразделение по штатной структуре (org_departments). NULL — вне структуры.
    # Через него — руководитель, цепочка эскалации и подача людей по отделам.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_departments.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# SpaceInboundKey — именной входящий ключ пространства (docs/CONNECT.md, В2)
# ---------------------------------------------------------------------------
class SpaceInboundKey(Base):
    """Ключ, по которому внешняя система стучится К НАМ (X-Cloud-API-Key).

    Раньше ключ был один на компанию (companies.cloud_api_key) и на всех
    потребителей сразу: нельзя ни понять, кто именно ходит, ни отозвать одного,
    не уронив остальных. Здесь — ключ на потребителя: в БД только SHA256-хеш
    (доктрина «секрет не лежит в БД»), сам ключ показывается один раз при
    выдаче; prefix — первые символы для узнавания в списке.

    Имя таблицы с префиксом space_: у Поддержки в той же базе свои таблицы,
    и совпадающее имя молча уводит create_all в чужую схему (грабля departments).
    """
    __tablename__ = "space_inbound_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Кто ходит по ключу: «Дедуп-нода АЗС 208», «Аудитор Поддержки», …
    consumer: Mapped[str] = mapped_column(String(200), nullable=False)
    # Чем этот ключ представляется в следе: `partner` — чужая система (учётная
    # система контрагента, шлюз оператора), `agent` — наш автоматический
    # участник. Разница не косметическая: за партнёром стоит организация с
    # договором, за агентом — мы сами, и спрашивать с них по-разному.
    actor_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="partner")
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Department — подразделение компании: узел штатной структуры пространства
# ---------------------------------------------------------------------------
class Department(Base):
    """Дерево подразделений с руководителями — «кто кому подчиняется».

    По нему строится цепочка эскалации (сначала начальник подразделения, потом
    выше — не сразу директору), подача людей по отделам и, дальше, права и
    скоупы данных на уровне подразделения.

    Имя org_departments, а не departments: у Поддержки в той же базе (schema
    public) есть своя departments, а create_all ищет по search_path — совпадающее
    имя молча резолвится в чужую схему (та же грабля, что с core.users).
    """
    __tablename__ = "org_departments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Родительское подразделение: NULL — верхний уровень (дирекция).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_departments.id", ondelete="SET NULL"), nullable=True
    )
    # Руководитель: к нему идёт первая эскалация по людям этого подразделения.
    head_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    # Куда зовут: `company` — в одну организацию, `space` — в пространство целиком, то
    # есть во все его организации сразу. В контейнере на одну компанию разницы нет, но
    # в пространстве вроде «Аудита» (своя практика + обслуживаемые организации) это два
    # РАЗНЫХ приглашения, и человек обязан видеть, какое из них принимает: «Аудит» —
    # имя пространства, а не компании, и «вас приглашают в компанию Аудит» вводило в
    # заблуждение. `company_id` при `space` — организация, от имени которой позвали.
    scope: Mapped[str] = mapped_column(
        String(10), nullable=False, default="company", server_default=text("'company'")
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

    # Какой канал загрузки породил документ (трасса, docs/CONNECT.md В3).
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True
    )

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

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    fact_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    supersedes_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "data_entries.id", ondelete="RESTRICT",
            name="fk_data_entry_supersedes",
        ),
        nullable=True,
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

    __table_args__ = (
        CheckConstraint(
            "revision IS NULL OR revision > 0",
            name="ck_data_entry_revision_positive",
        ),
        CheckConstraint(
            "content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_data_entry_content_hash",
        ),
        CheckConstraint(
            "fact_origin IS NULL OR fact_origin IN "
            "('edge','store','onec_legacy','edo','cash')",
            name="ck_data_entry_fact_origin",
        ),
        Index(
            "uq_data_entry_document_revision",
            "company_id", "document_id", "revision",
            unique=True,
            postgresql_where=text("document_id IS NOT NULL"),
        ),
    )


class AccountingSourceLink(Base):
    __tablename__ = "accounting_source_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    projection_source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    canonical_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    confirmed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "projection_source IN ('edge','store','onec_legacy','edo','cash','bp')",
            name="ck_accounting_source_link_projection_source",
        ),
        Index(
            "uq_accounting_source_link_scope",
            "company_id", "projection_source", "source_kind", "source_document_id",
            unique=True,
        ),
    )


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
# ProcessSnapshot
# ---------------------------------------------------------------------------
class ProcessSnapshot(Base):
    """Последний известный ход процесса по предмету.

    Ход ведёт Координатор, и когда он недоступен, карточка проекта открывалась без
    панели хода вовсе: ни стадии, ни пройденного пути, ни вех. Человек в этот момент
    не может ничего нажать — но посмотреть, где стройка, должен.

    Снимок пишется на КАЖДОМ действии и на фоновой сверке, но никогда на чтении:
    открытие карточки не должно писать в базу (фаза 1). Поэтому он может отставать —
    и отдаётся честно помеченным, с временем последнего обновления.
    """

    __tablename__ = "process_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# SecurityEvent
# ---------------------------------------------------------------------------
class SecurityEvent(Base):
    """Отбитая попытка: перебор токенов публичной ссылки или подбор пароля.

    Отдельно от `audit_events` намеренно: там у каждой записи есть компания и
    пользователь, а перебор идёт до всякой аутентификации — ни того, ни другого у
    него нет. Пишется одна запись на окно и ключ: иначе перебор превращался бы в
    тысячи вставок, то есть в атаку нашими же руками.
    """

    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    ip: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(200), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


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
    # data — приём данных (портал загрузки, выгрузка учётной системы);
    # attachment — вложение чата или задачи. В слой L1 идёт только `data`.
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="data")
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
    # Папка справочника («Государственные органы»): не контрагент, но приезжает
    # наравне с ними и попадает в счётчик «Контрагентов: 268».
    is_group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    lifecycle_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default=text("'draft'")
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
    # ⚠ Исторически сюда клали ВИД номенклатуры («Товары»), а экраны печатали его как
    # единицу измерения — выходило «2548 Товары». Вид переехал в `kind`, здесь снова
    # человеческое имя единицы.
    unit_label: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # Ставка НДС позиции. Раньше у всех стояло 20 — значение по умолчанию модели, а не
    # из источника: «Без НДС» было не отличить от общей ставки.
    vat_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    vat_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Вид номенклатуры из справочника (Товары, Услуги, Материалы).
    kind: Mapped[str | None] = mapped_column(String(100), nullable=True)
    article: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Папка справочника: группы приезжают наравне с позициями и без признака выглядят
    # товаром («ОБЩЕСТРОИТЕЛЬНЫЕ ТОВАРЫ» в списке номенклатуры).
    is_group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: CounterpartyContact (контактные лица контрагента)
# ---------------------------------------------------------------------------
class CounterpartyContact(Base):
    """Живой человек на стороне контрагента: кому звонить и по какому поводу.

    Отдельной таблицей, а не полем в `Counterparty.raw`: raw — снимок выгрузки
    источника и перезаписывается при каждом импорте, ручной ввод там бы пропал.
    Телефон и почта самой организации остаются в карточке (`phone`/`email`) —
    это её реквизиты, а здесь люди.

    Роль отвечает на вопрос «по какому поводу»: заказчик просил различать
    договорную, техническую и общую связь — эскалация упирается именно в это.
    """

    __tablename__ = "counterparty_contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # contract | tech | comm | other
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Представление договора в 1С («№ 06/21 от 22.06.2021»): ИМЕННО ЭТА строка стоит
    # в субконто оборотов и в реквизитах документов. Без неё связь восстанавливается
    # разбором строки, а он спотыкается на «233\2011-пост от 20.06.11».
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Срок действия из карточки 1С. Пока его не грузили, «просроченные договоры»
    # считались эвристикой «заключён больше года назад» — 22 из 55 ложных.
    valid_until: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # UUID со ссылкой, как во всём остальном слое. Раньше здесь стояла строка без
    # внешнего ключа — единственное место ядра, где ось «контрагент» была не ссылкой:
    # целостность никто не проверял, и каждый запрос писал `c.counterparty_id::text`.
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
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
    # Вид договора по справочнику `contract_types` (rent, energy_supply, works…).
    # Колонка живёт с v2.30 и заполняется разбором `type`, но в ORM её не было:
    # запросы через модель падали с AttributeError, хотя в базе поле есть.
    # Без ForeignKey: сам справочник заведён сырым DDL и в метаданных ORM его нет,
    # а FK на неизвестную таблицу уронил бы create_all.
    type_code: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Показания прибора учёта и коэффициент трансформации: объём = (curr − prev) × КТ.
    # Именно так объём считает заказчик — в исходном файле лежат формулы `=46*30`
    # и пометка `198 - ПУ | К/Т = 50`. Без этих полей «нет расчёта» неотличимо от
    # «забыли внести», а цифра в intake_kwh невоспроизводима.
    meter_prev: Mapped[float | None] = mapped_column(Float, nullable=True)
    meter_curr: Mapped[float | None] = mapped_column(Float, nullable=True)
    ktrans: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Узел учёта, когда один прибор стоит на несколько станций (38 таких случаев).
    meter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ops_meters.id", ondelete="SET NULL"), nullable=True)
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
# Бухгалтерия-эталон: план счетов и проводки (GlAccount / GlEntry)
# ---------------------------------------------------------------------------
# Первоисток концепции: бухгалтерия компании — источник ЭТАЛОНА. Закрытый период в
# ней неизменяем, и всё остальное (первичка, продажи, услуги) сверяется с ним. До сих
# пор в Ядре были только `accounting_docs` (документы) и `periods` (статус закрытия),
# а самого регистра не было: топливной рознице эталон приходил агрегатами. Офисной
# компании нужен регистр как есть — план счетов и проводки.
#
# Источник — выгрузка бухгалтерии клиента (первый заход: файл .dt, дальше коннектор к
# живой базе). Данные принадлежат компании (`company_id`) и не пересекаются между
# организациями пространства.
# ---------------------------------------------------------------------------
class GlAccount(Base):
    """Счёт плана счетов организации."""

    __tablename__ = "gl_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    # Активный | Пассивный | Активно-пассивный — как в источнике.
    kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    off_balance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quantitative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    currency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Виды субконто счёта ПО ПОРЯДКУ: ["Контрагенты", "Договоры"]. Без них аналитика
    # оборота — просто строка: по счёту 62.01 первое субконто контрагент, по 20.01 —
    # номенклатурная группа, и понять это можно только из плана счетов.
    subconto: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_gl_account_code", "company_id", "code", unique=True),
    )


class GlReference(Base):
    """Справочник бухгалтерии, у которого нет своей таблицы в Ядре.

    Складов, статей затрат, статей ДДС, банков, физлиц и единиц измерения в
    нормализованном слое по отдельности не нужно — их не с чем сводить и незачем
    расширять. Но без них срез компании неполон: документ ссылается на склад и
    статью, и в разрезах учёта они обязаны существовать.

    Поэтому одна таблица на все мелкие справочники: `kind` — вид, `meta` — то, что
    у конкретного вида своё (БИК банка, вид статьи ДДС, родитель группы). Заводить
    десяток таблиц ради двух-трёх колонок в каждой значило бы утроить схему без
    единого нового вопроса, на который она отвечает.
    """

    __tablename__ = "gl_references"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Вид справочника как в источнике: warehouses, cost_items, cashflow_items,
    # banks, bank_accounts, persons, units, nomenclature_kinds, subdivisions.
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    parent_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_gl_references_kind", "company_id", "kind"),
        Index("uq_gl_reference", "company_id", "kind", "code", "name", unique=True),
    )


class GlEntry(Base):
    """Проводка регистра бухгалтерии: дата, корреспонденция, сумма."""

    __tablename__ = "gl_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Организация (юрлицо) внутри учёта клиента. У аутсорсера в одной базе 1С обычно
    # несколько юрлиц одного владельца, и без этой оси их цифры складываются в одну —
    # тихо, без ошибки на экране. Пусто означает «вся компания».
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    entry_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    # Год и месяц держим колонками: обороты по периодам — самый частый запрос, а
    # EXTRACT по дате индекс не берёт.
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    # Вид документа-регистратора («Реализация (акт, накладная, УПД)») и его
    # представление — по ним видно, чем порождена проводка.
    doc_kind: Mapped[str | None] = mapped_column(String(200), nullable=True)
    doc_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Ссылка на первичный документ. Без неё проводка знает документ только СТРОКОЙ
    # (`doc_title`), и от этого зависело сразу четыре измерения: контрагент,
    # организация, номенклатура и подразделение известны на уровне документа.
    # Разворот оборотки до первички тоже упирался сюда.
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_docs.id", ondelete="SET NULL"), nullable=True
    )
    account_dt: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_kt: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Откуда приехало: `1c_dt` (разовая выгрузка), позже — код коннектора.
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="1c_dt")
    # Ключ идемпотентности загрузки: повторный заход не должен задваивать обороты.
    external_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_gl_entries_period", "company_id", "period_year", "period_month"),
        Index("idx_gl_entries_doc", "company_id", "doc_id"),
        Index("idx_gl_entries_accounts", "company_id", "account_dt", "account_kt"),
        Index("uq_gl_entry_external", "company_id", "external_key", unique=True),
    )


class GlTurnover(Base):
    """Оборот Дт-Кт с аналитикой за месяц.

    Проводка (`gl_entries`) знает только корреспонденцию и сумму: субконто в
    основной таблице регистра бухгалтерии через COM недоступно — обращение к
    `СубконтоДт1` роняет выборку. Аналитика достаётся ТОЛЬКО из виртуальной
    таблицы оборотов и приходит уже свёрнутой по месяцу. Поэтому это отдельная
    сущность, а не колонки в проводке: гранулярность другая.

    На ней стоят взаиморасчёты («сколько должен покупатель и по какому договору»)
    и любой разрез, где нужен контрагент со стороны счёта.
    """

    __tablename__ = "gl_turnovers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Организация (юрлицо) внутри учёта клиента. У аутсорсера в одной базе 1С обычно
    # несколько юрлиц одного владельца, и без этой оси их цифры складываются в одну —
    # тихо, без ошибки на экране. Пусто означает «вся компания».
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    account_dt: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_kt: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Субконто приходят представлениями — имя контрагента, договора, статьи.
    dt1: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dt2: Mapped[str | None] = mapped_column(String(500), nullable=True)
    kt1: Mapped[str | None] = mapped_column(String(500), nullable=True)
    kt2: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Разобранная аналитика: субконто приходит ПРЕДСТАВЛЕНИЕМ, и пока это строка,
    # оборот нельзя связать ни с карточкой контрагента, ни с договором. Вид субконто
    # известен из плана счетов (`gl_accounts.subconto`), значение ищется в своём
    # справочнике по имени — см. `tools/onec/first-run/link-subconto.py`.
    dt_counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id"), nullable=True
    )
    kt_counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id"), nullable=True
    )
    dt_contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True
    )
    kt_contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True
    )
    # Остальные виды (номенклатура, статьи затрат и ДДС, склады, банковские счета,
    # работники) — одной картой, а не колонкой на каждый: колонок было бы двенадцать,
    # а витрины ходят по контрагенту и договору.
    #   {"dt1": {"kind": "Номенклатура", "table": "nomenclature", "id": "..."}, ...}
    sub_links: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    qty_dt: Mapped[float | None] = mapped_column(Numeric(18, 3), nullable=True)
    qty_kt: Mapped[float | None] = mapped_column(Numeric(18, 3), nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="1c_dt")
    external_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_gl_turnovers_period", "company_id", "period_year", "period_month"),
        Index("idx_gl_turnovers_accounts", "company_id", "account_dt", "account_kt"),
        Index("idx_gl_turnovers_dt_cp", "company_id", "dt_counterparty_id"),
        Index("idx_gl_turnovers_kt_cp", "company_id", "kt_counterparty_id"),
        Index("uq_gl_turnover_external", "company_id", "external_key", unique=True),
    )


class GlBalance(Base):
    """Сальдо счёта с аналитикой на дату среза.

    Снимок, а не расчёт: остаток считается по всей истории регистра, включая
    периоды до начала выгрузки, поэтому вывести его из наших проводок нельзя.
    Хранится с датой среза, чтобы старый снимок не выдавал себя за сегодняшний
    остаток.
    """

    __tablename__ = "gl_balances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Организация (юрлицо) внутри учёта клиента. У аутсорсера в одной базе 1С обычно
    # несколько юрлиц одного владельца, и без этой оси их цифры складываются в одну —
    # тихо, без ошибки на экране. Пусто означает «вся компания».
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    as_of: Mapped[date_type] = mapped_column(Date, nullable=False)
    account: Mapped[str] = mapped_column(String(20), nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Первое субконто счетов расчётов — контрагент. Ссылку проставляет загрузка:
    # сводить имя на лету нельзя, оно приходит представлением и в разном написании.
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True
    )
    sub1: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sub2: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sub3: Mapped[str | None] = mapped_column(String(500), nullable=True)
    debit: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    credit: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    qty_debit: Mapped[float | None] = mapped_column(Numeric(18, 3), nullable=True)
    qty_credit: Mapped[float | None] = mapped_column(Numeric(18, 3), nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="1c_dt")
    external_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_gl_balances_account", "company_id", "as_of", "account"),
        Index("uq_gl_balance_external", "company_id", "as_of", "external_key", unique=True),
    )


class VatEntry(Base):
    """Запись НДС: счёт-фактура журнала или предъявленный поставщиком налог.

    Одна таблица на три родственных набора (`kind`) — по той же причине, что и
    `gl_references`: поля совпадают на три четверти, а вопрос у них один — «чем
    подтверждён налог».
    """

    __tablename__ = "vat_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Организация (юрлицо) внутри учёта клиента. У аутсорсера в одной базе 1С обычно
    # несколько юрлиц одного владельца, и без этой оси их цифры складываются в одну —
    # тихо, без ошибки на экране. Пусто означает «вся компания».
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    # issued — выставленный покупателю, received — полученный от поставщика,
    # claimed — НДС, предъявленный поставщиком (движение вычета).
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    doc_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    counterparty_inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    counterparty_kpp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    vat: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    rate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Представление самого счёта-фактуры и документа-регистратора движения.
    invoice_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    registrar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    operation_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Реквизиты книги покупок и продаж: событие, дата счёта-фактуры, документ оплаты,
    # договор, дополнительный лист и корректируемый период. Из них собирается
    # декларация и сверка с контрагентом; своих колонок они не заслуживают —
    # у журнала счетов-фактур этих полей нет вовсе.
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="1c_dt")
    external_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_vat_entries_kind", "company_id", "kind", "doc_date"),
        Index("uq_vat_entry_external", "company_id", "external_key", unique=True),
    )


class InvoicePayment(Base):
    """Оплата счёта покупателю: чем и когда закрыт выставленный счёт.

    Главный вопрос аудита по счёту — «оплачен ли», и в самой первичке ответа нет:
    счёт и платёж связывает регистр «Оплата счетов», а не реквизиты документов.
    """

    __tablename__ = "invoice_payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Организация (юрлицо) внутри учёта клиента. У аутсорсера в одной базе 1С обычно
    # несколько юрлиц одного владельца, и без этой оси их цифры складываются в одну —
    # тихо, без ошибки на экране. Пусто означает «вся компания».
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    # Представление счёта на оплату и платёжного документа — как в источнике.
    invoice_title: Mapped[str] = mapped_column(String(500), nullable=False)
    payment_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Связь со счётом в нашем реестре документов, когда его удалось опознать.
    invoice_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_docs.id", ondelete="SET NULL"), nullable=True
    )
    paid_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    vat: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="1c_dt")
    external_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_invoice_payments_doc", "company_id", "invoice_doc_id"),
        Index("uq_invoice_payment_external", "company_id", "external_key", unique=True),
    )


class ExportAdjustment(Base):
    """Корректировка документа перед выгрузкой в бухгалтерию.

    Нормализованный слой — это то, ЧТО ЕСТЬ: копия учёта клиента. Выгрузка — то, что
    мы предлагаем провести. Это разные вещи, и они обязаны жить раздельно: правка
    прямо в слое стёрла бы исходник, и через месяц никто не отличил бы данные 1С от
    нашей интерпретации.

    Поэтому корректировка не меняет документ, а лежит рядом: было → стало, причина,
    автор, период. Выгрузка собирается как «слой плюс утверждённые корректировки»,
    и в любой момент видно, чем она отличается от источника.

    Корректировка ВСЕГДА адресная: у неё есть документ, поле и обоснование. Массовых
    правок «поднять все расходы на 10 %» здесь нет и не будет — это уже не учёт.
    """

    __tablename__ = "export_adjustments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Организация (юрлицо) внутри учёта клиента. У аутсорсера в одной базе 1С обычно
    # несколько юрлиц одного владельца, и без этой оси их цифры складываются в одну —
    # тихо, без ошибки на экране. Пусто означает «вся компания».
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)      # ГГГГ-ММ
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_docs.id", ondelete="CASCADE"), nullable=True
    )
    # Что правим: amount, vat_amount, date, contract, cost_account, article,
    # counterparty, status — имя поля документа или строки.
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Зачем: без причины корректировка неотличима от ошибки, и через квартал её
    # никто не защитит перед проверяющим.
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # draft — черновик, approved — утверждена к выгрузке, exported — ушла в 1С,
    # rejected — отклонена (оставляем след, а не удаляем).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("export_rules.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_export_adj_period", "company_id", "period", "status"),
        Index("idx_export_adj_doc", "company_id", "doc_id"),
    )


class ExportRule(Base):
    """Правило, по которому корректировка повторяется в следующих периодах.

    Разовая правка — это работа руками каждый месяц. Если основание постоянное
    («аренда всегда на 26 счёт, а не на 44»), решение принимается один раз и дальше
    применяется само — но КАЖДОЕ применение видно отдельной корректировкой, а не
    молча вшито в выгрузку.

    Правило предлагает, человек утверждает. Иначе через полгода в выгрузке живут
    решения, которых никто не помнит.
    """

    __tablename__ = "export_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # Условие отбора документов: вид, контрагент, статья, счёт — что задано, то и
    # проверяется. Пустое поле означает «любой».
    doc_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="CASCADE"), nullable=True
    )
    match_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    new_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # С какого периода действует: правило не должно задним числом переписывать то,
    # что уже выгружено.
    valid_from: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_export_rules_company", "company_id", "active"),
    )


class FindingDecision(Base):
    """Решение человека по находке проверки или тенденции.

    Проверки и тенденции пересчитываются с нуля при каждом открытии — иначе они
    отстанут от данных. Но у находки есть вторая жизнь: её один раз разобрали и
    объяснили. Без следа этого разбора объяснённый разовый поставщик 2022 года
    висит вечно, и к третьей неделе экран перестают открывать.

    Поэтому решение живёт отдельно от находки и цепляется к ней ключом
    «правило + строка». Находка исчезла — решение осталось; вернулась (данные
    перезалили) — решение снова к ней применится.

    `valid_until` для повторяющихся сюжетов: «в этом квартале объяснили, в новом
    посмотрим заново». Пусто — решение бессрочно.
    """

    __tablename__ = "finding_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Откуда находка: checks — проверки учёта, trends — тенденции, closing — дыры.
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="checks")
    rule_key: Mapped[str] = mapped_column(String(60), nullable=False)
    # Что именно разобрали: id документа, либо «период|предмет» для сводных строк.
    row_key: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # reviewed — посмотрели и вопросов нет, accepted — так и должно быть,
    # ignored — не наш случай (правило шумит на этих данных).
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="reviewed")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    valid_until: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_finding_decision", "company_id", "scope", "rule_key", "row_key",
              unique=True),
    )


class DocRequest(Base):
    """Требование документа: что ждём от контрагента и что уже делали, чтобы получить.

    Находка «оплата есть, документа нет» живёт ровно до перезагрузки данных, и пока
    её никто не взял в работу, «не пришло» неотличимо от «не смотрели». Требование —
    это находка, взятая человеком под контроль: у неё есть срок, ответственный,
    история обращений и итог.

    Реестр держим ЗДЕСЬ, а не в «Задачах» пространства (решение МАГа 13.08.2026):
    работа бухгалтера идёт от периода и контрагента, а не от карточки задачи, и
    требование обязано пересчитываться вместе с данными — задача этого не умеет.

    Закрывается требование не кнопкой «сделано», а появлением документа: `resolve`
    ищет его в слое по контрагенту, виду и периоду. Ручное закрытие тоже есть —
    у него отдельный статус, чтобы «нашли» не смешивалось с «махнули рукой».
    """

    __tablename__ = "doc_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Организация (юрлицо) внутри учёта клиента. У аутсорсера в одной базе 1С обычно
    # несколько юрлиц одного владельца, и без этой оси их цифры складываются в одну —
    # тихо, без ошибки на экране. Пусто означает «вся компания».
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    # Период, за который ждём документ (ГГГГ-ММ): у бухгалтера всё считается месяцем.
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    # Правило, которым находка была найдена (`purchase_no_vat_invoice` и т. п.) —
    # чтобы повторный разбор периода не заводил дубль того же требования.
    rule: Mapped[str] = mapped_column(String(50), nullable=False)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True
    )
    counterparty_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Документ-повод: платёж без закрывающего, поступление без счёта-фактуры.
    source_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_docs.id", ondelete="SET NULL"), nullable=True
    )
    # Чего именно ждём («Счёт-фактура», «Акт», «Накладная») и на какую сумму.
    doc_kind: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # open — на контроле, requested — запросили, promised — обещали, received —
    # документ появился в слое, disputed — контрагент спорит, dropped — решили не ждать.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    # Как документ придёт: от этого зависит, можно ли оформить задним числом.
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)   # edo | paper | unknown
    due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(300), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # История обращений: [{at, who, channel, text, result}] — эскалация это не поле
    # «напомнили», а лента: кто, когда, каким каналом и что ответили.
    escalations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    resolved_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_docs.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_doc_requests_period", "company_id", "period", "status"),
        # Одна находка — одно требование: повторный разбор периода не должен плодить
        # дубли, а перезагрузка данных не должна терять историю обращений.
        Index("uq_doc_request", "company_id", "rule", "source_doc_id", unique=True),
    )


class Employee(Base):
    """Сотрудник компании клиента: тот, кому начисляют и платят.

    Отдельная сущность, а не контрагент: у сотрудника другой набор реквизитов
    (СНИЛС, дата рождения), другие счета учёта (70, 68.01, 69) и другой режим
    доступа — это персональные данные, и роль «Коммерсант» их видеть не должна.

    ⚠ ПДн. Таблица содержит ФИО, ИНН и СНИЛС физических лиц. Заводится по прямому
    решению МАГа 13.08.2026: без зарплатного блока 86 проводок оставались без
    документа, а расходы не разворачивались до первички.
    """

    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    snils: Mapped[str | None] = mapped_column(String(20), nullable=True)
    birth_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="1c_dt")
    external_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_employee_external", "company_id", "external_key", unique=True),
    )


class PayrollEntry(Base):
    """Строка расчёта: начислено, удержано, НДФЛ или выплачено — по сотруднику и месяцу.

    Одна таблица на четыре вида (`kind`) по той же причине, что и `vat_entries`:
    поля совпадают, а вопрос один — «что человеку начислили и что он получил».
    Разводить по четырём таблицам значило бы четырежды повторить сотрудника, месяц
    и сумму.

    Месяц — это МЕСЯЦ НАЧИСЛЕНИЯ, а не дата документа: зарплату за декабрь считают
    в декабре, а платят в январе, и по дате документа расчёт разъезжается с периодом.
    """

    __tablename__ = "payroll_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Организация (юрлицо) внутри учёта клиента. У аутсорсера в одной базе 1С обычно
    # несколько юрлиц одного владельца, и без этой оси их цифры складываются в одну —
    # тихо, без ошибки на экране. Пусто означает «вся компания».
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    # accrual — начислено, deduction — удержано, ndfl — налог, payment — выплачено.
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_docs.id", ondelete="SET NULL"), nullable=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    employee_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Вид начисления или удержания как в 1С («Оплата по окладу», «НДФЛ»).
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    period_month: Mapped[str | None] = mapped_column(String(7), nullable=True)   # ГГГГ-ММ
    doc_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    days: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    hours: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="1c_dt")
    external_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_payroll_kind", "company_id", "kind", "period_month"),
        Index("idx_payroll_employee", "company_id", "employee_id"),
        Index("uq_payroll_external", "company_id", "external_key", unique=True),
    )


# ---------------------------------------------------------------------------
# AccountingDoc (Учётные документы 1С)
# ---------------------------------------------------------------------------
class CounterpartyEmail(Base):
    """Почтовый адрес контрагента — ответ на вопрос «кто это написал».

    Один контрагент пишет с нескольких адресов: `sales@`, бухгалтер лично, ЭДО-робот.
    Адреса берутся из карточки, из правил и — главное — ОБУЧЕНИЕМ: человек один раз
    сказал «это письмо от ТСМ», и дальше все письма с этого адреса опознаются сами,
    включая уже полученные.
    """

    __tablename__ = "counterparty_emails"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="CASCADE"), nullable=False)
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    # card | learned | rule — откуда узнали. Обученное человеком сильнее домена.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="learned")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("company_id", "address", name="uq_cp_email_company_address"),
        Index("idx_cp_email_cp", "company_id", "counterparty_id"),
    )


class MailRule(Base):
    """Правило обработки письма (docs/MAIL.md).

    Правила читаются по порядку, первое сработавшее решает судьбу письма. Условия
    пустые = «подходит всем»: правило без условий в конце списка — это политика по
    умолчанию, а не ошибка.
    """

    __tablename__ = "mail_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Пусто — правило применяется ко всем ящикам компании.
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mail_accounts.id", ondelete="CASCADE"), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Условия. Любое пустое поле условием не является.
    from_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    from_domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subject_like: Mapped[str | None] = mapped_column(String(300), nullable=True)
    has_attachment: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    unknown_sender: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Действие: intake | ticket | chat | task | doc | archive | quarantine | reject.
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="archive")
    # Что правило проставляет письму помимо действия: контрагента и договор.
    set_counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    set_contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True)
    # Куда доставить: комната чата для действия `chat`, объект для `ticket`.
    # Заявка всегда про объект — это устройство разреза поддержки, а не ограничение.
    set_room_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_rooms.id", ondelete="SET NULL"), nullable=True)
    set_object_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Сколько раз сработало: правило, которое не срабатывает, — мусор в списке.
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_mail_rules_company", "company_id", "sort"),
    )


class MailAccount(Base):
    """Почтовый ящик компании (docs/MAIL.md).

    Один коннектор «Почта компании» — много ящиков: info@, buh@, edo@, личный ящик
    менеджера. Механика у них одна, различаются учётка, назначение и правила,
    поэтому ящик — настройка коннектора, а не отдельный коннектор.

    Пароль в базе НЕ хранится: здесь имя переменной окружения стека (`secret_env`),
    значение живёт в `.env` рядом с остальными секретами — то же правило поставки,
    что у прочих коннекторов пространства.
    """

    __tablename__ = "mail_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Зачем этот ящик существует — человеческими словами. Без описания через месяц
    # никто не помнит, чем info@ отличается от edo@ и какие письма туда идут.
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    # in | out | both — только приём, только отправка или оба.
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="both")
    imap_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)
    imap_folder: Mapped[str] = mapped_column(String(100), nullable=False, default="INBOX")
    login: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # Два способа задать пароль, и оба нужны:
    #   secret_env      — имя переменной окружения стека (ставит внедренец);
    #   password_enc    — сам пароль, зашифрованный ключом стека (вводит СОТРУДНИК).
    # Без второго настроить ящик может только тот, у кого есть доступ к `.env` и
    # право провижинить стек, — то есть почта компании зависит от нас, а не от неё.
    secret_env: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    # Как шифруется канал: ssl (порт 465), starttls (587) или none (внутренний релей).
    smtp_security: Mapped[str] = mapped_column(String(10), nullable=False, default="starttls")
    imap_security: Mapped[str] = mapped_column(String(10), nullable=False, default="ssl")
    # Имя в поле «От кого» и подпись — то, что видит контрагент. Настройка ящика, а
    # не отправителя: письма от `buh@` подписаны бухгалтерией, кто бы их ни писал.
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Каждые сколько минут забирать почту. 0 — только вручную кнопкой.
    poll_interval_min: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Где остановились в прошлый раз. UIDVALIDITY обязателен: сервер вправе
    # перенумеровать ящик, и тогда старый UID указывает на чужое письмо.
    last_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uid_validity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Когда почта РЕАЛЬНО приходила. `last_sync_at` — «когда пытались»: по нему
    # считается расписание, и он обновляется даже когда сервер отбил пароль. На
    # витрине подключений это выглядело свежим обменом у ящика, который месяцами
    # не принимает ни письма.
    last_ok_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_mail_accounts_company", "company_id", "address"),
    )


class MailThread(Base):
    """Нить переписки: письмо и все ответы на него.

    Склейка идёт по In-Reply-To/References, а НЕ по теме: тему правят, переводят и
    дописывают «Re:», и по ней одна переписка разваливается на пять.
    """

    __tablename__ = "mail_threads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mail_accounts.id", ondelete="SET NULL"), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Корневой Message-ID: по нему нить находится, когда приходит ответ.
    root_message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    participants: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    messages_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_mail_threads_company", "company_id", "last_message_at"),
        Index("idx_mail_threads_root", "company_id", "root_message_id"),
    )


class MailMessage(Base):
    """Письмо: входящее из ящика или исходящее из пространства."""

    __tablename__ = "mail_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mail_accounts.id", ondelete="SET NULL"), nullable=True)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mail_threads.id", ondelete="CASCADE"), nullable=True)
    direction: Mapped[str] = mapped_column(String(3), nullable=False, default="in")
    uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    from_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    from_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    to_emails: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    # new | accepted | quarantine | rejected — судьба письма по правилам.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    # Кто написал, если удалось опознать по адресу.
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    # Заголовки целиком: проверки SPF/DKIM и разбор спорных случаев идут по ним.
    headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    has_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Письмо целиком, как пришло. Тело и заголовки разобраны в колонках выше, но
    # спор «что именно было в письме» решается оригиналом, а не нашим разбором.
    raw_eml: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Куда письмо доехало: chat | task | ticket | intake | doc. Пусто — осталось в переписке.
    routed_to: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Неудачная доставка не должна исчезать в логе: письмо остаётся в очереди,
    # администратор видит причину и может повторить маршрут после исправления.
    route_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    route_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    route_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_mail_messages_thread", "company_id", "thread_id"),
        Index("idx_mail_messages_msgid", "company_id", "message_id"),
        Index("uq_mail_messages_company_msgid", "company_id", "message_id",
              unique=True, postgresql_where=text("message_id IS NOT NULL")),
        Index("idx_mail_messages_account_uid", "account_id", "uid"),
    )


class MailAttachment(Base):
    """Вложение письма. Дубли ловятся хешем: одно и то же приходит по три раза."""

    __tablename__ = "mail_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mail_messages.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Вложение, ставшее кандидатом приёмки первички (docs/INTAKE.md).
    intake_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intake_batches.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_mail_attach_message", "company_id", "message_id"),
        Index("idx_mail_attach_hash", "company_id", "sha256"),
    )


class IntakeBatch(Base):
    """Пакет загрузки первички: один файл, одна выгрузка, одно письмо.

    Приём в пространство идёт не «файлами в папку», а пакетами: у пакета есть
    источник, автор, время и судьба каждой строки. Без этого нельзя ответить на
    два вопроса, которые задают всегда: «откуда взялся этот документ» и «что
    именно я загрузил в прошлый вторник».
    """

    __tablename__ = "intake_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # file | onec | edo | email | messenger — откуда пришёл пакет. Экран разбора
    # один на все источники: меняется способ доставки, а не работа с документом.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="file")
    file_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Что человек сказал про содержимое при загрузке («это реализации»). Пустое —
    # вид определяется по самим строкам.
    declared_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="parsed")
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_intake_batches_company", "company_id", "created_at"),
    )


class IntakeItem(Base):
    """Документ-кандидат из пакета: распознан, сопоставлен, проверен — но ещё не принят.

    Между «файл прочитан» и «документ в учёте» лежит работа, которую нельзя
    пропускать: сопоставить контрагента и договор с уже заведёнными, сверить с
    ранее загруженным (дубль? тот же номер?), убедиться, что месяц не закрыт, что
    сумма сходится со строками. Результат этих проверок живёт здесь, а не гибнет
    в логе разбора: человек принимает решение, глядя на них.
    """

    __tablename__ = "intake_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intake_batches.id", ondelete="CASCADE"), nullable=False
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False, default="sale")
    number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    counterparty_inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True)
    contract_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    vat_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    lines: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    # Исходная строка файла — чтобы человек видел, из чего распознали, и мог
    # спорить с разбором, а не с системой.
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Отпечаток документа (вид+номер+дата+ИНН+сумма): им ловится повторная
    # загрузка того же файла и совпадение с уже принятым документом.
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # new | ready | warning | duplicate | accepted | rejected
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    checks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    accounting_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_docs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_intake_items_batch", "company_id", "batch_id"),
        Index("idx_intake_items_status", "company_id", "status"),
        Index("idx_intake_items_fingerprint", "company_id", "fingerprint"),
    )


class AccountingDoc(Base):
    __tablename__ = "accounting_docs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Организация (юрлицо) внутри учёта клиента. У аутсорсера в одной базе 1С обычно
    # несколько юрлиц одного владельца, и без этой оси их цифры складываются в одну —
    # тихо, без ошибки на экране. Пусто означает «вся компания».
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)  # GUID 1С
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    number: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[str] = mapped_column(String(20), nullable=False)
    counterparty_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    counterparty_inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Ссылки в нормализованный слой. Текст выше остаётся исходником — как приехало из
    # 1С, — а вопросы «все документы этого покупателя», «его долг», «по какому договору»
    # отвечает связь: сводить строку на лету нельзя, имя приходит в разном написании,
    # а у платежей ИНН нет вовсе. Заполняет `services/books_links.py`.
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"),
        nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True)
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
    # Реквизиты, обязательные для СВОЕГО вида и бессмысленные для прочих: у платежа
    # назначение и счёт организации, у поступления входящий документ, у счёта-фактуры
    # основание и код операции, у акта сверки период. Колонка на каждый такой реквизит
    # дала бы полтора десятка полей, из которых у любого документа заполнены два.
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    # Реквизиты документа, за которыми не заводят колонку: время проведения, автор,
    # договор, комментарий, склад, статья ДДС, признак проведения. Для среза компании
    # они обязательны (по времени формирования документов вопрос задаётся в первую
    # очередь), но разбирать их по колонкам рано: у каждого вида документа состав свой.
    doc_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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

    __table_args__ = (
        # Ключ идемпотентности: этим набором срез ОБНОВЛЯЮТ, и без него второй заход
        # из выгрузки удвоил бы реестр, выручку и обороты — молча.
        Index("uq_accounting_doc_external", "company_id", "external_id", unique=True),
        Index("idx_accounting_docs_date", "company_id", "date"),
    )


class BusinessShift(Base):
    __tablename__ = "business_shifts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_key: Mapped[str] = mapped_column(String(120), nullable=False)
    station_id: Mapped[str] = mapped_column(String(80), nullable=False)
    business_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="resolved")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('resolved','needs_review')",
            name="ck_business_shift_status",
        ),
        Index(
            "ix_business_shift_scope",
            "company_id", "station_id", "business_date",
        ),
    )


class BusinessShiftAlias(Base):
    __tablename__ = "business_shift_aliases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_shifts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    algorithm: Mapped[str] = mapped_column(String(50), nullable=False)
    alias_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "algorithm IN ('business-shift-alias-v1',"
            "'business-shift-common-alias-v1')",
            name="ck_business_shift_alias_algorithm",
        ),
        CheckConstraint(
            "alias_hash ~ '^[0-9a-f]{64}$'",
            name="ck_business_shift_alias_hash",
        ),
        UniqueConstraint(
            "company_id", "algorithm", "alias_hash",
            name="uq_business_shift_alias_scope",
        ),
        Index(
            "ix_business_shift_alias_shift",
            "company_id", "business_shift_id",
        ),
    )


class AccountingBusinessGroup(Base):
    __tablename__ = "accounting_business_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_shifts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    business_key_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    packet_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    current_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    current_packet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "current_revision IS NULL OR current_revision > 0",
            name="ck_accounting_business_group_revision",
        ),
        CheckConstraint(
            "current_content_hash IS NULL OR "
            "current_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_accounting_business_group_hash",
        ),
        CheckConstraint(
            "status IN ('active','needs_review')",
            name="ck_accounting_business_group_status",
        ),
        UniqueConstraint(
            "company_id", "business_shift_id",
            name="uq_accounting_business_group_shift",
        ),
        UniqueConstraint(
            "company_id", "business_key_hash",
            name="uq_accounting_business_group_key",
        ),
        UniqueConstraint(
            "company_id", "packet_uuid",
            name="uq_accounting_business_group_packet",
        ),
    )


class AccountingSourceDecision(Base):
    __tablename__ = "accounting_source_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_shifts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    candidate_business_shift_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    winner_fact_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    loser_fact_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    fact_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    policy_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    manifest_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    manifest_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    shadow_status: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('resolved','needs_review')",
            name="ck_accounting_source_decision_status",
        ),
        CheckConstraint(
            "shadow_status IN ('winner','shadow','blocked','not_applicable')",
            name="ck_accounting_source_decision_shadow_status",
        ),
        Index(
            "ix_accounting_source_decision_shift",
            "company_id", "business_shift_id", "created_at",
        ),
    )


class AccountingClaimRequest(Base):
    __tablename__ = "accounting_claim_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    consumer_id: Mapped[str] = mapped_column(String(160), nullable=False)
    claim_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    lease_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    packet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("export_packets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "lease_seconds BETWEEN 1 AND 3600",
            name="ck_accounting_claim_lease",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_accounting_claim_hash",
        ),
        UniqueConstraint(
            "company_id", "consumer_id", "claim_request_id",
            name="uq_accounting_claim_request",
        ),
    )


class BusinessShiftMigrationCollision(Base):
    __tablename__ = "business_shift_migration_collisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    collision_key: Mapped[str] = mapped_column(String(200), nullable=False)
    collision_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id", "collision_kind", "collision_key",
            name="uq_business_shift_migration_collision",
        ),
    )


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

    packet_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contract_version: Mapped[str | None] = mapped_column(String(10), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    fact_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transport_producer: Mapped[str | None] = mapped_column(String(30), nullable=True)
    accounting_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounting_business_groups.id", ondelete="RESTRICT"),
        nullable=True,
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ack_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    component_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    __table_args__ = (
        CheckConstraint(
            "revision IS NULL OR revision > 0",
            name="ck_export_packet_revision_positive",
        ),
        CheckConstraint(
            "content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_export_packet_content_hash",
        ),
        CheckConstraint(
            "fact_origin IS NULL OR fact_origin IN "
            "('edge','store','onec_legacy','edo','cash')",
            name="ck_export_packet_fact_origin",
        ),
        CheckConstraint(
            "kind NOT IN ('food_accounting_group','store_accounting_group') OR "
            "(packet_uuid IS NOT NULL AND revision IS NOT NULL "
            "AND contract_version IS NOT NULL AND content_hash IS NOT NULL "
            "AND fact_origin IS NOT NULL AND transport_producer IS NOT NULL "
            "AND status IN ('draft','validated','queued','retry_wait','leased',"
            "'sent_waiting_ack','accepted','rejected','blocked_mapping',"
            "'needs_review'))",
            name="ck_export_packet_accounting_contract",
        ),
        Index(
            "uq_export_packets_accounting_revision",
            "company_id", "packet_uuid", "revision",
            unique=True,
            postgresql_where=text(
                "kind IN ('food_accounting_group','store_accounting_group')"
            ),
        ),
        Index(
            "uq_export_packets_active_business_group",
            "company_id", "accounting_group_id",
            unique=True,
            postgresql_where=text(
                "accounting_group_id IS NOT NULL AND kind IN "
                "('food_accounting_group','store_accounting_group') AND status IN "
                "('draft','validated','queued','retry_wait','leased',"
                "'sent_waiting_ack','blocked_mapping')"
            ),
        ),
    )


class AccountingOutboxAttempt(Base):
    __tablename__ = "accounting_outbox_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("export_packets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ack_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    component_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_accounting_outbox_attempt_packet",
            "company_id", "packet_id", "created_at",
        ),
    )


# ---------------------------------------------------------------------------
# Защитный контур бухгалтерского egress сопутки/общепита
# ---------------------------------------------------------------------------

class AccountingSourcePolicy(Base):
    __tablename__ = "accounting_source_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_group: Mapped[str] = mapped_column(
        String(50), nullable=False, default="sidegoods_foodservice"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="prepared", server_default="prepared"
    )
    fact_cutover_business_date: Mapped[date_type] = mapped_column(
        Date, nullable=False
    )
    station_timezone: Mapped[str] = mapped_column(
        String(80), nullable=False, default="Europe/Moscow"
    )
    fact_origin_before: Mapped[str] = mapped_column(
        String(20), nullable=False, default="onec_legacy"
    )
    fact_origin_after: Mapped[str] = mapped_column(
        String(20), nullable=False, default="edge"
    )
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transport_cutover_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    transport_producer_before: Mapped[str] = mapped_column(
        String(30), nullable=False, default="legacy_epf"
    )
    transport_producer: Mapped[str] = mapped_column(String(30), nullable=False)
    shadow_validation_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_accounting_source_policy_window",
        ),
        CheckConstraint(
            "transport_producer IN ('central_ledger', 'legacy_epf')",
            name="ck_accounting_source_policy_producer",
        ),
        CheckConstraint(
            "transport_producer_before IN ('central_ledger', 'legacy_epf')",
            name="ck_accounting_source_policy_producer_before",
        ),
        CheckConstraint(
            "fact_origin_before IN ('edge', 'onec_legacy') AND "
            "fact_origin_after IN ('edge', 'onec_legacy')",
            name="ck_accounting_source_policy_fact_origins",
        ),
        CheckConstraint(
            "state IN ('prepared', 'approved', 'armed', 'effective', "
            "'expired', 'superseded')",
            name="ck_accounting_source_policy_state",
        ),
        UniqueConstraint(
            "company_id", "station_id", "policy_group", "revision",
            name="uq_accounting_source_policy_revision",
        ),
        Index(
            "ix_accounting_source_policy_lookup",
            "company_id", "station_id", "policy_group", "effective_from",
        ),
    )


class CutoverManifest(Base):
    __tablename__ = "cutover_manifests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounting_source_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_group: Mapped[str] = mapped_column(String(50), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="prepared")
    canonical_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    approvals: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    operational_cutover_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accounting_transport_cutover_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    late_arrival_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    arm_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    prepare_ack_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    arm_ack_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('prepared', 'approved', 'armed', 'effective', "
            "'expired', 'superseded')",
            name="ck_cutover_manifest_state",
        ),
        CheckConstraint(
            "accounting_transport_cutover_at >= operational_cutover_at",
            name="ck_cutover_manifest_cutover_order",
        ),
        CheckConstraint(
            "arm_deadline IS NULL OR arm_deadline < accounting_transport_cutover_at",
            name="ck_cutover_manifest_arm_deadline",
        ),
        UniqueConstraint("policy_id", name="uq_cutover_manifest_policy"),
        UniqueConstraint(
            "company_id", "station_id", "policy_group", "revision",
            name="uq_cutover_manifest_revision",
        ),
        Index(
            "ix_cutover_manifest_lookup",
            "company_id", "station_id", "policy_group", "state",
        ),
    )


class CutoverApproval(Base):
    __tablename__ = "cutover_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    manifest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cutover_manifests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "manifest_id", "user_id", name="uq_cutover_approval_user"
        ),
        Index(
            "ix_cutover_approval_manifest",
            "company_id", "manifest_id", "approved_at",
        ),
    )


class AccountingShadowResult(Base):
    __tablename__ = "accounting_shadow_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_group: Mapped[str] = mapped_column(
        String(50), nullable=False, default="sidegoods_foodservice"
    )
    source_document_id: Mapped[str] = mapped_column(String(120), nullable=False)
    accounting_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    fact_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    blockers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('shadow_validated', 'shadow_blocked')",
            name="ck_accounting_shadow_result_status",
        ),
        UniqueConstraint(
            "company_id", "source_document_id", "result_hash",
            name="uq_accounting_shadow_result_version",
        ),
        Index(
            "ix_accounting_shadow_result_lookup",
            "company_id", "station_id", "policy_group", "fact_at",
        ),
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
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True,
    )
    station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
# FuelTransaction (пооперационная реализация — STS /v2/transactions)
# ---------------------------------------------------------------------------
class FuelTransaction(Base):
    """Пооперационная транзакция отпуска топлива из STS /v2/transactions.

    Грейн = одна операция на ТРК (в отличие от FuelShiftSale = агрегат смена×канал×
    топливо). Даёт счётчик реализаций (как в эталонной системе), реестр операций и
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
    receipt: Mapped[int | None] = mapped_column(Integer, nullable=True)  # номер чека (STS `number`)
    pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nozzle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    fuel_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pay_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pay_type_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Нормализованный вид оплаты («Банковские», «Наличные», «Купон»…) — по нему
    # группируются KPI-карточки и фильтруется реестр: сырых имён у STS десятки
    # вариантов на один смысл. Заполняется при ингесте (payment_normalize).
    payment_method: Mapped[str | None] = mapped_column(String(120), nullable=True)
    card: Mapped[str | None] = mapped_column(String(64), nullable=True)

    liters: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)   # quantity
    price: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)          # ₽/л
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)    # ₽ (STS cost)
    mass: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)           # кг (STS amount)
    density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    # Заказ клиента до отпуска: «залей на 1000 ₽» — расхождение с фактом видно в карточке.
    order_qty: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    order_cost: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    # STS отдаёт только завершённые реализации; поле — под будущие отменённые/сбойные.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed",
                                        server_default="completed")

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

    # Какой канал загрузки породил смену (трасса, docs/CONNECT.md В3).
    # NULL — ручной /fuel/normalize или данные до введения трассы.
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"),
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

    # Какой канал загрузки породил поступление (трасса, docs/CONNECT.md В3).
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"),
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

    # Какой канал загрузки породил заказ (трасса, docs/CONNECT.md В3).
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True
    )

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
    # Источник Ядра — у пакета, привезённого нашим каналом. Стал необязательным,
    # когда сырое начали класть и приложения: у подключения Координатора источника
    # в Ядре нет и быть не должно — свой обмен оно ведёт само.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=True
    )
    # Подключение пространства — у пакета, положенного приложением. Заполнена
    # ровно одна из двух ссылок: пакет либо наш, либо чужой, и «оба сразу»
    # означало бы, что мы не знаем, кто его привёз.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eco_space_connections.id", ondelete="CASCADE"), nullable=True
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
    # Читать через location_bindings() — в JSONB попадала и одиночная привязка
    # объектом, а на ней падал весь справочник (см. функцию ниже).
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


def location_bindings(loc: "ServiceLocation") -> list[dict]:
    """Привязки объекта к источникам — всегда списком словарей.

    В колонку писали не только список: сведение справочника 28.07.2026 положило
    142 объектам одиночную привязку ОБЪЕКТОМ (`{"origin": "hubex_mirror", …}`).
    Схема ждёт список, поэтому весь `GET /api/locations` отвечал 500 — вместе с
    ним пустели селектор станций, карта, парк и все экраны, перечисляющие сеть.
    Ошибка одной записи не должна ронять весь справочник: приводим тип на чтении
    и молча пропускаем то, что привязкой быть не может.
    """
    raw = loc.source_bindings
    if isinstance(raw, dict):
        return [raw]
    if not isinstance(raw, list):
        return []
    return [b for b in raw if isinstance(b, dict)]


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
# FuelTankSpec — ПАСПОРТ РЕЗЕРВУАРА: вместимость для отбраковки замеров.
#
# Нужен, чтобы отличать невозможное показание уровнемера от настоящего. Без
# паспорта вместимость оценивается по книге (максимум остатка за историю), а книга
# на части станций сама завышена — тогда невозможный замер проходит проверку.
#
# Источник вместимости — сам STS: `/v1/tanks` отдаёт `volume_max` по каждому
# резервуару станции (это же значение «Ёмкость» показывает «Монитор»). Поэтому
# паспорт синхронизируется, а не набивается руками; ручной ввод остаётся как
# уточнение, когда прибор врёт и про свою ёмкость тоже.
#
# `source`: sts — из источника, manual — введено человеком (приоритетнее всего),
# estimate — наша оценка по книге, отправная точка до синхронизации.
# ---------------------------------------------------------------------------
class FuelTankSpec(Base):
    __tablename__ = "fuel_tank_specs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id", ondelete="CASCADE"), nullable=False
    )
    tank_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fuel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Номинал по паспорту и рабочая ёмкость (по ней проверяется замер).
    nominal_liters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    usable_liters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Мёртвый остаток — ниже него топливо не выдаётся, замер около него нормален.
    dead_liters: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # sts | manual | estimate — откуда взялась вместимость (см. шапку модели).
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="estimate")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_fuel_tank_spec", "company_id", "station_id", "tank_number", unique=True),
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
    # Обогащение картой (`ezs_rfid_cards` витрины АСУиМ). В самой сессии от карты
    # есть только UID вида «26AA5969»: по нему нельзя ни отобрать заправки по
    # заблокированной карте, ни назвать владельца. Проставляет enrich_session_cards().
    card_number: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    card_status: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    card_owner_ext_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    # Заправка не владельцем карты: телефон карты не совпал с телефоном сессии.
    # Для корпоративных карт это то, что стоит видеть списком, а не находить.
    card_foreign: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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


class ChargePayment(Base):
    """Платёж эквайринга по зарядной сессии — витрина АСУиМ (`payments_ru`).

    Закрывает контур «сессия → списание → фискальный чек» без отдельных
    коннекторов к банку и ОФД. Механика оплаты картой трёхтактная: на старте
    ставится ХОЛД (предавторизация), по завершении списывается фактическая
    сумма, разница ВОЗВРАЩАЕТСЯ. Поэтому выручка — это `amount`; складывать
    `hold_amount` нельзя (в пробной выгрузке холдов 73,6 млн ₽ против 24,5 млн ₽
    выручки). Проверка целостности строки: hold − refund = amount.

    Связь с сессией — по `session_ext_id` (без FK): платежи приходят окнами по
    датам и обгоняют сессии, поэтому платёж существует и до того, как загружена
    его сессия. Дедуп по (компания, id платежа) — повторные окна безопасны."""
    __tablename__ = "charge_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True)

    payment_ext_id: Mapped[str] = mapped_column(String(64), nullable=False)      # «id_платежа»
    bank_txn_id: Mapped[str | None] = mapped_column(String(64), nullable=True)   # «id_транзакции_банка»
    session_ext_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)         # списано
    hold_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)    # предавторизация
    refund_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)  # возврат остатка

    by_card: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    op_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    op_type: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    # Код статуса АСУиМ (0/1/2/4). Выручку несут и «0», и «2», поэтому фильтром по
    # статусу пользоваться нельзя, пока заказчик не расшифрует значения.
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # чек ОФД
    user_ext_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    user_phone: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_charge_payments", "company_id", "payment_ext_id", unique=True),
        Index("idx_charge_payments_paid", "company_id", "paid_at"),
    )


class EzsCustomer(Base):
    """Клиент ЭЗС из витрины АСУиМ (`users_ru`) — БЕЗ персональных данных.

    Решение МАГа 08.08.2026: пока нет отдельного разрешения на обработку ПДн,
    из справочника физлиц берём ТОЛЬКО номер телефона — он и так является ключом
    связи в модели (в сессиях `user_id` = телефон). ФИО, отчество, e-mail, логин
    и аватар не переносим и не храним. Для юридических лиц ограничения нет:
    телефон корпоративного аккаунта — идентификатор организации, а не человека.

    Зачем нужен: телефон + дата регистрации дают когорты («когда клиент пришёл»),
    а `organization_ext_id` — точную связку с ЮЛ вместо сопоставления по телефону."""
    __tablename__ = "ezs_customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)

    customer_ext_id: Mapped[str] = mapped_column(String(40), nullable=False)   # «id_пользователя»
    # Нормализованный (+7XXXXXXXXXX): витрина отдаёт «+7(999) 999 99-95», а сессии
    # и платежи — «+79999999995». Без приведения связка не собирается.
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    organization_ext_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    balance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_ezs_customers", "company_id", "customer_ext_id", unique=True),
    )


class EzsRfidCard(Base):
    """RFID-карта клиента ЭЗС — витрина АСУиМ (`rfid_cards_ru`).

    Нужна, чтобы у сессии по карте был владелец: в `charge_sessions.rfid` лежит
    UID карты (в нижнем регистре), в витрине — тот же UID в верхнем, поэтому
    храним нормализованный. Персональных данных, кроме телефона, не несёт."""
    __tablename__ = "ezs_rfid_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)

    card_ext_id: Mapped[str] = mapped_column(String(40), nullable=False)       # «id_карты»
    uid: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)   # UPPER
    number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_ext_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_ezs_rfid_cards", "company_id", "card_ext_id", unique=True),
    )


class EzsReference(Base):
    """Малые справочники витрины АСУиМ: бренды станций, группы станций, модели ЭМ.

    Одна таблица на три вида, а не три модели: вместе они дают 282 строки, а
    состав полей у каждого — два-три значения. `kind` разделяет виды, редкие
    атрибуты лежат в `payload`.

    Связи с объектами пока нет и она не наша вина: в `stations_ru` колонки
    `id_бренда` и `id_группы` пусты, бренд записан текстом. Справочники держим
    заведёнными, чтобы связь села сразу, как заказчик её отдаст."""
    __tablename__ = "ezs_references"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)

    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # brand|group|car
    ext_id: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_ezs_references", "company_id", "kind", "ext_id", unique=True),
    )


class EzsTariff(Base):
    """Номинал прайса ЭЗС — витрина АСУиМ (`tariffs_ru`).

    Тариф разложен построчно по типу разъёма, поэтому строка = (тариф, тип
    разъёма). Нужен, чтобы «факт против номинала» сравнивал факт с прайсом, а не
    факт с фактом: до появления справочника цена бралась из самой сессии."""
    __tablename__ = "ezs_tariffs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)

    tariff_ext_id: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tariff_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    connector_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    connector_type: Mapped[str | None] = mapped_column(String(40), nullable=True)

    price_all_day: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_day: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_night: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_halfpeak: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_peak: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    reservation_cost: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    idle_cost: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    valid_from: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Привязки приходят строкой-перечислением (в пробной выгрузке пусты).
    stations: Mapped[str | None] = mapped_column(Text, nullable=True)
    organizations: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_ezs_tariffs", "company_id", "tariff_ext_id", "connector_type_id", unique=True),
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
    # ── Графы складского реестра заказчика ──────────────────────────────────
    # Регион и хранитель отвечают на вопрос «где физически лежит станция и кто за
    # неё отвечает», пока она не смонтирована: склад заказчика, склад подрядчика и
    # склад производителя — три разных ответственности, а не одна «локация».
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    keeper: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Номер счёта 08 у заказчика: станция на складе — это капвложение, и в его
    # учёте она живёт этим номером. Свой идентификатор объекта им не подменяется
    # (СТО, п. 8.5) — графа отдельная и названа честно.
    accounting_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Номер во внешнем реестре заказчика (ZOI/ЗЕВС), если он уже присвоен.
    external_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Данные подтверждены поставщиком. Реестр приходит с позициями, по которым
    # количество и порты ещё уточняются: показать их как обычный остаток значило бы
    # выдать ожидание за факт, а выбросить — потерять то, что уже известно.
    data_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    unconfirmed_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # ── Паспорт станции как объекта инфраструктуры (СТО, уровень «станция») ──
    # До разделения уровней эти графы жили в `ServiceLocation` — там, где теперь
    # точка обслуживания. Уровни разъехались: замена станции не прерывает
    # аналитику выручки точки (СТО п. 5.2), а перемещение станции не меняет её
    # инвентарный номер (п. 5.3). Размещение — не колонка, а связь с периодом
    # (`object_links`): оно меняется во времени, и «где было на дату» скалярной
    # ссылкой не выражается.
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)          # коммерческое обозначение (п. 2.18)
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)     # владелец (п. 2.16)
    operator_name: Mapped[str | None] = mapped_column(String(200), nullable=True)  # оператор (п. 2.17)
    ocpp_protocol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    firmware: Mapped[str | None] = mapped_column(String(80), nullable=True)
    speed_class: Mapped[str | None] = mapped_column(String(10), nullable=True)     # fast | slow
    # Даты жизненного цикла ISO 'YYYY-MM-DD'. Дата ввода берётся из акта о
    # приёме-передаче (п. 9.3), а не из дня, когда её заметили: реквизит
    # обязателен при переводе станции в эксплуатацию.
    commissioned_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    decommissioned_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    hubex_asset_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
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


# ---------------------------------------------------------------------------
# Связи объектов с периодом действия (общая механика, СТО разделы 3 и 8)
# ---------------------------------------------------------------------------
class ObjectLink(Base):
    """Привязка одного объекта к другому на период времени.

    Уровни объектов не просто вложены — их связи меняются: станцию заменяют,
    перемещают между точками обслуживания, точку обслуживания закрывают, а
    площадка остаётся. Скалярная ссылка отвечает только на вопрос «где сейчас»
    и теряет ответ на вопрос «где было на дату», без которого не считается ни
    выручка точки за прошлый период, ни наработка станции.

    Одна механика на все привязки: и на внутренние связи уровней
    (`placed_at`, `mounted_in`, `belongs_to`), и на идентификаторы внешних
    систем (`external_id`) — реестр соответствий СТО раздела 8 устроен так же,
    вплоть до закрытия датой вместо удаления.

    Два времени различаются намеренно: `valid_from`/`valid_to` — когда связь
    действует по документу, `recorded_at` — когда её внесли. СТО п. 13.1 сам
    даёт подразделениям N рабочих дней на внесение сведений, поэтому запись
    задним числом — штатный режим, а не сбой.

    Непересечение периодов обеспечивается EXCLUDE-ограничением (заводится
    DDL-патчем: декларативно gist-исключение не выразить). Оно и есть смысл
    таблицы: станция не может одновременно стоять в двух точках обслуживания,
    а внешний идентификатор — принадлежать двум объектам в один период
    (СТО п. 8.4).
    """
    __tablename__ = "object_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    # site | point_of_service | station | evse | connector | external
    parent_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # String(64), а не UUID: id точки обслуживания — строковый nanoid, id станции —
    # UUID, а значением внешнего идентификатора бывает строка любого формата.
    parent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    child_type: Mapped[str] = mapped_column(String(30), nullable=False)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # placed_at (станция в точке) | mounted_in (точка отпуска на станции) |
    # belongs_to (точка обслуживания на площадке) | external_id (реестр соответствий)
    relation: Mapped[str] = mapped_column(String(30), nullable=False)
    valid_from: Mapped[date_type] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # Документ-основание: накладная на внутреннее перемещение, акт о приёме-передаче,
    # приказ (СТО, приложение Б). Мягкая ссылка на doc_cards — как supply_id у
    # движения: документ живёт своим жизненным циклом и переживает связь.
    basis_doc_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    basis_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recorded_by_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recorded_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        Index("ix_object_links_child", "company_id", "child_type", "child_id"),
        Index("ix_object_links_parent", "company_id", "parent_type", "parent_id"),
        Index("ix_object_links_open", "company_id", "relation", "valid_to"),
    )


# ---------------------------------------------------------------------------
# Журнал отбракованных транзакций ЭЗС
# ---------------------------------------------------------------------------
class ChargeRejected(Base):
    """Сессия или платёж, помеченные источником как недостоверные.

    Витрина АСУиМ отдаёт у сессии колонку `подозрительная`; помеченные ею
    зарядки в учёт не идут — решение МАГа 27.08.2026: «мы их просто не
    показываем, вообще». Такие строки не лежат в `charge_sessions` и
    `charge_payments` вовсе — ровно так же, как прогоны тестовых станций,
    которые загрузчик отбрасывает на входе.

    Почему отдельная таблица, а не флаг в рабочих: сессии читают 39 мест, платежи
    ещё 8, и фильтр, расставленный по одному, рано или поздно где-нибудь забудут —
    отбракованная зарядка вылезет в одном отчёте из двадцати, и цифры разойдутся
    молча. Здесь же чистота витрин обеспечена тем, что данных в них просто нет.

    Один журнал на оба рода записей: у отбракованной сессии и её платежа общая
    судьба и общий экран разбора, а разводить две почти одинаковые таблицы ради
    различия в четырёх полях смысла нет — разное лежит в `payload`.
    """

    __tablename__ = "charge_rejected"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    # session | payment
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Идентификатор в источнике: `id_сессии` либо `id_платежа`.
    ext_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Сессия платежа — по ней собирается пара «зарядка + деньги» на экране разбора.
    session_ext_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    station_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    location_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    energy_kwh: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Почему отбракована. Пока единственная причина — `suspicious` (признак
    # источника), но причина названа полем: тестовые прогоны и будущие правила
    # лягут сюда же, а не заведут второй журнал.
    reason: Mapped[str] = mapped_column(String(40), nullable=False, default="suspicious")
    # Строка источника целиком: разбор отбракованного — работа редкая и глубокая,
    # и ходить за подробностями обратно в выгрузку неоткуда.
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rejected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "kind", "ext_id", name="uq_charge_rejected"),
        Index("ix_charge_rejected_company_time", "company_id", "occurred_at"),
    )


class EzsEvse(Base):
    """Точка отпуска — часть станции, заряжающая не более одного ТС (СТО п. 2.5).

    Единица информационного обмена: именно ей принадлежит внешний идентификатор
    формата `RU*OOO*TNNNNN*C` (п. 11.4). Единицей бухгалтерского учёта не
    является — инвентарный объект это станция (п. 4.6).
    """
    __tablename__ = "ezs_evse"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_equipment_units.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Порядковый номер в пределах станции, начиная с единицы (приложение А).
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Внешний идентификатор. Пока уровень не введён повсеместно, п. 15.8 разрешает
    # вести его на станции — тогда здесь NULL, а значение лежит в реестре соответствий.
    external_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    power_kwt: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        UniqueConstraint("unit_id", "number", name="uq_ezs_evse_number"),
        Index("uq_ezs_evse_external", "company_id", "external_id", unique=True,
              postgresql_where=text("external_id IS NOT NULL")),
    )


class EzsConnector(Base):
    """Коннектор — физический разъём точки отпуска (СТО п. 2.6).

    Имя таблицы с префиксом `ezs_` намеренно: `connectors` в этой же схеме —
    подключения к внешним системам, совсем другая сущность. Одно слово в двух
    несовместимых смыслах уже путало при аудите, в схеме этого быть не должно.
    """
    __tablename__ = "ezs_connectors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    evse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_evse.id", ondelete="CASCADE"), nullable=False, index=True)
    # Порядковый номер в пределах точки отпуска, начиная с единицы (приложение А).
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    connector_type: Mapped[str | None] = mapped_column(String(40), nullable=True)  # CCS2 | CHADEMO | GBT_DC | TYPE2
    power_kwt: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("evse_id", "number", name="uq_ezs_connector_number"),
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
    # Вид работы: new_build | retrofit | relocation | decommission. Без него
    # модернизация действующего объекта выглядела обычной стройкой, и карточка
    # рисовала ей этап «Подбор площадки», которого в этой работе не было.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="new_build")
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
    # ── По какому маршруту ведётся проект ──
    # Маршрут у стройки не один: полный регламент, короткий для переноса и
    # модернизации, свой у компании. Выбор делается один раз — при постановке на
    # рельсы — и хранится ЗДЕСЬ, а не только в кейсе Координатора: состав проекта
    # уезжает в кейс раньше первого шага (`_push_participants`), и без записи
    # выбор затирался бы умолчанием ещё до того, как человек его сделал.
    # Пусто — маршрут по умолчанию, тот же, что брался всегда.
    route_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ── Отметка намерения: шаг маршрута начат, но ещё не отражён в проекте ──
    # Шаг применяется в двух системах по очереди: Координатор коммитит переход,
    # Ядро двигает воронку. Если между этими точками оборвалась связь, маршрут
    # ушёл вперёд, а проект остался в прежней стадии — и повторить шаг нельзя,
    # второй раз ребро не сработает. Отметка ставится ДО вызова и снимается после
    # отражения: по ней фоновый проход находит, что осталось досверить, а раньше
    # это чинилось только чужим открытием карточки.
    pending_link_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class EzsSiteParticipant(Base):
    """Кто ведёт проект: человек в роли службы из регламента заказчика.

    Роль назначается НА ПРОЕКТ, а не на человека вообще: один и тот же сотрудник
    ведёт один объект как ОР и лишь наблюдает за соседним. Глобальная роль в
    пространстве на этот вопрос не отвечает, поэтому состав живёт здесь.

    Приёмщики (ОЭ — принимает станцию, ОЦО — принимает документы) заводятся тем
    же списком: приёмка это такое же участие, только с кнопкой в конце маршрута.

    Состав уезжает в кейс Координатора вместе со сводкой проекта — там он
    становится третьим слоем полномочий на рёбрах маршрута.
    """
    __tablename__ = "ezs_site_participants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ezs_sites.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Код службы из ezs_checklist.ROLES: ОР, ДР/ГД, ОКС, ОЭ, ЮБ, ФБ, ОЦО, Подрядчик
    role_code: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("site_id", "user_id", "role_code", name="uq_ezs_site_participant"),
        Index("ix_ezs_site_participant_site", "site_id", "role_code"),
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
    # Структурированное «было → стало». Текст события остаётся пояснением,
    # но аналитика изменений строится только по этим проверяемым значениям.
    changes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="user", server_default="user")
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ezs_site_event_site", "site_id", "created_at"),
        Index("ix_ezs_site_event_company_created", "company_id", "created_at"),
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
    # Серийный номер приехавшей станции. Вносит ОКС по ходу СМР, до постановки на
    # учёт: пока единицы склада нет, записать номер было некуда, и он жил в
    # переписке (замечание отдела развития 07.08.2026). При постановке на учёт
    # номер уезжает в карточку единицы (`unit_id`) и остаётся здесь как след.
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Связь с фактом на складе — появляется, когда железо приехало.
    unit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    supply_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_ezs_site_equipment_status", "company_id", "status"),
    )


class InboundEvent(Base):
    """Входящие события от приложений пространства — с защитой от повтора.

    Обратный канал нужен там, где раньше была синхронная пара вызовов: Координатор
    коммитит переход, Ядро следом двигает воронку. Если между этими точками рвалась
    связь, маршрут уходил вперёд, а проект оставался позади — и повторить шаг было
    нельзя, второй раз ребро не срабатывает.

    Теперь Координатор кладёт событие в свой outbox и доставляет с ретраями, а
    Ядро принимает его сюда. Повторная доставка — штатный режим такой доставки,
    поэтому ключ `(provider, external_id)` уникален: второе появление того же
    события не обрабатывается заново, а сразу отвечает «уже принято».

    Обработка отделена от приёма намеренно: приём обязан быть быстрым и почти
    всегда успешным, иначе отправитель будет ретраить из-за нашей внутренней
    ошибки и копить очередь.

    Префикс `eco_` обязателен: Ядро и Поддержка живут в одной базе (схемы `core`
    и `public`, `search_path = core, public`), и имя `inbound_events` у Поддержки
    уже занято. Без префикса `CREATE TABLE IF NOT EXISTS` нашёл бы чужую таблицу
    через `search_path`, промолчал — и мы писали бы в чужую очередь.
    """
    __tablename__ = "eco_inbound_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    # Кто прислал: код приложения пространства (`support`, …).
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    # Идентификатор события у отправителя — он же ключ идемпотентности.
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ok | skipped | failed — и текст, если не вышло: молчаливая потеря события
    # хуже видимой ошибки, потому что о ней никто не узнает.
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("uq_eco_inbound_events_key", "provider", "external_id", unique=True),
        Index("ix_eco_inbound_events_unprocessed", "received_at",
              postgresql_where=text("processed_at IS NULL")),
    )


class SpaceConnection(Base):
    """Учётная запись подключения к внешней системе — одна на пространство.

    До неё записей о подключениях было две: в Ядре `Source` с каналами, в
    Координаторе своя таблица `connectors`. Витрина «что подключено у компании»
    собиралась опросом приложений на лету — и потому молчала, когда приложение не
    отвечало, а глобально настроенные интеграции не показывала вовсе.

    Здесь только УЧЁТ: кто, куда, чем, в каком состоянии. Транспорт и настройки
    остаются у владельца — приложение продолжает ходить в свою внешнюю систему
    само, а сюда сообщает, что у него есть и как оно себя чувствует.

    Почему не расширили `Source`. У него другой смысл: источник данных Ядра с
    каналами, потоками и расписанием. Подключение Координатора каналов не имеет,
    и общая таблица смешала бы «источник, который мы прогоняем» с «подключением,
    о котором мы знаем». Одна лишняя таблица дешевле одного размытого понятия.

    Секрет здесь не лежит и лежать не может: `secret_ref` — это ссылка (имя
    переменной окружения или ключ в хранилище владельца), а не значение.
    """
    __tablename__ = "eco_space_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Владелец записи: код приложения, которое обслуживает подключение. Для
    # собственных подключений Ядра — `core`.
    app_code: Mapped[str] = mapped_column(String(40), nullable=False)
    # Идентификатор подключения У ВЛАДЕЛЬЦА. Строкой: у приложений свои типы
    # ключей, и приводить их к общему — плодить сопоставления на ровном месте.
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    # Что за система: `hubex`, `megafon`, `mango`, `email`, `sts`, `onec`, …
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    # Род подключения: channel | tracker | db | proxy | asr | api_consumer | …
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="channel")
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Куда текут данные: in | out | both.
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="in")
    # Кто начинает обмен: `us` — мы ходим к ним, `them` — они стучатся к нам.
    # Ось отдельная от направления: опрашиваемый источник и вебхук могут нести
    # данные в одну сторону, но настраиваются и ломаются по-разному.
    initiator: Mapped[str] = mapped_column(String(10), nullable=False, default="us")
    # Роль компании в обмене: own | coordinate | enrich.
    engagement_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="own")
    # active | disabled | error | draft
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Настроено ли подключение по мнению владельца: пустые ключи — не настроено.
    configured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"))
    # Ссылка на секрет, но НЕ секрет: имя переменной окружения или ключ хранилища.
    secret_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Когда владелец в последний раз сообщал о себе. Запись, о которой давно не
    # сообщали, — повод спросить приложение, а не тихо считать её живой.
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "app_code", "external_id",
                         name="uq_eco_space_connections"),
        Index("ix_eco_space_connections_company", "company_id", "app_code"),
    )


class EventSubscription(Base):
    """Кто и о чём просит сообщать: подписка на события пространства.

    Форма взята из зоны `Subscriptions` ГОСТ Р 53898 — набор флагов на типы
    уведомлений плюс срок, в течение которого подписчик события ждёт
    (`StopDayCount`). Норма на нас не распространяется, берём конструкцию: она
    решает ровно нашу задачу и решает её лучше, чем «получай всё подряд».

    Два отличия от шины Поддержки, оба намеренные:

    * **`company_id` обязателен.** Там подписка с пустой компанией означает «все
      компании стека». Стек мультикомпанийный, и это ровно тот механизм, которым
      события одной компании уедут потребителю другой. Нужны все — заводится
      несколько строк, зато в витрине видно, кто что получает.
    * **Пустой список типов запрещён.** Там пусто означает «на всё», то есть
      тихую подписку на события, которых подписчик не заказывал.
    """
    __tablename__ = "eco_event_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    # app — приложение пространства по служебному каналу; url — внешний потребитель.
    target_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="app")
    # Для app адрес НЕ храним: его знает реестр приложений. Вторая копия адреса
    # в Ядре разъедется с первой в тот день, когда приложение переедет.
    app_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    path: Mapped[str] = mapped_column(
        String(200), nullable=False, default="/api/v1/eco/events")
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # HMAC-секрет под Fernet — как реквизиты источников. Держать его открытым
    # было бы нарушением собственной доктрины ровно там, где она записана.
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_hint: Mapped[str | None] = mapped_column(String(12), nullable=True)
    event_types: Mapped[list] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    # Срок ожидания в днях. Событие старше срока не доставляем — подписчик его
    # уже не ждёт; молчащую дольше срока подписку гасим.
    stop_day_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30"))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"))
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"))
    # С какого момента подписчик молчит. Без этой отметки срок ожидания не к чему
    # приложить: число неудач не отвечает на вопрос «как давно».
    failing_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "label", name="uq_eco_event_subs_label"),
        Index("ix_eco_event_subs_company", "company_id",
              postgresql_where=text("enabled")),
    )


class OutboxEvent(Base):
    """Событие пространства, ждущее доставки подписчику.

    Транзакционный outbox: строка пишется в той же транзакции, что и само
    изменение. Или произошло и записано к отправке, или не произошло вовсе —
    третьего состояния, при котором документ зарегистрирован, а никто об этом не
    узнал, не бывает.

    **Одна строка — одна доставка одному подписчику**, `event_id` общий. В шине
    Поддержки строка одна на факт, а рассылка идёт при доставке, и там ошибка
    одного получателя возвращает событие в очередь целиком — живые получают дубль
    столько раз, сколько мёртвый не ответил. Здесь дохлая подписка остаётся своей
    бедой: попытки считаются на адресата, и на вопрос «почему одному дошло, а
    другому нет» отвечает одна выборка.

    Чего сознательно нет: клеймящего статуса `processing` с отметкой блокировки —
    доставка живёт в общем планировщике, где уже есть advisory-lock на проход и
    `SKIP LOCKED` на батч.
    """
    __tablename__ = "eco_outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # CloudEvents `id`, он же заголовок `webhook-id`. Стабилен на все попытки:
    # получатель отсеивает повтор по нему.
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eco_event_subscriptions.id", ondelete="CASCADE"),
        nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    # Предмет события — идентификатор документа. Вынесен из тела ради поиска
    # «что уходило по этому документу».
    subject: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(
        String(120), nullable=False, default="/elsyplus/core/docs")
    # Время ФАКТА, а не записи: иначе после разбора очереди история сложится в
    # момент доставки, а не в момент, когда документ зарегистрировали.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    # pending | done | failed | expired | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("event_id", "subscription_id",
                         name="uq_eco_outbox_delivery"),
        Index("ix_eco_outbox_pending", "next_attempt_at",
              postgresql_where=text("status = 'pending'")),
        Index("ix_eco_outbox_company_time", "company_id", "occurred_at"),
        Index("ix_eco_outbox_subject", "subject",
              postgresql_where=text("status <> 'done'")),
    )


class ApprovalRequest(Base):
    """Круг виз, запущенный узлом маршрута процесса, и возврат его исхода.

    Согласование документа — работа «Трека», ход стройки — работа Координатора.
    Раньше связать их мог только человек: посмотрел, что визы собраны, и нажал
    кнопку в процессе. Здесь эта передача становится машинной.

    Запись живёт дольше самого вызова, потому что исход надо не только узнать, но
    и **доставить**. Доставка идёт фоновым проходом с ретраями: сеть между двумя
    сервисами рвётся, а круг виз к тому моменту уже закрыт — терять его исход
    нельзя, второй раз согласовывать никто не будет.

    Идемпотентность — `request_id`: повторная доставка `approval.requested`
    (штатная при at-least-once) не открывает второго круга по тому же документу.

    Действие процесса задаётся глаголом, а не идентификатором ребра: граф
    пересобирают, идентификаторы при этом меняются, а «согласовано» остаётся
    «согласовано».
    """
    __tablename__ = "eco_approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    # Идентификатор события, породившего запрос, — он же ключ от второго круга.
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    # Процесс в Координаторе и, если ход идёт по ветви, сама ветвь.
    process_id: Mapped[str] = mapped_column(String(64), nullable=False)
    branch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Чего именно ждёт процесс: круг виз по документу или выполнения поручения.
    # Вид один, потому что ожидание одно: работа делается людьми в «Треке», а
    # обратно едет одно событие исхода. Второй механизм доставки означал бы вторые
    # ретраи, второй счётчик попыток и вторую историю о том, где исход потерялся.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="approval")
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"), nullable=True, index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Чем двигать процесс при каждом исходе. Пусто — исход только фиксируется.
    on_approved: Mapped[str | None] = mapped_column(String(120), nullable=True)
    on_rejected: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # approved | rejected | cancelled
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_eco_approval_requests_key", "company_id", "request_id", unique=True),
        # Живой круг по документу один: второй запрос от процесса, пока прежний не
        # закрыт, — это ошибка настройки маршрута, а не новая работа.
        Index("uq_eco_errand_requests_open", "company_id", "task_id", unique=True,
              postgresql_where=text("outcome IS NULL AND task_id IS NOT NULL")),
        Index("uq_eco_approval_requests_open", "company_id", "doc_id", unique=True,
              postgresql_where=text("outcome IS NULL")),
        Index("ix_eco_approval_requests_undelivered", "decided_at",
              postgresql_where=text("outcome IS NOT NULL AND delivered_at IS NULL")),
    )


class ObjectExportLog(Base):
    """Журнал выгрузок сведений об объектах (СТО п. 12.3).

    Норма требует фиксировать каждую передачу: кто (работник либо учётная запись
    интеграции), когда, какой состав и какой объём. Журнал нужен и сам по себе, и
    как основание четвёртого замораживающего события (п. 7.6): по нему видно, что
    объект уже уехал наружу и его номер трогать нельзя.

    `is_external` разделяет две принципиально разные записи. Обмен между
    информационными системами ОРГАНИЗАЦИИ замораживающим событием не является —
    это оговорено нормой прямо, — поэтому проекция Ядро → Поддержка и выгрузка по
    внутреннему ключу пишутся сюда с `false`. Без этого флага первая же внутренняя
    синхронизация заморозила бы номера всей сети.
    """
    __tablename__ = "object_export_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Кто передал: работник (его id) либо учётная запись интеграции (её имя).
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)  # user | integration
    actor_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Куда: код внешней системы либо приложения экосистемы.
    destination: Mapped[str] = mapped_column(String(80), nullable=False)
    is_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Что и сколько: перечень переданных реквизитов и число объектов.
    fields: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    objects_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        Index("ix_object_export_company_at", "company_id", "at"),
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
    """Комната чата пространства: company | direct | group | channel.

    Концепция (решение МАГа 30.07.2026), по образцу Telegram:
      • `channel` — ОДНОСТОРОННИЙ: новости, рассылки, слово руководителя. Пишут только
        владелец и админы канала; остальные читают. Создать канал может лишь
        администратор пространства;
      • `group`   — обычная группа: пишут все участники. Создаёт любой свой сотрудник;
      • `direct`  — личный чат двоих;
      • `company` — системные комнаты пространства (`kind` general/news).

    В группе могут быть и сотрудники компании-владельца, и люди компаний-партнёров —
    поэтому в списке участников каждый помечен как свой или как сотрудник партнёра
    (см. `ParticipantOut` в роутере): без этого непонятно, при ком идёт разговор.
    """
    __tablename__ = "chat_rooms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # type: company | direct | group | channel. kind (только company): general | news.
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
    # Приложение, к которому привязана комната («fuel», «store», …). NULL — чат всего
    # пространства. Правая рельса показывает чаты своего приложения плюс общие, верхняя
    # кнопка — всё подряд: один и тот же чат, разные предустановки.
    scope_product: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Объект пространства, при котором живёт чат («группа по станции»): карточка
    # объекта показывает его чаты, привязка видна и в самом чате. Ортогонален
    # scope_product: группа может быть и «по станции», и «в Эксплуатации».
    scope_object_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    # Чат ЗАЯВКИ (id из public.tickets, FK через схему не заводим): скрытая группа
    # «быстро обсудить и записать следующий шаг» — в общий список чатов НЕ попадает,
    # открывается только из карточки заявки (решение МАГа 31.07.2026).
    scope_ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True)
    # Чат ЗАДАЧИ — та же скрытая группа, но для работы компании. Задача живёт в
    # этой же схеме, поэтому FK настоящий: комната исчезает вместе с задачей.
    scope_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True, index=True)
    # Аватар чата: относительный путь файла пространства (/api/files/<id>), грузится
    # владельцем/админом чата. NULL — иконка по типу комнаты.
    avatar_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
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
    # owner — создатель (в канале и группе), admin — назначенный им, member — остальные.
    # Право писать в канал и менять состав определяется этой ролью, а не ролью в компании.
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # «Без звука»: до этого момента чат не шлёт push и не красит общий счётчик.
    # NULL — уведомления включены; 9999 год — навсегда.
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Чат закреплён вверху списка — настройка ЛИЧНАЯ (у каждого свои важные
    # разговоры), поэтому живёт в участии, а не в комнате.
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Граница видимой истории: NULL — человек видит переписку с самого начала
    # (так по умолчанию), время — приходит «с чистого листа» и читает только то,
    # что написано после. Решает тот, кто добавляет: в рабочую группу зовут ради
    # общего контекста, а к разговору с подрядчиком новичку прошлое ни к чему.
    history_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    # Пересланное: имя автора ОРИГИНАЛА (денормализовано, как user_name). Цепочка
    # пересылок оригинал не теряет: форвард форварда несёт то же имя.
    forwarded_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Сообщение пришло не из интерфейса, а извне (пока единственный случай — почта).
    # `external_id` — Message-ID письма: повторная доставка дубля не создаёт.
    # `external_ref` — письмо-первоисточник в архиве Поддержки, чтобы из ленты
    # можно было дойти до оригинала, а не только до вычищенного текста.
    external_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_chat_messages_room_created", "room_id", "created_at"),
    )


class ChatTicketLink(Base):
    """Связь «сообщение → заявка»: заявка родилась из обсуждения, след остаётся
    с обеих сторон (в чате — системное сообщение, в заявке — origin по этой записи)."""
    __tablename__ = "chat_ticket_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    # id заявки в public.tickets — другая схема, FK не заводим.
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    ticket_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatPushKeys(Base):
    """VAPID-ключи Web Push стека: генерируются при первом старте и НЕ меняются —
    смена ключей протухает все подписки браузеров."""
    __tablename__ = "chat_push_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    private_pem: Mapped[str] = mapped_column(Text, nullable=False)
    # Публичный ключ в base64url (uncompressed point) — applicationServerKey для браузера.
    public_key: Mapped[str] = mapped_column(String(200), nullable=False)


class ChatPushSubscription(Base):
    """Подписка браузера на Web Push: доставка чата при закрытой вкладке."""
    __tablename__ = "chat_push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    # Показывать ли текст сообщения в самом уведомлении: на заблокированном экране
    # его читает любой, кто взял телефон в руки. Настройка на устройство, а не на
    # человека: рабочий ноутбук и личный телефон — разные обстоятельства.
    show_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                               server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatPoll(Base):
    """Опрос в чате: собрать мнение, не собирая совещание.

    Живёт при сообщении (`message_id`), поэтому попадает в ленту на общих
    правах — его видно в переписке, можно процитировать и переслать. Варианты
    хранятся списком в jsonb: у опроса они неизменны после создания, отдельная
    таблица строк дала бы только join на каждом чтении.

    Анонимность — свойство опроса, а не настройка показа: в рабочем чате чаще
    важно знать, кто как ответил («кто едет на объект»), но бывает и обратное,
    и это решает автор в момент создания.
    """
    __tablename__ = "chat_polls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False, unique=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # ["Да", "Нет", …] — порядок вариантов и есть их идентификатор (индекс).
    options: Mapped[list] = mapped_column(JSONB, nullable=False)
    multiple: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Участник может дописать свой вариант: спрашивающий редко знает все ответы
    # заранее, а «Другое ___» без текста не отвечает ни на что.
    allow_custom: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatPollVote(Base):
    """Голос за вариант. Переголосование — это удаление прежних строк и вставка
    новых, поэтому история «кто передумал» не хранится: опрос отвечает на вопрос
    «что думают сейчас»."""
    __tablename__ = "chat_poll_votes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    poll_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_polls.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    option_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_chat_poll_vote", "poll_id", "user_id", "option_index", unique=True),
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


# ===========================================================================
# РЫНОК (продукт «Маркетинг», docs/MARKET.md)
# Внешний мир вокруг нашей сети: чужие станции, точки притяжения, их цены и
# состояние. Живёт ОТДЕЛЬНО от реестра объектов (`service_locations`): у нашего
# объекта есть паспорт, договоры и ответственные, у чужого — только наблюдения
# и гипотезы. Смешать их значит однажды выставить счёт по чужой станции.
# ===========================================================================
class MarketOperator(Base):
    """Оператор рынка — чья это точка (конкурент, партнёр, мы сами).

    Отдельная сущность, а не строка в карточке: политику цен и динамику открытий
    смотрят ПО ОПЕРАТОРУ («что делает конкурент»), а не по одной точке.
    """
    __tablename__ = "market_operators"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Кто он нам: competitor | partner | own (наша же сеть — чтобы карта была полной) | other
    relation: Mapped[str] = mapped_column(String(20), nullable=False, default="competitor")
    site_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_market_operator_company", "company_id", "relation"),
    )


class MarketSite(Base):
    """Точка рынка: чужая ЭЗС, торговый центр, парковка, АЗС — всё, что объясняет
    спрос или занимает территорию.

    Решение МАГа 28.07.2026: берём не только зарядки. Торговый центр не конкурент,
    но именно он объясняет, ПОЧЕМУ в этом месте заряжают, и он же кандидат под
    размещение. Поэтому вид точки — открытый список, а роль (конкурент или точка
    притяжения) выводится из вида и оператора, а не задаётся отдельным флагом.

    Связь с нашим миром — `location_id`: если точка оказалась нашим объектом
    (импорт приносит наши и чужие вперемешку), она помечается и на карте не двоится.
    """
    __tablename__ = "market_sites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market_operators.id", ondelete="SET NULL"), nullable=True, index=True)
    # ezs | mall | parking | fuel | hotel | office | other
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="ezs")
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    region: Mapped[str | None] = mapped_column(String(160), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    # Гексагон хранения (H3 res 8; на трассах res 7) — ключ агрегации фактов во
    # времени: он не меняется, когда рядом открывается новая станция.
    hex_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # Только для ЭЗС: чем оснащена точка. Порты и мощность решают, конкурент это нам
    # или другой класс сервиса (медленная AC-зарядка у ТЦ — не конкурент быстрой DC).
    ports: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_power_kw: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    connectors: Mapped[str | None] = mapped_column(String(200), nullable=True)
    opened_on: Mapped[str | None] = mapped_column(String(10), nullable=True)   # ISO-дата открытия
    closed_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active|planned|closed
    # Наш объект, если точка — это мы.
    location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True, index=True)
    # ── происхождение факта (принцип 2 docs/MARKET.md) ──
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(400), nullable=True)   # ссылка/идентификатор в источнике
    source_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=50)  # 100 партнёр/API … 20 парсинг
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Ручная правка сильнее машинной: импорт её не затирает, а показывает расхождение.
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Ключ дедупа: округлённая координата + вид (две карты дают одну точку).
    dedup_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_market_site_company_kind", "company_id", "kind", "status"),
        Index("ix_market_site_geo", "company_id", "city"),
    )


class MarketObservation(Base):
    """Наблюдение по точке: цена, доступность, состояние — на конкретную дату.

    Отдельная сущность, а не поля в карточке (решение МАГа 28.07.2026): наблюдения
    приходят из разных рук — сервис на выезде, маркетинг, партнёр, парсер, — и у
    каждого свой возраст и своя достоверность. Цена конкурента без даты и автора
    опаснее её отсутствия: выглядит достоверной, а решение по ней ошибочно.

    История наблюдений — материал для «эластичности»: что стало с нашими сессиями
    после того, как сосед изменил тариф.
    """
    __tablename__ = "market_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("market_sites.id", ondelete="CASCADE"), nullable=False, index=True)
    # price | availability | equipment | closed | opened | photo | note
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="price")
    observed_on: Mapped[str] = mapped_column(String(10), nullable=False)   # ISO-дата наблюдения
    # ── цена как её увидели и как привели к сравнимой (принцип 3 docs/MARKET.md) ──
    price_value: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)   # kwh | session | minute
    price_per_kwh: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    basis: Mapped[str | None] = mapped_column(String(120), nullable=True)  # «DC 60+ кВт, будни днём»
    connector_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    power_kw: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    # ── происхождение ──
    # manual | service_visit | marketing | partner | import | parser
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # confirmed (два источника) | single | conflict
    confidence: Mapped[str] = mapped_column(String(12), nullable=False, default="single")
    snapshot_url: Mapped[str | None] = mapped_column(String(400), nullable=True)  # снимок первоисточника
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_market_obs_site_date", "site_id", "observed_on"),
        Index("ix_market_obs_company_kind", "company_id", "kind", "observed_on"),
    )


# ===========================================================================
# «Эксплуатация» — денежный контур площадок: что мы должны собрать за месяц
# ===========================================================================
# Контрагенты обязаны сами выставлять закрывающие документы и делают это не
# всегда: в рабочем файле заказчика 54 пометки «Нет расчёта», ежемесячно 3–6
# станций закрываются без первички. Задача контура — ежемесячный реестр
# «что ожидали ↔ что получили ↔ чем подтверждено ↔ где расхождение».
#
# Разделение мастерства с уже существующим реестром:
#   StationContractSettlement — СНИМОК реестра контрагента, идемпотентно
#     перезаписываемый ингестом (uq_station_settlement). Дисциплина ОПЛАТЫ.
#   OpsContractTerm — НАШЕ знание об обязательстве: версионное, редактируемое.
#   OpsPeriodCharge — помесячный факт учёта, неизменяемый после закрытия.
# Условия рождаются из реестра разовым бэкфиллом (database.py) и дальше живут
# сами: дописать их в settlements значило бы терять при каждой загрузке файла.
# ===========================================================================


class OpsCostItem(Base):
    """Статья затрат эксплуатации — ORM-вид справочника из database.py.

    Таблица создаётся и сидируется сырым DDL рядом с `contract_types`: это
    закрытый список, который правится вместе с кодом, а не пользователем.
    Здесь — только чтение и джойны.
    """
    __tablename__ = "ops_cost_items"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    contract_type_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Мост к StationContractSettlement.role: energy | rent | service.
    settlement_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    measure: Mapped[str | None] = mapped_column(Text, nullable=True)  # fixed|metered|pct_revenue
    default_expected_docs: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
    default_estimate_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    bp_account: Mapped[str | None] = mapped_column(Text, nullable=True)  # 20/26/44 — задел под 1С
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class OpsContractTerm(Base):
    """Условие обязательства: из чего разворачивается ожидание месяца.

    Отвечает на вопросы, которые сегодня живут словом в примечании файла:
    как часто платим, сколько, до какого числа контрагент обязан дать документ,
    чем считать, если документа нет.

    ВЕРСИОННОСТЬ ВМЕСТО ПЕРЕСЧЁТА. Индексация ставки — новая строка с
    `valid_from`, старой проставляется `valid_to`. Автоматическая формула
    пересчитала бы задним числом месяцы, по которым документы уже приняты;
    `index_kind`/`index_month` держат только «когда напомнить».
    """
    __tablename__ = "ops_contract_terms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    cost_item: Mapped[str] = mapped_column(
        Text, ForeignKey("ops_cost_items.code"), nullable=False)
    # Свой охват, а не Contract.scope_type: один договор несёт и объектную статью
    # (аренда площадки), и общую (обслуживание всей сети). location | company.
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="location")
    # NULL при scope_type='location' — разворот по всем ContractLocation договора.
    location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="CASCADE"), nullable=True, index=True)
    # monthly | quarterly | annual | one_time
    periodicity: Mapped[str] = mapped_column(String(16), nullable=False, default="monthly")
    amount_gross: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    amount_net: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    vat_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Переменная часть: metered_kwh (объём × тариф) | pct_revenue (% от выручки).
    variable_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tariff_rub: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    pct_of_revenue: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    # Чем закрывается период: {act,invoice} / {upd,invoice,sf}. Переопределяет статью.
    expected_docs: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
    # До какого числа СЛЕДУЮЩЕГО месяца ждём документ. По нему считается просрочка.
    doc_due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pay_due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # contract | prev_period | average | none — переопределяет статью.
    estimate_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Памятка об индексации, НЕ автоформула: annual_pct | cpi | manual.
    index_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    index_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    index_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Горизонт версии, ISO-даты строкой — как contract_start/contract_end реестра.
    valid_from: Mapped[str] = mapped_column(String(10), nullable=False)
    valid_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    doc_channel: Mapped[str | None] = mapped_column(String(16), nullable=True)  # email|edo|paper
    # Адрес для матчинга входящего письма и для напоминаний. Отдельно от
    # Counterparty.email: у крупного поставщика бухгалтерия шлёт с другого ящика.
    counterparty_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Кто ведёт это обязательство. Объектов и контрагентов много — без владельца
    # на строке рабочий стол превращается в общую свалку.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # NULL в location_id означает «весь охват договора», и штатным Index такой
        # ключ не выразить (NULL != NULL) — та же причина, что у StationDispensePeriod.
        Index("uq_ops_term", "contract_id", "cost_item",
              text("coalesce(location_id,'')"), "valid_from", unique=True),
        Index("ix_ops_term_company", "company_id", "cost_item", "valid_from"),
        Index("ix_ops_term_owner", "company_id", "owner_user_id"),
    )


class OpsCounterpartyDoc(Base):
    """Входящая первичка контрагента: акт, УПД, счёт, расшифровка.

    Одна таблица на все каналы — почту, ЭДО и ручную загрузку. ЭДО поэтому
    подключается без единой правки модели: меняется только `channel`,
    `external_key` и содержимое `channel_ref`.

    `AccountingDoc` для этого не годится: там `external_id` (GUID 1С) обязателен,
    и вся семантика — «пришло из 1С, сверяется с DataEntry». Здесь 1С нет.
    """
    __tablename__ = "ops_counterparty_docs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    # act | upd | invoice | sf | torg12 | report | other
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    doc_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    counterparty_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True)
    # Отчётный месяц документа (первое число). Заполнен, когда документ за месяц.
    period: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    # Плавающий период — из данных заказчика: «За период май – август 2025»,
    # «С 11.02.26 - 10.03.26», квартальные акты. Разносится по месяцам по дням.
    period_from: Mapped[str | None] = mapped_column(String(10), nullable=True)
    period_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    amount_gross: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    amount_net: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    vat_amount: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    qty: Mapped[float | None] = mapped_column(Numeric(16, 3), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    # Message-ID письма | docId ЭДО | sha256 файла — ключ идемпотентности приёма.
    external_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True)
    # Счёт и счёт-фактура прицепляются к акту-основанию: комплект закрывает период,
    # а ожидание закрывает именно основание.
    parent_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ops_counterparty_docs.id", ondelete="SET NULL"), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(12), nullable=False, default="raw")
    # Письмо/нагрузка ЭДО как есть — L1 RAW, принятый в Ядре приём.
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # unmatched | auto | manual | rejected
    match_status: Mapped[str] = mapped_column(String(12), nullable=False, default="unmatched")
    matched_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Повторная доставка того же письма или выгрузка того же документа ЭДО
        # дубля не создаёт. Ручные документы ключа не имеют — там дубль осознан.
        Index("uq_ops_doc_external", "company_id", "channel", "external_key", unique=True,
              postgresql_where=text("external_key IS NOT NULL")),
        Index("ix_ops_doc_inbox", "company_id", "match_status", "created_at"),
    )


class OpsPeriodCharge(Base):
    """Начисление: объект × период × статья × сумма. Ядро реестра.

    Одна строка = одно ожидание одного месяца. Разворачивается из условия
    автоматически; нет документа к закрытию — закрывается РАСЧЁТНОЙ суммой с
    пометкой метода в `expected_basis`, и метка видна человеку рядом с цифрой.

    Сумма расхождения не хранится — считается на чтении, как стоимость в
    StationEnergyPeriod. Хранится только классификация, по которой фильтруют.
    """
    __tablename__ = "ops_period_charges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    # Первое число месяца ISO — как в StationEnergyPeriod.
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    cost_item: Mapped[str] = mapped_column(
        Text, ForeignKey("ops_cost_items.code"), nullable=False)
    # NULL = строка заведена руками, без условия.
    term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ops_contract_terms.id", ondelete="SET NULL"), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True)
    counterparty_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # NULL = ОБЩАЯ затрата компании, не привязанная к объекту. Штатный разрез,
    # а не пропуск: у части договоров охват — вся сеть.
    location_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="CASCADE"), nullable=True)
    # 0 = начисление периода, >0 = корректировка за прошлый закрытый месяц.
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    expected_gross: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    expected_net: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    expected_qty: Mapped[float | None] = mapped_column(Numeric(16, 3), nullable=True)
    vat_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Откуда взялась сумма — показывается меткой рядом с цифрой:
    # document | contract | metered | metered_prev | prev_period | average |
    # manual | correction | none
    expected_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    doc_due_on: Mapped[str | None] = mapped_column(String(10), nullable=True)

    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ops_counterparty_docs.id", ondelete="SET NULL"), nullable=True)
    actual_gross: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    actual_net: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    actual_qty: Mapped[float | None] = mapped_column(Numeric(16, 3), nullable=True)

    # expected | received | matched | disputed | accrued | corrected | waived
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="expected")
    # Те же слова, что у AccountingDoc.discrepancy_status: расхождение в двух
    # контурах обязано называться одинаково.
    variance_class: Mapped[str | None] = mapped_column(String(16), nullable=True)
    corrects_charge_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ops_period_charges.id", ondelete="SET NULL"), nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_in_period: Mapped[str | None] = mapped_column(String(10), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Журнал напоминаний контрагенту: reminders[] — когда, кому, кем.
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Разворот идемпотентен: повторный прогон не задваивает. Ручные строки
        # (term_id IS NULL) не дедуплицируются — ручная строка всегда осознанна.
        Index("uq_ops_charge_term", "company_id", "period", "term_id", "seq", unique=True,
              postgresql_where=text("term_id IS NOT NULL")),
        Index("ix_ops_charge_location", "company_id", "period", "location_id"),
        Index("ix_ops_charge_cp", "company_id", "counterparty_id", "period"),
        Index("ix_ops_charge_status", "company_id", "period", "status"),
    )


class OpsPayment(Base):
    """Кассовый факт: сколько контрагенту заплатили за период по статье.

    В «Хозяйстве» до сих пор жила только одна сторона дела — ОЖИДАНИЕ:
    `OpsPeriodCharge` разворачивает условия договоров в «сколько должно быть
    начислено». Сравнить это было не с чем: первичка приходит поштучно, а денег,
    ушедших со счёта, в пространстве не было вовсе. Отсюда вопрос, на который
    «Хозяйство» не отвечало: «мы платим больше, чем должны, — или меньше?»

    Строка — это выгрузка казначейства/бухгалтерии заказчика, а не наш расчёт.
    Поэтому она не участвует в закрытии месяца и не правит начислений: закрытый
    месяц не переписывается (см. `ops_closing`), а факт лишь показывает рядом,
    сколько ушло. Расхождение считается на чтении — как и везде в этом контуре.

    Объекты названы бухгалтерскими номерами заказчика, и их в одной строке
    обычно несколько: энергосбыт выставляет счёт сразу на десятки площадок. Мы
    храним перечень как есть — раскладывать сумму по объектам без основания
    значило бы выдумать распределение, которого в документе нет.
    """

    __tablename__ = "ops_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Первое число месяца ISO — как в OpsPeriodCharge. Годовые итоги выгрузки
    # ложатся на январь своего года с пометкой `granularity = 'year'`: смешивать
    # их с месяцами нельзя, но и терять историю 2022–2024 незачем.
    period: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    granularity: Mapped[str] = mapped_column(String(10), nullable=False, default="month")
    cost_item: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # Инвестиции идут теми же статьями, но это капитальные вложения, а не расход
    # периода: в отчёте о результате им не место, в стоимости объекта — место.
    is_capital: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    # Имя из выгрузки хранится всегда, даже когда контрагент опознан: сопоставление
    # может оказаться ошибочным, и тогда нужно видеть, что было написано в источнике.
    counterparty_name: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    # Бухгалтерские номера объектов заказчика, к которым относится платёж.
    object_numbers: Mapped[list[str] | None] = mapped_column(ARRAY(String(40)), nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    # Ключ идемпотентности: повторная загрузка того же файла не задваивает суммы.
    external_key: Mapped[str] = mapped_column(String(200), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("uq_ops_payments_key", "company_id", "external_key", unique=True),
        Index("ix_ops_payments_period_item", "company_id", "period", "cost_item"),
    )


class OpsPeriodClose(Base):
    """Закрытие месяца по затратам эксплуатации.

    Свой, а не `Period`: тот реплицирует периоды из 1С (`closure_source`) и для
    профиля `energy` вообще не показывается. Здесь период закрывает наш человек
    кнопкой, и после закрытия суммы перестают плавать.

    Квартал и год своего закрытия не получают: квартальных документов не бывает,
    бывают квартальные договоры — они дают ожидание в месяце окончания квартала.
    """
    __tablename__ = "ops_period_close"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    # open | collecting | review | closed | reopened
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    expected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_expected_gross: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_actual_gross: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Снимок на момент закрытия: разрезы по статьям, объектам, методам оценки.
    # Нужен, чтобы «как было при закрытии» пережило любые последующие правки.
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_ops_period_close", "company_id", "period", unique=True),
    )


class OpsMeter(Base):
    """Узел учёта электроэнергии — когда один прибор стоит на несколько станций.

    Из данных заказчика: 38 пометок «Один счетчик на три станции», «Потребление
    по двум станциям». Плюс коэффициент трансформации, без которого объём не
    воспроизводится: в файле лежат формулы вида `=46*30` и комментарий
    `198 - ПУ | К/Т = 50`, поэтому значения кратны 30/40/50/60.
    """
    __tablename__ = "ops_meters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ktrans: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    counterparty_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True)
    # {location_id: доля_в_процентах}. Таблицей связи не делаем: 38 случаев на
    # 760 станций джойна не требуют, разнос идёт в коде расчёта.
    shares: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_ops_meter_company", "company_id", "number"),
    )


# ---------------------------------------------------------------------------
# PulseAck — «принято» на карточке «Пульса» (рабочее место руководителя)
# ---------------------------------------------------------------------------
class PulseAck(Base):
    """Руководитель снял карточку с экрана дня — «сегодня видел».

    Действует до конца суток: назавтра живое условие вернёт карточку само,
    «принято» не означает «больше не показывать никогда» (ecosystem-deploy/
    docs/PULSE.md §3). Ack общий на компанию: экран дня один у всего контура
    руководства, секретарь гасит карточку и для директора.
    """
    __tablename__ = "pulse_acks"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    card_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    acked_on: Mapped[date_type] = mapped_column(Date, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Отложено до этой даты: «вернуться через три дня». NULL — обычное «принято
    # на сегодня». Карточка не показывается, пока срок не наступил, но остаётся
    # в списке отложенного — это обязательство руководителя, а не забывание.
    snooze_until: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PulseTarget(Base):
    """Порог эскалации «Пульса», заданный компанией.

    Норма — мнение компании, а не константа в коде: 19% пропущенных звонков для
    одной сети катастрофа, для другой — обычный вторник. Реестр допустимых
    ключей и дефолты живут в `routers/pulse_router.THRESHOLDS`; здесь только то,
    что руководитель поменял руками.
    """
    __tablename__ = "pulse_targets"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# EdgePacket — сырой пакет от edge-агента станции (проект Ledger Edge)
# ---------------------------------------------------------------------------
class EdgePacket(Base):
    """Пакет смены, пришедший с агента станции, как он есть.

    Хранится сырьём: разбор идёт отдельно и может быть переигран. Уникальность
    по (company_id, packet_uuid) даёт идемпотентность — агент повторяет отправку при любой
    неопределённости (обрыв на ответе), и повтор не создаёт дубль.

    Пакет остаётся неизменным L1; edge_projection идемпотентно материализует
    из него канонические документы Ledger L2.
    """
    __tablename__ = "edge_packets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    packet_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    shift_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    shift_internal_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wire_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "packet_uuid",
                         name="uq_edge_packets_company_packet"),
        Index("ix_edge_packets_station_shift", "company_id", "station_id", "shift_internal_no"),
    )


class EdgePacketRevision(Base):
    """Неизменяемая raw-версия доставки Edge-пакета."""
    __tablename__ = "edge_packet_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    edge_packet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("edge_packets.id", ondelete="RESTRICT"), nullable=False)
    packet_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wire_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_edge_packet_revision_content_hash",
        ),
        CheckConstraint(
            # Ревизия append-only: исход её разбора живёт отдельным фактом в
            # edge_packet_revision_decisions, а не в этом поле (см. v2.41).
            "status IN ('received','needs_review')",
            name="ck_edge_packet_revision_status",
        ),
        UniqueConstraint(
            "company_id", "packet_uuid", "content_hash",
            name="uq_edge_packet_revision_content",
        ),
        Index("ix_edge_packet_revision_packet", "edge_packet_id", "received_at"),
    )


class EdgePacketProcessingIssue(Base):
    """Append-only ошибка обработки уже сохранённой raw-версии пакета."""
    __tablename__ = "edge_packet_processing_issues"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    edge_packet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("edge_packets.id", ondelete="RESTRICT"), nullable=False)
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("edge_packet_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    packet_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    phase: Mapped[str] = mapped_column(String(30), nullable=False, default="derived")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="needs_review")
    error: Mapped[str] = mapped_column(Text, nullable=False)
    error_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_edge_packet_issue_content_hash",
        ),
        CheckConstraint(
            "error_hash ~ '^[0-9a-f]{64}$'",
            name="ck_edge_packet_issue_error_hash",
        ),
        CheckConstraint(
            "status = 'needs_review'",
            name="ck_edge_packet_issue_status",
        ),
        UniqueConstraint(
            "company_id", "packet_uuid", "content_hash", "error_hash",
            name="uq_edge_packet_processing_issue_error",
        ),
        Index("ix_edge_packet_issue_packet", "edge_packet_id", "created_at"),
    )


class StoreStockBalance(Base):
    """Последний полный остаток собственного учёта агента.

    Таблица намеренно находится в основном контуре Ledger и содержит company_id:
    старые edge.stock/edge.item создавались до мультитенантности и различали
    станции только по номеру, поэтому две компании с АЗС №208 пересекались бы.
    """
    __tablename__ = "store_stock_balances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    place: Mapped[str] = mapped_column(String(80), nullable=False)
    place_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    balance_key: Mapped[str] = mapped_column(String(200), nullable=False)
    item_uuid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    barcode: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    quantity: Mapped[float] = mapped_column(Numeric(16, 3), nullable=False, default=0)
    retail_price: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    cost_unit: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    cost_known_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="edge_ledger")
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "station_id", "place", "balance_key",
                         name="uq_store_stock_balance"),
        Index("ix_store_stock_company_place", "company_id", "station_id", "place"),
        Index("ix_store_stock_item", "company_id", "item_uuid"),
        Index("ix_store_stock_barcode", "company_id", "barcode"),
    )


class StoreReceipt(Base):
    """Приёмка товара — документ Ledger, а не зеркало 1С.

    Первый документ, который система не читает из ЦБ, а порождает сама. Точек
    ввода две, и обе законны: центр заводит накладную от поставщика (в том
    числе из ЭДО), станция принимает товар физически. Документ при этом ОДИН —
    иначе фактическая приёмка и накладная разъедутся, а сверять их будет некому.

    Модель следует ордерной схеме 1С:Розница, к которой привык товаровед:
    `expected` — «к поступлению», товар заявлен, но на складе его ещё нет;
    `accepted` — «принят», посчитан и оприходован. Пока документ не принят,
    остатки не двигаются.

    Строки держим в JSONB: документ читается и пишется целиком, приёмку ведёт
    один человек, а состав строки будет расти (коды маркировки, партии, сроки).
    """
    __tablename__ = "store_receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    doc_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Поставщик: пока строкой — справочник контрагентов Ledger появится вместе
    # с ЭДО, а до тех пор товаровед пишет имя, как в накладной.
    supplier: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contract: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="RESTRICT"), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True)
    incoming_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    incoming_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # draft — набирается; expected — заявлен к поступлению; accepted — принят.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Откуда пришёл документ: center | station | edo. Нужно, чтобы понимать, кто
    # владеет правкой, и не затирать фактическую приёмку заявкой из центра.
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="center")

    # Логистика и юридически значимое подписание — независимые оси.
    delivery_scheme: Mapped[str] = mapped_column(
        String(30), nullable=False, default="supplier_to_station")
    receiving_warehouse: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signing_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="office_director")
    signer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Кто принял товар на станции: «Жукова» либо «Михеев (из центра)». Не то же,
    # что подписант ЭДО и не подотчётное лицо: тот покупал, этот считал коробки.
    # Пусто у документов, принятых до появления подписи.
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mchd_guid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mchd_registry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mchd_valid_until: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    signature_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    signature_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    distribution: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    services: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    supplier_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    contract_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    organization_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warehouse_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    accounting_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'"))
    accounting_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    accounting_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"))
    content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    total_amount: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    vat_amount: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # UUID пакета станции — идемпотентность при доставке снизу.
    source_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_store_receipts_company_station", "company_id", "station_id", "doc_date"),
        Index("ix_store_receipts_supplier", "company_id", "supplier_id"),
        Index("ix_store_receipts_contract", "company_id", "contract_id"),
        Index("ix_store_receipts_organization", "company_id", "organization_id"),
        Index("ix_store_receipts_warehouse", "company_id", "warehouse_id"),
        CheckConstraint(
            "accounting_status IN ('pending','needs_review','ready')",
            name="ck_store_receipt_accounting_status",
        ),
        CheckConstraint(
            "accounting_revision >= 0",
            name="ck_store_receipt_accounting_revision",
        ),
        CheckConstraint(
            "content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_store_receipt_content_hash",
        ),
        UniqueConstraint("company_id", "source_uuid", name="uq_store_receipts_company_source"),
        UniqueConstraint("company_id", "dedup_key", name="uq_store_receipts_company_dedup"),
    )


class StoreReceiptStockMovement(Base):
    """Неизменяемое движение склада, созданное приёмкой или распределением."""
    __tablename__ = "store_receipt_stock_movements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("store_receipts.id", ondelete="RESTRICT"), nullable=False)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("store_receipt_stock_movements.id", ondelete="RESTRICT"),
        nullable=True)
    allocation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    line_index: Mapped[int] = mapped_column(Integer, nullable=False)
    station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True)
    warehouse: Mapped[str] = mapped_column(String(200), nullable=False)
    item_key: Mapped[str] = mapped_column(String(200), nullable=False)
    item_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(16, 3), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key",
                         name="uq_store_receipt_stock_movement_key"),
        Index("ix_store_receipt_stock_movement_receipt", "receipt_id", "created_at"),
        Index("ix_store_receipt_stock_movement_balance",
              "company_id", "warehouse", "item_key", "created_at"),
        Index("ix_store_receipt_stock_movement_canonical_balance",
              "company_id", "warehouse_id", "item_key", "created_at"),
    )


class StoreRecipeVersion(Base):
    """Версия ТТК, которой владеет центр Ledger.

    Строки лежат одним JSONB-снимком: версия неизменяема после активации, а
    станция получает весь согласованный набор атомарно. Историческую ТТК нельзя
    восстановить из текущей edge.recipe — поэтому это отдельный первичный слой,
    а не дополнительные флаги поверх импортированного среза 1С.
    """
    __tablename__ = "store_recipe_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    dish_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    dish_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    recipe_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="dish")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    output_qty: Mapped[float] = mapped_column(Numeric(16, 6), nullable=False, default=1)
    output_unit: Mapped[str] = mapped_column(String(20), nullable=False, default="шт")
    lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="center")
    source_station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_bundle_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "dish_uuid", "version",
                         name="uq_store_recipe_version"),
        Index("ix_store_recipe_active", "company_id", "status", "valid_from"),
    )


class StoreAssortmentRule(Base):
    """Матрица станции: разрешён ли товар к продаже и в какой период."""
    __tablename__ = "store_assortment_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    item_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "station_id", "item_uuid",
                         name="uq_store_assortment_rule"),
        Index("ix_store_assortment_station", "company_id", "station_id", "active"),
    )


class StoreItemAlias(Base):
    """Неизменяемая трасса слияния карточки-дубля в канон Ledger."""
    __tablename__ = "store_item_aliases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    alias_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "alias_uuid", name="uq_store_item_alias"),
        Index("ix_store_item_alias_canon", "company_id", "canonical_uuid"),
    )


class EdgeDownlink(Base):
    """Очередь заданий центра для станции.

    Станция за CGNAT: постучаться к ней нельзя, поэтому «канал вниз» — это
    очередь, которую агент забирает сам своим тактом. Отсюда два времени:
    delivered_at — станция получила, acked_at — станция подтвердила, что
    применила. Между ними может пройти сколько угодно: агент мог получить
    пакет и потерять связь до подтверждения, и тогда пакет придёт повторно.
    Приёмная сторона обязана быть идемпотентной — как и на пути наверх.
    """
    __tablename__ = "edge_downlink"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # goods_receipt_expected | nsi_delta | price_update | command
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Отмена — не то же, что применение. Задание, снятое из центра, обязано
    # выглядеть снятым: иначе история говорит, что станция его выполнила.
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        Index("ix_edge_downlink_pending", "company_id", "station_id", "acked_at"),
        UniqueConstraint("company_id", "idempotency_key",
                         name="uq_edge_downlink_company_idempotency"),
    )


class StoreCheque(Base):
    """Фискальный чек станции — продажа на уровне покупки, а не смены.

    Отчёт о розничных продажах закрывает смену сводом, и этого хватает
    бухгалтерии. Но спорная продажа, возврат, проверка маркированного товара и
    разбор жалобы разбираются по конкретному чеку: когда, что, за сколько и по
    какому фискальному номеру. Свод на такие вопросы не отвечает.

    Хранится только товарная часть: топливо живёт в своём контуре, и дублировать
    его здесь незачем. Признак `had_fuel` оставлен, потому что смешанный чек
    (заправка плюс кофе) — обычное дело на АЗС, и по нему видно, что чек
    показан не целиком.
    """
    __tablename__ = "store_cheques"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    shift_number: Mapped[int] = mapped_column(Integer, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    cash_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
                                         server_default=text("0"))
    cash_key: Mapped[str] = mapped_column(String(200), nullable=False)
    # Фискальный номер документа: по нему чек ищут в ОФД и в кассе.
    fiscal_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_return: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    had_fuel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pay_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pay_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    total: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    packet_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "station_id", "shift_number", "cash_key",
                         name="uq_store_cheque"),
        Index("ix_store_cheques_at", "company_id", "station_id", "at"),
        CheckConstraint("version > 0", name="ck_store_cheque_version"),
    )


class StorePricePlan(Base):
    """Намерение сменить цену: корзина изменений и отложенное применение.

    Отделено от истории цен (`edge.price`) намеренно: там факт — «цена стала
    такой тогда-то», здесь план — «хотим такую с такого-то времени». Пока план
    не применён, на полке и в кассе прежняя цена.

    Зачем корзина вообще нужна. Массовое правило — самая опасная операция сети:
    одна опечатка в поле «процент» переписывает весь прайс. Черновик даёт
    остановиться и посмотреть, отложенное применение — сменить цены к открытию
    смены, а не посреди неё. Ровно так это устроено на станции
    (`agent/internal/store/prices.go`, таблица `price_plan`), и центр обязан
    работать так же: одинаковое действие не может называться по-разному.

    Одна активная строка на (АЗС, карточка): корзина — это «что хотим сделать
    сейчас», а не журнал намерений. Повторное правило по той же позиции заменяет
    прежнюю строку, а не копит вторую с другой ценой.
    """
    __tablename__ = "store_price_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    item_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    old_price: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    new_price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    author: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # draft — копится в корзине; scheduled — ждёт своего времени;
    # applied — применён; cancelled — снят до применения.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Когда применить. Пусто у черновика: ещё не решили когда.
    effective_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Почему не поехало: карточки нет в справочнике, цену перехватила станция.
    # Пустое у успешных — иначе разбирать нечего.
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        Index("uq_store_price_plan_active", "company_id", "station_id", "item_uuid",
              unique=True, postgresql_where=text("status IN ('draft','scheduled')")),
        Index("ix_store_price_plans_due", "status", "effective_at"),
        CheckConstraint("new_price >= 0", name="ck_store_price_plan_price"),
    )


class StoreDocumentProjection(Base):
    """Пересобираемая поисковая шапка документа сопутки/общепита."""
    __tablename__ = "store_document_projections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    accounting_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    # shift_no: внутренний номер кассовой смены. Пусто у документов, которые
    # смене не принадлежат, — приёмка от поставщика приходит в смену, но ей не
    # принадлежит: она условие смены, а не её часть.
    shift_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    projection_source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    document_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    document_role: Mapped[str] = mapped_column(String(30), nullable=False)
    station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    counterparty_inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    vat_amount: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    operational_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    sync_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    accounting_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    discrepancy_status: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    requires_attention: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_files: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_fuel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_payload_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    header: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rebuilt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_store_document_projection_document", "company_id", "document_id"),
        Index("ix_store_document_projection_source_document", "company_id",
              "projection_source", "source_document_id"),
        Index("ix_store_document_projection_accounting_group",
              "company_id", "accounting_group_id"),
        UniqueConstraint("company_id", "projection_source", "source_kind", "source_record_id",
                         name="uq_store_document_projection_source"),
        Index("ix_store_document_projection_register",
              "company_id", "station_id", "document_at", "document_kind"),
        CheckConstraint(
            "document_kind IN ('purchase','return_purchase','transfer','inventory',"
            "'gain','writeoff','retail_sale_sidegoods','return_sale','recipe',"
            "'production_release','ingredients_writeoff','fiscal_receipt','store_shift',"
            "'revaluation')",
            name="ck_store_document_projection_kind",
        ),
        CheckConstraint(
            "projection_source IN ('edge','store','onec_legacy','edo','cash','bp')",
            name="ck_store_document_projection_source",
        ),
        CheckConstraint(
            "document_role IN ('primary_evidence','operational','fiscal','accounting_derived')",
            name="ck_store_document_projection_role",
        ),
        CheckConstraint("revision > 0", name="ck_store_document_projection_revision"),
        CheckConstraint(
            "content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_store_document_projection_content_hash",
        ),
    )


class StoreDocumentProjectionLine(Base):
    """Ссылка на строку первичного источника без копирования её содержимого."""
    __tablename__ = "store_document_projection_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("store_document_projections.id", ondelete="CASCADE"), nullable=False)
    source_section: Mapped[str] = mapped_column(String(30), nullable=False)
    source_line_id: Mapped[str] = mapped_column(String(200), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "record_id", "source_section", "source_line_id",
                         name="uq_store_document_projection_line"),
        Index("ix_store_document_projection_line_record", "record_id", "ordinal"),
    )


class StoreDocumentRelation(Base):
    """Связь документа с другим документом либо неизменяемым source-ref."""
    __tablename__ = "store_document_relations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("store_document_projections.id", ondelete="CASCADE"), nullable=False)
    related_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("store_document_projections.id", ondelete="SET NULL"), nullable=True)
    relation_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(250), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("company_id", "record_id", "relation_kind", "target_ref",
                         name="uq_store_document_relation"),
        Index("ix_store_document_relation_related", "company_id", "related_record_id"),
    )


class StoreDocMeta(Base):
    """Реквизиты документа, которых нет в пакете станции: стороны и примечание.

    Перемещение между станциями — не запись в журнале, а передача имущества:
    один сдал, другой принял, и без двух фамилий документ не имеет смысла.
    Агент сегодня передаёт только автора, поэтому ответственных дописывают в
    центре — и они же уходят в печатную форму, которую подписывают.

    Отдельная таблица, а не поля в пакете: сырьё станции неизменно по канону
    проекта, дописывать в него центр не вправе.
    """
    __tablename__ = "store_doc_meta"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    doc_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Кто передал имущество и кто принял: фамилии, как в накладной.
    responsible_from: Mapped[str | None] = mapped_column(String(200), nullable=True)
    responsible_to: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Регистрационный номер центра: номер станции присваивает касса, и у двух
    # АЗС он совпадает. В переписке, в претензии поставщику и в акте нужен
    # номер, который в сети один — этот присваивается при регистрации.
    reg_number: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)
    registered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # принят | проверен | спорный | закрыт
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="принят")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "doc_ref", name="uq_store_doc_meta"),
    )


class StoreDocFile(Base):
    """Образ первичного документа склада: скан накладной, УПД, акт, опись.

    Учётная запись документа и его бумажное основание — разные вещи. Приёмка
    может быть проведена, а накладной поставщика в системе нет; при проверке
    предъявлять нечего, и товар считается принятым без документа.

    Файл лежит в общем хранилище пространства (`source_files`) — том же, что у
    документов проектов и затрат: второй способ хранить одно и то же расходится
    с первым на первой же правке. Здесь только связь с документом и его роль.

    `doc_ref` — ссылка вида «receipt:<uuid>» или «station:<packet_uuid>:<i>»:
    документы приходят из разных контуров, и заводить внешний ключ на каждый
    значит переписывать таблицу с каждым новым видом.
    """
    __tablename__ = "store_doc_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    doc_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # накладная | упд | акт | опись | фото | прочее
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="накладная")
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    mime: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tombstoned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    tombstone_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        Index("ix_store_doc_files_ref", "company_id", "doc_ref"),
        Index("ix_store_doc_files_record", "company_id", "record_id", "tombstoned_at"),
        Index(
            "uq_store_doc_file_revision",
            "record_id", "revision", "role", "sha256",
            unique=True,
            postgresql_where=text(
                "record_id IS NOT NULL AND revision IS NOT NULL "
                "AND role IS NOT NULL AND sha256 IS NOT NULL"
            ),
        ),
        CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_store_doc_file_sha256",
        ),
    )


class MarkingIntegration(Base):
    """Подключение компании к внешней системе маркировки.

    Реквизиты вводятся в интерфейсе, а не правкой окружения: доступ к ГИС МТ
    оформляет бухгалтерия и юрист, а не тот, кто умеет перевыкатывать стек.

    Секреты лежат отдельным полем и зашифрованы Fernet тем же ключом, что
    пароли подключений к 1С: `settings` можно показывать и логировать,
    `secrets` — никогда. Наружу секрет уходит только маской вида «••••1234»,
    расшифровка живёт на сервере и нужна лишь в момент запроса к системе.
    """
    __tablename__ = "marking_integrations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    # gismt | ofd | nk | egais | mercury | local_module
    system: Mapped[str] = mapped_column(String(30), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Ключ поля → Fernet-токен. Отдельно от settings, чтобы дамп настроек
    # физически не мог вынести секрет.
    secrets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_check_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "system", name="uq_marking_integration"),
    )


class StoreStationAlert(Base):
    """Находка по станции как СОБЫТИЕ, а не как срез на момент взгляда.

    Отчёт «что требует внимания» считался на лету, и ответить на вопрос «это
    появилось вчера или висит третью неделю» было нечем. Идентичность находки —
    тема (касса, выгрузка, учёт, НСИ, коды кассы, сверка смен): текст меняется
    вместе с числами, а проблема остаётся той же.

    Закрытие проставляет тот же расчёт: если при очередном пересчёте темы среди
    находок нет, она ушла — и это тоже событие, которое стоит помнить.
    """
    __tablename__ = "store_station_alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(String(40), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    text: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_store_station_alerts_open", "company_id", "station_id", "resolved_at"),
    )


class EdgeHeartbeat(Base):
    """След телеметрии: одна строка на каждый выход агента на связь.

    `edge_agents` хранит только последнее состояние, и по нему нельзя ответить
    на вопрос «сколько станция была недоступна за месяц» — а это и есть
    качество канала, ради которого затевался офлайн-первый агент. Сеансы
    обмена считаются по пакетам, но пакеты идут неравномерно: снимок раз в час
    не доказывает, что между ними связь была.

    Строка в минуту на станцию — примерно 43 тысячи в месяц; хранение
    ограничено чисткой, история старше квартала ничего не решает.
    """
    __tablename__ = "edge_heartbeats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    queue_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_edge_heartbeats_station_at", "company_id", "station_id", "at"),
    )


class EdgeAgent(Base):
    """Состояние агента станции: кто на связи, какая версия, что в очереди.

    Заполняется телеметрией самого агента (heartbeat раз в минуту). Нужна,
    чтобы центр видел парк станций так же, как станция видит себя: онлайн ли,
    свежий ли код, разобрана ли очередь. Пока такой таблицы не было, станция
    для «Магазина» оставалась чёрным ящиком — о проблеме узнавали из письма
    оператора.

    Наличие свежего `last_seen` НЕ означает, что идёт передача данных: это
    значит, что канал есть и обмен возможен.
    """
    __tablename__ = "edge_agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    queue_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queue_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_shift: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Полная телеметрия как прислал агент: состав растёт, ломать схему на
    # каждое новое поле нельзя — станции обновляются не одновременно.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "station_id", name="uq_edge_agents_station"),
    )


# ---------------------------------------------------------------------------
# Задачи пространства — продукт «Задачи» (ecosystem-deploy/docs/TASKS.md)
# ---------------------------------------------------------------------------
class TaskType(Base):
    """Тип задачи и его маршрут: чем задача отличается от задачи.

    Маршрут — упорядоченный список стадий, а не скрипт: `[{"code","name"}]`.
    Так тип заводит руководитель, а не разработчик, и правило видно целиком в
    одной строке. Стадии живут в JSONB намеренно: отдельная таблица дала бы
    ссылочную целостность, которая тут не нужна (стадию нельзя «потерять» —
    она часть определения типа), зато потребовала бы транзакции на каждую
    правку порядка.
    """
    __tablename__ = "task_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Тип принадлежит проекту или всей компании (NULL). У разработки свои маршруты
    # (ошибка → воспроизведение → правка → проверка), у делопроизводства свои, а
    # общие типы вроде «Поручения» нужны обоим — поэтому связь необязательная.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_projects.id", ondelete="CASCADE"),
        nullable=True, index=True)
    # [{"code": "new", "name": "Постановка"}, …] — порядок = порядок движения.
    route: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    default_priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    # Срок по умолчанию от постановки; NULL — без срока.
    due_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Сколько часов даётся на первый отклик исполнителя. NULL — не следим.
    # Время реакции — свойство ТИПА, а не задачи: это регламент, одинаковый для
    # всех работ этого вида, и держать его в каждой задаче значило бы разрешить
    # тихо разойтись правилу и практике.
    reaction_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Кому сообщить, если отклика нет. NULL — сообщить автору задачи.
    escalate_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_task_types_code"),
    )


_tasks_number_seq = Sequence("tasks_number_seq", start=1, metadata=Base.metadata)


class Task(Base):
    """Задача пространства: кто, что и к какому сроку делает.

    Не заявка Поддержки: та описывает поломку у заявителя и живёт в контуре
    Поддержки со своим SLA и внешними сторонами. Задача — внутренняя работа
    компании, её ставят люди пространства друг другу. Общее у них словари
    (приоритет, «у кого мяч») и объект пространства, к которому привязана
    работа; правда — раздельная, вторых копий никто не заводит.
    """
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Человеческий номер. Сквозной по контейнеру: последовательность БД снимает
    # гонку двух одновременных постановок, которую max(number)+1 не снимает.
    number: Mapped[int] = mapped_column(
        Integer, _tasks_number_seq, server_default=_tasks_number_seq.next_value(),
        nullable=False, unique=True)
    # Проект работы. NULL допустим только на время переноса старых поручений:
    # задача без проекта — это свалка, в которой не собрать ни релиз, ни бэклог.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_projects.id", ondelete="SET NULL"),
        nullable=True, index=True)
    # Номер внутри проекта: показывается как `TF-42`. Сквозной `number` остаётся
    # внутренним — на него уже ссылаются написанные интеграции.
    project_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Версии проекта: в какой обнаружено и в какой исправлено. Второе — ответ
    # заявителю («исправлено в 1.4.2»), первое — с чего разбираться, когда через
    # три релиза окажется, что сломали давно. Обе принадлежат проекту задачи:
    # версия чужого проекта в карточке не значит ничего.
    found_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_versions.id", ondelete="SET NULL"), nullable=True)
    fix_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_versions.id", ondelete="SET NULL"), nullable=True)
    # Отрезок работы. Пусто — бэклог: задача есть, а когда её делать, ещё не
    # решили. Это состояние нормальное, а не незаполненное поле.
    sprint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_sprints.id", ondelete="SET NULL"), nullable=True)
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_types.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    # open | done | cancelled. Стадия — где внутри маршрута, статус — жива ли.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    stage_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Колонка текущей стадии на общей оси пространства (`work_state`). Хранится
    # рядом с кодом стадии, потому что вычисляется из маршрута ТИПА (JSONB), а
    # отбор по состоянию должен идти в SQL: разбирать маршрут запросом — дорого
    # и нечитаемо, а фильтровать в приложении значит сломать постраничность.
    stage_column: Mapped[str | None] = mapped_column(String(20), nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Объект пространства — общая ось с заявками, чатами и «Проектами».
    object_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    # Предмет работы — тем же механизмом, что у документа: `<вид>:<ключ>`
    # (`site:<uuid>`, `contract:<uuid>`, `object:<ключ>`). Объекта сети у площадки
    # может ещё не быть — он появляется со вводом в эксплуатацию, — а поручить
    # выезд или согласование нужно раньше; без предмета такая работа не
    # находилась по проекту вовсе.
    #
    # Уникальности здесь нет, в отличие от документа: документ по предмету один
    # («договор аренды этого участка»), поручений по нему сколько угодно.
    subject_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # У кого мяч: us — ждём себя, external — ждём внешнюю сторону. NULL = у нас,
    # как и было до появления внешних участников. Отдельное поле, а не вывод из
    # состава участников: «отправили и ждём» — это решение человека, а не факт
    # наличия чужого адреса в карточке.
    waiting_for: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Когда исполнитель впервые отозвался (двинул стадию или написал реплику) —
    # по этой отметке считается время реакции и эскалация.
    reacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Когда последний раз напоминали о сроке. Без отметки напоминание уходило бы
    # каждый тик планировщика, и его перестали бы читать на второй день.
    reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Оценка трудоёмкости в минутах (как `estimation` в YouTrack). План живёт в
    # задаче, факт — в записях о работе: их сравнение и есть весь смысл учёта.
    estimate_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Кто видит задачу: company — вся компания (обычный случай), private —
    # только причастные (автор, исполнитель, наблюдатели, участники) и админ
    # пространства. Кадровые и денежные поручения не должны читаться всеми, а
    # заводить под них отдельный продукт — лишнее.
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="company")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskEvent(Base):
    """След задачи: постановка, движение по маршруту, переадресация, реплики.

    Лента — единственный источник ответа «почему работа стоит»: без неё
    переадресация выглядит как самопроизвольная смена исполнителя.
    """
    __tablename__ = "task_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # created | stage | assign | status | comment | mail | external_stage | delegate
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Имя автора без учётки: письмо мог прислать человек, которого в пространстве
    # нет вовсе, и подписывать его событие «система» — терять единственный ответ
    # на вопрос «кто это сказал».
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Закреплённая реплика: договорённость, к которой возвращаются, не должна
    # тонуть в ленте из тридцати событий.
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    from_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class TaskLink(Base):
    """Связь двух задач: подзадача, блокировка, «связана», дубль.

    Одна таблица на все виды связи, обратную сторону не дублируем — читаем в обе
    стороны. Пара таблиц (подзадачи отдельно, связи отдельно) дала бы два способа
    спросить «что мешает этой задаче» и два места, где связь можно забыть удалить.
    """
    __tablename__ = "task_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False, index=True)
    related_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # subtask (task_id — родитель) | blocks (task_id мешает related) | relates | duplicates
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="relates")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("task_id", "related_task_id", "kind", name="uq_task_links"),
    )


class TaskChecklistItem(Base):
    """Пункт чек-листа задачи: что именно осталось сделать внутри одной работы."""
    __tablename__ = "task_checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    done_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class TaskAttachment(Base):
    """Файл при задаче или при комментарии.

    Сам файл лежит там же, где остальные файлы Ядра (`source_files` + `UPLOAD_DIR`),
    здесь только привязка: имя, размер и тип уже описаны один раз в `SourceFile`,
    второй копии этих полей не заводим.
    """
    __tablename__ = "task_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Заполнен, если файл приложен к реплике, а не к задаче целиком.
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_events.id", ondelete="SET NULL"), nullable=True)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class TaskWatcher(Base):
    """Кто следит за задачей помимо автора и исполнителя.

    `reason` отвечает на вопрос «почему я это вижу»: подписался сам, упомянули
    в реплике или поставил задачу. Без него человек не понимает, за что ему
    приходят оповещения, и отписывается от всего сразу.
    """
    __tablename__ = "task_watchers"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # manual | mention | author
    reason: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class TaskProject(Base):
    """Проект: контейнер работы со своим номером, участниками и составом.

    Заведён 22.08.2026 (решение МАГа) под трекерный контур «Трека»: без проекта не
    собирается ни бэклог, ни релиз, ни «мои задачи по продукту» — всё лежит одной
    кучей на пространство.

    Почему отдельная сущность, а не ось объектов: объекты пространства — нормативная
    модель зарядной инфраструктуры (СТО, пять уровней), и программный продукт туда не
    кладётся без искажения предметной области. Почему не метка: метка не несёт ни
    префикса номера, ни своих типов задач, ни прав.
    """
    __tablename__ = "task_projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Код идёт в номер задачи и в разговор: «посмотри TF-42». Короткий и в верхнем
    # регистре — из тех же соображений, по которым он такой в YouTrack.
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Счётчик своей нумерации. Растёт только вперёд: номер закрытой задачи не
    # переиспользуется, иначе ссылка из переписки однажды укажет на чужую работу.
    counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_task_projects_code"),
    )


class TaskVersion(Base):
    """Версия проекта: «исправлено в 1.4.2» — то, чего ждёт заявитель.

    Заведена 22.08.2026, этап 10 трекерного контура. Версия принадлежит проекту,
    а не компании: «1.4» у фронта и «1.4» у бэкенда — разные вещи, и общий на
    пространство справочник заставил бы придумывать им разные имена.

    Состояние тремя словами: `open` — версия набирается, `released` — выпущена
    (дата выпуска проставлена), `cancelled` — отменена, задачи из неё надо
    перецелить. Версия не удаляется: её номер уже назван заявителю в ответе.
    """
    __tablename__ = "task_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_projects.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Имя версии — как её называют в разговоре и пишут заявителю: «1.4.2»,
    # «2026.08». Свободная строка: схемы нумерации у продуктов разные, и
    # навязывать semver значило бы спорить с командой о том, что не наше дело.
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # open | released | cancelled
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    # Дата выпуска: план, пока версия набирается, и факт после выпуска. Дата, а
    # не отметка времени: релиз называют днём, а не минутой.
    released_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_task_versions_name"),
    )


class TaskSprint(Base):
    """Спринт проекта: что берём в работу следующим отрезком времени.

    Заведён 22.08.2026, этап 11 трекерного контура. Доска по стадиям отвечает
    «где работа стоит», но не отвечает «что берём следующим»: без спринта живая
    работа и бэклог лежат вперемешку, и планёрка сводится к чтению всего списка.

    Задача без спринта — это и есть бэклог. Отдельной сущности «бэклог» нет:
    она означала бы, что задачу надо куда-то положить дважды.
    """
    __tablename__ = "task_sprints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_projects.id", ondelete="CASCADE"),
        nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    starts_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # planned | active | closed. Активный спринт в проекте один — это правило
    # держится в роутере: два «текущих» отрезка означают, что плана нет.
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    # Сколько задач ушло обратно в бэклог при закрытии. Считать это потом
    # неоткуда: задачи к тому моменту уже без спринта, и «взято» превратилось бы
    # в «сделано» — итог, по которому не видно, что отрезок переоценили.
    carried_over: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_task_sprints_name"),
    )


class TaskCodeRef(Base):
    """Что в коде сделано по этой задаче: ветка, коммит, запрос на слияние.

    «Исправлено в версии» отвечает заявителю, а этот след отвечает разработчику:
    каким изменением. Без него вопрос «что именно поменяли» решается поиском по
    сообщениям коммитов, и ответ зависит от того, вспомнил ли автор написать
    номер задачи.

    Ссылка, а не копия: заголовок и автор сохраняются как подпись на момент
    добавления, содержимое остаётся в системе, где живёт код. Хранить у себя
    диффы — заводить вторую историю изменений, которая разойдётся с первой.
    """
    __tablename__ = "task_code_refs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # branch | commit | pr | other. Вид определяется по адресу и меняется руками,
    # если распознали неверно: чужих хостингов больше, чем шаблонов у нас.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # Как это называть в карточке: «fix/export-bp», «a1b2c3d», «#128».
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Хранилище и репозиторий строкой: «github · Electro-Interfaces/ClearLedger».
    repo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Одна ссылка на задачу один раз: повторное добавление того же коммита
        # это опечатка, а не второе изменение.
        UniqueConstraint("task_id", "url", name="uq_task_code_refs_url"),
    )


class TaskLabel(Base):
    """Метка компании: свободный ярлык поверх типа и стадии."""
    __tablename__ = "task_labels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    # Имя тона из альфа-шкалы подачи (amber, sky, …), а не hex: цвет обязан
    # работать в обеих темах, а произвольный hex этого не гарантирует.
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="slate")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_task_labels_name"),
    )


class TaskParticipant(Base):
    """Кто участвует в задаче и каким способом до него доходит слово.

    Внешний человек участвует одним из трёх способов (docs/TASKS.md §9): работает
    прямо в пространстве, разговаривает каналом (почта) или сидит во внешней
    системе за коннектором. Способ хранится здесь, чтобы карточка могла честно
    показать, куда именно уходит текст, — «просто участник» без канала оставлял бы
    автора в догадках.
    """
    __tablename__ = "task_participants"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # assignee | external | observer
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="external")
    # space | mail | connector — где человек на самом деле работает.
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="space")
    # Адрес в канале: почтовый ящик, идентификатор в чужой системе.
    channel_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class TaskWorkItem(Base):
    """Запись о работе: сколько времени человек потратил и на что.

    Устроено как в YouTrack (`IssueWorkItem`): отдельная запись, а не поле-счётчик
    в задаче. Счётчик отвечает только «сколько всего», а запись — «кто, когда и
    что делал», и именно по ней собираются трудозатраты за период по людям.

    Длительность в минутах: часы дробью («1,5 ч») в сумме дают копеечные ошибки,
    а минуты складываются точно. Человеку она показывается как «2 ч 30 мин».
    """
    __tablename__ = "task_work_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Одно из двух: время тратится либо на поручение, либо на документ.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True, index=True)
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"),
        nullable=True, index=True)
    # Чья работа. Отделено от `created_by`: руководитель может записать время за
    # человека, и в отчёте оно должно лечь на того, кто работал.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Дата работы, а не записи: время часто заносят на следующий день.
    work_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Вид работы для разреза отчёта: выезд, разработка, согласование…
    kind: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class TaskTemplate(Base):
    """Заготовка задачи: что и как обычно ставят.

    Отличается от типа: тип — правило движения (маршрут, срок, срочность),
    шаблон — содержание («Закрыть месяц по объекту» с готовым чек-листом).
    Их часто путают, поэтому шаблон ссылается на тип, а не заменяет его.
    """
    __tablename__ = "task_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_types.id", ondelete="SET NULL"), nullable=True)
    # Заполнен — шаблон порождает ДОКУМЕНТ этого вида, а не поручение. Так
    # описывается «акт сверки к 5 числу каждого месяца»: работа и документ
    # заводятся одним механизмом, и второй планировщик не нужен.
    doc_kind_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_kinds.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ["пункт", …] — чек-лист заготовки, разворачивается при постановке.
    checklist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    object_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    due_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class TaskRecurrence(Base):
    """Расписание повторяющейся задачи: каждый день, неделю или месяц.

    Порождает новую задачу по шаблону — не воскрешает старую. Продлевать одну и
    ту же задачу значило бы терять историю: «делали ли в прошлом месяце» ответа
    бы не имело.
    """
    __tablename__ = "task_recurrences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_templates.id", ondelete="CASCADE"),
        nullable=False)
    # {"mode": "daily|weekly|monthly", "at": "09:00", "weekday": 0, "day": 1,
    #  "tz": "Europe/Moscow"} — часовой пояс обязателен по смыслу: сервер живёт
    # в UTC, а «в понедельник утром» человек понимает по своему времени.
    rule: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class PersonalReminder(Base):
    """Личное напоминание: «вернуться к этому в 15:00».

    Отдельно от `Task.due_at` и `Task.reminded_at` намеренно, и причин четыре.
    Напоминание персональное, а задача общая — поле в задаче обслуживало бы
    одного человека, и «напомни мне о чужой работе, где я наблюдатель» стало бы
    невыразимым. Напоминать надо и о встрече, и о документе — поле пришлось бы
    заводить в каждой из трёх таблиц. Откладывание — частая операция, а правка
    задачи двигает `updated_at`, по которому сортируется лента работы: три
    нажатия «отложить» вытолкнули бы задачу наверх у всей компании. И наконец,
    существующее регламентное напоминание о сроке остаётся нетронутым.

    Состояние не хранится колонкой, а выводится из отметок времени:
    `fired_at IS NOT NULL AND done_at IS NULL` — это и есть «горит сейчас».
    """
    __tablename__ = "personal_reminders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Владелец — единственный, кто эту строку видит и правит.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Предмет: `task:<uuid>`, `event:<uuid>`, `doc:<uuid>` — тот же словарь
    # `<вид>:<ключ>`, что у `Task.subject_ref` и `DocRelation.target_ref`.
    # Без предмета напоминание — это личное дело со сроком, оно уже есть.
    target_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    # Что именно напомнить: «взять паспорт». Человек чаще напоминает себе
    # действие, а не название задачи, поэтому поле своё, а не пересказ заголовка.
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    remind_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)
    # Доставлено. Планировщик не берёт строку повторно.
    fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Сколько раз отложено. Единственный сигнал, который личный помощник может
    # вернуть человеку: отложенное шестой раз — это дело, которого не будет.
    snooze_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class CalendarEvent(Base):
    """Встреча: время, место, люди и их ответ.

    Отдельная сущность, а не поручение со сроком, по трём причинам, каждая из
    которых видна на первом же экране календаря. У встречи есть КОНЕЦ — без
    него нельзя ни нарисовать неделю, ни ответить «занят ли человек в 15:00».
    У участников есть СОГЛАСИЕ («буду / не буду»), а `TaskParticipant.role`
    описывает канал доставки, а не согласие. И участники встречи РАВНЫ, тогда
    как у поручения есть исполнитель, с которого спрашивают.

    Конец хранится временем, а не длительностью: при переносе встречи и при
    переводе часов «90 минут» каждый клиент считает по-своему, а два момента
    времени однозначны везде.

    `tz` — пояс, в котором встречу задали. Пространство растянуто от
    Владивостока до Москвы: «планёрка в 10:00» без пояса — это разное время
    для организатора и участника, и показывать её надо в поясе, где её назвали.
    """
    __tablename__ = "calendar_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organizer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Событие на весь день (отпуск, командировка): время в карточке не
    # показывается, а в сетке такое занимает всю ячейку.
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tz: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Moscow")
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Ссылка на видеовстречу. Гостевая, а не модераторская: модераторская
    # подписана именем организатора и живёт часы — рассылать её в приглашении
    # значит отдать права ведущего всем, кого позвали.
    conference_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # company | private | personal — тот же словарь, что у поручения: человеку
    # незачем помнить два набора слов для одного и того же вопроса.
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="company")
    # planned | cancelled. Встречу с участниками нельзя удалить — только
    # отменить: она уже стоит в чужих календарях, и молча исчезнувшая встреча
    # означает, что кто-то придёт в пустую переговорную.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    cancel_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Предмет, вокруг которого встреча: `task:<uuid>`, `doc:<uuid>`.
    subject_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # ── Повторение ──────────────────────────────────────────────────────────
    # Серия материализуется вперёд настоящими строками, а не разворачивается на
    # чтении. Так участники, ответы, занятость, отмена и правка одной встречи
    # работают тем же кодом, что у обычной: «изменить эту» — это правка строки, а
    # не машина исключений из серии. Цена — фоновый проход, который у нас и так
    # ходит каждые пять минут ради расписаний поручений.
    #
    # `recurrence` заполнен ТОЛЬКО у головы серии, у порождённых он пуст: иначе
    # каждая порождённая начала бы порождать своё продолжение.
    recurrence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # До какого дня продолжать. Пусто — пока не выключат: планёрка не имеет
    # конца, и требовать его при заведении значит выдумывать дату.
    recurrence_until: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # Голова серии. У самой головы пусто — по этому и отличаем.
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendar_events.id", ondelete="CASCADE"),
        nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_calendar_event_span"),
        Index("ix_calendar_events_span", "company_id", "starts_at", "ends_at"),
    )


class CalendarAttendee(Base):
    """Участник встречи и его ответ.

    Ответов четыре, а не три: «может быть» — настоящий ответ, и без него
    человек ставит «буду» и не приходит, а организатор считает, что кворум есть.

    Смена времени встречи сбрасывает ответы в `pending`: «буду в 10» не равно
    «буду в 18», и молча переносить чужое согласие — значит собрать встречу,
    на которую половина не придёт.
    """
    __tablename__ = "calendar_attendees"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendar_events.id", ondelete="CASCADE"),
        nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # required — без него встречу переносят; optional — зовут для сведения.
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="required")
    # pending | accepted | declined | tentative
    response: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        Index("uq_calendar_attendees", "event_id", "user_id", unique=True),
        Index("ix_calendar_attendees_user", "user_id"),
    )


class PersonalDigest(Base):
    """Сводка «Секретаря» за одно окно доставки.

    Строка отвечает на единственный вопрос: какое сообщение править. Пока окно
    то же, сводка та же — новые поводы дописываются в НЕЁ, а не приходят
    отдельными сообщениями. Иначе личная комната становится свалкой, и
    напоминание в ленте тонет ровно так же, как тонут напоминания в Slack, за
    что их и ругают.

    Почему поводы вообще копятся, а не летят по одному: на 1,27 млн напоминаний
    измерено, что каждый лишний алерт в одной единице внимания снижает принятие
    на 30%, а отклонивший ПЕРВОЕ напоминание серии отклоняет следующие в 88%
    случаев. Гипотезу привыкания там проверяли отдельно и не подтвердили — дело
    в перегрузке. Значит лечится числом сообщений, а не их текстом.

    `slot_at` — момент открытия окна и одновременно ключ: два окна в день
    (начало работы и середина), считаются от рабочего дня человека в его поясе.
    """
    __tablename__ = "personal_digests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    slot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)
    # Сообщение, которое правим. Пропадёт (комнату почистили) — заведём новое:
    # сводка не должна исчезать из-за уборки в чате.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True)
    # Что уже сказано человеку в этом окне: ключи поводов через перевод строки.
    # Хранится, чтобы правка не повторяла сказанное и чтобы «ничего нового» не
    # приводило к переписыванию сообщения.
    said: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_personal_digests_slot", "company_id", "user_id", "slot_at",
              unique=True),
    )


class PersonalList(Base):
    """Именованная подборка человека: «Ремонт офиса», «Прочитать», «Разобрать».

    Не метка и не проект. Метка живёт в общем справочнике компании и меняет сам
    предмет — повесив её на чужой документ, человек поменял его для всех.
    Подборка не трогает предмет ничем: в ней лежит ссылка, видит её только хозяин,
    и положить в неё можно и свою запись, и чужое поручение, и визу.

    Имени достаточно: цвет, иконка и описание — украшения, из-за которых
    заведение списка становится делом, а не движением руки.
    """
    __tablename__ = "personal_lists"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Когда подборку последний раз открывали. Единственный продукт, где «потом» не
    # превращается в кладбище, — тот, где обзор встроен в модель, а не оставлен
    # привычке. По этой отметке считается «не открывали N дней».
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "company_id", "name", name="uq_personal_lists_name"),
    )


class PersonalMark(Base):
    """Как человек разложил у себя предмет пространства.

    Строка на пару «человек — предмет», и в ней три ответа об одном и том же:
    в какой моей подборке лежит (`list_id`), когда я им занимаюсь (`taken_for`,
    `deferred_until`) и важен ли он мне (`starred`). Тремя таблицами это не
    отвечается: подборка ЭКСКЛЮЗИВНА — предмет лежит в одной или ни в одной, —
    а «сегодня» и «важно» стоят поверх и с подборкой не спорят. Так и доска по
    подборкам однозначна: перенос карточки есть перенос, а не загадка
    «переместить или добавить». Кому предмет нужен сразу в двух разрезах, для
    этого есть представления: они собираются правилом и пересекаться вправе.

    Ничего в предмете эта строка не меняет и никому, кроме хозяина, не видна —
    ни администратору пространства, ни постановщику. Наружу видно объективное:
    срок, состояние, просрочка. То, что человек решил заняться этим в четверг,
    не отчётность. И `defer_count` наверх не уходит никогда: увидев его,
    перестают откладывать и начинают закрывать формально.

    Дата, а не отметка «в дне»: ночной проход не нужен — вчерашнее число само
    перестаёт быть сегодняшним.
    """
    __tablename__ = "personal_marks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Предмет: `task:<uuid>`, `doc:<uuid>` — тот же словарь `<вид>:<ключ>`, что
    # у напоминания и у связей документа. Третьего механизма привязки к предмету
    # в пространстве не заводим.
    target_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    list_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personal_lists.id", ondelete="SET NULL"),
        nullable=True)
    # На какой день человек взял предмет. Прошлое число — не «мой день»: взятое
    # вчера и не сделанное приходит утром отдельной строкой, а не тянется само.
    taken_for: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # До какого дня предмет не показывается в раскладке. Личное сокрытие, а не
    # перенос срока: срок предмета общий и остаётся на месте, просрочка идёт по
    # расписанию компании.
    deferred_until: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Сколько раз откладывали. Показывается хозяину и меняет ПРЕДЛОЖЕНИЕ, а не
    # текст: на измеренных данных отклонивший первое напоминание серии отклоняет
    # следующие в 88% случаев, поэтому повторять то же самое бессмысленно.
    defer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Ручной порядок внутри подборки. Живёт только здесь: общий ранг — та самая
    # причина, по которой в чужих трекерах заводят дублирующий личный проект.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "company_id", "target_ref",
                         name="uq_personal_marks_target"),
        Index("ix_personal_marks_day", "user_id", "company_id", "taken_for"),
    )



class TaskView(Base):
    """Сохранённый отбор реестра: «Мои просрочки», «Работа по объекту 208».

    `user_id = NULL` — представление компании, видят все; иначе личное. Общими
    распоряжается администратор: иначе список представлений компании зарастёт
    чужими черновиками.
    """
    __tablename__ = "task_views"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # task | doc — к какому списку относится отбор. Справочник один на оба:
    # в «Деле» человек видит свои представления в одном месте, а не в двух.
    list_scope: Mapped[str] = mapped_column(String(10), nullable=False, default="task")
    # Тот же набор параметров, что в адресе реестра: {"scope","assignee",…}.
    query: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class TaskExternalRef(Base):
    """Зеркало работы во внешней системе — не копия.

    У нас своя задача, у них своя; здесь только связь между ними: чей коннектор,
    какой у работы номер и адрес, в каком она у них состоянии и когда мы это
    видели. Вторую правду о чужой работе не заводим — состояние приходит
    синхронизацией и живёт как отметка, а не как наш статус.

    Владелец коннектора — приложение (Координатор), поэтому здесь его
    идентификатор строкой: реестра коннекторов в Ядре нет и заводить его нельзя.
    """
    __tablename__ = "task_external_refs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Ключ строки витрины подключений: «<приложение>:<id коннектора>».
    connector_key: Mapped[str] = mapped_column(String(120), nullable=False)
    connector_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # out — мы отдали работу наружу; in — их система завела работу у нас.
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="out")
    # Зеркалить ли их закрытие в наш статус. По умолчанию выключено: наше
    # состояние меняет наш человек, а не чужая система.
    mirror_close: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class TaskLabelLink(Base):
    """Метка на задаче."""
    __tablename__ = "task_label_links"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    label_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_labels.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


# ── Аудитор пространства (ecosystem-deploy/docs/AUDITOR.md) ──────────────────
# Настройки живут в БАЗЕ, а не в окружении сервиса: их правит человек в интерфейсе,
# они переживают пересборку образа и попадают в бэкап пространства. В окружении
# остаётся только секрет подписки.

class AuditorSetting(Base):
    """Как аудитор работает в этой компании: чем ему нельзя пользоваться и что помнить."""
    __tablename__ = "auditor_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    # ВЫКЛЮЧЕННЫЕ навыки, а не включённые: каталог растёт с каждым выкатом, и список
    # «что разрешено» пришлось бы дополнять руками, иначе новое умение молча не работало бы.
    disabled_skills: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    # Постоянные указания компании: «НДС по ставке 22 %», «Соболеву не трогать».
    # Едут в системный промпт каждого ответа.
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Режим: careful — только факты; normal — ответ и находки; thorough — ищет сам, шире.
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    model_plan: Mapped[str | None] = mapped_column(String(60), nullable=True)
    model_answer: Mapped[str | None] = mapped_column(String(60), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AuditorRun(Base):
    """След разговора: что спросили, куда смотрел, что нашёл.

    Нужен не для истории чата, а для разбора: почему агент ответил именно так и
    какие навыки при этом сработали. Отсюда же берутся находки, которые стоит
    превратить в требование или задачу.
    """
    __tablename__ = "auditor_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # Экран, с которого спросили: тот же вопрос из разных мест означает разное.
    path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    skills: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    findings: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)
    # ── Оценка человека: вход петли обучения ──
    # ok — ответ верный; wrong — неверный; not_an_issue — находка не ошибка.
    # Последнее ценнее всего: из него рождается правило исключения, и агент перестаёт
    # повторять ложную находку. Пусто = не оценивали, и это не «плохо».
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # Почему. Без объяснения оценка бесполезна: «неверно» без причины нечего исправить.
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    rated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


# ───────────────────────────────────────────────────────────────────────────
# Периметр компании: третий слой — то, чего нет ни в балансе, ни на забалансе
# ───────────────────────────────────────────────────────────────────────────
# Первые два слоя приезжают из бухгалтерии: забалансовые счета (001–012, МЦ.*) и
# имущество, видимое только сопоставлением счетов. Третий слой в учёт не попадает
# вовсе, и источник у него один — человек.
#
# Это устные договорённости с клиентом, обещания «сделаем к сентябрю», решения
# собственника, поручительства без бумаги, чужое имущество, принятое «по-соседски»,
# и претензии, о которых пока никто не написал. Юридической силы у записи нет, но
# деньги и репутация за ней стоят настоящие, и при передаче дел она теряется первой.
#
# Отдельная таблица, а не запись в учёте: смешивать документально подтверждённое с
# записанным со слов нельзя ни в отчёте, ни на экране. У записи всегда видно, чем
# она подтверждена (`confidence`), — от «сказали на встрече» до «есть подпись».
class OffLedgerRecord(Base):
    """Запись периметра: обязательство, право или имущество вне учёта."""

    __tablename__ = "off_ledger_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)

    # Что это: agreement — договорённость, promise — обещание, guarantee — гарантия
    # или поручительство, decision — решение, property — чужое или наше имущество без
    # документа, claim — претензия и спор, other — прочее.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="agreement")
    # Куда смотрит: we_owe — должны мы, owed_to_us — должны нам, property — про вещь,
    # info — просто важно знать. Без этой оси реестр превращается в свалку заметок.
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="we_owe")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"),
        nullable=True)
    # Вторая сторона, которой нет в справочнике: договорённость случается раньше
    # первого документа, и требовать карточку контрагента значило бы не записать её.
    counterparty_name: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Сумма, если её вообще можно назвать. Отсутствие суммы — законное состояние:
    # «починим бесплатно, если сломается» деньгами не меряется до поломки.
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    started_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    due_on: Mapped[date_type | None] = mapped_column(Date, nullable=True, index=True)

    # active — действует, done — исполнено, cancelled — снято, formalized — оформлено
    # документом и ушло в учёт. Последнее и есть цель половины записей: третий слой
    # либо дозревает до первого, либо закрывается.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active",
                                        index=True)
    # Чем подтверждено: spoken — со слов, correspondence — письмо или чат,
    # signed — есть подпись. Цена ошибки у этих трёх разная, и в реестре это видно.
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="spoken")
    # Где зафиксировано: встреча, звонок, письмо, чат, совещание.
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Ссылка на подтверждение: письмо, сообщение, файл. Хранится строкой намеренно —
    # подтверждение живёт в чужой системе, и тащить его копию сюда незачем.
    evidence: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Что будет, если сработает. Записывается словами: «вернём предоплату 300 тыс.».
    consequence: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Забалансовый счёт, на который это встало бы при оформлении (001, 008, 009…).
    # Мост между третьим слоем и первым: по нему видно, что уже пора оформлять.
    account: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── Насколько вероятно, что сработает ──
    # У поручительства на пять миллионов с шансом три процента и у претензии на
    # полмиллиона, которую почти наверняка удовлетворят, одна сумма означает разное.
    # Градация взята из практики условных обязательств (IAS 37): probable — больше
    # половины (это уже кандидат в резерв), possible — возможно, remote — маловероятно.
    likelihood: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Вилка: минимум и максимум, если сумма не одна. `amount` остаётся ожидаемой —
    # той, которую разумно назвать одним числом.
    amount_min: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    amount_max: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_off_ledger_company_status", "company_id", "status"),
    )


# Наличные расчёты вне учёта: четвёртая грань периметра.
#
# У предпринимателя часть расчётов идёт мимо кассы компании: работу частного лица
# оплатили наличными, дали в долг знакомому, вложили свои деньги в закупку, забрали
# выручку на личные нужды. В бухгалтерии этих движений нет, а помнить о них надо —
# особенно кто кому сколько остался должен.
#
# Отдельная сущность, а не вид записи периметра: у денег своя арифметика. Договорённость
# либо действует, либо закрыта; выданный заём гасится частями, и по каждому человеку
# нужно сальдо, а не список фраз. Возврат привязывается к своей выдаче (`parent_id`),
# иначе «отдал 50 из 200» превращается в две несвязанные строки.
class OffLedgerCash(Base):
    """Движение наличных мимо учёта: кому, сколько, за что и что осталось."""

    __tablename__ = "off_ledger_cash"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)

    # out — деньги ушли, in — пришли. Знак операции всегда явный: «минус» в сумме
    # читается двусмысленно, когда речь и о выдаче, и о возврате.
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="out")
    # work — оплата работ и услуг физлицу, loan — заём, repayment — возврат займа,
    # advance — выдача под отчёт (купить оборудование, материалы), report — отчёт по
    # выданному (чеки, накладные), travel — компенсация проезда, bonus — премия,
    # expense — расход на нужды компании, owner — движение с собственником,
    # other — прочее.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="work")
    # Кто вторая сторона: employee — свой сотрудник, individual — частное лицо,
    # owner — собственник, other — прочее. Ось важна не для красоты: выдачи сотруднику
    # бухгалтерия потом проводит документами, а расчёт с частным лицом — нет.
    person_kind: Mapped[str] = mapped_column(String(20), nullable=False,
                                             default="individual")
    happened_on: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    # С кем рассчитались. Имя строкой хранится всегда: операцию записывают на ходу, и
    # требовать карточку значило бы не записать её вовсе. Ссылка проставляется рядом —
    # карточка заводится сама при первом расчёте с человеком.
    person_name: Mapped[str] = mapped_column(String(300), nullable=False)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("off_ledger_people.id", ondelete="SET NULL"),
        nullable=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"),
        nullable=True)
    # За что: «монтаж стеллажей на складе», «в долг до зарплаты».
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Чем подтверждено: none — ничем, receipt — расписка, contract — договор ГПХ,
    # act — акт или наряд. Для займа расписка это единственное, чем он доказуем.
    proof: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    # Чьи деньги: owner — личные средства собственника, company — наличные компании.
    # Без этой оси нельзя ответить, сколько собственник вложил своего.
    purse: Mapped[str] = mapped_column(String(20), nullable=False, default="owner")

    # Возврат ссылается на свою выдачу: остаток долга считается по цепочке, а не
    # вычитанием всех возвратов человека из всех его займов.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("off_ledger_cash.id", ondelete="SET NULL"),
        nullable=True)
    # Связь с договорённостью периметра: заём часто сначала обещание, потом деньги.
    record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("off_ledger_records.id", ondelete="SET NULL"),
        nullable=True)
    # Каким регулярным обязательством вызвана выплата: ежемесячная доплата водителю,
    # компенсация аренды. По этой ссылке считается, за какие периоды уже рассчитались.
    commitment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("off_ledger_commitments.id", ondelete="SET NULL"),
        nullable=True)
    # За КАКОЙ период платим (первый день периода). Хранится у операции, а не выводится
    # из даты: доплату за август выдают в сентябре. Без этого поля правка операции
    # пересчитывала период заново и заводила вторую отметку.
    commitment_period: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # Срок возврата — у займов и выдач под отчёт.
    due_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # ── Исковая давность ──
    # Три года считаются не от выдачи: срок ПРЕРЫВАЕТСЯ действием должника, из которого
    # видно, что он долг признаёт, — частичной оплатой, подписанным актом сверки,
    # просьбой об отсрочке (ст. 203 ГК). После перерыва срок течёт заново, и прошедшее
    # время не засчитывается. Поэтому храним последнее такое действие, а не считаем от
    # даты займа: иначе продукт объявит долг сгоревшим, когда он живой.
    acknowledged_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # Чем признан: оплата, акт сверки, переписка.
    acknowledged_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Почему списали долг: forgiven — простили, hopeless — взыскать не с кого,
    # expired — истёк срок давности. Долг не исчезает бесследно: он меняет природу и
    # по правилам учёта уходит на забалансовый счёт 007 ещё на пять лет.
    writeoff_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Мост в бухгалтерию ──
    # Часть этих движений учёт всё-таки принимает: выданное под отчёт закрывается
    # авансовым отчётом, премия проводится ведомостью, компенсация проезда — приказом
    # и чеками. Пока документы не сделаны, операция живёт только здесь, и главное для
    # владельца — видеть, что ждёт оформления, а что уже проведено.
    formalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    formalized_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # Чем оформлено: «авансовый отчёт № 12 от 14.08», «ведомость за август».
    formalized_by: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_off_cash_company_date", "company_id", "happened_on"),
        Index("idx_off_cash_person", "company_id", "person_name"),
    )


# Люди периметра: с кем компания имеет дело помимо штата и договоров.
#
# Это НЕ зарплатный контур и не справочник контрагентов. Здесь монтажник, который
# приезжает на разовые работы; водитель, возящий товар за наличные; сотрудник, которому
# выдают под отчёт; знакомый, взявший в долг; представитель поставщика, с которым
# договорились устно. Часть из них есть в штате, часть — в справочнике контрагентов
# (`counterparty_id`), часть не заведена нигде, и именно ради последних список
# существует: через полгода «Сергей с гидравликой» не восстанавливается ничем.
#
# Карточка заводится САМА при первом расчёте: заставлять человека сначала завести
# карточку, а потом записать выдачу, значит получить журнал без карточек.
class OffLedgerPerson(Base):
    """Человек или представитель, участвующий в расчётах и договорённостях."""

    __tablename__ = "off_ledger_people"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # employee — свой сотрудник, individual — частное лицо, owner — собственник,
    # contractor_rep — представитель контрагента, other — прочее.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="individual")
    # Кем приходится делу: «монтажник», «водитель», «прораб у подрядчика».
    role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Из персональных данных держим только телефон — по правилу пространства.
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Как вернуть деньги этому человеку: телефон для перевода, банк, любой другой
    # способ словами. Долг зафиксирован, а действие «верни» упирается в поиск
    # реквизитов по переписке — поэтому они лежат там же, где сальдо.
    payout_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payout_bank: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payout_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Если человек представляет компанию из справочника.
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"),
        nullable=True)
    # Ссылка на учётную запись пространства — если это наш человек и он здесь работает.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ушедших не удаляют: за ними остаётся история расчётов. Их скрывают из подсказок.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_off_person_name", "company_id", "name", unique=True),
    )


# Регулярные обязательства перед людьми.
#
# Отличаются от разовой договорённости тем, что повторяются: доплата водителю каждый
# месяц, компенсация аренды жилья мастеру, обед бригаде по пятницам, обучение раз в
# квартал. Разовую запись закрывают один раз, регулярную — каждый период, и вопрос к
# ней другой: за какой период рассчитались, а какой пропустили.
#
# Форма исполнения не обязана быть денежной. Часть обязательств выполняется деньгами
# (тогда исполнение это операция журнала наличных), часть — действием, часть — вещами.
# Поэтому форма хранится отдельным полем, а сумма может отсутствовать.
class OffLedgerCommitment(Base):
    """Обязательство, которое надо выполнять с некоторой периодичностью."""

    __tablename__ = "off_ledger_commitments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True)

    # Перед кем. Имя строкой всегда, ссылка на карточку — рядом (заводится сама).
    person_name: Mapped[str] = mapped_column(String(300), nullable=False)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("off_ledger_people.id", ondelete="SET NULL"),
        nullable=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    # money — выплата, service — работа или услуга с нашей стороны, goods — передача
    # вещей, other — прочее. Не всё меряется деньгами, и подставлять ноль нельзя.
    form: Mapped[str] = mapped_column(String(20), nullable=False, default="money")
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    # month по умолчанию: месяц — естественный шаг таких договорённостей.
    periodicity: Mapped[str] = mapped_column(String(20), nullable=False, default="month")
    # День месяца (или день недели для недельной периодичности), к которому ждут
    # исполнения. Пусто — «в течение периода», без точной даты.
    due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_on: Mapped[date_type] = mapped_column(Date, nullable=False)
    # Бессрочное обязательство — обычный случай: «пока работает у нас».
    ends_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)

    # active — действует, paused — приостановлено, ended — прекращено.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active",
                                        index=True)
    # Когда приостановили. Без этой даты пауза не защищает от пропусков: исключать
    # можно только текущий период, и через месяц пауза выглядит как забывчивость.
    paused_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # Чем подтверждено — те же три ступени, что у договорённостей.
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="spoken")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_off_commitment_company_status", "company_id", "status"),
    )


class OffLedgerCommitmentMark(Base):
    """Отметка исполнения обязательства за период.

    Одна таблица на все формы исполнения намеренно: иначе «когда в последний раз
    выполняли» пришлось бы собирать из двух источников и сверять между собой. Денежное
    исполнение дополнительно ссылается на операцию журнала наличных — сумма живёт там,
    здесь только факт закрытия периода.
    """

    __tablename__ = "off_ledger_commitment_marks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("off_ledger_commitments.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Первый день закрываемого периода: по нему период и опознаётся. Хранить «август
    # 2026» строкой значило бы разбирать её при каждом сравнении.
    period_start: Mapped[date_type] = mapped_column(Date, nullable=False)
    done_on: Mapped[date_type] = mapped_column(Date, nullable=False)
    # done — выполнено, skipped — период пропущен сознательно (договорились, что в этом
    # месяце не надо). Пропуск отмечают явно, иначе он неотличим от забытого.
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="done")
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    cash_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("off_ledger_cash.id", ondelete="SET NULL"),
        nullable=True)
    # Кто поставил отметку: cash — журнал наличных, manual — человек руками.
    # Отдельным полем, а не по наличию `cash_id`: у ссылки ON DELETE SET NULL, и при
    # удалении ошибочной выплаты признак исчезал вместе с ней — период оставался
    # зелёным без единой копейки за ним. По тексту заметки его тоже не опознать:
    # заметку правят.
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Один период закрывается один раз: две отметки за август означают, что
        # обязательство выполнили дважды, а на деле кто-то не увидел чужую отметку.
        Index("uq_off_mark_period", "commitment_id", "period_start", unique=True),
    )


class PulseView(Base):
    """Витрина «Пульса»: что и кому показываем наружу.

    «Пульс» отвечает на вопрос своего руководителя. Витрина — тот же продукт,
    повёрнутый наружу: заказчику, владельцу сети, куратору со стороны холдинга нужна
    проверенная информация по своей теме без погружения в приложения.

    Витрина — это ПОДАЧА готовых разрезов, а не новый источник правды: блоки берутся
    из каталога `PULSE_ITEMS`, и второго набора метрик мы не заводим. Если цифра
    неверна — чинится источник, а не витрина.

    Почему не роль с правами на разделы: права отвечают «что открыто», витрина — «что
    показать и в каком порядке». Категорий получателей много, состав меняется от
    разговора к разговору, и менять его нужно за минуту — а права это медленный контур
    с журналом и последствиями. Плюс витрина несёт обязательства: подпись
    ответственного и дату актуальности, которых право не несёт.
    """

    __tablename__ = "pulse_views"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Для кого — словами человека, а не кодом роли: «Куратор со стороны РусГидро».
    # Категорий получателей больше, чем ролей, и заводить роль под каждую значило бы
    # плодить права, которые никому не дают доступа к работе.
    audience: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Юрлицо, о котором витрина. Пусто — вся компания; заданное — только его
    # данные. В пространстве аутсорсера без этого заказчику показывались бы
    # сводные цифры всех клиентов, и то же уходило бы по публичной ссылке.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    period: Mapped[str] = mapped_column(String(20), nullable=False, default="month")
    # Кто отвечает за цифры. Витрина уходит наружу, и «данные из системы» там не ответ:
    # у показанного числа должен быть человек.
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # draft — собирается, published — видна получателям.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Куда уходит обратная связь: task — задача (не потеряется), chat — сообщение
    # в комнату (скорость), both — и то и другое, none — витрина только показывает.
    # Своего ящика обращений витрина не заводит: ответ получателя должен попасть
    # туда, где с ним работают.
    feedback_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="task")
    feedback_room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    feedback_assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_pulse_views_company", "company_id", "status"),
    )


class PulseViewBlock(Base):
    """Блок витрины: разрез «Пульса» под своим заголовком.

    Заголовок «своими словами» обязателен по смыслу: на витрине заказчика «Продажи»
    называются «Отпуск энергии», и переименование здесь дешевле, чем объяснение
    на встрече, почему в системе это называется иначе.
    """

    __tablename__ = "pulse_view_blocks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    view_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pulse_views.id", ondelete="CASCADE"), nullable=False
    )
    block_key: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PulseViewGrant(Base):
    """Кому назначена витрина.

    Внешний получатель входит в пространство участником с одной этой витриной и без
    рабочих мест. Права на данные при этом продолжают действовать: витрина не может
    показать то, чего человеку не положено видеть по скоупу объектов и юрлицу.
    """

    __tablename__ = "pulse_view_grants"

    view_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pulse_views.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


# Настройки «Периметра» на компанию.
#
# Продукт закрывает разные по чувствительности вещи: арендованный склад на 001 — обычный
# учёт, а доплата сверх ведомости — то, за что отвечают лично. Поэтому спорные
# возможности не включены по умолчанию: компания включает их сама, видя предупреждение,
# и решение остаётся зафиксированным — кем и когда.
#
# Пороговые значения тоже здесь, а не в коде: лимит наличных расчётов и срок отчёта по
# подотчёту компания устанавливает сама (для подотчёта это прямо предписано Указанием
# ЦБ 3210-У), и зашитая константа была бы чужим решением.
class OffLedgerSettings(Base):
    """Что включено в «Периметре» у этой компании."""

    __tablename__ = "off_ledger_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        primary_key=True)

    # Доплаты сверх ведомости — выплаты работникам из средств собственника помимо
    # расчётного листка. Выключено по умолчанию: у компании, которая так не работает,
    # этого вида в списке быть не должно.
    allow_extra_pay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Через сколько дней подотчётное лицо обязано отчитаться. Срок устанавливает
    # работодатель; невозвращённое и неотчитанное налоговая признаёт доходом.
    advance_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Предел наличных расчётов по одному договору между организациями и ИП.
    cash_limit: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False,
                                              default=100000)
    # Порог, выше которого заём между гражданами требует письменной формы.
    loan_written_from: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False,
                                                     default=10000)
    # Порог, выше которого заём по умолчанию считается процентным.
    loan_interest_from: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False,
                                                      default=100000)
    # Срок исковой давности в годах — общий, но у отдельных требований свой.
    limitation_years: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # Показывать в выгрузках и на экранах оговорку о статусе данных.
    show_disclaimer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# Заказчик не заведёт пароль ради одного экрана, а показать ему картину нужно.
# Ссылка решает это, но она же и самый опасный элемент концепции: по ней уходят
# финансовые данные компании. Поэтому у неё есть всё, чего нет у «просто ссылки»:
# срок жизни, отзыв, счётчик открытий и журнал последнего входа. Ссылка отдаёт
# ТОЛЬКО опубликованную витрину и только на чтение — ни обращений, ни ответов по
# требованиям с неё нет: писать может тот, кто вошёл под собой.


class PulseViewLink(Base):
    """Ссылка на витрину без учётки."""

    __tablename__ = "pulse_view_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    view_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pulse_views.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Без срока ссылка живёт вечно, а вечная ссылка на финансы — это утечка,
    # отложенная во времени.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opened_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Разбор недели: отметка о том, что периметр просмотрели.
#
# Реестры такого рода умирают не от нехватки возможностей, а от нерегулярности: записи
# заводят неделю, потом бросают, и через полгода им не верят. Ежедневная дисциплина
# здесь не работает — событий мало; ежемесячная приходит поздно. Рабочий ритм —
# короткий еженедельный просмотр: что записано, что просрочено, что до сих пор держится
# на словах.
#
# Отметка о разборе нужна не для отчётности перед кем-то, а как след регулярности: у
# компании есть доказательство, что контроль вёлся, а не «кто-то что-то писал». Поэтому
# в ней сохраняется снимок счётчиков на момент разбора — иначе через год не отличить
# «разобрали пустую неделю» от «разобрали неделю с семью просрочками».
class OffLedgerReview(Base):
    """Отметка о разборе периметра за неделю."""

    __tablename__ = "off_ledger_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Понедельник разбираемой недели: по нему неделя и опознаётся.
    week_start: Mapped[date_type] = mapped_column(Date, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Что было на момент разбора: сколько записано, сколько просрочено, сколько ждёт
    # оформления. Снимок, а не пересчёт задним числом.
    snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Неделя разбирается один раз: повторная отметка исправляет прежнюю.
        Index("uq_off_review_week", "company_id", "week_start", unique=True),
    )


# Напоминание — запись, а не рассылка.
#
# Для просроченной устной договорённости важнее не сумма, а то, сколько раз о ней
# напоминали и что отвечали. Фоновая рассылка этого не даёт: она не знает, дошло ли и
# что сказали в ответ. Поэтому напоминание фиксируется человеком как факт разговора —
# с каналом, текстом и результатом.
class OffLedgerReminder(Base):
    """Напоминание о долге или договорённости: когда, как и с каким результатом."""

    __tablename__ = "off_ledger_reminders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # О чём напоминали: операция журнала, договорённость или обязательство. Ровно одна
    # из ссылок заполнена — напоминание всегда о чём-то конкретном.
    cash_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("off_ledger_cash.id", ondelete="CASCADE"),
        nullable=True)
    record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("off_ledger_records.id", ondelete="CASCADE"),
        nullable=True)
    commitment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("off_ledger_commitments.id", ondelete="CASCADE"),
        nullable=True)
    person_name: Mapped[str] = mapped_column(String(300), nullable=False)
    happened_on: Mapped[date_type] = mapped_column(Date, nullable=False)
    # Как напомнили: разговор, звонок, письмо, чат, сообщение.
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="talk")
    # Чем закончилось: promised — обещал, refused — отказал, silent — молчит,
    # paid — сразу рассчитался.
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="promised")
    # Что обещал: дата, к которой вернёт. Отсюда растёт следующее напоминание.
    promised_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_off_reminder_company", "company_id", "happened_on"),
    )


# ---------------------------------------------------------------------------
# «Дело» — документооборот пространства
#
# Документ здесь самостоятельный объект с реквизитами и регистрационным номером,
# а не вложение задачи. Причина простая: реестр входящих за квартал, отбор по
# корреспонденту и срок хранения из файла, приложенного к поручению, не строятся.
# Поручение по документу ставится существующими «Задачами» — второй движок работы
# заводить незачем.
#
# Все таблицы с префиксом `doc_`: рядом со схемой `core` в той же базе живёт
# `public` контура Поддержки, и совпадающее имя молча резолвится в чужую схему
# (на этом уже спотыкались — отсюда `org_departments` и `space_inbound_keys`).
# Поле называется `doc_id`, а не `document_id`: последнее в системе означает
# идентификатор канонического факта товарного контура.
# ---------------------------------------------------------------------------
class DocKind(Base):
    """Вид документа компании: приказ, входящее письмо, договор.

    Вид несёт правило нумерации и схему предметных реквизитов. Маршрут
    согласования появится здесь же второй волной, поэтому справочник заведён
    сразу отдельной таблицей, а не набором констант в коде.
    """
    __tablename__ = "doc_kinds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ord (приказы и распоряжения) | incoming | outgoing | internal | contract | other
    family: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    # in | out | none — по нему делится реестр корреспонденции.
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    # Шаблон номера: «{prefix}-{yyyy}-{n:04d}». Переменные подставляет
    # services/doc_numbers.py; str.format по строке от пользователя не применяем.
    number_template: Mapped[str] = mapped_column(
        String(80), nullable=False, default="{prefix}-{yyyy}-{n:04d}")
    # Область непрерывной нумерации: kind | kind_year | kind_org | kind_org_year.
    #
    # По умолчанию — год без юрлица, в пару к шаблону выше. Раньше здесь стоял
    # `kind_org_year`, и дефолты спорили друг с другом: счётчик отдельный по
    # юрлицу, а признака юрлица в номере нет. Правило вида такое сочетание
    # запрещает, и вид, заведённый посевом, нельзя было сохранить через форму —
    # 400 на каждой правке. Кому нужен журнал по юрлицу, включает область и
    # добавляет `{org}` в шаблон; отказ прямо об этом говорит.
    number_scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="kind_year")
    number_prefix: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # Схема предметных реквизитов вида: [{code,label,type,options,required}].
    # У приказа это гриф и основание, у входящего — способ доставки. Заводить под
    # каждый вид свою таблицу незачем: в реестр эти поля не попадают.
    fields: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Маршрут согласования: [{code,name,mode,quorum,sla_hours,actors:[{by,ref}]}].
    # Своё поле, а не маршрут задачи: тот сознательно линеен, а виза бывает
    # параллельной, и стадия задачи такого состояния не выражает.
    route: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Дело, в которое ложится документ этого вида по умолчанию.
    default_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cases.id", ondelete="SET NULL"), nullable=True)
    # Каким типом задачи ставится поручение по документу: резолюция живёт в
    # «Задачах» со своим сроком, эскалацией и почтой.
    errand_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_types.id", ondelete="SET NULL"), nullable=True)
    requires_registration: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Какой пункт чек-листа проекта закрывает согласованный документ этого вида
    # (`contract`, `tp_contract`, `project`, `act` — ключи `ezs_checklist`).
    #
    # Связь данными, а не кодом: какой именно вид считается «договором аренды
    # ЗУ», решает делопроизводство компании, и зашивать это в наш перечень
    # значило бы требовать релиз ради переименования вида. Пусто — вид гейтов
    # не касается, это обычное состояние для большинства.
    gate_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_doc_kinds_code"),
    )


class DocCard(Base):
    """Карточка документа: то, что регистрируют, ищут и хранят.

    Реквизиты корреспонденции (корреспондент, направление, их исходящий номер)
    вынесены в колонки, а не в JSONB: по ним строится реестр и отбор, а по
    содержимому JSONB отбор пришлось бы делать перебором.
    """
    __tablename__ = "doc_cards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    kind_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_kinds.id", ondelete="RESTRICT"), nullable=False)
    # Копия кода вида: реестр рисуется без соединения со справочником.
    kind_code: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    family: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # draft | registered | in_force | executed | archived | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    reg_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reg_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # Случайный публичный код проверки записи. UUID карточки наружу не отдаём:
    # он внутренний идентификатор, а не capability-токен.
    verify_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Номер введён руками только при переносе нашего прежнего бумажного журнала.
    # Чужой исходящий номер хранится отдельно в external_number.
    number_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Наше юрлицо: ось нумерации и шапка печатной формы.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True)
    # Имя корреспондента строкой — как в реестре первички: письмо приходит и от
    # того, кого в справочнике ещё нет, и терять отправителя из-за этого нельзя.
    counterparty_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    external_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)

    # Предмет документа в чужой модели: `contract:<uuid>`, `article:<uuid>`.
    # Реквизиты договора остаются в `contracts`, здесь только делопроизводство.
    subject_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Ключ объекта сети строковый (`ezs-…`, `rh-…`), а не UUID: три четверти парка
    # достались от первой загрузки, и переприсваивать ключи нельзя.
    object_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="SET NULL"),
        nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_departments.id", ondelete="SET NULL"),
        nullable=True)

    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    responsible_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    signatory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # company | private. Закрытую карточку дополнительно открывают правила
    # doc_access_grants и назначение на визу/ознакомление.
    confidentiality: Mapped[str] = mapped_column(String(20), nullable=False, default="company")
    inherit_kind_acl: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"))
    acl_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"))
    attrs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Откуда документ появился: manual | intake | mail | chat | edo | api.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_files: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cases.id", ondelete="SET NULL"), nullable=True)
    # Хранить до этой даты. Считается при регистрации и потом не пересчитывается:
    # правка справочника сроков не должна задним числом списывать старые документы.
    storage_until: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    retention_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="working", server_default=text("'working'"))
    retention_class: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unclassified",
        server_default=text("'unclassified'"))
    retention_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retention_extended_until: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    archive_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    archive_accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(
            "users.id", ondelete="SET NULL", name="fk_doc_cards_archive_accepted_by"),
        nullable=True)
    primary_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    destroyed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Идёт ли по документу согласование прямо сейчас: none | pending | approved | rejected.
    approval_status: Mapped[str] = mapped_column(String(15), nullable=False, default="none")
    approval_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # У каждого юрлица свой журнал. NULL сводим к одному значению, чтобы у
        # карточек без юрлица номер тоже оставался уникальным.
        Index("uq_doc_cards_reg_number", "company_id",
              text("COALESCE(organization_id, "
                   "'00000000-0000-0000-0000-000000000000'::uuid)"),
              "reg_number", unique=True,
              postgresql_where=text("reg_number IS NOT NULL")),
        Index("uq_doc_cards_verify_token", "verify_token", unique=True,
              postgresql_where=text("verify_token IS NOT NULL")),
        # Две карточки на один договор — это две правды о нём.
        Index("uq_doc_cards_subject", "company_id", "subject_ref",
              unique=True, postgresql_where=text("subject_ref IS NOT NULL")),
        Index("uq_doc_cards_mail_source", "company_id", "source_ref", unique=True,
              postgresql_where=text(
                  "source = 'mail' AND source_ref IS NOT NULL")),
        Index("idx_doc_cards_registry", "company_id", "family", "reg_date"),
        Index("idx_doc_cards_counterparty", "company_id", "counterparty_id"),
        Index("idx_doc_cards_retention", "company_id", "retention_state",
              "storage_until", "id"),
        CheckConstraint(
            "family IN ('ord','incoming','outgoing','internal','contract','other')",
            name="ck_doc_cards_family"),
        CheckConstraint(
            "status IN ('draft','registered','in_force','executed','archived','cancelled')",
            name="ck_doc_cards_status"),
        CheckConstraint(
            "retention_state IN ('working','archive_pending','archived','legacy_review',"
            "'under_expertise','permanent','destruction_ready','destruction_authorized',"
            "'primary_purged','destroyed')",
            name="ck_doc_cards_retention_state"),
        CheckConstraint(
            "retention_class IN ('temporary','epk','permanent','unclassified')",
            name="ck_doc_cards_retention_class"),
        CheckConstraint("acl_revision >= 0", name="ck_doc_cards_acl_revision"),
    )


class DocVersion(Base):
    """Файл документа и его редакция.

    Дисциплина повторяет `StoreDocFile`: содержимое опознаётся хешем, замена
    оформляется новой редакцией со ссылкой на предшественника, удаление — только
    отметкой с обязательной причиной. Спор «какую редакцию согласовали» иначе не
    разрешить.
    """
    __tablename__ = "doc_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"),
        nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # body (сам документ) | appendix | signed_scan | attachment
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="body")
    # Ссылка на общее хранилище файлов. Внешнего ключа нет по той же причине, что
    # в `StoreDocFile`: файл живёт дольше карточки и переживает её пересборку.
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_versions.id", ondelete="RESTRICT"), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    tombstoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    tombstoned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    tombstone_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    archive_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    purge_result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    destruction_act_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(
            "doc_destruction_acts.id", ondelete="SET NULL",
            name="fk_doc_versions_destruction_act"),
        nullable=True)
    # Текст файла для полнотекстового поиска. Для сканов его даёт OCR, для
    # текстовых и офисных форматов — извлечение без распознавания.
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("doc_id", "revision", "role", "sha256",
                         name="uq_doc_versions_content"),
        Index("uq_doc_versions_current_role", "doc_id", "role", unique=True,
              postgresql_where=text(
                  "is_current = true AND tombstoned_at IS NULL")),
        Index("idx_doc_versions_live", "company_id", "doc_id", "tombstoned_at"),
        Index("idx_doc_versions_destruction_act", "destruction_act_id"),
        Index("idx_doc_versions_text",
              text("to_tsvector('russian', coalesce(content_text, ''))"),
              postgresql_using="gin"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_doc_versions_sha256"),
        CheckConstraint("revision > 0", name="ck_doc_versions_revision"),
    )


class DocEvent(Base):
    """След карточки: кто, когда и что сделал с документом.

    Форма повторяет ленту задачи, включая имя автора без учётки: письмо от
    контрагента должно ложиться в след с его подписью, а не «от системы».
    """
    __tablename__ = "doc_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # created | registered | version | status | field | approval | sign |
    # dispatch | comment | errand | relation | mail
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="comment")
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # user | partner | agent | system. Действие машины должно быть видно как
    # машинное: подпись «Аудитор Поддержки» без этого читается как имя человека,
    # и разбор «кто это решил» упирается в справочник сотрудников.
    actor_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user")
    from_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class DocRelation(Base):
    """Связь документа с чем угодно в пространстве.

    Адресат хранится строкой (`task:<uuid>`, `doc:<uuid>`, `contract:<uuid>`):
    контуров много, и внешний ключ на каждый означал бы правку таблицы при
    появлении следующего. Для связи документа с документом ключ всё же есть — по
    нему идёт соединение в карточке.
    """
    __tablename__ = "doc_relations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # reply_to | annex_of | amends | cancels | basis | errand | related
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="related")
    target_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    target_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="SET NULL"), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "doc_id", "kind", "target_ref",
                         name="uq_doc_relations"),
        # Обратный вопрос «по какому документу эта задача» задают не реже прямого.
        Index("idx_doc_relations_target", "company_id", "target_ref"),
    )


class DocCounter(Base):
    """Счётчик регистрационных номеров.

    Транзакционный, а не последовательность базы: последовательность не
    откатывается, и отменённая регистрация оставила бы дыру в журнале. Дыру
    первым делом спрашивает проверяющий, поэтому цена в виде сериализации
    регистраций одного вида здесь оправдана.
    """
    __tablename__ = "doc_counters"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        primary_key=True)
    # <код вида>|<юрлицо или «-»>|<год или «-»>
    scope_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True)


class DocCase(Base):
    """Дело номенклатуры: куда документ ложится и сколько там хранится.

    Срок хранения берётся отсюда один раз, при регистрации, и дальше живёт в самой
    карточке. Считать его на лету нельзя: правка справочника задним числом сделала
    бы вчерашние документы подлежащими уничтожению.
    """
    __tablename__ = "doc_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    # Индекс дела по номенклатуре: «01-15», «02-03».
    index: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # Срок словами, как в перечне: «5 лет», «75 лет ЭПК», «Постоянно».
    storage_term: Mapped[str] = mapped_column(String(60), nullable=False, default="5 лет")
    # Он же числом для расчёта. NULL — хранение постоянное, срок не наступает.
    storage_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    epk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retention_basis: Mapped[str | None] = mapped_column(String(300), nullable=True)
    retention_class: Mapped[str] = mapped_column(
        String(20), nullable=False, default="temporary",
        server_default=text("'temporary'"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_departments.id", ondelete="SET NULL"), nullable=True)
    # open | closed — закрытое дело новых документов не принимает.
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    # Переходящее дело: начато в одном году, продолжается в следующем. По
    # Перечню Росархива такие дела существуют (длящиеся договоры, переписка по
    # одному вопросу), и запрет «год дела равен году регистрации» их просто
    # запрещал: в январе делопроизводитель упирался в отказ и заводил дубль.
    carry_over: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "uq_doc_cases_index",
            "company_id",
            text("COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "year",
            "index",
            unique=True,
        ),
        CheckConstraint(
            "retention_class IN ('temporary','epk','permanent','unclassified')",
            name="ck_doc_cases_retention_class"),
    )


class DocApproval(Base):
    """Виза: кто согласует шаг маршрута и чем это кончилось.

    Отдельная строка на каждого согласующего, потому что параллельное визирование
    это несколько одновременных состояний одного документа, а не одна стадия.
    Исполнитель фиксируется снимком при запуске: человек может уйти из отдела, а
    виза должна остаться на нём, а не исчезнуть вместе с его должностью.
    """
    __tablename__ = "doc_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Круг согласования. После правки по замечанию открывается следующий, прошлые
    # остаются: лист согласования показывает всю историю, а не последнее состояние.
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    step_code: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    step_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # serial (шаг за шагом) | parallel (все визируют одновременно)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="serial")
    # all | any | число — сколько виз нужно, чтобы шаг считался пройденным.
    quorum: Mapped[str] = mapped_column(String(10), nullable=False, default="all")
    # user | role | department | head_of | position — из чего резолвился человек.
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    actor_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # waiting | pending | approved | rejected | skipped. Будущие шаги ждут:
    # иначе последовательный маршрут фактически становится параллельным.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # SLA хранится отдельно от срока: due_at появляется только при активации
    # шага, поэтому время будущих шагов не уходит, пока документ до них не дошёл.
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    activation_estimated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"))
    # Доказательство того, что именно согласовывали: реквизиты карточки и точный
    # набор текущих файлов с их SHA-256. Снимок дублируется в строках круга,
    # чтобы история оставалась самодостаточной без отдельной сущности процесса.
    document_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    snapshot_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # При отказе обязателен: возврат без причины бессмыслен, автор не поймёт, что править.
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Напоминание о визе. Разделено на «отправлено» и «пробовали отправить», как у
    # ознакомления: почта падает, и без второй отметки прогон долбил бы мёртвый
    # ящик каждую минуту, а без первой — молчал бы, решив, что уже написал.
    reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    reminder_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    reminder_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("doc_id", "round", "step_no", "assignee_id",
                         name="uq_doc_approvals_actor"),
        # Экран «на мне»: одним индексом отвечает на главный вопрос согласующего.
        Index("idx_doc_approvals_mine", "company_id", "assignee_id", "status"),
        Index("idx_doc_approvals_report", "company_id", "round", "created_at", "doc_id"),
        Index("idx_doc_approvals_pending_due", "company_id", "due_at",
              postgresql_where=text("status = 'pending'")),
    )


class DocSignatureEvidence(Base):
    __tablename__ = "doc_signature_evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"),
        nullable=False, index=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_approvals.id", ondelete="RESTRICT"), nullable=True)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    signer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    signer_name: Mapped[str] = mapped_column(String(300), nullable=False)
    represented_signer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    snapshot_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    document_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="verified")
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    verification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("approval_id", name="uq_doc_signature_evidence_approval"),
        CheckConstraint(
            "method IN ('internal_approval','internal_direct','qualified_external')",
            name="ck_doc_signature_evidence_method"),
        CheckConstraint(
            "verification_status IN ('pending','verified','failed','revoked')",
            name="ck_doc_signature_evidence_status"),
        Index("idx_doc_signature_evidence_company_doc",
              "company_id", "doc_id", "signed_at"),
    )


class DocShareLink(Base):
    """Показ документа контрагенту по ссылке, без учётки в пространстве.

    Срок обязателен: вечная ссылка на документ это утечка, отложенная во времени.
    Подтверждение получения хранится вместе с текстом, который человеку показали:
    через два года вопрос будет «с чем именно он согласился», и наш пересказ на
    него не отвечает.

    Юридический предел назван прямо: это простая электронная подпись, и она
    работает, только если порядок её использования согласован сторонами в
    договоре. Без такой оговорки запись остаётся счётчиком открытий.
    """
    __tablename__ = "doc_share_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Токен в базе НЕ хранится: дамп таблицы означал бы рабочие ссылки на все
    # непросроченные документы. Хранится его SHA-256 (по нему идёт поиск) и
    # первые символы — чтобы человек узнал свою ссылку в списке, не имея её
    # целиком. Полную ссылку показываем один раз, при выпуске.
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    token_prefix: Mapped[str | None] = mapped_column(String(12), nullable=True)
    # Колонка прежнего открытого токена: остаётся до конца перехода, чтобы уже
    # выданные ссылки продолжали работать, и очищается бэкфиллом после того, как
    # хеши проставлены.
    token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    # Зачем выдана ссылка: `view` — показать документ, `approve` — дать право
    # поставить одну визу. Право именно на активность, а не на документ: внешний
    # человек не получает ни учётки, ни членства в компании, ни доступа к
    # остальному — только к тому шагу, ради которого его позвали.
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="view")
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_approvals.id", ondelete="CASCADE"), nullable=True)
    # Момент, когда правом воспользовались. Виза ставится один раз, и ссылка
    # после этого мертва: одноразовость здесь не украшение, а условие того, что
    # пересланная кому-то ссылка не превращается во вторую подпись.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recipient_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opened_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(String(60), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    acknowledged_by_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Редакции, которые были показаны при выпуске ссылки. Без снимка замена файла
    # задним числом меняет содержание уже подтверждённого получения.
    version_snapshot: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    card_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Снимок момента подтверждения: адрес, время и ДОСЛОВНЫЙ текст согласия.
    ack_evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


# ── ниже: связь метки с документом ──────────────────────────────────────────


class DocLabelLink(Base):
    """Метка на документе.

    Справочник меток общий с поручениями (`task_labels`): в одном продукте
    человек не должен видеть два разных списка меток. Здесь только связь.
    """
    __tablename__ = "doc_label_links"

    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"),
        primary_key=True)
    label_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_labels.id", ondelete="CASCADE"),
        primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class DocAccessGrant(Base):
    """Права уровня записи: документ или вид × субъект × действия.

    `scope_id` и `subject_id` намеренно полиморфны: областью бывает карточка или
    вид, субъектом — человек, роль или подразделение. Их принадлежность компании
    проверяет сервис при записи, а одна таблица не плодит три параллельных
    механизма доступа.
    """
    __tablename__ = "doc_access_grants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # doc | kind
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # user | role | department
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # read | edit | approve | sign | download | print | export | send |
    # manage_acl | archive. Запреты на унаследованные действия лежат отдельно:
    # отсутствие разрешения не должно означать явный deny.
    permissions: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    denied_permissions: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "scope_type", "scope_id", "subject_type",
                         "subject_id", name="uq_doc_access_grant"),
        Index("idx_doc_access_scope", "company_id", "scope_type", "scope_id"),
        CheckConstraint("scope_type IN ('doc','kind')", name="ck_doc_access_scope"),
        CheckConstraint("subject_type IN ('user','role','department')",
                        name="ck_doc_access_subject"),
    )


class DocLegalHold(Base):
    __tablename__ = "doc_legal_holds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"), nullable=False)
    authority: Mapped[str] = mapped_column(String(300), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    placed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    released_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_doc_legal_holds_active", "company_id", "doc_id", "placed_at",
              postgresql_where=text("released_at IS NULL")),
        Index("idx_doc_legal_holds_doc", "doc_id", "placed_at"),
        CheckConstraint(
            "released_at IS NULL OR release_reason IS NOT NULL",
            name="ck_doc_legal_holds_release_reason"),
    )


class DocRetentionDecision(Base):
    __tablename__ = "doc_retention_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    epk_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    new_storage_until: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_doc_retention_decisions_doc", "company_id", "doc_id", "created_at"),
        CheckConstraint(
            "decision IN ('destroy','extend','permanent')",
            name="ck_doc_retention_decisions_decision"),
        CheckConstraint(
            "(decision = 'extend' AND new_storage_until IS NOT NULL) OR "
            "(decision <> 'extend' AND new_storage_until IS NULL)",
            name="ck_doc_retention_decisions_extension"),
        CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_doc_retention_decisions_sha256"),
    )


class DocDestructionAct(Base):
    __tablename__ = "doc_destruction_acts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    act_number: Mapped[str] = mapped_column(String(80), nullable=False)
    act_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    committee: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default=text("'draft'"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    backup_attested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    backup_attested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    backup_evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sealed_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sealed_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)

    __table_args__ = (
        Index(
            "uq_doc_destruction_acts_number",
            "company_id",
            text("COALESCE(organization_id, "
                 "'00000000-0000-0000-0000-000000000000'::uuid)"),
            "act_number",
            unique=True,
        ),
        Index("idx_doc_destruction_acts_status", "company_id", "status", "act_date"),
        CheckConstraint(
            "status IN ('draft','approved','executing','primary_purged','destroyed','failed','cancelled')",
            name="ck_doc_destruction_acts_status"),
        CheckConstraint(
            "sealed_sha256 IS NULL OR sealed_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_doc_destruction_acts_sha256"),
        CheckConstraint(
            "status IN ('draft','cancelled') OR "
            "(sealed_snapshot IS NOT NULL AND sealed_sha256 IS NOT NULL)",
            name="ck_doc_destruction_acts_sealed"),
        CheckConstraint(
            "status <> 'destroyed' OR backup_attested_at IS NOT NULL",
            name="ck_doc_destruction_acts_backup_attested"),
    )


class DocDestructionItem(Base):
    __tablename__ = "doc_destruction_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    act_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_destruction_acts.id", ondelete="CASCADE"),
        nullable=False)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"), nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_retention_decisions.id", ondelete="RESTRICT"),
        nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'"))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("act_id", "doc_id", name="uq_doc_destruction_items_act_doc"),
        Index(
            "uq_doc_destruction_items_active_doc",
            "company_id", "doc_id", unique=True,
            postgresql_where=text(
                "status IN ('pending','primary_purged','failed')"),
        ),
        Index("idx_doc_destruction_items_act", "act_id", "status", "doc_id"),
        Index("idx_doc_destruction_items_decision", "decision_id"),
        CheckConstraint(
            "status IN ('pending','primary_purged','destroyed','failed','cancelled')",
            name="ck_doc_destruction_items_status"),
        CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_doc_destruction_items_sha256"),
        CheckConstraint(
            "status NOT IN ('primary_purged','destroyed') OR purged_at IS NOT NULL",
            name="ck_doc_destruction_items_purged_at"),
    )


class DocArchiveEvent(Base):
    __tablename__ = "doc_archive_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="SET NULL"), nullable=True)
    act_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_destruction_acts.id", ondelete="SET NULL"),
        nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    prev_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_doc_archive_events_company", "company_id", "created_at", "id"),
        Index("idx_doc_archive_events_doc", "doc_id", "created_at"),
        Index("idx_doc_archive_events_act", "act_id", "created_at"),
        CheckConstraint(
            "prev_hash IS NULL OR prev_hash ~ '^[0-9a-f]{64}$'",
            name="ck_doc_archive_events_prev_hash"),
        CheckConstraint(
            "event_hash ~ '^[0-9a-f]{64}$'",
            name="ck_doc_archive_events_event_hash"),
    )


class DocBreakGlassAccess(Base):
    __tablename__ = "doc_break_glass_accesses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    permissions: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"))
    notification_recipients: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    notification_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending", server_default=text("'pending'"))
    notification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_doc_break_glass_active", "company_id", "doc_id", "user_id",
              "expires_at", postgresql_where=text("revoked_at IS NULL")),
        Index("idx_doc_break_glass_user", "company_id", "user_id", "created_at"),
        CheckConstraint("use_count >= 0", name="ck_doc_break_glass_use_count"),
        CheckConstraint(
            "notification_status IN ('pending','sent','error')",
            name="ck_doc_break_glass_notification_status"),
        CheckConstraint("expires_at > created_at", name="ck_doc_break_glass_expiry"),
    )


class DocExchangeTarget(Base):
    """Точка обмена с корпоративной системой: папка туда и папка обратно.

    Обмен файловый, через каталог на диске: у головной компании свои СЭД (SEDO,
    Naumen), API к ним нам не дают, а папка есть всегда. Адрес папки — настройка
    пространства, а не секрет: в ней лежат наши же документы.

    Формат описи назван отдельно, потому что у каждой принимающей системы он
    свой. Пока пишем свой полный формат; когда заказчик даст спецификацию, меняем
    генератор описи, а не весь контур обмена.
    """
    __tablename__ = "doc_exchange_targets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # sedo | naumen | other — чей формат описи готовим.
    system: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    # Куда кладём пакеты для головной компании.
    outbox_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Откуда забираем то, что головная компания прислала нам.
    inbox_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Складывать ли пакет одной папкой или zip-архивом.
    as_archive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_export_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Автосканирование включается только после ручной обкатки конкретной папки.
    scan_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scan_interval_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Следующий проход продолжает после последнего просмотренного имени: ведущие
    # дубли и большая папка не должны навсегда закрывать хвост очереди.
    scan_cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_doc_exchange_targets_code"),
    )


class DocExport(Base):
    """Выгрузка документа в корпоративную систему: что, куда и когда ушло.

    Журнал нужен не для красоты: вопрос «отдавали ли мы этот приказ в головную»
    возникает на каждой сверке, и ответ «кажется, да» её не закрывает. Хеш
    пакета отвечает и на второй вопрос — ту ли редакцию отдали.
    """
    __tablename__ = "doc_exports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"),
        nullable=False, index=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_exchange_targets.id", ondelete="SET NULL"),
        nullable=True)
    # pending | placed | downloaded | failed | unknown. pending/unknown означают,
    # что внешняя доставка могла состояться и блокируют финальное уничтожение.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="placed")
    package_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    package_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    package_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Что вошло в пакет: файлы, опись, лист согласования.
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class DocInboxItem(Base):
    """Файл, пришедший от головной компании и ждущий решения человека.

    Приём устроен как приёмка первички: система показывает, что нашла, человек
    смотрит и решает. Автоматическое заведение карточек означало бы, что чужой
    мусор и дубли попадают в реестр без разбора, а чистить реестр документов
    дороже, чем разобрать десяток файлов.
    """
    __tablename__ = "doc_inbox_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_exchange_targets.id", ondelete="SET NULL"),
        nullable=True)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_path: Mapped[str] = mapped_column(String(700), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Хеш содержимого: тот же файл, замеченный второй раз, кандидата не плодит.
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Реквизиты, вычитанные из описи, если она была рядом с файлом.
    parsed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # new | accepted | rejected
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="SET NULL"), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    found_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "sha256", name="uq_doc_inbox_sha"),
    )


class DocAcquaint(Base):
    """Ознакомление с документом: кому направлен и кто расписался.

    Классика распорядительной документации: приказ не действует «вообще», он
    доводится до людей под подпись. Без листа ознакомления вопрос «а он знал?»
    решается словами, а через полгода не решается никак.

    Отдельно от согласования: виза это «я не возражаю» до подписания, а
    ознакомление — «я прочитал» после. Смешивать их значит терять оба смысла.
    """
    __tablename__ = "doc_acquaints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"),
        nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Как человек попал в лист: сам, по подразделению, по роли.
    reason: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    reason_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # pending | done
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    reminder_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    reminder_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Ознакомление относится к точным реквизитам и хешам файлов, а не к «карточке
    # вообще»: следующая редакция требует нового цикла и не переписывает прошлый.
    document_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    snapshot_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    # Отметка ставится только за себя, поэтому автора отдельно не храним.
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_doc_acquaints_snapshot", "doc_id", "user_id", "snapshot_sha256",
              unique=True, postgresql_where=text("snapshot_sha256 IS NOT NULL")),
        Index("idx_doc_acquaints_mine", "company_id", "user_id", "status"),
    )


class UserSubstitution(Base):
    """Замещение: кто работает за человека, пока его нет.

    Виза за другого запрещена — это подделка согласования. Но человек уходит в
    отпуск, и без замещения документ встаёт до его возвращения. Разница
    принципиальная: заместитель ставит визу ОТ СВОЕГО ИМЕНИ на основании
    замещения, и в листе согласования видно обоих — за кого и кто фактически.
    """
    __tablename__ = "user_substitutions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Кого замещают.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Кто замещает.
    deputy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    starts_on: Mapped[date_type] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date_type] = mapped_column(Date, nullable=False)
    # Основание: приказ о возложении обязанностей, номер и дата.
    basis: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_substitutions_period", "company_id", "user_id", "starts_on", "ends_on"),
        CheckConstraint("ends_on >= starts_on", name="ck_substitution_period"),
        CheckConstraint("user_id <> deputy_id", name="ck_substitution_self"),
    )


class SiteCabinetUser(Base):
    """Доступ клиента в кабинет сайта: кто заходит, кем считается, что ему открыто.

    Хозяин доступа — ПРОСТРАНСТВО, а не сайт: решение «этот человек видит наши
    документы и наши стенды» принимает тот, кто ведёт клиента, и принимает один раз.
    Сайт держит вход (код на почту, сессия, одноразовый пропуск в стенд) — это его
    дело и его безопасность, — но состав людей и их уровень читает отсюда.

    Клиент указывается СВЯЗЬЮ на контрагента пространства, а не строкой с названием
    компании: у контрагента есть договоры, документы и акты сверки, и кабинет должен
    показывать их, а не угадывать по совпадению написания.
    """
    __tablename__ = "site_cabinet_users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Клиент, от имени которого человек входит. Пусто — обращение с улицы: заявку
    # оставили до всякого договора, и показывать ему нечего, кроме общей витрины.
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"),
        nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    # guest — только витрина; client — свои документы; partner — ещё и материалы;
    # admin — управление кабинетом на самом сайте. Слова те же, что у сайта: одно
    # значение не должно называться по-разному на двух концах.
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="guest")
    # Какие стенды открыты: пусто = все (звёздочка сайта), иначе список кодов.
    demos: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Один адрес — один доступ в пространстве: два доступа с разными уровнями
        # означали бы, что ответ на «что ему видно» зависит от порядка выборки.
        UniqueConstraint("company_id", "email", name="uq_site_cabinet_email"),
    )


class SiteDemo(Base):
    """Демо-стенд, который показывают клиенту из кабинета.

    Был списком в коде сайта (EP-project/server/demos.js): чтобы завести показ или
    снять его с витрины, правили файл и выкатывали сервер. Стенд — не код, а решение
    («этому клиенту показываем процессинг»), и решение должно приниматься галочкой.

    Адрес стенда живёт здесь же, но САМ ПРОХОД остаётся за сайтом: одноразовый
    пропуск, кука на путь и журнал — его механика, проверенная и работающая.
    """
    __tablename__ = "site_demos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Стенд у нас: кромка сайта проксирует его под /demo-run/<code>/app/.
    upstream_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Стенд ещё на своём адресе: ведём по пропуску, но адрес открыт напрямую.
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # С какого экрана открывать: показывают ради раздела, а не ради входа.
    landing: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_site_demo_code"),
    )


class ClientSpace(Base):
    """Пространство, развёрнутое клиенту: его адрес и состояние.

    Решение МАГа (29.08.2026): каждому клиенту разворачивается СВОЁ пространство, и
    работает он с нами там. Поэтому кабинет сайта перестаёт быть местом работы —
    он прихожая: пускает внутрь и даёт поговорить. Договоры, акты и сверки в кабинет
    больше не возятся: у клиента они и так есть, в его собственном контуре.

    Отсюда и эта запись. Кабинет спрашивает пространство «куда пускать этого
    человека» и получает адрес отсюда, а не из настройки на своей стороне: адрес
    контура — свойство клиента, а не сайта.

    Состояние честное: пока стек разворачивается, кнопка в кабинете не появляется.
    Дверь, которая ведёт в недоделанное, хуже отсутствующей двери.
    """
    __tablename__ = "client_spaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Наша компания — та, что обслуживает.
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Клиент, которому развёрнуто. Связь, а не строка с названием: у контрагента
    # есть договоры и учёт, и по ним видно, за что этот контур.
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # Код стека поставки (`stacks/<slug>` в ecosystem-deploy) — по нему контур
    # разворачивают и находят на ВМ.
    slug: Mapped[str] = mapped_column(String(50), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # planned — решили развернуть; deploying — разворачивается; active — работает;
    # suspended — приостановлено (долг, окончание договора).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "slug", name="uq_client_space_slug"),
    )


class PartnerSpace(Base):
    """Другое пространство, с которым это связано: клиент или наш поставщик услуг.

    Замысел МАГа (29.08.2026). Наши люди заведены в пространстве клиента и работают
    внутри него — это ДОСТУП, и он остаётся: инженер должен видеть и править. Но
    разговор — обращения, чат, документы — должен вестись из СВОЕГО пространства, а
    не изнутри чужого. Иначе поддержка живёт в контуре заказчика, и у неё нет ни
    своей очереди, ни своей истории, ни возможности обслуживать второго клиента.
    Сегодня это временная мера, дальше поддержка целиком переезжает к себе.

    Запись симметрична, и это не экономия, а условие правильности: оба конца —
    экземпляры одного Ядра, и код доставки должен быть один. У клиента в этой
    таблице лежим мы с ролью `vendor`, у нас — он с ролью `client`.

    Секрет здесь не лежит: `secret_ref` — имя переменной окружения стека, как у
    коннекторов (docs/CORE.md §7а). Ключ, уехавший в дамп базы, — это ключ, который
    уже не наш.
    """
    __tablename__ = "eco_partner_spaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # `client` — их пространство, которое мы обслуживаем; `vendor` — наша служба
    # поддержки, если эта запись стоит в контуре заказчика.
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="client")
    # Код пространства-партнёра (`gig`, `elsyplus`) — совпадает с кодом стека.
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Куда стучаться: корень домена партнёра, без пути.
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Имя переменной окружения с ключом партнёра (X-Cloud-API-Key для его приёмника).
    secret_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Клиент как контрагент нашего учёта — если он у нас заведён. У обратной записи
    # (мы в контуре клиента) пусто: мы для него не контрагент этой таблицы.
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="SET NULL"),
        nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "code", "role", name="uq_partner_space_code"),
    )


class PartnerMessage(Base):
    """Сообщение между пространствами: обращение к поддержке и ответ на него.

    Одна таблица на оба конца, потому что событие одно: человек из пространства
    клиента написал в техподдержку, техподдержка ответила. У клиента это лента на
    экране «Техподдержка», у нас — то же самое плюс зеркало в очереди Поддержки,
    чтобы оператор видел разговор рядом со звонками и письмами.

    `external_id` — идентификатор сообщения У ОТПРАВИТЕЛЯ. По нему повторная
    доставка не плодит дублей: сеть рвётся, отправитель повторяет, и без ключа
    идемпотентности лента набивается копиями.
    """
    __tablename__ = "eco_partner_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True)
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eco_partner_spaces.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # `out` — написали мы, `in` — написали нам. Направление считается ОТ ЭТОГО
    # пространства: у обеих сторон одна и та же переписка читается зеркально.
    direction: Mapped[str] = mapped_column(String(4), nullable=False)
    # Кто написал: адрес и имя человека в его пространстве.
    author_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Предмет разговора, если он привязан к чему-то в пространстве: заявка, объект.
    subject_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    subject_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Ошибка последней попытки доставки — чтобы «не дошло» было видно, а не
    # выяснялось через неделю от клиента.
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("partner_id", "direction", "external_id",
                         name="uq_partner_message_external"),
        Index("idx_partner_messages_feed", "company_id", "partner_id", "created_at"),
    )
