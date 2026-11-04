"""Advanced Data Protection (PCS) tests.

Every fixture here is synthetic: cookie names come from Apple's own web client
and all values are placeholders. Nothing in this file was copied from another
implementation -- the scenarios follow the documented request/response contract.
"""

import http.cookiejar as cookielib
import json
import os
import tempfile
import time
from unittest import TestCase
from unittest.mock import patch

import pytest

from icloudpy import pcs
from icloudpy.exceptions import (
    ICloudPyPCSAppNameMismatchException,
    ICloudPyPCSRequiredException,
    ICloudPyPCSTimeoutException,
    ICloudPyWebAccessDisabledException,
    ICloudPyWebSessionIncompleteException,
)

from . import ICloudPyServiceMock
from .const import AUTHENTICATED_USER, CLIENT_ID, VALID_PASSWORD

PHOTOS_COOKIES = ("X-APPLE-WEBAUTH-PCS-Photos", "X-APPLE-WEBAUTH-PCS-Sharing")
DRIVE_COOKIES = ("X-APPLE-WEBAUTH-PCS-Documents",)
WEB_AUTH = "X-APPLE-WEBAUTH-TOKEN"


class FakeSession:
    """Minimal stand-in for ICloudPySession."""

    def __init__(self, cookie_path=None):
        self.cookies = cookielib.LWPCookieJar()
        if cookie_path:
            self.cookies.filename = cookie_path
        self.headers = {"Origin": "https://www.icloud.com", "Referer": "https://www.icloud.com/"}
        self.verify = True


class FakeService:
    """The parts of ICloudPyService that pcs.py reads."""

    def __init__(self, directory, webservices=None, dsid=None, cookies=()):
        self.session = FakeSession(os.path.join(directory, "account"))
        self.params = {"clientId": "synthetic-client"}
        self.data = {"webservices": webservices or {}, "dsInfo": {}}
        if dsid:
            self.data["dsInfo"]["dsid"] = dsid
        self.setup_endpoint = "https://setup.example.invalid/setup/ws/1"
        self._webservices = None
        self.session_path = os.path.join(directory, "account.session")
        self.cookiejar_path = os.path.join(directory, "account")
        for name in cookies:
            add_cookie(self, name, expires=None)


def add_cookie(service, name, *, value="synthetic", expires=None):
    """Put a cookie in the service's jar."""
    service.session.cookies.set_cookie(
        cookielib.Cookie(
            0,
            name,
            value,
            None,
            False,
            ".icloud.com",
            True,
            False,
            "/",
            True,
            False,
            expires,
            False,
            None,
            None,
            {},
        ),
    )


class Backend:
    """Scripted replacement for pcs._post."""

    def __init__(self):
        self.calls = []
        self.responses = []

    def push(self, status, payload, cookies=()):
        self.responses.append((status, payload, cookies))

    def __call__(self, api, path, body=None, **kwargs):
        self.calls.append((path, body, kwargs))
        if path == pcs.GENERATE_SESSION_ID_TOKEN:
            # Minted best-effort between consent and the cookie request; not
            # what these cases script, so it answers itself. Ordering and the
            # request itself are asserted in PCSWireShapeTest.
            return 200, {}
        status, payload, cookies = self.responses.pop(0)
        for name in cookies:
            add_cookie(api, name)
        return status, payload

    def paths(self):
        return [path for path, _, _ in self.calls]

    def bodies(self):
        return [body for _, body, _ in self.calls]

    def kwargs(self):
        return [kwargs for _, _, kwargs in self.calls]


def web_state(*, allowed: bool | None = True, consented: bool | None = True, drs_disabled: bool | None = True):
    """A requestWebAccessState payload."""
    return {
        "isWebAccessAllowed": allowed,
        "isDeviceConsentedForPCS": consented,
        "isICDRSDisabled": drs_disabled,
        "deviceConsentForPCSExpiry": 1_700_000_000_000,
    }


