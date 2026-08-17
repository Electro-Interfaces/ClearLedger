"""
Конфигурация приложения.
Загружает переменные окружения из .env файла.
"""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Значение секрета по умолчанию — заведомо небезопасное. Если оно доедет до
# прода, JWT можно подделать публично известным ключом. main.lifespan проверяет
# и кричит в лог; деплой обязан задать SECRET_KEY (или JWT_SECRET).
DEFAULT_INSECURE_SECRET = "change-me-in-production-use-openssl-rand-hex-32"


class Settings(BaseSettings):
    """Настройки TradeLedger Server."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Имя среды — для «отпечатка среды» /api/_debug/state и баннера в UI.
    # dev по умолчанию; прод переопределяет APP_ENV=prod в .env/compose. Помогает
    # мгновенно понять, dev это или прод (частый источник путаницы при разработке).
    app_env: str = "dev"

    # SHA сборки (опц.) — прод может пробросить GIT_SHA в окружение контейнера,
    # чтобы /api/_debug/state показывал, какой код реально задеплоен.
    git_sha: str = ""

    # База данных
    database_url: str = (
        "postgresql+asyncpg://clearledger:clearledger@localhost:5432/clearledger"
    )

    # Безопасность. Секрет читается из SECRET_KEY ИЛИ JWT_SECRET — историческое
    # расхождение имён (прод-compose отдавал JWT_SECRET, а приложение ждало
    # SECRET_KEY → втихую брался дефолт). AliasChoices принимает оба.
    secret_key: str = Field(
        default=DEFAULT_INSECURE_SECRET,
        validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET"),
    )
    access_token_expire_minutes: int = 1440  # 24 часа
    algorithm: str = "HS256"

    # Сид суперадмина. Создаётся при старте ТОЛЬКО если заданы обе переменные
    # (SEED_SUPERADMIN_EMAIL + SEED_SUPERADMIN_PASSWORD). Пусто → суперадмин на
    # старте НЕ создаётся (нет дефолтного бэкдора admin@clearledger.ru/admin123).
    seed_superadmin_email: str = ""
    seed_superadmin_password: str = ""

    # Состав компаний экосистемы (модель «стек-на-компанию»). Пусто → сидится
    # встроенный каталог seed.COMPANIES (текущий мультитенант-прод
    # ledger.dataworker.ru). Задано → сидятся ТОЛЬКО перечисленные: изолированный
    # стек не должен знать о чужих компаниях (ecosystem-deploy/docs/CORE.md §1 —
    # контейнер = экосистема, между экосистемами не пересекается ничего).
    # Формат: компании через ';', поля через '|'.
    #   ECOSYSTEM_COMPANIES=rushydro                        — взять из встроенного каталога
    #   ECOSYSTEM_COMPANIES=lukoil|ЛУКОЙЛ|ЛУКОЙЛ|fuel|#00a  — компании нет в каталоге
    ecosystem_companies: str = ""

    # Бренд экосистемы-контейнера (white-label). Контейнер = экосистема заказчика,
    # поэтому имя задаётся на контейнер. Влияет на имена приложений реестра
    # (`<brand> Ledger`). Фронт бакует свой `VITE_ECOSYSTEM_BRAND` отдельно. Дефолт —
    # платформенный. rushydro → «РусГидро», gig → «ГИГ».
    ecosystem_brand: str = "ElsyPlus"

    # Видеоконференции Jitsi (meet.dataworker.ru, RS256/ASAP). TradeLedger подписывает
    # JWT организатора СВОИМ приватным ключом (iss=ledger); prosody проверяет публичным
    # ключом с keyserver по kid. Приватный ключ (PEM) — в base64, НЕ в git.
    jitsi_signing_key: str = ""            # приватный RSA-ключ (PEM) в base64
    jitsi_kid: str = "ledger/1"
    jitsi_issuer: str = "ledger"
    jitsi_domain: str = "meet.dataworker.ru"   # публичный домен ссылки
    jitsi_xmpp_domain: str = "meet.jitsi"      # внутренний XMPP-домен (sub)

    @property
    def jitsi_enabled(self) -> bool:
        """Конференции доступны (задан приватный ключ подписи)?"""
        return bool(self.jitsi_signing_key)

    # Платформенный SSO ElsyPlus (Фаза 0). Ledger — временный провайдер: подписывает
    # короткоживущий RS256-токен (iss=elsyplus), приложения экосистемы (Support/
    # Координатор) проверяют его публичным ключом через JWKS, без общего секрета.
    # Прецедент — jitsi_* выше. Приватный ключ (PEM) в base64, НЕ в git; фича
    # гейтится его наличием (sso_enabled). На Фазе 1/2 провайдер переедет на Zitadel,
    # контракт JWKS/клеймы сохранится.
    sso_signing_key: str = ""              # приватный RSA-ключ (PEM) в base64
    sso_kid: str = "elsyplus/1"
    sso_issuer: str = "elsyplus"
    sso_token_ttl_seconds: int = 300       # короткий handoff-токен (5 мин)
    # Каталог приложений экосистемы (Фаза 0 — статический из env; Фаза 1 — БД-реестр).
    # Формат строки: "code|Название|https://base-url|/callback|icon", записи через «;».
    sso_apps: str = ""
    # Платформенный сервис ЧАТ (Matrix Synapse) — адрес homeserver в стеке экосистемы
    # (пусто = чат не подключён). Используется модулем «Чат» и статусом Ядра.
    # synapse_url — ВНУТРЕННИЙ адрес (admin API, backend-only).
    synapse_url: str = ""
    # Модель чата «как в Ангаре»: провижининг через Synapse Admin API сервисным
    # аккаунтом. Токен НИКОГДА не уходит на фронт; фронту отдаётся публичный homeserver.
    matrix_admin_token: str = ""              # access_token сервисного @<prefix>-svc (admin)
    matrix_homeserver_public: str = ""        # публичный https homeserver (в браузер)
    matrix_server_name: str = ""              # домен mxid (обычно = DOMAIN)
    matrix_mxid_prefix: str = "elsy"          # префикс локалпарта mxid: @elsy_<...>:server

    @property
    def chat_enabled(self) -> bool:
        """Чат доступен: есть внутренний адрес Synapse и admin-токен."""
        return bool(self.synapse_url and self.matrix_admin_token)

    @property
    def sso_enabled(self) -> bool:
        """Платформенный SSO доступен (задан приватный ключ подписи)?"""
        return bool(self.sso_signing_key)

    @property
    def secret_is_insecure(self) -> bool:
        """Секрет не задан в окружении (используется небезопасный дефолт)?"""
        return self.secret_key == DEFAULT_INSECURE_SECRET

    # CORS — список origin через запятую
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # OCR / загрузка файлов (лимит /api/intake — общий на все загрузки, вкл. xlsx
    # выгрузок сессий/реестров, которые бывают крупными).
    ocr_enabled: bool = True
    ocr_max_file_size: int = 100 * 1024 * 1024  # 100 МБ
    ocr_timeout: int = 30  # секунд

    # SMTP — отправка писем (приглашения сотрудников). Mailcow на services-01.
    # На проде SMTP_HOST=10.10.70.51 (внутренний IP хоста), 587 STARTTLS,
    # SMTP_SERVERNAME=mail.dataworker.ru для проверки TLS-сертификата.
    # Пусто → dev-режим: ссылка приглашения печатается в лог.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "TradeLedger <ledger@dataworker.ru>"
    smtp_servername: str = ""
    smtp_secure: bool = False  # True для 465 SMTPS; False для 587 STARTTLS

    # Ящик приёма пространства: адрес, на который отвечают внешние участники чатов.
    # Ответ адресуется комнате плюс-адресацией (`ящик+r<комната>@домен`), поэтому
    # тема письма может быть любой — человек отвечает как обычно, из своей почты.
    # Пусто = почтовых участников в чатах нет, письма из комнат не уходят.
    chat_mail_inbox: str = ""

    # Публичный URL пространства для ссылок в письмах. Пространство живёт в корне
    # своего домена: внутреннее имя репозитория в адресах заказчика не появляется.
    app_public_url: str = "https://ledger.dataworker.ru"

    # Папки обмена с корпоративной СЭД доступны только внутри явно смонтированных
    # корней. Администратор пространства не должен превращать сканер в чтение
    # произвольных файлов контейнера. Несколько корней разделяются `;`.
    doc_exchange_roots: str = "/exchange"

    # Authentication-Results доверяем только от своего принимающего MTA. Пустой
    # список означает fail-closed для автоматического создания документов.
    mail_authserv_ids: str = ""

    # Сверки — внешние API (прокси на стороне сервера, секреты не уходят на фронт)
    tradecorp_api_url: str = ""
    tradecorp_login: str = ""
    tradecorp_password: str = ""
    tradecorp_emitent_id: int = 15
    msto_api_url: str = ""
    msto_username: str = ""
    msto_password: str = ""

    # HubEx FSM — сервисные заявки/ремонты ЭЗС РусГидро (прокси на сервере,
    # сервисный токен НЕ уходит на фронт). Пусто → вкладка «Сервис» без заявок.
    hubex_service_token: str = ""
    hubex_base_url: str = "https://api.hubex.ru/fsm"
    hubex_app_id: str = "5"
    hubex_tasks_limit: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        """Разбирает CORS_ORIGINS в список."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Кешированный экземпляр настроек."""
    return Settings()


# Модульный алиас: часть кода (`services/chat_mail.py`) обращается к настройкам
# как к объекту, а не зовёт фабрику. Кеш общий — это тот же экземпляр.
settings = get_settings()
