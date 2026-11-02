"""Проверки допуска: импорт не открывает БД и не загружает Ядро."""
from pathlib import Path
from urllib.parse import urlsplit
import os


def validate(environ=None, *, ddl=False):
    env = os.environ if environ is None else environ
    if env.get('RUN_PARTNER_PILOT_SANDBOX') != '1':
        raise ValueError('RUN_PARTNER_PILOT_SANDBOX=1 is required')
    raw = env.get('TEST_DATABASE_URL', '')
    try:
        url = urlsplit(raw)
        valid = (url.scheme == 'postgresql+asyncpg' and url.hostname == '127.0.0.1'
                 and url.port == 33546 and url.username == 'clearledger'
                 and url.password == 'api_test_only' and url.path == '/api_partner_pilots_test'
                 and not url.query and not url.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Explicit dedicated loopback pilot TEST_DATABASE_URL is required')
    upload = Path(env.get('UPLOAD_DIR', ''))
    if not upload.is_absolute() or 'test' not in upload.name.lower():
        raise ValueError('Explicit absolute test UPLOAD_DIR is required')
    # Это отдельное подтверждение оператора, а не разрешение из общего флага.
    if ddl and not env.get('PARTNER_SANDBOX_SQL_WINDOW', '').strip():
        raise ValueError('Separate root SQL-window authorization is required')
    return raw, upload
