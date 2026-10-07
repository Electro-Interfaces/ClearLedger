"""Распознавание враждебных действий и пороги эпизодов (`app/guard.py`)."""
from types import SimpleNamespace

from app import guard


def req(path="/api/x", status_ua="Mozilla/5.0", auth=None, method="GET", xff="1.2.3.4"):
    headers = {"user-agent": status_ua, "x-forwarded-for": f"{xff}, 10.10.70.99"}
    if auth:
        headers["authorization"] = auth
    return SimpleNamespace(url=SimpleNamespace(path=path), headers=headers, method=method, client=None)


def test_ловушки_и_инструменты():
    for p in ("/.env", "/.git/config", "/wp-login.php", "/blog/wp-includes/wlwmanifest.xml",
              "/phpmyadmin/", "/api/admin/export-all", "/api/graphql", "/api/config"):
        assert guard.is_trap(p), p
    for p in ("/api/sites/1/docs", "/api/meetings/config", "/projects", "/assets/index-a.js",
              "/api/admin/backups", "/support/"):
        assert not guard.is_trap(p), p
    assert guard.is_bad_ua("sqlmap/1.7.2#stable") and guard.is_bad_ua("Mozilla/5.0 Nuclei")
    assert not guard.is_bad_ua("Mozilla/5.0 (Windows NT 10.0) Chrome/128 Safari/537.36")


def test_адрес_клиента_первый_в_цепочке():
    assert guard.client_ip(req(xff="92.100.2.253")) == "92.100.2.253"


def test_шквал_отказов_и_выкачка():
    guard._probe.clear(); guard._reads.clear()
    r = req(xff="5.5.5.5")
    got = [guard.note_response(r, 404) for _ in range(guard.PROBE_BLOCK)]
    assert got[guard.PROBE_ALERT - 2] is None and got[guard.PROBE_ALERT - 1][0] == "probe"
    assert got[-1][0] == "probe_block"
    a = req(auth="Bearer t", xff="6.6.6.6")
    got = [guard.note_response(a, 200) for _ in range(guard.READ_ALERT)]
    assert got[-2] is None and got[-1][0] == "mass_read"


def test_подбор_пароля_по_учётной_записи():
    guard._login.clear()
    n = [guard.note_login_failed("A@x.ru", f"1.1.1.{i}") for i in range(guard.LOGIN_ALERT)]
    assert n[-1] == guard.LOGIN_ALERT  # адреса меняются — счёт по учётной записи


def test_внутренние_адреса_не_блокируются():
    assert guard._internal("10.10.70.50") and guard._internal("172.18.0.1") and guard._internal("127.0.0.1")
    assert not guard._internal("92.100.2.253") and guard._internal("мусор")
