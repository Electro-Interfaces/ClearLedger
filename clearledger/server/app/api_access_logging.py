"""Redact query authority in standard HTTP access and WS handshake records."""
from collections.abc import Mapping
from copy import copy
import logging
import re

_PRIVATE = ("/api/oauth2/", "/api/developer/docs/", "/developer/")
_AUTH_QUERY = re.compile(r"(?:^|&)(?:code|state|access_token|refresh_token|id_token|token)=", re.I)
# Uvicorn 0.34.0 websockets_impl and wsproto_impl emit these on uvicorn.error.
_WS_HANDSHAKE_FORMATS = {
    '%s - "WebSocket %s" [accepted]': 2,
    '%s - "WebSocket %s" 403': 2,
    '%s - "WebSocket %s" %d': 3,
}


def safe_target(target):
    if not isinstance(target, str):
        return target
    path, separator, query = target.partition("?")
    # Chat requires a query credential; its key can also be percent-encoded.
    if path == "/api/chat/ws":
        return path
    return path if separator and (path.startswith(_PRIVATE) or _AUTH_QUERY.search(query)) else target


class OAuthAccessFilter(logging.Filter):
    def filter(self, record):
        if record.name == "uvicorn.error":
            # This logger also carries arbitrary errors/exceptions. Only touch the
            # URL argument of the pinned backend's known handshake formats.
            if (isinstance(record.msg, str) and isinstance(record.args, tuple)
                    and len(record.args) == _WS_HANDSHAKE_FORMATS.get(record.msg)):
                args = list(record.args)
                args[1] = safe_target(args[1])
                record.args = tuple(args)
            return True
        if isinstance(record.args, tuple) and len(record.args) == 5:
            # Uvicorn emits (client, method, path_with_query, http_version, status).
            args = list(record.args)
            args[2] = safe_target(args[2])
            record.args = tuple(args)
        elif isinstance(record.args, Mapping):
            # Gunicorn's default and custom atom formats share this mapping.
            # Preserve SafeAtoms' missing/custom-header fallback and escaping.
            atoms = copy(record.args)
            target = f'{atoms.get("U") or ""}?{atoms.get("q") or ""}'
            private = safe_target(target) != target
            if private:
                atoms["q"] = ""
                atoms["r"] = f'{atoms.get("m", "-")} {atoms.get("U", "-")} {atoms.get("H", "-")}'
            atoms["f"] = safe_target(atoms.get("f", "-"))
            for key in atoms:
                if str(key).lower() in {"{authorization}i", "{cookie}i", "{set-cookie}o"}:
                    atoms[key] = "[redacted]"
                elif str(key).lower() == "{referer}i":
                    atoms[key] = safe_target(atoms[key])
            record.args = atoms
        return True


def install_oauth_access_filters():
    for name in ("uvicorn.access", "gunicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, OAuthAccessFilter) for item in logger.filters):
            logger.addFilter(OAuthAccessFilter())
