"""Контекст аудита HTTP-запроса; не содержит токенов, query string или тела."""
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

from starlette.requests import Request


@dataclass(frozen=True)
class SecurityContext:
    request_id: str
    ip: str
    peer: str
    path: str
    user_agent: str


current: ContextVar[SecurityContext | None] = ContextVar("security_context", default=None)


class SecurityContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from app.guard import client_ip
        request = Request(scope)
        context = SecurityContext(
            request_id=uuid4().hex, ip=client_ip(request),
            peer=request.client.host if request.client else "-",
            path=request.url.path[:200],
            user_agent=(request.headers.get("user-agent") or "")[:300],
        )
        token = current.set(context)

        async def traced_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [(k, v) for k, v in message.get("headers", [])
                                      if k.lower() != b"x-request-id"]
                message["headers"].append((b"x-request-id", context.request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, traced_send)
        finally:
            current.reset(token)