class PCSTestBase(TestCase):
    """Shared fixture: a service that advertises PCS for both services."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.api = FakeService(
            self.directory,
            webservices={
                "ckdatabasews": {"url": "https://photos.invalid", "pcsRequired": True},
                "drivews": {"url": "https://drive.invalid", "pcsRequired": True},
            },
            dsid="synthetic-dsid",
            cookies=(WEB_AUTH,),
        )
        self.backend = Backend()
        patcher = patch.object(pcs, "_post", self.backend)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(pcs, "_sleep", lambda _seconds: None)
        sleeper.start()
        self.addCleanup(sleeper.stop)


class EnsurePCSFastPathsTest(PCSTestBase):
    """Cases that must cost zero requests."""

    def test_cookies_already_present_make_no_request(self):
        add_cookie(self.api, PHOTOS_COOKIES[0])
        add_cookie(self.api, PHOTOS_COOKIES[1])

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.ALREADY_PRESENT
        assert set(result.cookies_present) == set(PHOTOS_COOKIES)
        assert self.backend.calls == []

    def test_expired_cookie_is_not_treated_as_present(self):
        add_cookie(self.api, PHOTOS_COOKIES[0], expires=int(time.time()) - 60)
        add_cookie(self.api, PHOTOS_COOKIES[1], expires=int(time.time()) - 60)
        self.backend.push(200, web_state())
        self.backend.push(200, {"status": "success"}, PHOTOS_COOKIES)

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.ACQUIRED
        assert self.backend.paths()[0] == pcs.REQUEST_WEB_ACCESS_STATE

    def test_service_without_pcs_required_is_untouched(self):
        self.api.data["webservices"]["ckdatabasews"] = {"url": "https://photos.invalid"}

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.NOT_REQUIRED
        assert self.backend.calls == []

    def test_drs_enabled_means_not_required(self):
        self.backend.push(200, web_state(drs_disabled=False))

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.NOT_REQUIRED
        assert result.adp is pcs.ADP.OFF

    def test_drs_message_from_request_pcs_means_not_required(self):
        self.backend.push(200, web_state(consented=None))
        self.backend.push(412, {"status": "failure", "message": "User has not disabled iCloud DRS."})

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.NOT_REQUIRED


class EnsurePCSConsentTest(PCSTestBase):
    """Consent handling and the on_waiting hook."""

    def test_consent_already_granted_skips_the_prompt(self):
        self.backend.push(200, web_state(consented=True))
        self.backend.push(
            200,
            {"status": "success", "message": "Cookies attached."},
            PHOTOS_COOKIES,
        )

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.ACQUIRED
        assert pcs.ENABLE_DEVICE_CONSENT not in self.backend.paths()

    def test_prompt_fires_on_waiting_exactly_once(self):
        waited = []
        self.backend.push(200, web_state(consented=False))
        self.backend.push(200, {"isDeviceConsentNotificationSent": True})
        self.backend.push(200, web_state(consented=True))
        self.backend.push(200, {"status": "failure", "message": pcs.PENDING_MESSAGES[0]})
        self.backend.push(200, {"status": "success"}, PHOTOS_COOKIES)

        result = pcs.ensure_pcs(self.api, "photos", on_waiting=lambda: waited.append(1))

        assert result.status == pcs.ACQUIRED
        assert len(waited) == 1
        assert self.backend.paths().count(pcs.ENABLE_DEVICE_CONSENT) == 1

    def test_prompt_not_sent_raises(self):
        self.backend.push(200, web_state(consented=False))
        self.backend.push(200, {"isDeviceConsentNotificationSent": False})

        with pytest.raises(ICloudPyPCSRequiredException):
            pcs.ensure_pcs(self.api, "photos")

    def test_consent_timeout_is_bounded(self):
        self.backend.push(200, web_state(consented=False))
        self.backend.push(200, {"isDeviceConsentNotificationSent": True})
        for _ in range(2):
            self.backend.push(200, web_state(consented=False))

        with pytest.raises(ICloudPyPCSTimeoutException) as caught:
            pcs.ensure_pcs(self.api, "photos", timeout=10, interval=5)

        assert caught.value.attempts == 2

    def test_unknown_consent_probes_without_notifying(self):
        self.backend.push(200, web_state(consented=None))
        self.backend.push(200, {"status": "success"}, PHOTOS_COOKIES)

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.ACQUIRED
        probe = self.backend.bodies()[1]
        assert probe["derivedFromUserAction"] is False
        assert pcs.ENABLE_DEVICE_CONSENT not in self.backend.paths()


class EnsurePCSPollingTest(PCSTestBase):
    """The requestPCS poll itself."""

    def test_pending_then_success(self):
        self.backend.push(200, web_state())
        self.backend.push(200, {"status": "failure", "message": pcs.PENDING_MESSAGES[1]})
        self.backend.push(200, {"status": "success"}, PHOTOS_COOKIES)

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.ACQUIRED
        assert self.backend.paths().count(pcs.REQUEST_PCS) == 2

    def test_success_without_cookie_raises_mismatch(self):
        self.backend.push(200, web_state())
        self.backend.push(200, {"status": "success"})

        with pytest.raises(ICloudPyPCSAppNameMismatchException) as caught:
            pcs.ensure_pcs(self.api, "photos")

        assert set(caught.value.missing) == set(PHOTOS_COOKIES)

    def test_derived_from_user_action_only_on_first_attempt(self):
        self.backend.push(200, web_state())
        self.backend.push(200, {"status": "failure", "message": pcs.PENDING_MESSAGES[0]})
        self.backend.push(200, {"status": "failure", "message": pcs.PENDING_MESSAGES[0]})
        self.backend.push(200, {"status": "success"}, PHOTOS_COOKIES)

        pcs.ensure_pcs(self.api, "photos")

        derived = [body["derivedFromUserAction"] for body in self.backend.bodies() if body and "appName" in body]
        assert derived == [True, False, False]

    def test_app_name_is_per_service(self):
        self.backend.push(200, web_state())
        self.backend.push(200, {"status": "success"}, DRIVE_COOKIES)
        pcs.ensure_pcs(self.api, "drive")
        drive_body = self.backend.bodies()[-1]
        assert drive_body["appName"] == "iclouddrive"

        self.backend.push(200, web_state())
        self.backend.push(200, {"status": "success"}, PHOTOS_COOKIES)
        pcs.ensure_pcs(self.api, "photos")
        photos_body = self.backend.bodies()[-1]
        assert photos_body["appName"] == "photos"

    def test_rejected_message_raises(self):
        self.backend.push(200, web_state())
        self.backend.push(200, {"status": "failure", "message": "Unknown PCS state"})

        with pytest.raises(ICloudPyPCSRequiredException):
            pcs.ensure_pcs(self.api, "photos")

    def test_retries_exhausted_raises_timeout(self):
        self.backend.push(200, web_state())
        for _ in range(3):
            self.backend.push(200, {"status": "failure", "message": pcs.PENDING_MESSAGES[0]})

        with pytest.raises(ICloudPyPCSTimeoutException) as caught:
            pcs.ensure_pcs(self.api, "photos", timeout=15, interval=5)

        assert caught.value.attempts == 3
        assert self.backend.paths().count(pcs.REQUEST_PCS) == 3

    def test_interrupt_returns_aborted(self):
        self.backend.push(200, web_state())
        self.backend.push(200, {"status": "failure", "message": pcs.PENDING_MESSAGES[0]})

        result = pcs.ensure_pcs(self.api, "photos", interrupt=lambda: True)

        assert result.status == pcs.ABORTED

    def test_broken_interrupt_hook_is_ignored(self):
        self.backend.push(200, web_state())
        self.backend.push(200, {"status": "success"}, PHOTOS_COOKIES)

        def explode():
            raise RuntimeError("boom")

        result = pcs.ensure_pcs(self.api, "photos", interrupt=explode)

        assert result.status == pcs.ACQUIRED


class EnsurePCSErrorTest(PCSTestBase):
    """Conditions that must raise a specific, actionable exception."""

    def test_web_access_disabled(self):
        self.backend.push(200, web_state(allowed=False))

        with pytest.raises(ICloudPyWebAccessDisabledException) as caught:
            pcs.ensure_pcs(self.api, "photos")

        assert "Access iCloud Data on the Web" in str(caught.value)

    def test_missing_web_auth_cookie_raises_incomplete(self):
        self.api.session.cookies.clear()

        with pytest.raises(ICloudPyWebSessionIncompleteException):
            pcs.ensure_pcs(self.api, "photos")

        assert self.backend.calls == []

    def test_expired_web_auth_cookie_raises_incomplete(self):
        self.api.session.cookies.clear()
        add_cookie(self.api, WEB_AUTH, expires=int(time.time()) - 60)

        with pytest.raises(ICloudPyWebSessionIncompleteException):
            pcs.ensure_pcs(self.api, "photos")

    def test_500_with_web_auth_message_is_incomplete(self):
        self.backend.push(200, web_state())
        self.backend.push(500, {"message": "Missing X-APPLE-WEBAUTH-TOKEN cookie"})

        with pytest.raises(ICloudPyWebSessionIncompleteException):
            pcs.ensure_pcs(self.api, "photos")

    def test_unknown_service_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown PCS service"):
            pcs.ensure_pcs(self.api, "calendar")


class PCSPredicateTest(PCSTestBase):
    """The local ``pcsRequired`` read."""

    def test_reads_webservices(self):
        assert pcs.pcs_required(self.api, "photos") is True

    def test_falls_back_to_data_when_webservices_absent(self):
        self.api._webservices = None
        assert pcs.pcs_required(self.api, "photos") is True

    def test_false_when_entry_missing(self):
        self.api.data = {"webservices": {}}
        self.api._webservices = {}
        assert pcs.pcs_required(self.api, "drive") is False

    def test_missing_flag_is_false(self):
        self.api._webservices = {"drivews": {"url": "https://drive.invalid"}}
        assert pcs.pcs_required(self.api, "drive") is False

    def test_malformed_entry_is_false(self):
        self.api._webservices = {"drivews": "not-a-dict"}
        assert pcs.pcs_required(self.api, "drive") is False


class PCSTransportTest(TestCase):
    """The private transport is single-shot and keeps the JSON body."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.api = FakeService(
            self.directory,
            webservices={"drivews": {"url": "https://drive.invalid", "pcsRequired": True}},
            dsid="synthetic-dsid",
            cookies=(WEB_AUTH,),
        )

    def test_post_sends_the_web_client_envelope_and_does_not_retry(self):
        calls = []

        class FakeResponse:
            status_code = 500

            def json(self):
                return {"message": "Missing X-APPLE-WEBAUTH-TOKEN cookie"}

        class FakeRequestsSession:
            def __init__(self):
                self.headers = {}

            def post(self, url, **kwargs):
                calls.append((url, kwargs))
                return FakeResponse()

        with patch.object(pcs.requests, "Session", FakeRequestsSession):
            status, payload = pcs._post(self.api, pcs.REQUEST_PCS, pcs._pcs_body(pcs._target("drive"), True))

        assert status == 500
        assert payload["message"] == "Missing X-APPLE-WEBAUTH-TOKEN cookie"
        assert len(calls) == 1
        kwargs = calls[0][1]
        sent = json.loads(kwargs["data"])
        assert sent["appName"] == "iclouddrive"
        assert sent["derivedFromUserAction"] is True
        assert sent["isFinalAttempt"] is False
        assert sent["workflowUuid"] == sent["workflowUuid"].upper()
        assert len(sent["workflowUuid"]) == 36
        assert kwargs["headers"]["Content-Type"] == "text/plain;charset=UTF-8"
        assert "json" not in kwargs
        assert kwargs["params"]["clientBuildNumber"] == pcs.CLIENT_BUILD_NUMBER
        assert kwargs["params"]["clientMasteringNumber"] == pcs.CLIENT_MASTERING_NUMBER
        assert kwargs["params"]["dsid"] == "synthetic-dsid"

    def test_params_include_dsid_only_when_present(self):
        assert pcs._params(self.api)["dsid"] == "synthetic-dsid"
        self.api.data = {"webservices": {}, "dsInfo": {}}
        assert "dsid" not in pcs._params(self.api)

    def test_params_carry_client_identity_without_account_data(self):
        self.api.data = []
        params = pcs._params(self.api)
        assert params == {
            "clientBuildNumber": pcs.CLIENT_BUILD_NUMBER,
            "clientMasteringNumber": pcs.CLIENT_MASTERING_NUMBER,
            "clientId": "synthetic-client",
        }


