"""Условные запросы: метка на чтении и 304 на повтор.

Проверяем не «есть ли заголовок», а то, из-за чего это легко сломать: что 304 уходит
без тела, что метка не появляется на не-JSON и на ошибках, что `Vary: Authorization`
на месте (иначе ответ одного пользователя мог бы достаться другому в том же браузере)
и что `Origin` из CORS в `Vary` не затёрт.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from app.http_cache import conditional_get


def _app() -> Starlette:
    async def spravochnik(request):
        return JSONResponse({"items": [1, 2, 3]})

    async def tekst(request):
        return PlainTextResponse("не json")

    async def oshibka(request):
        return JSONResponse({"detail": "нет"}, status_code=404)

    async def s_vary(request):
        return JSONResponse({"ok": True}, headers={"Vary": "Origin"})

    async def otkaz_limita(request):
        # Ровно то, что отдаёт `rate_limit_public`: JSON с кодом 429.
        return JSONResponse({"detail": "Слишком много попыток"}, status_code=429,
                            headers={"Retry-After": "59"})

    app = Starlette(routes=[
        Route("/spravochnik", spravochnik),
        Route("/tekst", tekst),
        Route("/oshibka", oshibka),
        Route("/s-vary", s_vary),
        Route("/limit", otkaz_limita),
        Route("/zapis", spravochnik, methods=["POST"]),
    ])
    app.middleware("http")(conditional_get)
    return app


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t")


@pytest.mark.asyncio
async def test_chtenie_poluchaet_metku(client):
    r = await client.get("/spravochnik")
    assert r.status_code == 200
    assert r.headers["etag"].startswith('"')
    assert r.headers["cache-control"] == "private, no-cache"
    assert "Authorization" in r.headers["vary"]
    assert r.json() == {"items": [1, 2, 3]}


@pytest.mark.asyncio
async def test_povtor_s_metkoy_daet_304_bez_tela(client):
    first = await client.get("/spravochnik")
    second = await client.get("/spravochnik", headers={"If-None-Match": first.headers["etag"]})
    assert second.status_code == 304
    assert second.content == b"", "304 обязан идти без тела — в этом вся экономия"
    assert second.headers["etag"] == first.headers["etag"]


@pytest.mark.asyncio
async def test_chuzhaya_metka_ne_sovpadaet(client):
    r = await client.get("/spravochnik", headers={"If-None-Match": '"postoronnyaya"'})
    assert r.status_code == 200 and r.json()["items"]


@pytest.mark.asyncio
async def test_zvezdochka_schitaetsya_sovpadeniem(client):
    r = await client.get("/spravochnik", headers={"If-None-Match": "*"})
    assert r.status_code == 304


@pytest.mark.asyncio
async def test_slabaya_metka_tozhe_sovpadaet(client):
    first = await client.get("/spravochnik")
    r = await client.get("/spravochnik", headers={"If-None-Match": "W/" + first.headers["etag"]})
    assert r.status_code == 304


@pytest.mark.asyncio
async def test_ne_json_i_oshibki_metku_ne_poluchayut(client):
    assert "etag" not in (await client.get("/tekst")).headers
    assert "etag" not in (await client.get("/oshibka")).headers


@pytest.mark.asyncio
async def test_otkaz_limita_ne_keshiruetsya(client):
    """Отказ лимита частоты не должен получать метку — ни при каком порядке цепочки.

    В цепочке приложения этот middleware стоит СНАРУЖИ `rate_limit_public`, то есть
    ответ 429 проходит через него. Если бы метка ставилась не только на 200, браузер
    начал бы кэшировать отказы и показывал бы «слишком много попыток» человеку,
    которого уже разблокировали. Защита — код, а не порядок регистрации: порядок
    меняется при любой правке соседних middleware (так и вышло, когда CORS перенесли
    наружу), а это условие — нет.
    """
    r = await client.get("/limit")
    assert r.status_code == 429
    assert "etag" not in r.headers
    assert "cache-control" not in r.headers
    assert r.headers["retry-after"] == "59", "свои заголовки отказа мы не теряем"


@pytest.mark.asyncio
async def test_zapis_metku_ne_poluchaet(client):
    r = await client.post("/zapis")
    assert r.status_code == 200 and "etag" not in r.headers


@pytest.mark.asyncio
async def test_vary_ot_cors_ne_zatert(client):
    r = await client.get("/s-vary")
    vary = r.headers["vary"]
    assert "Origin" in vary and "Authorization" in vary
