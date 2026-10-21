"""Служебный токен Ядра обязан называть арендатора (аудит решения 21.10.2026, B-11).

Один служебный токен Ядра действовал в контуре ЛЮБОЙ компании Поддержки: область
действия задавал параметр `companyId` запроса, а удостоверение не называло никого.
Токен, выданный для компании А, обслуживался на заявке компании Б — достаточно было
подменить параметр. Контракт версии 2
(`TSupport:docs/process-facade-service-channel.md`) закрывает это так: арендатор
следует из токена, а `companyId` запроса лишь выбирает внутри названного.

Проверяется ровно одно: каждый путь выдачи служебного токена в Ядре называет компанию
в терминах приложения-получателя — там, где эта компания и так известна (карта
`eco_app_company_links`). Проверка идёт по фактически уходящему заголовку
`Authorization`, а не по аргументам функции: смысл в том, что получатель увидит в
токене, а не в том, что мы собирались положить.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

from app.services import (
    managed_connectors, space_connectors, space_desk, space_events,
    space_projection, sso, ticket_communications, voice_support_context,
)

COMPANY = uuid.UUID("11111111-1111-4111-8111-111111111111")
# Компания на стороне Поддержки — её собственный идентификатор, не наш.
REMOTE = "33333333-3333-4333-8333-333333333333"
ACTOR = uuid.UUID("44444444-4444-4444-8444-444444444444")
TICKET = "55555555-5555-4555-8555-555555555555"
RealClient = httpx.AsyncClient

APP = SimpleNamespace(id=uuid.uuid4(), code="support", name="Поддержка",
                      base_url="/support", is_active=True,
                      config={"internalUrl": "http://support.test:3003"})
LINK = SimpleNamespace(external_company_id=REMOTE, external_code="rushydro",
                       company_id=COMPANY)


@pytest.fixture
def signing(monkeypatch):
    """Свой ключ подписи: проверяем выданный токен так же, как его проверит получатель."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    monkeypatch.setattr(sso, "_private_key", lambda: private)
    return key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)


class StubDB:
    """Карта приложений и компаний — всё, без чего пути выдачи не доходят до подписи.

    База не поднимается намеренно: проверяется, что в токен попадает
    `external_company_id` прочитанной пары, а не то, как эта пара читается из Postgres.
    """

    async def execute(self, statement):
        строка = LINK if "eco_app_company_links" in str(statement) else APP
        return SimpleNamespace(
            first=lambda: (APP, LINK),
            scalar_one_or_none=lambda: строка,
            scalars=lambda: SimpleNamespace(all=lambda: [строка]),
        )

    async def scalar(self, statement):
        # `support_company_id` читает ровно одну колонку; `App` — объект приложения.
        return APP if "eco_apps" in str(statement) and "code" in str(statement) else REMOTE

    async def get(self, model, key):
        return SimpleNamespace(company_id=COMPANY, user_id=ACTOR)