class PCSTimeoutMathTest(TestCase):
    """The deadline, not a fixed attempt count, decides how long we wait."""

    def test_attempts_derive_from_timeout(self):
        assert pcs._attempts(600, 5.0, None) == 120
        assert pcs._attempts(100, 5.0, None) == 20

    def test_explicit_attempts_win(self):
        assert pcs._attempts(600, 5.0, 3) == 3

    def test_zero_interval_does_not_divide_by_zero(self):
        assert pcs._attempts(600, 0, None) == 1


class PCSEdgeCaseTest(PCSTestBase):
    """Branches that only odd payloads or timing reach."""

    def test_web_access_off_surfaces_from_the_probe(self):
        self.backend.push(200, web_state(consented=None))
        self.backend.push(200, {"isWebAccessAllowed": False})

        with pytest.raises(ICloudPyWebAccessDisabledException):
            pcs.ensure_pcs(self.api, "photos")

    def test_rejected_probe_raises(self):
        self.backend.push(200, web_state(consented=None))
        self.backend.push(200, {"status": "failure", "message": "something unexpected"})

        with pytest.raises(ICloudPyPCSRequiredException):
            pcs.ensure_pcs(self.api, "photos")

    def test_pending_probe_falls_through_to_consent(self):
        self.backend.push(200, web_state(consented=None))
        self.backend.push(200, {"status": "failure", "message": pcs.PENDING_MESSAGES[0]})
        self.backend.push(200, {"isDeviceConsentNotificationSent": True})
        self.backend.push(200, web_state(consented=True))
        self.backend.push(200, {"status": "success"}, PHOTOS_COOKIES)

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.ACQUIRED

    def test_interrupt_during_consent_poll_aborts(self):
        self.backend.push(200, web_state(consented=False))
        self.backend.push(200, {"isDeviceConsentNotificationSent": True})

        result = pcs.ensure_pcs(self.api, "photos", interrupt=lambda: True)

        assert result.status == pcs.ABORTED

    def test_interrupt_between_cookie_polls_aborts(self):
        answers = iter([False, True])
        self.backend.push(200, web_state())
        self.backend.push(200, {"status": "failure", "message": pcs.PENDING_MESSAGES[0]})

        result = pcs.ensure_pcs(self.api, "photos", interrupt=lambda: next(answers))

        assert result.status == pcs.ABORTED

    def test_web_access_state_http_error_without_body_raises(self):
        self.backend.push(503, {})

        with pytest.raises(ICloudPyPCSRequiredException):
            pcs.ensure_pcs(self.api, "photos")

    def test_drs_reported_during_cookie_poll_means_not_required(self):
        self.backend.push(200, web_state())
        self.backend.push(412, {"status": "failure", "message": "User has not disabled iCloud DRS."})

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.NOT_REQUIRED


