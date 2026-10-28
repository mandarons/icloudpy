"""Session and cookie persistence tests (atomic save, merge, file modes)."""

import http.cookiejar as cookielib
import json
import os
import stat
import tempfile
import threading
import time
from unittest import TestCase
from unittest.mock import patch

import pytest

from icloudpy import session_store
from icloudpy.base import ICloudPyPasswordFilter, ICloudPySession


class FakeSession:
    """Just enough of ICloudPySession for the store."""

    def __init__(self, cookie_path):
        self.cookies = cookielib.LWPCookieJar(filename=cookie_path)


class FakeService:
    """Just enough of ICloudPyService for the store."""

    def __init__(self, directory, name="account", session_data=None):
        self.session_path = os.path.join(directory, f"{name}.session")
        self.cookiejar_path = os.path.join(directory, name)
        self.session = FakeSession(self.cookiejar_path)
        self.session_data = {"session_token": "synthetic", "trust_token": "synthetic"}
        if session_data is not None:
            self.session_data = session_data


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


def read_jar(path):
    """Load a cookie jar from disk and return {name: value}."""
    jar = cookielib.LWPCookieJar()
    jar.load(path, ignore_discard=True, ignore_expires=True)
    return {cookie.name: cookie.value for cookie in jar}


class SaveSessionDataTest(TestCase):
    """Session tokens are written atomically and owner-only."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.service = FakeService(self.directory)

    def test_writes_json_and_mode(self):
        session_store.save_session_data(self.service)

        assert json.loads(open(self.service.session_path, encoding="utf-8").read()) == self.service.session_data
        assert stat.S_IMODE(os.stat(self.service.session_path).st_mode) == 0o600

    def test_leaves_no_temporary_file(self):
        session_store.save_session_data(self.service)

        leftovers = [name for name in os.listdir(self.directory) if name.startswith(".tmp-")]
        assert leftovers == []

    def test_pre_existing_loose_mode_is_tightened(self):
        with open(self.service.session_path, "w", encoding="utf-8") as handle:
            handle.write("{}")
        os.chmod(self.service.session_path, 0o644)

        session_store.save_session_data(self.service)

        assert stat.S_IMODE(os.stat(self.service.session_path).st_mode) == 0o600

    def test_overwrites_previous_content(self):
        session_store.save_session_data(self.service)
        self.service.session_data = {"session_token": "new"}

        session_store.save_session_data(self.service)

        assert json.loads(open(self.service.session_path, encoding="utf-8").read()) == {"session_token": "new"}


class SaveCookiesTest(TestCase):
    """The jar is atomic, merged with the other writer, and owner-only."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.service = FakeService(self.directory)

    def test_saves_cookie_and_mode(self):
        add_cookie(self.service, "X-APPLE-WEBAUTH-PCS-Documents")

        session_store.save_cookies(self.service)

        assert "X-APPLE-WEBAUTH-PCS-Documents" in read_jar(self.service.cookiejar_path)
        assert stat.S_IMODE(os.stat(self.service.cookiejar_path).st_mode) == 0o600

    def test_merges_a_cookie_another_writer_added(self):
        # Another instance writes a cookie this service never saw.
        other = FakeService(self.directory)
        add_cookie(other, "X-APPLE-WEBAUTH-PCS-Documents", value="from-other")
        session_store.save_cookies(other)

        add_cookie(self.service, "X-APPLE-WEBAUTH-PCS-Photos", value="mine")
        session_store.save_cookies(self.service)

        saved = read_jar(self.service.cookiejar_path)
        assert saved["X-APPLE-WEBAUTH-PCS-Documents"] == "from-other"
        assert saved["X-APPLE-WEBAUTH-PCS-Photos"] == "mine"

    def test_in_memory_value_wins_over_disk(self):
        other = FakeService(self.directory)
        add_cookie(other, "X-APPLE-WEBAUTH-PCS-Documents", value="stale")
        session_store.save_cookies(other)

        add_cookie(self.service, "X-APPLE-WEBAUTH-PCS-Documents", value="fresh")
        session_store.save_cookies(self.service)

        assert read_jar(self.service.cookiejar_path)["X-APPLE-WEBAUTH-PCS-Documents"] == "fresh"

    def test_expired_disk_cookie_is_not_merged(self):
        other = FakeService(self.directory)
        add_cookie(other, "X-APPLE-WEBAUTH-PCS-Documents", value="dead", expires=int(time.time()) - 60)
        session_store.save_cookies(other)

        add_cookie(self.service, "X-APPLE-WEBAUTH-PCS-Photos", value="mine")
        session_store.save_cookies(self.service)

        assert "X-APPLE-WEBAUTH-PCS-Documents" not in read_jar(self.service.cookiejar_path)

    def test_corrupt_jar_is_replaced_not_fatal(self):
        with open(self.service.cookiejar_path, "w", encoding="utf-8") as handle:
            handle.write("not a cookie jar")
        add_cookie(self.service, "X-APPLE-WEBAUTH-PCS-Documents")

        session_store.save_cookies(self.service)

        assert "X-APPLE-WEBAUTH-PCS-Documents" in read_jar(self.service.cookiejar_path)

    def test_no_cookie_path_is_a_no_op(self):
        self.service.session.cookies.filename = None
        self.service.cookiejar_path = None

        session_store.save_cookies(self.service)

    def test_concurrent_writers_keep_both_cookies(self):
        first = FakeService(self.directory, name="account")
        second = FakeService(self.directory, name="account")
        add_cookie(first, "X-APPLE-WEBAUTH-PCS-Documents", value="one")
        add_cookie(second, "X-APPLE-WEBAUTH-PCS-Photos", value="two")

        barrier = threading.Barrier(2)

        def save(service):
            barrier.wait()
            for _ in range(20):
                session_store.save_cookies(service)

        threads = [threading.Thread(target=save, args=(service,)) for service in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        saved = read_jar(first.cookiejar_path)
        assert saved["X-APPLE-WEBAUTH-PCS-Documents"] == "one"
        assert saved["X-APPLE-WEBAUTH-PCS-Photos"] == "two"


class SaveSessionFilesTest(TestCase):
    """Both files are written under one call."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.service = FakeService(self.directory)

    def test_writes_both(self):
        add_cookie(self.service, "X-APPLE-WEBAUTH-PCS-Documents")

        session_store.save_session_files(self.service)

        assert os.path.exists(self.service.session_path)
        assert "X-APPLE-WEBAUTH-PCS-Documents" in read_jar(self.service.cookiejar_path)


class AtomicWriteFailureTest(TestCase):
    """A failed save must not leave a temporary file behind."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.service = FakeService(self.directory)

    def test_failure_cleans_up_and_propagates(self):
        with patch("icloudpy.session_store.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                session_store.save_session_data(self.service)

        leftovers = [name for name in os.listdir(self.directory) if name.startswith(".tmp-")]
        assert leftovers == []

    def test_jar_filename_is_recorded_when_missing(self):
        self.service.session.cookies.filename = None

        session_store.save_cookies(self.service)

        assert self.service.session.cookies.filename == self.service.cookiejar_path


class _FakeResponse:
    """Minimal requests.Response stand-in."""

    def __init__(self, payload, headers=None, status_code=200):
        self._payload = payload
        self.headers = headers or {"Content-Type": "application/json"}
        self.status_code = status_code
        self.ok = status_code < 400
        self.reason = "OK"

    def json(self):
        return self._payload


class _BadJsonResponse(_FakeResponse):
    def json(self):
        raise ValueError("no json")


class _SessionService:
    """The attributes ICloudPySession.request reads, and nothing else."""

    def __init__(self, directory):
        self.user = {"accountName": "user@example.com", "password": "synthetic"}
        self.session_data = {}
        self.password_filter = ICloudPyPasswordFilter("synthetic")
        self.session_path = os.path.join(directory, "account.session")
        self.cookiejar_path = os.path.join(directory, "account")
        self.session = ICloudPySession(self)
        self.session.cookies = cookielib.LWPCookieJar(filename=self.cookiejar_path)


class RequestPersistenceTest(TestCase):
    """The real session request path writes both files (not the test mock)."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.service = _SessionService(self.directory)

    def test_request_persists_session_data_and_cookies(self):
        response = _FakeResponse(
            {"ok": True},
            headers={"Content-Type": "application/json", "X-Apple-Session-Token": "synthetic-token"},
        )

        with patch("requests.sessions.Session.request", return_value=response):
            self.service.session.request("POST", "https://setup.example.invalid/validate")

        assert self.service.session_data["session_token"] == "synthetic-token"
        saved = json.loads(open(self.service.session_path, encoding="utf-8").read())
        assert saved["session_token"] == "synthetic-token"
        assert stat.S_IMODE(os.stat(self.service.session_path).st_mode) == 0o600
        assert os.path.exists(self.service.cookiejar_path)
        assert stat.S_IMODE(os.stat(self.service.cookiejar_path).st_mode) == 0o600

    def test_non_json_response_is_returned_untouched(self):
        response = _FakeResponse({}, headers={"Content-Type": "text/plain"})

        with patch("requests.sessions.Session.request", return_value=response):
            returned = self.service.session.request("POST", "https://setup.example.invalid/validate")

        assert returned is response

    def test_unparseable_json_is_returned_untouched(self):
        response = _BadJsonResponse({}, headers={"Content-Type": "application/json"})

        with patch("requests.sessions.Session.request", return_value=response):
            returned = self.service.session.request("POST", "https://setup.example.invalid/validate")

        assert returned is response
