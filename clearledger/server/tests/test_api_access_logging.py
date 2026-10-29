import logging

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
    for name in ("uvicorn.access", "gunicorn.access"):
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