class PCSHelperTest(TestCase):
    """Small pure helpers, including their defensive branches."""

    def test_adp_is_undetermined_without_the_flag(self):
        assert pcs.WebAccessState().adp is pcs.ADP.UNDETERMINED

    def test_adp_reads_the_drs_flag(self):
        assert pcs.WebAccessState(is_icdrs_disabled=True).adp is pcs.ADP.ON
        assert pcs.WebAccessState(is_icdrs_disabled=False).adp is pcs.ADP.OFF

    def test_optional_bool_rejects_non_booleans(self):
        assert pcs._optional_bool("true") is None
        assert pcs._optional_bool(1) is None
        assert pcs._optional_bool(True) is True

    def test_consent_expiry_rejects_junk(self):
        assert pcs._consent_expiry(None) is None
        assert pcs._consent_expiry(True) is None
        assert pcs._consent_expiry(-1) is None
        assert pcs._consent_expiry(1e308) is None

    def test_consent_expiry_decodes_milliseconds(self):
        decoded = pcs._consent_expiry(1_700_000_000_000)
        assert decoded is not None
        assert decoded.tzinfo is not None

    def test_json_payload_returns_empty_for_non_json(self):
        class Broken:
            def json(self):
                raise ValueError("no json")

        assert pcs._json_payload(Broken()) == {}

    def test_json_payload_returns_empty_for_non_dict(self):
        class Listy:
            def json(self):
                return [1, 2]

        assert pcs._json_payload(Listy()) == {}

    def test_classify_marks_web_access_off(self):
        assert pcs._classify(200, {"isWebAccessAllowed": False}) == pcs._WEB_ACCESS_OFF

    def test_classify_marks_session_failures_incomplete(self):
        assert pcs._classify(421, {}) == pcs._INCOMPLETE
        assert pcs._classify(500, {"message": "Missing X-APPLE-WEBAUTH-TOKEN cookie"}) == pcs._INCOMPLETE

    def test_classify_unknown_payload(self):
        assert pcs._classify(200, {}) == pcs._UNKNOWN

    def test_sleep_delegates_to_time(self):
        with patch.object(pcs.time, "sleep") as sleeper:
            pcs._sleep(0.01)
        sleeper.assert_called_once_with(0.01)


