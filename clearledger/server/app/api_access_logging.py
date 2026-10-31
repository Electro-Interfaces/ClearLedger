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

# These three source-owned URL families carry authority in a path segment.
_CAPABILITY_PREFIXES = ("/api/doc-share/", "/api/invite/", "/api/work/calendar/feed/")
_CAPABILITY_MARKER = "[redacted-capability-target]"
# Recognize raw percent spellings only to fail closed. No request path is decoded.
_CAPABILITY_PREFIX_SPELLINGS = re.compile("(?:" + "|".join(
    "".join(f"(?:{re.escape(char)}|(?i:%{ord(char):02x}))" for char in prefix)
    for prefix in _CAPABILITY_PREFIXES) + ")")
_VERIFY_SPELLING = re.compile(r"(?:v|%76)(?:e|%65)(?:r|%72)(?:i|%69)(?:f|%66)(?:y|%79)")


def safe_target(target):
    if not isinstance(target, str):
        return target
    # A probe, not URL normalization: malformed wrappers never become a new URL.
    probe = re.sub(r"^[\x00-\x20\x7f\"'<>]+", "", target)
    authority = re.match(r"(?i)^([a-z][a-z0-9+.-]*:)?//[^/?#]*", probe)
    head = authority.group(0) if authority else ""
    raw_path = probe[len(head):]
    capability_path = re.split(r"[?#]", raw_path, maxsplit=1)[0]
    prefix = next((p for p in _CAPABILITY_PREFIXES if capability_path.startswith(p)), None)
    # Preserve the real static rotate endpoint and its existing query policy.
    static_rotate = capability_path == "/api/work/calendar/feed/rotate"
    if static_rotate:
        prefix = None
    if prefix is None:
        # Encoded structural prefixes are ambiguous logging inputs, not routing evidence.
        if not static_rotate and _CAPABILITY_PREFIX_SPELLINGS.match(capability_path):
            return _CAPABILITY_MARKER
    else:
        if probe != target or re.search(r"[\x00-\x1f\x7f]", probe):
            return _CAPABILITY_MARKER
        if authority:
            scheme = (authority.group(1) or "").lower()
            host = head.split("//", 1)[1]
            if (scheme not in {"http:", "https:"} or not host or "@" in host
                    or re.search(r"[\x00-\x20\x7f\\<>\"']", host)):
                return _CAPABILITY_MARKER
        parts = capability_path[len(prefix):].split("/")
        if not parts[0]:
            return _CAPABILITY_MARKER
        if prefix == "/api/doc-share/":
            if len(parts) == 2 and _VERIFY_SPELLING.fullmatch(parts[0]):
                # GET /verify/{token} overlaps POST /{token}/ack|decide.
                if parts[0] != "verify" or parts[1] in {"ack", "decide"} or not parts[1]:
                    return _CAPABILITY_MARKER
                return head + prefix + "verify/[redacted]"
            if (len(parts) == 1 or len(parts) == 2 and parts[1] in {"ack", "decide"}
                    or len(parts) == 3 and parts[1] == "file" and parts[2]):
                return head + prefix + "/".join(["[redacted]", *parts[1:]])
        elif prefix == "/api/invite/":
            if (len(parts) == 1 or len(parts) == 2 and parts[1] in {"respond", "propose", "poll", "ics"}
                    or len(parts) == 3 and parts[1:] == ["poll", "vote"]):
                return head + prefix + "/".join(["[redacted]", *parts[1:]])
        else:
            if len(parts) == 1 and parts[0].endswith(".ics") and parts[0][:-4]:
                return head + prefix + "[redacted].ics"
        # Unknown suffix/empty/malformed shapes under a known family disclose no target.
        return _CAPABILITY_MARKER
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
            safe = safe_target(target)
            private = safe != target
            if private:
                atoms["q"] = ""
                if "U" in atoms:
                    atoms["U"] = safe
                atoms["r"] = f'{atoms.get("m", "-")} {safe if "U" in atoms else "-"} {atoms.get("H", "-")}'
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
