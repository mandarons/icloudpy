"""Security key (WebAuthn) authentication tests for base.py."""

import base64
import json
from unittest import TestCase
from unittest.mock import MagicMock, patch

import pytest

from icloudpy.base import (
    SECURITY_KEY_ACCEPTED_STATUSES,
    build_security_key_assertion,
)
from icloudpy.exceptions import ICloudPyFailedLoginException

CHALLENGE = {
    "challenge": base64.b64encode(b"c" * 32).decode().rstrip("="),
    "keyHandles": [base64.b64encode(b"h" * 48).decode().rstrip("=")],
    "rpId": "apple.com",
}


def _assertion_response(user_handle=b"user"):
    """A stand-in for fido2's AuthenticatorAssertionResponse."""
    response = MagicMock()
    response.response.client_data = json.dumps(
        {"type": "webauthn.get", "challenge": "a-b_c"},
    ).encode()
    response.response.signature = b"sig"
    response.response.authenticator_data = b"auth"
    response.response.user_handle = user_handle
    response.raw_id = b"cred"
    return response


class TestBuildAssertion(TestCase):
    """``build_security_key_assertion`` produces Apple's payload."""

    def test_challenge_comes_from_client_data(self):
        """Keeps the value signed and the value declared in step."""
        payload = build_security_key_assertion(_assertion_response(), "apple.com")
        assert payload["challenge"] == "a+b/c"

    def test_binary_fields_are_standard_base64(self):
        payload = build_security_key_assertion(_assertion_response(), "apple.com")
        assert base64.b64decode(payload["signatureData"]) == b"sig"
        assert base64.b64decode(payload["authenticatorData"]) == b"auth"
        assert base64.b64decode(payload["credentialID"]) == b"cred"

    def test_user_handle_is_unpadded(self):
        payload = build_security_key_assertion(_assertion_response(), "apple.com")
        assert not payload["userHandle"].endswith("=")

    def test_absent_user_handle_is_empty(self):
        payload = build_security_key_assertion(
            _assertion_response(user_handle=None),
            "apple.com",
        )
        assert payload["userHandle"] == ""

    def test_request_id_is_always_present(self):
        payload = build_security_key_assertion(_assertion_response(), "apple.com")
        assert payload["requestId"] == ""
        payload = build_security_key_assertion(_assertion_response(), "apple.com", "r1")
        assert payload["requestId"] == "r1"


class TestAcceptedStatuses(TestCase):
    """Apple answers an accepted assertion with 409."""

    def test_409_is_accepted(self):
        assert 409 in SECURITY_KEY_ACCEPTED_STATUSES

    def test_ordinary_success_codes_are_accepted(self):
        assert {200, 204, 250} <= SECURITY_KEY_ACCEPTED_STATUSES

    def test_failures_are_not_accepted(self):
        assert not {400, 401, 403, 412, 500} & SECURITY_KEY_ACCEPTED_STATUSES


class TestSecurityKeyChallenge(TestCase):
    """``security_key_challenge`` reports what Apple is asking for."""

    def _service(self, payload):
        service = MagicMock()
        service.session.get.return_value.json.return_value = payload
        service.session_data = {"scnt": "s", "session_id": "i"}
        service.auth_endpoint = "https://idmsa.apple.com/appleauth/auth"
        return service

    def test_returns_the_challenge_when_present(self):
        from icloudpy.base import ICloudPyService

        service = self._service({"fsaChallenge": CHALLENGE})
        assert ICloudPyService.security_key_challenge.fget(service) == CHALLENGE

    def test_returns_none_when_absent(self):
        from icloudpy.base import ICloudPyService

        service = self._service({})
        assert ICloudPyService.security_key_challenge.fget(service) is None

    def test_returns_none_when_incomplete(self):
        from icloudpy.base import ICloudPyService

        service = self._service({"fsaChallenge": {"challenge": "x"}})
        assert ICloudPyService.security_key_challenge.fget(service) is None


class TestConfirmSecurityKey(TestCase):
    """``confirm_security_key`` submits an assertion and trusts the session."""

    def _service(self, status):
        service = MagicMock()
        service.session.post.return_value.status_code = status
        service.session_data = {"scnt": "s", "session_id": "i"}
        service.auth_endpoint = "https://idmsa.apple.com/appleauth/auth"
        service._get_auth_headers.return_value = {}
        service.requires_2sa = False
        return service

    def _confirm(self, service, **kwargs):
        from icloudpy.base import ICloudPyService

        return ICloudPyService.confirm_security_key(service, **kwargs)

    def test_409_completes_authentication(self):
        service = self._service(409)
        assert self._confirm(service, assertion={"credentialID": "x"}) is True
        service.trust_session.assert_called_once()

    def test_success_codes_complete_authentication(self):
        for status in (200, 204, 250):
            service = self._service(status)
            assert self._confirm(service, assertion={"credentialID": "x"}) is True

    def test_a_refusal_returns_false(self):
        service = self._service(400)
        assert self._confirm(service, assertion={"credentialID": "x"}) is False
        service.trust_session.assert_not_called()

    def test_a_supplied_assertion_uses_no_device(self):
        service = self._service(409)
        self._confirm(service, assertion={"credentialID": "x"})
        service.sign_security_key_challenge.assert_not_called()

    def test_signs_when_no_assertion_is_supplied(self):
        service = self._service(409)
        service.security_key_challenge = CHALLENGE
        service.fido2_devices = ["device"]
        service.sign_security_key_challenge.return_value = {"credentialID": "x"}
        assert self._confirm(service) is True
        service.sign_security_key_challenge.assert_called_once_with(CHALLENGE, "device")

    def test_raises_when_apple_is_not_asking(self):
        service = self._service(409)
        service.security_key_challenge = None
        with pytest.raises(ICloudPyFailedLoginException):
            self._confirm(service)

    def test_raises_when_no_device_is_attached(self):
        service = self._service(409)
        service.security_key_challenge = CHALLENGE
        service.fido2_devices = []
        with pytest.raises(ICloudPyFailedLoginException):
            self._confirm(service)


class TestFido2Devices(TestCase):
    """``fido2_devices`` degrades when the optional package is absent."""

    def test_empty_without_fido2(self):
        from icloudpy.base import ICloudPyService

        with patch.dict("sys.modules", {"fido2.hid": None}):
            assert ICloudPyService.fido2_devices.fget(MagicMock()) == []