class PCSServiceFacadeTest(TestCase):
    """ICloudPyService delegates to pcs and exposes the account flags."""

    def setUp(self):
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)

    def test_pcs_required_for_delegates(self):
        self.service._webservices = {"drivews": {"pcsRequired": True}}
        assert self.service.pcs_required_for("drive") is True

    def test_ensure_pcs_delegates(self):
        self.service._webservices = {"drivews": {}}
        assert self.service.ensure_pcs("drive").status == pcs.NOT_REQUIRED

    def test_fast_path_works_on_a_real_service(self):
        add_cookie(self.service, PHOTOS_COOKIES[0])
        add_cookie(self.service, PHOTOS_COOKIES[1])
        self.service._webservices = {"ckdatabasews": {"pcsRequired": True}}

        result = self.service.ensure_pcs("photos")

        assert result.status == pcs.ALREADY_PRESENT

    def test_account_flags_default_false(self):
        self.service.data.pop("termsUpdateNeeded", None)
        self.service.data.pop("isRepairNeeded", None)
        assert self.service.terms_update_needed is False
        assert self.service.repair_needed is False

    def test_account_flags_surface_from_sign_in_payload(self):
        self.service.data["termsUpdateNeeded"] = True
        self.service.data["isRepairNeeded"] = True
        assert self.service.terms_update_needed is True
        assert self.service.repair_needed is True

    def test_account_flags_tolerate_non_dict_data(self):
        self.service.data = []
        assert self.service.terms_update_needed is False
        assert self.service.repair_needed is False


