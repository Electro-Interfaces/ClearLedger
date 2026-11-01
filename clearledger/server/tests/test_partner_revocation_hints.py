"""AUTHORED / NOTCOLLECTED / NOTRUN: actual RFC7009 parameter override.

No extracted implementation or replacement parser. Parent conftest imports the
application before module admission: ROOT must isolate it before any collection.
"""
import os

import pytest
from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_PARTNER_IDENTITY_TESTS") != "1":
    pytest.skip("Existing partner opt-in required; author execution NOT_GRANTED", allow_module_level=True)
if error := partner_test_safety_error(os.environ):
    raise RuntimeError(error)
if os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL"):
    raise RuntimeError("Existing isolated partner composition must use matching URLs")

from authlib.oauth2.rfc6749 import InvalidRequestError
from app.services import partner_identity as identity


@pytest.mark.parametrize("hint", [None, "unregistered-hint", "access_token", "refresh_token", ""])
@pytest.mark.parametrize("token", ["", "synthetic-access", "synthetic-refresh"])
def test_actual_check_params_requires_presence_not_truthiness_and_ignores_hint(monkeypatch, token, hint):
    monkeypatch.setattr(identity.settings, "partner_oauth_issuer", "https://identity.example")
    form = {"token": token}
    if hint is not None:
        form["token_type_hint"] = hint
    request = identity.ProtocolRequest("POST", form)
    # The actual override needs neither a server nor an authenticated client.
    # Type fallback and ownership are asserted through real HTTP in the PG file.
    assert identity.RevokeEndpoint.check_params(None, request, None) is None


@pytest.mark.parametrize("hint", [None, "unregistered-hint", "access_token", "refresh_token", ""])
def test_actual_check_params_missing_token_keeps_invalid_request(monkeypatch, hint):
    monkeypatch.setattr(identity.settings, "partner_oauth_issuer", "https://identity.example")
    form = {} if hint is None else {"token_type_hint": hint}
    with pytest.raises(InvalidRequestError) as error:
        identity.RevokeEndpoint.check_params(None, identity.ProtocolRequest("POST", form), None)
    assert error.value.error == "invalid_request"
    assert error.value.description == InvalidRequestError().description
