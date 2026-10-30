import ast
from importlib.util import find_spec
import logging
from pathlib import Path

import pytest

from app.api_access_logging import OAuthAccessFilter, install_oauth_access_filters, safe_target


def test_uvicorn_access_record_drops_auth_query_before_formatting():
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", "/api/developer/docs/oauth2-redirect?code=PRIVATE&state=STATE", "1.1", 200), None)
    assert OAuthAccessFilter().filter(record)
    assert record.getMessage() == '127.0.0.1:1234 - "GET /api/developer/docs/oauth2-redirect HTTP/1.1" 200'


def test_gunicorn_default_and_custom_atoms_drop_authority():
    atoms = {"r": "GET /developer/api/callback?code=PRIVATE HTTP/1.1", "m": "GET",
        "U": "/developer/api/callback", "q": "code=PRIVATE", "H": "HTTP/1.1", "f": "https://example.invalid/cb?code=REFERER",
        "{authorization}i": "Bearer TOKEN", "{cookie}i": "COOKIE", "{set-cookie}o": "SESSION"}
    record = logging.LogRecord("gunicorn.access", logging.INFO, __file__, 1,
        '%(r)s %(q)s %(f)s %({authorization}i)s %({cookie}i)s %({set-cookie}o)s', (atoms,), None)
    assert OAuthAccessFilter().filter(record)
    message = record.getMessage()
    assert not any(value in message for value in ("PRIVATE", "REFERER", "TOKEN", "COOKIE", "SESSION"))
    assert atoms["q"] == "code=PRIVATE"  # Other consumers keep their own input mapping.


def test_normal_access_diagnostics_are_preserved():
    assert safe_target("/api/objects?q=charger&page=2") == "/api/objects?q=charger&page=2"
    assert safe_target("/ordinary?token=PRIVATE") == "/ordinary"
    assert safe_target("/developer/authorize?requestId=PRIVATE") == "/developer/authorize"
    assert safe_target("/api/oauth2/authorize?state=PRIVATE") == "/api/oauth2/authorize"


def test_filter_installation_is_idempotent():
    install_oauth_access_filters()
    install_oauth_access_filters()
    for name in ("uvicorn.access", "gunicorn.access", "uvicorn.error"):
        assert sum(isinstance(item, OAuthAccessFilter) for item in logging.getLogger(name).filters) == 1


def test_gunicorn_safe_atoms_keep_custom_header_and_missing_atom_semantics():
    from gunicorn.glogging import SafeAtoms
    atoms = SafeAtoms({"r": "GET /api/oauth2/authorize?state=PRIVATE HTTP/1.1", "m": "GET",
        "U": "/api/oauth2/authorize", "q": "state=PRIVATE", "H": "HTTP/1.1",
        "{referer}i": "https://example.invalid/cb?code=REFERER", "{custom}i": 'quoted"value'})
    record = logging.LogRecord("gunicorn.access", logging.INFO, __file__, 1,
        '%(r)s %({Referer}i)s %({Custom}i)s %({absent}i)s %(absent)s', (atoms,), None)
    OAuthAccessFilter().filter(record)
    assert record.getMessage() == 'GET /api/oauth2/authorize HTTP/1.1 https://example.invalid/cb quoted\\"value - -'


@pytest.mark.parametrize("backend", ["websockets_impl", "wsproto_impl"])
def test_pinned_backend_handshake_log_records_from_source(backend):
    # AST permits proof of wsproto's exact formats without installing/importing it.
    source = Path(find_spec("uvicorn").origin).parent / "protocols" / "websockets" / f"{backend}.py"
    tree = ast.parse(source.read_text())
    assert any(isinstance(node, ast.Call) and ast.unparse(node.func) == "logging.getLogger"
               and ast.literal_eval(node.args[0]) == "uvicorn.error"
               for node in ast.walk(tree))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and ast.unparse(node.func) == "self.logger.info"
             and any(isinstance(arg, ast.Call) and ast.unparse(arg.func) == "get_path_with_query_string"
                     for arg in node.args)]
    assert {ast.literal_eval(node.args[0]) for node in calls} == {
        '%s - "WebSocket %s" [accepted]', '%s - "WebSocket %s" 403', '%s - "WebSocket %s" %d',
    }
    assert len(calls) == 3
    from uvicorn.protocols.utils import get_path_with_query_string
    for call in calls:
        assert ast.unparse(call.args[1]) == "self.scope['client']"
        assert ast.unparse(call.args[2]) == "get_path_with_query_string(self.scope)"
        for query in (b"token=SYNTHETIC_AUTHORITY", b"ACCESS_TOKEN=SYNTHETIC_AUTHORITY", b"q=charger&page=2"):
            scope = {"path": "/api/chat/ws", "query_string": query}
            target = get_path_with_query_string(scope)
            args = (("127.0.0.1", 1234), target) + ((401,) if len(call.args) == 4 else ())
            record = logging.LogRecord("uvicorn.error", logging.INFO, str(source), call.lineno,
                                       ast.literal_eval(call.args[0]), args, None)
            before = record.getMessage()
            assert OAuthAccessFilter().filter(record)
            assert record.args[0] == args[0]
            assert record.args[2:] == args[2:]
            assert record.getMessage() == before.replace(target, safe_target(target))
            assert "SYNTHETIC_AUTHORITY" not in record.getMessage()


@pytest.mark.parametrize("message,args", [
    ("Ordinary error %s %s", ("client", "/ordinary?token=SYNTHETIC")),
    ("Ordinary error %s %s %s %s %s", ("client", "GET", "/ordinary?token=SYNTHETIC", "1.1", 500)),
    ("Ordinary error %(target)s", ({"target": "/ordinary?token=SYNTHETIC"},)),
    ('%s - "WebSocket %s" [accepted] (custom)', ("client", "/ordinary?token=SYNTHETIC")),
    ('client - "WebSocket /ordinary?token=SYNTHETIC" [accepted]', ()),
])
def test_uvicorn_error_non_handshake_records_unchanged(message, args):
    error = ValueError("synthetic exception")
    record = logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1, message,
                               args, (ValueError, error, None))
    original_args = record.args
    before = logging.Formatter().format(record)
    assert OAuthAccessFilter().filter(record)
    assert record.args is original_args
    assert logging.Formatter().format(record) == before


def test_handshake_filter_requires_exact_logger_format_and_arity():
    for logger, message, args in [
        ("custom.error", '%s - "WebSocket %s" [accepted]', ("client", "/ws?token=SYNTHETIC")),
        ("uvicorn.error", '%s - "WebSocket %s" [accepted]', ("client",)),
        ("uvicorn.error", ["custom", "message"], ("client", "/ws?token=SYNTHETIC")),
    ]:
        record = logging.LogRecord(logger, logging.INFO, __file__, 1, message, args, None)
        assert OAuthAccessFilter().filter(record)
        assert record.args is args
