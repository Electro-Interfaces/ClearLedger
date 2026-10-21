"""Драйвер парной проверки R8: Ядро выдаёт служебный токен — Поддержка его принимает.

Проверяется вторая половина пары к находке B-11: Ядро обязано называть арендатора в
служебном токене. Первая половина (проверка на стороне Поддержки) лежит в ветке
`fix/audit-r2-core-channel-20261021` репозитория TSupport и здесь только читается.

Правила драйвера:

* токен выпускается **реальным путём выдачи Ядра** (`space_projection._target`,
  `space_desk._support`, `sso.sign_service_token`), а не синтетической подписью:
  красный и зелёный прогоны отличаются только продуктовым кодом, не драйвером;
* подпись не подделывается — экземпляр Поддержки контура настроен на JWKS именно
  этого ключа (`ECOSYSTEM_SSO_JWKS_URL` указывает на издателя драйвера);
* все вызовы Поддержки идут по HTTP штатными маршрутами, её код не импортируется;
* в доказательства попадают только разобранные клеймы без подписи; сам токен —
  никогда.

Запуск (из контейнера `fix-r8-py`, сеть host):

    FIX_LABEL=red-before python docs/solution-audit-20261021/fixes/R8/driver/run.py
"""
from __future__ import annotations

import base64
import inspect
import json
import os
import pathlib
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

КОРЕНЬ = pathlib.Path(__file__).resolve()
РАНТАЙМ = pathlib.Path(os.environ.get("FIX_RT", "/rt"))
ДОКАЗАТЕЛЬСТВА = КОРЕНЬ.parents[1] / "evidence"
ПОДДЕРЖКА = os.environ.get("FIX_SUPPORT", "http://127.0.0.1:37010")
ПОРТ_JWKS = int(os.environ.get("FIX_JWKS_PORT", "37020"))
МЕТКА = os.environ.get("FIX_LABEL", "run")

# Компании контура: идентификаторы — СОБСТВЕННЫЕ идентификаторы Поддержки, какими их
# знает карта `eco_app_company_links` Ядра. Свой UUID компании пространства Поддержке
# ничего не говорит, и подставлять его было бы той же ошибкой в другую сторону.
A = SimpleNamespace(support_id="a0000000-0000-4000-8000-000000000001", slug="fix-r8-a",
                    core_id=uuid.UUID("aa000000-0000-4000-8000-0000000000a1"),
                    process="a5000000-0000-4000-8000-000000000001", subject="obj-a",
                    link="a4000000-0000-4000-8000-000000000001",
                    email="dispatcher-a@fix-r8.invalid",
                    # Человек тот же в каждом прогоне: со случайным `sub` второй прогон
                    # получал бы 409 «связана с другим пользователем» — это свойство
                    # драйвера, а не граница, которую проверяют.
                    person=uuid.UUID("a6000000-0000-4000-8000-0000000000a6"))
B = SimpleNamespace(support_id="b0000000-0000-4000-8000-000000000002", slug="fix-r8-b",
                    core_id=uuid.UUID("bb000000-0000-4000-8000-0000000000b2"),
                    process="b5000000-0000-4000-8000-000000000002", subject="obj-b")

# --- Ключ подписи Ядра ---------------------------------------------------------
# Ключ живёт в рантайме, а не генерируется на прогон: JWKS кешируется Поддержкой на
# пять минут, и новая пара на каждый прогон требовала бы перезапуска её экземпляра
# между красным и зелёным — разными стали бы два условия вместо одного.
КЛЮЧ = РАНТАЙМ / "sso.key"
if not КЛЮЧ.exists():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat,
    )
    КЛЮЧ.write_bytes(rsa.generate_private_key(public_exponent=65537, key_size=2048)
                     .private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    КЛЮЧ.chmod(0o600)

os.environ["SSO_SIGNING_KEY"] = base64.b64encode(КЛЮЧ.read_bytes()).decode()
os.environ.setdefault("SECRET_KEY", "fix-r8-driver")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://clearledger:clearledger@127.0.0.1:37432/clearledger_test")

# Откуда берётся код Ядра. По умолчанию — дерево этого драйвера; красный прогон
# указывает сюда дерево на предправочном SHA, чтобы между прогонами отличался
# ТОЛЬКО продуктовый код, а не ещё и драйвер.
sys.path.insert(0, os.environ.get(
    "FIX_CORE", str(КОРЕНЬ.parents[5] / "clearledger" / "server")))
import httpx  # noqa: E402
import jwt as jwtlib  # noqa: E402

from app.services import space_desk, space_projection, sso  # noqa: E402


# --- Издатель JWKS Ядра --------------------------------------------------------

class JWKS(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        тело = json.dumps(sso.public_jwks()).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(тело)))
        self.end_headers()
        self.wfile.write(тело)

    def log_message(self, *_):
        pass


# --- Служебный токен реальными путями Ядра -------------------------------------