class PCSDeadlineTest(PCSTestBase):
    """The timeout is one budget for the whole call, not one per phase."""

    def test_consent_and_cookie_polls_share_one_deadline(self):
        clock = {"t": 0.0}

        def fake_sleep(seconds):
            clock["t"] += seconds

        # Consent arrives on the very last poll the timeout allows for.
        self.backend.push(200, web_state(consented=False))
        self.backend.push(200, {"isDeviceConsentNotificationSent": True})
        for _ in range(19):
            self.backend.push(200, web_state(consented=False))
        self.backend.push(200, web_state(consented=True))

        with patch.object(pcs, "_sleep", fake_sleep), patch.object(pcs.time, "monotonic", lambda: clock["t"]):
            with pytest.raises(ICloudPyPCSTimeoutException):
                pcs.ensure_pcs(self.api, "photos", timeout=100, interval=5)

        # One deadline: the cookie poll must not get a second 100 s budget.
        assert clock["t"] == 100.0
        assert pcs.REQUEST_PCS not in self.backend.paths()

    def test_explicit_attempts_still_respect_the_deadline(self):
        clock = {"t": 0.0}

        def fake_sleep(seconds):
            clock["t"] += seconds

        self.backend.push(200, web_state(consented=False))
        self.backend.push(200, {"isDeviceConsentNotificationSent": True})
        for _ in range(4):
            self.backend.push(200, web_state(consented=False))

        with patch.object(pcs, "_sleep", fake_sleep), patch.object(pcs.time, "monotonic", lambda: clock["t"]):
            with pytest.raises(ICloudPyPCSTimeoutException):
                pcs.ensure_pcs(self.api, "photos", timeout=10, interval=5, max_attempts=10)

        # max_attempts would allow 50 s of polling, but the deadline stops it at 10.
        assert clock["t"] == 10.0


