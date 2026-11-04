"""ICloudPySession gives every request a timeout unless the caller sets one."""

import http.cookiejar as cookielib
import logging
import types
from unittest import mock

from requests import Session

from icloudpy import base
from tests import ICloudPySessionMock

# The test service swaps ``base.ICloudPySession`` for the mock; the real
# class is the mock's parent.
RealSession = ICloudPySessionMock.__bases__[0]


def _session(tmp_path):
    service = types.SimpleNamespace(
        password_filter=logging.Filter(),
        session_path=str(tmp_path / "session.json"),
        session_data={},
        cookiejar_path=str(tmp_path / "cookies"),
    )
    session = RealSession(service)
    session.cookies = cookielib.LWPCookieJar(filename=service.cookiejar_path)
    return session


def _send(session, **kwargs):
    response = types.SimpleNamespace(ok=True, status_code=200, headers={"Content-Type": "text/plain"})
    with mock.patch.object(Session, "request", return_value=response) as sent:
        session.request("GET", "https://example.invalid/", **kwargs)
    return sent.call_args.kwargs


def test_a_request_without_a_timeout_gets_the_default(tmp_path):
    assert _send(_session(tmp_path))["timeout"] == base.DEFAULT_TIMEOUT


def test_a_callers_timeout_is_kept(tmp_path):
    assert _send(_session(tmp_path), timeout=5)["timeout"] == 5
