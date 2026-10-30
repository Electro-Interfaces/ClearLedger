"""Synthetic localhost Uvicorn proof; no application, DB, auth or real credentials.

Run with --noconftest and server/ on absolute PYTHONPATH. Child processes use only
this ASGI callable and inherit an already-bound ephemeral localhost socket.
"""
import asyncio
from importlib.util import find_spec
import logging
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile

import pytest

from app.api_access_logging import OAuthAccessFilter, install_oauth_access_filters


SENTINEL = "SYNTHETIC_WS_AUTHORITY_20261030"


async def synthetic_app(scope, receive, send):
    if scope["type"] == "http":
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"synthetic"})
        return
    assert scope["type"] == "websocket"
    assert (await receive())["type"] == "websocket.connect"
    if scope["path"] == "/refused":
        await send({"type": "websocket.close", "code": 1008})
    elif scope["path"] == "/denied":
        await send({"type": "websocket.http.response.start", "status": 401, "headers": []})
        await send({"type": "websocket.http.response.body", "body": b"denied"})
    else:
        await send({"type": "websocket.accept"})
        while (await receive())["type"] != "websocket.disconnect":
            pass


def _request(port, target, websocket=False):
    headers = (
        "Connection: Upgrade\r\nUpgrade: websocket\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Key: c3ludGhldGljLWtleS0xNg==\r\n"
        if websocket else "Connection: close\r\n"
    )
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall((f"GET {target} HTTP/1.1\r\nHost: localhost\r\n{headers}\r\n").encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = client.recv(4096)
            assert chunk, response
            response += chunk
        return int(response.split(b" ", 2)[1])


def _capture(filtered, backend):
    # Reserve the port until inherited by our child: no free-port race.
    with socket.socket() as listener, tempfile.TemporaryFile(mode="w+") as output:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve",
             str(listener.fileno()), str(int(filtered)), backend],
            pass_fds=(listener.fileno(),), stdout=output, stderr=subprocess.STDOUT,
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                 "PYTHONDONTWRITEBYTECODE": "1"},
        )
        try:
            assert _request(port, f"/accepted?token={SENTINEL}", True) == 101
            assert _request(port, f"/refused?token={SENTINEL}", True) == 403
            assert _request(port, f"/denied?access_token={SENTINEL}", True) == 401
            assert _request(port, "/ordinary-ws?q=charger&page=2", True) == 101
            assert _request(port, f"/ordinary-http?token={SENTINEL}") == 200
            assert _request(port, "/ordinary-http?q=charger&page=2") == 200
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        output.seek(0)
        logs = output.read()
        # Uvicorn 0.34 re-raises captured SIGTERM after graceful shutdown.
        assert process.returncode in (0, -signal.SIGTERM), logs
        assert "Finished server process" in logs, logs
        return logs


@pytest.mark.parametrize("backend", ["websockets", "wsproto"])
@pytest.mark.parametrize("filtered", [False, True], ids=["baseline", "candidate"])
def test_uvicorn_wire_handshake_and_http_logs(filtered, backend):
    if find_spec(backend) is None:
        pytest.skip(f"{backend} unavailable; source-backed format proof is in pure tests")
    logs = _capture(filtered, backend)
    for path, status in [("accepted", "[accepted]"), ("refused", "403"), ("denied", "401")]:
        target = f"/{path}" if filtered else f"/{path}?{'access_token' if path == 'denied' else 'token'}={SENTINEL}"
        assert f'"WebSocket {target}" {status}' in logs, logs
    assert (SENTINEL in logs) is not filtered, logs
    assert '"WebSocket /ordinary-ws?q=charger&page=2" [accepted]' in logs
    assert '"GET /ordinary-http HTTP/1.1" 200' in logs
    assert '"GET /ordinary-http?q=charger&page=2 HTTP/1.1" 200' in logs


def _serve():
    import uvicorn

    descriptor, filtered, backend = sys.argv[2:]
    config = uvicorn.Config(synthetic_app, ws=backend, http="h11", loop="asyncio",
                            lifespan="off", log_level="info", timeout_graceful_shutdown=1)
    # Config installs its handlers first, just as in the production launch.
    if filtered == "1":
        install_oauth_access_filters()
    else:
        # Reproduce the original installation: HTTP access logs already filtered.
        for name in ("uvicorn.access", "gunicorn.access"):
            logging.getLogger(name).addFilter(OAuthAccessFilter())
    with socket.socket(fileno=int(descriptor)) as listener:
        asyncio.run(uvicorn.Server(config).serve(sockets=[listener]))


if __name__ == "__main__":
    assert sys.argv[1] == "--serve"
    _serve()