class StubDB:
    """Карта приложений и компаний Ядра: больше путям выдачи ничего не нужно.

    База Ядра тут не поднимается намеренно: проверяется, что в токен попадает
    `external_company_id` из карты, а не то, как эта карта читается из Postgres.
    """

    def __init__(self, support_id: str):
        self.app = SimpleNamespace(
            id=uuid.uuid4(), code="support", name="Поддержка", base_url="/support",
            is_active=True, config={"internalUrl": ПОДДЕРЖКА})
        self.link = SimpleNamespace(external_company_id=support_id, external_code=None)

    async def execute(self, statement):
        строка = self.link if "eco_app_company_links" in str(statement) else self.app
        return SimpleNamespace(first=lambda: (self.app, self.link),
                               scalar_one_or_none=lambda: строка,
                               scalars=lambda: SimpleNamespace(all=lambda: [строка]))

    async def scalar(self, statement):
        return self.app


ПОДДЕРЖИВАЕТ_АРЕНДАТОРА = "app_company_id" in inspect.signature(sso.sign_service_token).parameters


async def токен_проекции(заказчик) -> str:
    """Тот самый токен, которым Ядро проецирует справочники: `_target`."""
    _app, _link, token = await space_projection._target(
        StubDB(заказчик.support_id), заказчик.core_id, "support")
    return token


async def токен_стола(заказчик) -> str | None:
    """Токен карточки заявок рабочего стола: `space_desk._support` — ещё один путь.

    Сам токен функция не возвращает, поэтому перехватываем уходящий заголовок.
    Проверяется то, что получатель увидит, а не аргументы вызова.
    """
    поймано: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        поймано["raw"] = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return httpx.Response(200, json={"tickets": {"total": 1, "open": 1, "fresh": 0}})

    настоящий = space_desk.httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    space_desk.httpx.AsyncClient = lambda **kw: настоящий(transport=transport, **kw)
    try:
        await space_desk._support(StubDB(заказчик.support_id), заказчик.core_id)
    finally:
        space_desk.httpx.AsyncClient = настоящий
    return поймано.get("raw")


def клеймы(token: str) -> dict:
    """Разбор без проверки подписи — в доказательства уходит только он."""
    полезное = jwtlib.decode(token, options={"verify_signature": False})
    полезное.pop("jti", None)
    return {"header": jwtlib.get_unverified_header(token), "claims": полезное}


def арендатор(claims: dict) -> str | None:
    """Арендатор так, как его прочитает Поддержка (`tokenTenantRefs`, контракт v2)."""
    for компания in claims.get("companies") or []:
        if компания.get("slug"):
            return str(компания["slug"])
    for ключ in ("company_id", "company"):
        значение = claims.get(ключ)
        if isinstance(значение, str) and значение.strip():
            return значение.strip()
    return None


# --- Вызовы Поддержки ----------------------------------------------------------

запросы: list[dict] = []


def вызов(путь: str, token: str, *, method: str = "GET", body=None) -> dict:
    with httpx.Client(timeout=20.0) as client:
        ответ = client.request(method, ПОДДЕРЖКА + путь,
                               headers={"Authorization": f"Bearer {token}"}, json=body)
    try:
        данные = ответ.json()
    except ValueError:
        данные = {"nonJson": ответ.text[:300]}
    запись = {"путь": путь, "метод": method, "статус": ответ.status_code,
              "код": данные.get("code"), "ошибка": данные.get("error"),
              "шаг": (данные.get("currentStep") or {}).get("code") if isinstance(данные, dict) else None}
    запросы.append(запись)
    return запись