@pytest.fixture
def captured(monkeypatch, signing):
    """Перехват ухода в сеть: собираем клеймы каждого служебного токена."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        claims = jwt.decode(raw, signing, algorithms=["RS256"],
                            audience=jwt.decode(raw, options={"verify_signature": False})["aud"],
                            issuer=sso.settings.sso_issuer)
        calls.append({"url": str(request.url), "claims": claims,
                      "kid": jwt.get_unverified_header(raw).get("kid")})
        body = {"tickets": {"total": 1, "open": 1, "fresh": 0}, "ticketId": TICKET,
                "supportCompanyId": REMOTE, "actorCoreUserId": str(ACTOR),
                "canStaffChat": True, "canVideo": True, "ok": True,
                "connectors": [], "providers": [], "availability": "available"}
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    for module in (space_projection, space_connectors, space_desk, space_events,
                   managed_connectors, ticket_communications, voice_support_context):
        monkeypatch.setattr(module.httpx, "AsyncClient",
                            lambda **kw: RealClient(transport=transport, **kw), raising=False)
    monkeypatch.setattr(voice_support_context, "company_apps",
                        _apps_stub, raising=False)
    monkeypatch.setattr(ticket_communications, "company_apps", _apps_stub, raising=False)
    monkeypatch.setattr(ticket_communications, "support_company_id",
                        lambda db, cid: _remote(), raising=False)
    return calls


async def _apps_stub(db, company_id):
    return [{"code": "support", "enabled": True}]


async def _remote():
    return REMOTE


def tenant_of(claims: dict) -> str | None:
    """Арендатор так, как его прочитает Поддержка (`tokenTenantRefs`, контракт v2)."""
    for company in claims.get("companies") or []:
        if company.get("slug"):
            return str(company["slug"])
    for key in ("company_id", "company"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# --- Прямая выдача: ключевой стык, через который проходят все пути ---------------

def test_sign_service_token_names_tenant(signing):
    """Токен называет компанию получателя клеймом прямой формы, и `kid` в заголовке."""
    token = sso.sign_service_token(aud="support", scope="projection",
                                   app_company_id=REMOTE)
    assert jwt.get_unverified_header(token)["kid"] == sso.settings.sso_kid
    claims = jwt.decode(token, signing, algorithms=["RS256"], audience="support",
                        issuer=sso.settings.sso_issuer)
    assert claims["svc"] == "projection"
    assert tenant_of(claims) == REMOTE
    # `cid` остаётся: по нему арендатора читают `connector-management`, `voice-*`
    # и `ticket-communications` Поддержки и API узла «Телефонии».
    assert claims["cid"] == REMOTE
    # Срок жизни — минуты, как и был: это не задача «сделать удобнее».
    assert claims["exp"] - claims["iat"] == 120


def test_sign_service_token_refuses_without_tenant(signing):
    """Безымянного служебного токена выдать нельзя — и это проверка на стыке.

    Повторять её в каждом маршруте бессмысленно: забыть компанию можно только здесь,
    и новый путь выдачи обязан назвать её, иначе не соберётся вызов.
    """
    with pytest.raises(TypeError):
        sso.sign_service_token(aud="support", scope="projection")
    for пусто in ("", "   ", None):
        with pytest.raises(ValueError):
            sso.sign_service_token(aud="support", scope="projection", app_company_id=пусто)


def test_slug_tenant_goes_to_company_claim(signing):
    """Не всякое приложение нумерует компании UUID: код уходит слагом.

    `eco_app_company_links.external_company_id` — строка («у разных приложений разный
    тип»). Поддержка читает `company_id` только как UUID, а неUUID — как слаг в
    `company`; положить код в `company_id` значило бы молча потерять арендатора.
    """
    claims = jwt.decode(
        sso.sign_service_token(aud="support", scope="projection", app_company_id="rushydro"),
        signing, algorithms=["RS256"], audience="support", issuer=sso.settings.sso_issuer)
    assert claims.get("company") == "rushydro" and "company_id" not in claims
    assert tenant_of(claims) == "rushydro"


def test_voice_service_token_names_company(signing):
    """Узел «Телефонии» пускает только свою компанию — она и названа."""
    claims = jwt.decode(
        sso.sign_voice_service_token(scope="voice.stats", company_id=str(COMPANY)),
        signing, algorithms=["RS256"], audience="voice", issuer=sso.settings.sso_issuer)
    assert claims["cid"] == str(COMPANY) and tenant_of(claims) == str(COMPANY)


# --- Пути выдачи: то, что реально уходит в Поддержку ----------------------------

async def test_projection_target_names_tenant(captured, signing):
    """Проекция справочников: `_target` держит и карту компаний, и подпись."""
    _app, link, token = await space_projection._target(StubDB(), COMPANY, "support")
    claims = jwt.decode(token, signing, algorithms=["RS256"], audience="support",
                        issuer=sso.settings.sso_issuer)
    assert tenant_of(claims) == link.external_company_id == REMOTE


async def test_object_tickets_names_tenant(captured):
    await space_projection.object_tickets(StubDB(), COMPANY, "obj-1")
    assert tenant_of(captured[-1]["claims"]) == REMOTE


async def test_app_connectors_names_tenant(captured):
    await space_connectors._app_connectors(APP, LINK, "support", "Поддержка")
    assert tenant_of(captured[-1]["claims"]) == REMOTE


async def test_external_work_names_tenant(captured):
    await space_connectors.fetch_external_work(
        StubDB(), COMPANY, connector_key=f"support:{TICKET}", external_ref="W-1")
    assert tenant_of(captured[-1]["claims"]) == REMOTE


async def test_desk_card_names_tenant(captured):
    await space_desk._support(StubDB(), COMPANY)
    assert tenant_of(captured[-1]["claims"]) == REMOTE


async def test_event_delivery_names_tenant(captured):
    """Фоновая доставка событий — тот же служебный канал, свой скоуп."""
    sub = SimpleNamespace(target_kind="app", app_code="support", path="/api/v1/eco/events",
                          url=None, secret_enc=None)
    row = SimpleNamespace(event_id=uuid.uuid4(), type="doc.posted", subject="doc:1",
                          occurred_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                          data={}, company_id=COMPANY)
    assert await space_events._send(StubDB(), sub, row) == 200
    assert captured[-1]["claims"]["svc"] == "events"
    assert tenant_of(captured[-1]["claims"]) == REMOTE


async def test_managed_connectors_names_tenant(captured):
    await managed_connectors.owner_request(StubDB(), COMPANY, ACTOR, "support", "GET", "/catalog")
    assert tenant_of(captured[-1]["claims"]) == REMOTE


async def test_ticket_communication_names_tenant(captured):
    user = SimpleNamespace(id=ACTOR, email="operator@test.ru", mail_only=False,
                           is_superadmin=False)
    await ticket_communications.access(StubDB(), COMPANY, user, TICKET)
    assert tenant_of(captured[-1]["claims"]) == REMOTE


async def test_voice_context_names_tenant(captured):
    await voice_support_context.support_tickets(
        StubDB(), COMPANY, phone="+70000000000", core_party_ref=None,
        object_refs=[], limit=5)
    assert tenant_of(captured[-1]["claims"]) == REMOTE


def test_every_issuance_site_names_the_tenant():
    """Ни одного пути выдачи без компании — проверяется по исходникам.

    Путей девять, и половина из них ходит в Поддержку из фона (доставка событий,
    контекст звонка) — туда тест запросом не попадает. Обязательный аргумент стыка
    делает безымянную выдачу невозможной, а эта проверка ловит обратное движение:
    вернуть аргументу значение по умолчанию.
    """
    import ast
    import pathlib
    import warnings

    корень = pathlib.Path(__file__).resolve().parents[1] / "app"
    сайты, безымянные = 0, []
    for путь in корень.rglob("*.py"):
        with warnings.catch_warnings():
            # Разбор чужих файлов — не повод показывать их предупреждения здесь.
            warnings.simplefilter("ignore", SyntaxWarning)
            дерево = ast.parse(путь.read_text(encoding="utf-8"))
        for узел in ast.walk(дерево):
            if (isinstance(узел, ast.Call) and isinstance(узел.func, ast.Attribute)
                    and узел.func.attr == "sign_service_token"):
                сайты += 1
                if not any(k.arg == "app_company_id" for k in узел.keywords):
                    безымянные.append(f"{путь.name}:{узел.lineno}")
    assert сайты >= 9, f"путей выдачи найдено {сайты} — проверка смотрит не туда"
    assert not безымянные, f"служебный токен без арендатора: {безымянные}"
