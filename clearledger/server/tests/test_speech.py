"""Речь в текст через распознаватель стека (28.10.2026): без распознавателя — внятный отказ."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_диктовка_без_распознавателя_и_пределы(auth_client, monkeypatch):
    from app.config import settings
    # Распознавателя в тестовом окружении нет: адрес заведомо закрыт.
    monkeypatch.setattr(settings, "asr_url", "http://127.0.0.1:9")
    r = await auth_client.get("/api/speech/health")
    assert r.status_code == 200 and r.json() == {"ready": False}

    r = await auth_client.post("/api/speech/dictate", files={"file": ("voice.webm", b"", "audio/webm")})
    assert r.status_code == 400, r.text
    r = await auth_client.post("/api/speech/dictate", files={"file": ("voice.webm", b"x" * (10 * 1024 * 1024 + 1), "audio/webm")})
    assert r.status_code == 413, r.text
    r = await auth_client.post("/api/speech/dictate", files={"file": ("voice.webm", b"webm", "audio/webm")})
    assert r.status_code == 503 and "недоступно" in r.json()["detail"], r.text


async def test_диктовка_только_вошедшим(client):
    r = await client.post("/api/speech/dictate", files={"file": ("voice.webm", b"webm", "audio/webm")})
    assert r.status_code == 401