class PCSWireShapeTest(TestCase):
    """The request envelope Apple validates, and the redacted diagnostic.

    Values are the personal part of a PCS request, so the failure message may
    name the parameters, body keys and cookies but must never carry their
    values. These cases assert both halves of that.
    """

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.api = FakeService(
            self.directory,
            webservices={
                "ckdatabasews": {"url": "https://photos.invalid", "pcsRequired": True},
            },
            dsid="synthetic-dsid",
            cookies=(WEB_AUTH,),
        )
        self.requests_seen = []
        self.queue = []
        captured = self

        class RecordingResponse:
            def __init__(self, status, payload):
                self.status_code = status
                self._payload = payload

            def json(self):
                return self._payload

        class RecordingSession:
            def __init__(self):
                self.headers = {}

            def post(self, url, **kwargs):
                captured.requests_seen.append(("POST", url, kwargs))
                status, payload, cookies = captured.queue.pop(0)
                for name in cookies:
                    add_cookie(captured.api, name)
                return RecordingResponse(status, payload)

            def get(self, url, **kwargs):
                captured.requests_seen.append(("GET", url, kwargs))
                status, payload, _ = captured.queue.pop(0) if captured.queue else (200, {}, ())
                return RecordingResponse(status, payload)

        patcher = patch.object(pcs.requests, "Session", RecordingSession)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(pcs, "_sleep", lambda _seconds: None)
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def names(self):
        return [url.rsplit("/", 1)[-1] for _, url, _ in self.requests_seen]

    def workflows(self):
        return {
            json.loads(kwargs["data"])["workflowUuid"] for method, _, kwargs in self.requests_seen if method == "POST"
        }

    def test_web_access_state_carries_client_identity_and_workflow(self):
        self.queue.append((200, web_state(), ()))

        state = pcs.web_access_state(self.api, "photos")

        assert state.is_device_consented is True
        method, url, kwargs = self.requests_seen[0]
        assert method == "POST"
        assert url == "https://setup.example.invalid/setup/ws/1/requestWebAccessState"
        assert kwargs["params"]["clientBuildNumber"] == pcs.CLIENT_BUILD_NUMBER
        assert kwargs["params"]["clientMasteringNumber"] == pcs.CLIENT_MASTERING_NUMBER
        assert kwargs["headers"]["Content-Type"] == "text/plain;charset=UTF-8"
        assert list(json.loads(kwargs["data"])) == ["workflowUuid"]

    def test_one_workflow_id_spans_the_whole_acquisition(self):
        self.queue.extend(
            [
                (200, web_state(consented=False), ()),
                (200, {"isDeviceConsentNotificationSent": True}, ()),
                (200, web_state(consented=True), ()),
                (200, {}, ()),
                (200, {"status": "success"}, PHOTOS_COOKIES),
            ]
        )

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.ACQUIRED
        assert self.names() == [
            "requestWebAccessState",
            "enableDeviceConsentForPCS",
            "requestWebAccessState",
            "generateSessionIdToken",
            "requestPCS",
        ]
        assert [method for method, _, _ in self.requests_seen][3] == "GET"
        assert len(self.workflows()) == 1

    def test_session_id_token_failure_is_not_fatal(self):
        self.queue.extend(
            [
                (200, web_state(), ()),
                (418, {}, ()),
                (200, {"status": "success"}, PHOTOS_COOKIES),
            ]
        )

        result = pcs.ensure_pcs(self.api, "photos")

        assert result.status == pcs.ACQUIRED

    def test_session_id_token_request_that_breaks_is_swallowed(self):
        def boom(*args, **kwargs):
            raise RuntimeError("network down")

        with patch.object(pcs, "_post", boom):
            assert pcs._generate_session_id_token(self.api) is False

    def test_rejection_message_carries_the_shape_but_no_values(self):
        self.queue.append((422, {}, ()))

        with pytest.raises(ICloudPyPCSRequiredException) as caught:
            pcs.ensure_pcs(self.api, "photos")

        message = str(caught.value)
        assert "422" in message
        assert "requestWebAccessState" in message
        # What we need in a bug report: the schema.
        assert "clientBuildNumber" in message
        assert "clientMasteringNumber" in message
        assert "workflowUuid" in message
        assert WEB_AUTH in message
        assert "text/plain" in message
        # What must never be there: the account's identifiers and cookie values.
        assert "synthetic" not in message
        assert "synthetic-dsid" not in message
        assert "synthetic-client" not in message

    def test_shape_helper_reports_names_only(self):
        shape = pcs._shape(
            self.api,
            "POST",
            pcs.REQUEST_PCS,
            {"appName": "photos", "derivedFromUserAction": True, "workflowUuid": "abc"},
        )

        assert "params=[clientBuildNumber, clientId, clientMasteringNumber, dsid]" in shape
        assert "body=[appName, derivedFromUserAction, workflowUuid]" in shape
        assert f"cookies=[{WEB_AUTH}]" in shape
        assert "synthetic-dsid" not in shape
        assert "synthetic-client" not in shape
        assert "abc" not in shape