async def main() -> int:
    издатель = HTTPServer(("127.0.0.1", ПОРТ_JWKS), JWKS)
    threading.Thread(target=издатель.serve_forever, daemon=True).start()

    проекция_а = await токен_проекции(A)
    проекция_б = await токен_проекции(B)
    стол_а = await токен_стола(A)

    пункты: list[dict] = []

    def пункт(идентификатор, что, ожидание, факт, зелёный):
        пункты.append({"id": идентификатор, "что": что, "ожидание": ожидание,
                        "факт": факт, "итог": "зелено" if зелёный else "КРАСНО"})

    # R8-01 — выдаваемый токен называет арендатора.
    разбор = клеймы(проекция_а)
    имя = арендатор(разбор["claims"])
    пункт("R8-01", "служебный токен Ядра (проекция) называет арендатора",
          f"клейм арендатора = {A.support_id}",
          {"арендатор": имя, "kid": разбор["header"].get("kid"), "клеймы": разбор["claims"]},
          имя == A.support_id and bool(разбор["header"].get("kid")))

    # R8-02 — тот же арендатор во втором пути выдачи (карточка стола).
    разбор_стол = клеймы(стол_а) if стол_а else {"claims": {}, "header": {}}
    пункт("R8-02", "второй путь выдачи (карточка заявок стола) называет того же арендатора",
          f"клейм арендатора = {A.support_id}",
          {"арендатор": арендатор(разбор_стол["claims"]), "svc": разбор_стол["claims"].get("svc")},
          арендатор(разбор_стол["claims"]) == A.support_id)

    # R8-03 — процессный фасад обслуживает запрос без companyId: область из токена.
    ответ = вызов(f"/api/v1/process/instances/{A.process}", проекция_а)
    пункт("R8-03", "фасад обслуживает запрос без companyId — арендатор из токена",
          "200, шаг new", ответ, ответ["статус"] == 200)

    # R8-04 — подмена параметра не выводит за область токена (ядро находки B-11).
    ответ = вызов(f"/api/v1/process/instances?subjectType=eco_object&subjectId={B.subject}"
                  f"&companyId={B.support_id}", проекция_а)
    пункт("R8-04", "токен заказчика А с подменённым companyId=Б",
          "403 SERVICE_TENANT_MISMATCH",
          ответ, ответ["статус"] == 403 and ответ["код"] == "SERVICE_TENANT_MISMATCH")

    # R8-05 — чужой экземпляр в своём контуре не виден.
    ответ = вызов(f"/api/v1/process/instances/{B.process}", проекция_а)
    пункт("R8-05", "токен заказчика А на экземпляре заказчика Б",
          "404 — в контуре А его нет", ответ, ответ["статус"] == 404)

    # R8-06 — токен второго заказчика работает в своём контуре (не «запретили всё»).
    ответ = вызов(f"/api/v1/process/instances/{B.process}", проекция_б)
    пункт("R8-06", "токен заказчика Б в своём контуре", "200, шаг new",
          ответ, ответ["статус"] == 200)

    # P-01 — доставка исхода внешней работы доходит (положительный контроль).
    ответ = вызов(f"/api/v1/process/instances/{A.process}/actions", проекция_а, method="POST",
                  body={"verb": "delivered",
                        "delivery": {"system": "Трек", "basis": "delivery",
                                     "reference": "R8-положительный-контроль"}})
    пункт("P-01", "доставка исхода внешней работы по ребру без слоёв полномочий",
          "200, шаг resolved", ответ, ответ["статус"] == 200)

    # P-02 — обычный handoff человека не затронут.
    человек = SimpleNamespace(id=A.person, email=A.email, name="Диспетчер заказчика А",
                              is_superadmin=False)
    handoff = sso.sign_sso_token(user=человек, company_id=A.core_id,
                                 companies=[{"id": str(A.core_id), "slug": A.slug,
                                             "role": "coordinator"}], aud="support")
    with httpx.Client(timeout=20.0) as client:
        вход = client.post(f"{ПОДДЕРЖКА}/api/v1/auth/sso", json={"token": handoff})
    тело = вход.json() if вход.headers.get("content-type", "").startswith("application/json") else {}
    запросы.append({"путь": "/api/v1/auth/sso", "метод": "POST", "статус": вход.status_code,
                    "ошибка": тело.get("error")})
    пункт("P-02", "обычный handoff человека через тот же издатель",
          "200, сессия поднята",
          {"статус": вход.status_code, "компания": тело.get("sso_company_id"),
           "ошибка": тело.get("error")},
          вход.status_code == 200 and тело.get("sso_company_id") == A.support_id)

    # P-03 — выданный токен не раздаёт лишнего: срок жизни и область прежние.
    пункт("P-03", "свойства токена не расширены: срок жизни и скоуп",
          "exp-iat = 120 с, svc = projection",
          {"ttl": разбор["claims"]["exp"] - разбор["claims"]["iat"],
           "svc": разбор["claims"].get("svc")},
          разбор["claims"]["exp"] - разбор["claims"]["iat"] == 120
          and разбор["claims"].get("svc") == "projection")

    издатель.shutdown()

    красные = [p for p in пункты if p["итог"] == "КРАСНО"]
    итог = {"метка": МЕТКА,
            "ядро_поддерживает_арендатора_в_подписи": ПОДДЕРЖИВАЕТ_АРЕНДАТОРА,
            "зелёных": len(пункты) - len(красные), "красных": len(красные),
            "пункты": пункты}
    ДОКАЗАТЕЛЬСТВА.mkdir(parents=True, exist_ok=True)
    (ДОКАЗАТЕЛЬСТВА / f"{МЕТКА}.json").write_text(
        json.dumps(итог, ensure_ascii=False, indent=2), encoding="utf-8")
    (ДОКАЗАТЕЛЬСТВА / f"{МЕТКА}-requests.json").write_text(
        json.dumps(запросы, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: итог[k] for k in ("метка", "зелёных", "красных")}, ensure_ascii=False))
    for p in пункты:
        print(f"{p['итог']:>7}  {p['id']}  {p['что']}")
    return 0


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
