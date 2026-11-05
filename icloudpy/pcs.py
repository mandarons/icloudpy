"""Advanced Data Protection (ADP) support.

Accounts with ADP enabled keep iCloud data end-to-end encrypted against their
own devices, so a web session cannot read it until Apple releases *per-service
encryption* (PCS) cookies to that session. Apple does that only after the user
approves a prompt on a trusted device, which makes this a human-in-the-loop
flow rather than something a daemon can do silently.

Three undocumented endpoints drive it, all ``POST`` to the setup endpoint:

``requestWebAccessState``
    Read-only. Reports ``isWebAccessAllowed``, ``isDeviceConsentedForPCS`` and
    ``isICDRSDisabled``. This is the only way to tell *why* access is refused.
``enableDeviceConsentForPCS``
    Pushes the approval prompt to the user's trusted devices.
``requestPCS``
    Issues the cookies once consent exists. ``status: failure`` with a
    "waiting" message means "not approved yet", not "failed".

Every call carries the client build numbers in the query string and, for a
``POST``, a JSON body tagged with the attempt's ``workflowUuid``: that is the
shape the icloud.com client uses, and the setup service answers a PCS request
without it ``422`` with an empty body -- a rejection that names nothing and
reads like a refusal. ``generateSessionIdToken`` is minted between consent and
the cookie request, best effort.

This module talks to those endpoints over its own :class:`requests.Session`
bound to the service's cookie jar, rather than through
:class:`icloudpy.base.ICloudPySession`. The session layer retries every 421/450/500
once and then rewrites the reason to "Authentication required for Account.",
which discards the JSON body these endpoints put their verdict in; its
rewriting is relied on elsewhere, so it is left untouched.

Two rules this module does not break: a ``423`` is also an Apple rate-limit
response and never proves ADP is on, and a service that does not advertise
``pcsRequired`` is left completely alone.
"""

from __future__ import annotations

import enum
import json
import logging
import time
import uuid

# Runtime import on purpose: Python 3.14 evaluates annotations lazily at
# access time (PEP 649), so a TYPE_CHECKING-only import makes
# inspect.signature()/get_type_hints() raise NameError on this module.
from collections.abc import Callable  # noqa: TC003
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from icloudpy import session_store
from icloudpy.exceptions import (
    ICloudPyPCSAppNameMismatchException,
    ICloudPyPCSRequiredException,
    ICloudPyPCSTimeoutException,
    ICloudPyWebAccessDisabledException,
    ICloudPyWebSessionIncompleteException,
)

LOGGER = logging.getLogger(__name__)

#: The web session cookie ``requestPCS`` needs. Without a live one Apple
#: answers 500 and no amount of retrying helps.
WEB_AUTH_COOKIE = "X-APPLE-WEBAUTH-TOKEN"

REQUEST_WEB_ACCESS_STATE = "/requestWebAccessState"
ENABLE_DEVICE_CONSENT = "/enableDeviceConsentForPCS"
REQUEST_PCS = "/requestPCS"
GENERATE_SESSION_ID_TOKEN = "/generateSessionIdToken"

#: Client fingerprints the PCS endpoints validate. The legacy setup endpoints
#: (``/validate``, ``/accountLogin``) accept a ``clientId``-only request, which
#: is why icloudpy never sent these -- but a PCS request without them is
#: answered 422 with an empty body, before any consent prompt can fire. The
#: values are the current icloud.com client's; bump them when Apple does.
CLIENT_BUILD_NUMBER = "2522Project44"
CLIENT_MASTERING_NUMBER = "2522B2"

#: ``icloud.com`` posts its PCS bodies as JSON under this content type, and
#: tags every call in one acquisition attempt with a shared ``workflowUuid``.
PCS_CONTENT_TYPE = "text/plain;charset=UTF-8"

#: ``requestPCS`` answers with one of these while the trusted device has not
#: finished uploading the keys. They mean "not ready", not "failed".
PENDING_MESSAGES = (
    "Requested the device to upload cookies.",
    "Cookies not available yet on server.",
)

DEFAULT_INTERVAL_SEC = 5.0
DEFAULT_TIMEOUT_SEC = 100.0
HTTP_TIMEOUT_SEC = 30.0

ALREADY_PRESENT = "already_present"
ACQUIRED = "acquired"
NOT_REQUIRED = "not_required"
UNDETERMINED = "undetermined"
ABORTED = "aborted"

_ACQUIRED = "acquired"
_PENDING = "pending"
_NOT_REQUIRED = "not_required"
_INCOMPLETE = "incomplete"
_WEB_ACCESS_OFF = "web_access_off"
_REJECTED = "rejected"
_UNKNOWN = "unknown"


class ADP(enum.StrEnum):
    """Tri-state ADP reading. ``UNDETERMINED`` is a real answer, not a guess."""

    ON = "on"
    OFF = "off"
    UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class PCSTarget:
    """One iCloud service and the cookie set Apple issues for it."""

    key: str
    webservice: str
    app_name: str
    cookies: tuple[str, ...]


#: ``app_name`` is what ``requestPCS`` expects and is *not* the webservice key.
#: A wrong value answers ``status: success`` and sets no cookie, so the result
#: is verified against the cookie names below.
TARGETS: dict[str, PCSTarget] = {
    "photos": PCSTarget(
        key="photos",
        webservice="ckdatabasews",
        app_name="photos",
        cookies=("X-APPLE-WEBAUTH-PCS-Photos", "X-APPLE-WEBAUTH-PCS-Sharing"),
    ),
    "drive": PCSTarget(
        key="drive",
        webservice="drivews",
        app_name="iclouddrive",
        cookies=("X-APPLE-WEBAUTH-PCS-Documents",),
    ),
}


@dataclass(frozen=True)
class WebAccessState:
    """What Apple reports about web access, and what it does not."""

    is_web_access_allowed: bool | None = None
    is_device_consented: bool | None = None
    is_icdrs_disabled: bool | None = None
    consent_expires_at: datetime | None = None

    @property
    def adp(self) -> ADP:
        """Whether Advanced Data Protection is on, off, or undetermined.

        iCloud Data Recovery Service being disabled is what makes ADP
        effective: with recovery enabled Apple still holds a key, and Apple
        answers ``requestPCS`` with 412 "User has not disabled iCloud DRS".
        """
        if self.is_icdrs_disabled is True:
            return ADP.ON
        if self.is_icdrs_disabled is False:
            return ADP.OFF
        return ADP.UNDETERMINED


@dataclass(frozen=True)
class PCSResult:
    """Outcome of an acquisition attempt. Cookie *names* only, never values."""

    service: str
    status: str
    cookies_present: tuple[str, ...] = ()
    cookies_missing: tuple[str, ...] = ()
    adp: ADP = ADP.UNDETERMINED


def _target(service: str) -> PCSTarget:
    """Resolve a service key, rejecting unknown ones loudly."""
    try:
        return TARGETS[str(service)]
    except KeyError:
        known = ", ".join(sorted(TARGETS))
        raise ValueError(f"Unknown PCS service {service!r}; expected one of: {known}") from None


def _optional_bool(value: Any) -> bool | None:
    """Return ``value`` only when Apple actually sent a boolean."""
    return value if isinstance(value, bool) else None


def _consent_expiry(value: Any) -> datetime | None:
    """Decode Apple's epoch-millisecond consent expiry."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except OverflowError, OSError, ValueError:
        return None


def pcs_required(api, service: str) -> bool:
    """Whether ``webservices.<key>.pcsRequired`` asks for a PCS cookie.

    This is a *local* read of the account data already in hand -- no request.
    It says "this service wants a cookie", not "ADP is on": a partial web
    session can set it on an account without ADP, which is why it is never
    reported to a user as proof of anything.
    """
    target = _target(service)
    webservices = getattr(api, "_webservices", None)
    if not webservices:
        data = getattr(api, "data", None)
        webservices = data.get("webservices") if isinstance(data, dict) else None
    entry = (webservices or {}).get(target.webservice)
    return bool(isinstance(entry, dict) and entry.get("pcsRequired"))


def _new_session(api) -> requests.Session:
    """A plain session sharing this service's cookie jar and headers."""
    session = requests.Session()
    session.cookies = api.session.cookies
    session.headers.update(dict(api.session.headers))
    session.verify = getattr(api.session, "verify", True)
    return session


def _params(api) -> dict[str, Any]:
    """Query parameters for every PCS call.

    ``clientBuildNumber``/``clientMasteringNumber`` are the client fingerprints
    the PCS endpoints validate; ``dsid`` is added when the account exposes one.
    """
    params: dict[str, Any] = {
        "clientBuildNumber": CLIENT_BUILD_NUMBER,
        "clientMasteringNumber": CLIENT_MASTERING_NUMBER,
    }
    params.update(getattr(api, "params", None) or {})
    data = getattr(api, "data", None)
    dsid = (data.get("dsInfo") or {}).get("dsid") if isinstance(data, dict) else None
    if dsid and "dsid" not in params:
        params["dsid"] = dsid
    return params


def _json_payload(response) -> dict[str, Any]:
    """Return a JSON object body, or an empty dict for anything else."""
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _new_workflow() -> str:
    """A per-attempt workflow id, the way the icloud.com client tags its calls."""
    return str(uuid.uuid4()).upper()


def _shape(api, method: str, path: str, body: dict[str, Any] | None) -> str:
    """Describe a request without recording anything personal.

    The *values* are the private part -- ``dsid``, ``clientId``, cookie values,
    the account's Apple ID -- so only the schema is described: which query
    parameters, which body keys, which cookie names, and the content type. That
    is what shows whether Apple rejected the request shape or the account
    state, and it is safe to paste into an issue.
    """
    params = ", ".join(sorted(_params(api)))
    keys = ", ".join(sorted(body)) if body else ""
    cookies = ", ".join(sorted({cookie.name for cookie in api.session.cookies}))
    content_type = PCS_CONTENT_TYPE if method != "GET" else ""
    return f"{method} {path} params=[{params}] body=[{keys}] content-type={content_type or '-'} cookies=[{cookies}]"


def _post(
    api,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    method: str = "POST",
    workflow: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """One HTTP request to a PCS endpoint, with no retry and no rewriting.

    Every call carries the client build numbers in the query string and, for a
    POST, a JSON body tagged with the attempt's ``workflowUuid`` -- the shape
    Apple's own web client sends. A POST without them is answered 422 with an
    empty body, which reads as a refusal rather than as a malformed request.

    The cookie jar is saved afterwards because Apple sets the PCS cookies on
    the ``requestPCS`` response itself.
    """
    session = _new_session(api)
    url = f"{api.setup_endpoint}{path}"
    sent: dict[str, Any] | None = None
    if method == "GET":
        response = session.get(url, params=_params(api), timeout=HTTP_TIMEOUT_SEC)
    else:
        sent = {"workflowUuid": workflow or _new_workflow(), **(body or {})}
        response = session.post(
            url,
            params=_params(api),
            data=json.dumps(sent),
            headers={"Content-Type": PCS_CONTENT_TYPE},
            timeout=HTTP_TIMEOUT_SEC,
        )
    LOGGER.debug("PCS request %s -> HTTP %s", _shape(api, method, path, sent), response.status_code)
    payload = _json_payload(response)
    session_store.save_cookies(api)
    return response.status_code, payload


def web_access_state(api, service: str, *, workflow: str | None = None) -> WebAccessState:
    """Ask Apple for the account's web-access state. Read-only."""
    target = _target(service)
    status, payload = _post(api, REQUEST_WEB_ACCESS_STATE, workflow=workflow)
    if not payload and status >= 400:
        raise ICloudPyPCSRequiredException(
            f"Apple refused the web-access check with HTTP {status}. "
            f"Request shape: {_shape(api, 'POST', REQUEST_WEB_ACCESS_STATE, {'workflowUuid': None})}",
            status,
            service=target.key,
            app_name=target.app_name,
        )
    return WebAccessState(
        is_web_access_allowed=_optional_bool(payload.get("isWebAccessAllowed")),
        is_device_consented=_optional_bool(payload.get("isDeviceConsentedForPCS")),
        is_icdrs_disabled=_optional_bool(payload.get("isICDRSDisabled")),
        consent_expires_at=_consent_expiry(payload.get("deviceConsentForPCSExpiry")),
    )


def request_device_consent(api, service: str, *, workflow: str | None = None) -> bool:
    """Ask Apple to push the approval prompt. Returns whether it was sent."""
    target = _target(service)
    _, payload = _post(api, ENABLE_DEVICE_CONSENT, workflow=workflow)
    sent = bool(payload.get("isDeviceConsentNotificationSent"))
    LOGGER.info("PCS: approval prompt for %s requested (sent=%s)", target.key, sent)
    return sent


def _held(api, target: PCSTarget) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Which expected cookies are in the jar, and which are not."""
    names = {cookie.name for cookie in api.session.cookies}
    present = tuple(name for name in target.cookies if name in names)
    missing = tuple(name for name in target.cookies if name not in names)
    return present, missing


def _has_expired(api, target: PCSTarget) -> bool:
    """Whether any expected cookie is present but past its expiry.

    The jar is loaded with ``ignore_expires=True``, so presence alone proves
    nothing: ``requests`` drops an expired cookie on the way out and Apple
    answers 423.
    """
    now = time.time()
    return any(cookie.name in target.cookies and cookie.is_expired(now) for cookie in api.session.cookies)


def _has_web_auth_cookie(api) -> bool:
    """Whether the jar holds a live web-auth cookie."""
    now = time.time()
    return any(
        cookie.name == WEB_AUTH_COOKIE and cookie.value and not cookie.is_expired(now) for cookie in api.session.cookies
    )


def _attempts(timeout: float, interval: float, max_attempts: int | None) -> int:
    """How many polls fit in ``timeout``.

    The attempt count is derived from the deadline, so a caller-supplied
    timeout genuinely extends the wait instead of being capped by the default
    attempt count.
    """
    if max_attempts is not None:
        return max(1, int(max_attempts))
    if interval <= 0:
        return 1
    return max(1, int(timeout // interval))


def _past_deadline(deadline: float | None) -> bool:
    """Whether an overall deadline has passed. ``None`` means unbounded."""
    return deadline is not None and time.monotonic() >= deadline


def _once(callback: Callable[[], None] | None) -> Callable[[], None]:
    """Wrap ``callback`` so it fires at most once."""
    fired = False

    def fire() -> None:
        nonlocal fired
        if fired or callback is None:
            return
        fired = True
        callback()

    return fire


def _interrupted(interrupt: Callable[[], bool] | None) -> bool:
    """Poll the caller's interrupt hook; a broken hook never blocks the wait."""
    if interrupt is None:
        return False
    try:
        return bool(interrupt())
    except Exception:  # noqa: BLE001 - advisory hook, never fatal
        LOGGER.debug("PCS: interrupt callback raised; ignoring", exc_info=True)
        return False


def _sleep(seconds: float) -> None:
    """Sleep between polls. A module-level seam so tests do not wait."""
    time.sleep(seconds)


def _classify(status: int, payload: dict[str, Any]) -> str:
    """Map one PCS response onto the internal outcome vocabulary."""
    message = str(payload.get("message") or "")
    if payload.get("isWebAccessAllowed") is False:
        return _WEB_ACCESS_OFF
    if status == 412 or "iCloud DRS" in message:
        # iCloud Data Recovery Service is on, so ADP is not in effect and no
        # PCS cookie is needed. Apple words this as a failure.
        return _NOT_REQUIRED
    if status == 500 and WEB_AUTH_COOKIE in message:
        return _INCOMPLETE
    if status in (401, 421):
        return _INCOMPLETE
    if payload.get("status") == "success":
        return _ACQUIRED
    if message in PENDING_MESSAGES:
        return _PENDING
    if status >= 400 or payload.get("status") == "failure":
        return _REJECTED
    return _UNKNOWN


def _acquired(api, target: PCSTarget, adp: ADP = ADP.UNDETERMINED) -> PCSResult:
    """Build the success result, proving the cookies actually arrived."""
    present, missing = _held(api, target)
    if missing:
        raise ICloudPyPCSAppNameMismatchException(
            f"Apple reported success for '{target.app_name}' but did not set {', '.join(missing)}.",
            expected=target.cookies,
            missing=missing,
        )
    return PCSResult(service=target.key, status=ACQUIRED, cookies_present=present, adp=adp)


def _raise_for(
    outcome: str,
    status: int,
    payload: dict[str, Any],
    target: PCSTarget,
    *,
    shape: str = "",
) -> None:
    """Raise the specific exception a failed outcome maps to."""
    message = str(payload.get("message") or "") or f"HTTP {status}"
    detail = f" Request shape: {shape}" if shape else ""
    if outcome == _WEB_ACCESS_OFF:
        raise ICloudPyWebAccessDisabledException(
            "Advanced Data Protection is on but 'Access iCloud Data on the Web' is off. "
            "Turn it on in Settings -> Apple ID -> iCloud, then retry.",
            service=target.key,
            app_name=target.app_name,
        )
    if outcome == _INCOMPLETE:
        raise ICloudPyWebSessionIncompleteException(
            "This session cannot request access to your encrypted data. Sign in again with your password.",
            service=target.key,
            app_name=target.app_name,
        )
    raise ICloudPyPCSRequiredException(
        f"Apple refused the data-access request for '{target.app_name}': {message}.{detail}",
        service=target.key,
        app_name=target.app_name,
    )


def _pcs_body(target: PCSTarget, derived: bool) -> dict[str, Any]:
    """The ``requestPCS`` body the web client sends.

    ``derivedFromUserAction`` is true only on the first attempt: it is what
    makes Apple notify the phone, and repeating it re-notifies on every poll.
    ``isFinalAttempt`` stays false, matching the icloud.com client, which keeps
    polling rather than announcing a last try.
    """
    return {
        "appName": target.app_name,
        "derivedFromUserAction": derived,
        "isFinalAttempt": False,
    }


def _request_pcs(api, target: PCSTarget, *, derived: bool, workflow: str | None = None) -> tuple[int, dict[str, Any]]:
    """One ``requestPCS`` call.

    ``derivedFromUserAction`` is true only on the first attempt: it is what
    makes Apple notify the phone, and repeating it re-notifies on every poll.
    """
    return _post(api, REQUEST_PCS, _pcs_body(target, derived), workflow=workflow)


def _generate_session_id_token(api, workflow: str | None = None) -> bool:
    """Mint the session-id token the web client has before ``requestPCS``.

    icloud.com calls this between the consent poll and the cookie request. It
    is best effort: a failure here must not turn a working acquisition into an
    error, because the cookie request itself is what decides the outcome.
    """
    try:
        status, _ = _post(api, GENERATE_SESSION_ID_TOKEN, method="GET", workflow=workflow)
    except Exception as error:  # noqa: BLE001 - best effort, never fatal
        LOGGER.debug("PCS session-id token request failed: %s", type(error).__name__)
        return False
    return 200 <= status < 300


def ensure_pcs(
    api,
    service: str,
    *,
    on_waiting: Callable[[], None] | None = None,
    interrupt: Callable[[], bool] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    max_attempts: int | None = None,
    interval: float = DEFAULT_INTERVAL_SEC,
) -> PCSResult:
    """Make the PCS cookies for ``service`` available, or explain why not.

    Returns immediately with zero requests when the cookies are already held
    and unexpired, or when the service does not advertise ``pcsRequired``.

    ``on_waiting`` fires at most once, immediately before the first blocking
    poll -- the hook a consumer uses to tell its user to approve the prompt.
    ``interrupt`` is polled between attempts; when it answers true the call
    returns ``status="aborted"`` so a daemon stays responsive.

    Raises an :class:`ICloudPyPCSRequiredException` subclass for every failure,
    each carrying the service and app name.
    """
    target = _target(service)
    present, missing = _held(api, target)
    if not missing and not _has_expired(api, target):
        return PCSResult(service=target.key, status=ALREADY_PRESENT, cookies_present=present)
    if not pcs_required(api, service):
        return PCSResult(
            service=target.key,
            status=NOT_REQUIRED,
            cookies_present=present,
            cookies_missing=missing,
        )
    if not _has_web_auth_cookie(api):
        raise ICloudPyWebSessionIncompleteException(
            "No valid X-APPLE-WEBAUTH-TOKEN cookie is stored, so Apple will not release "
            "access to your encrypted data. Sign in again with your password.",
            service=target.key,
            app_name=target.app_name,
        )

    workflow = _new_workflow()
    state = web_access_state(api, target.key, workflow=workflow)
    if state.is_web_access_allowed is False:
        raise ICloudPyWebAccessDisabledException(
            "Advanced Data Protection is on but 'Access iCloud Data on the Web' is off. "
            "Turn it on in Settings -> Apple ID -> iCloud, then retry.",
            service=target.key,
            app_name=target.app_name,
            web_access=state,
        )
    if state.adp is ADP.OFF:
        return PCSResult(
            service=target.key,
            status=NOT_REQUIRED,
            cookies_present=present,
            cookies_missing=missing,
            adp=state.adp,
        )

    waiting = _once(on_waiting)
    budget = _attempts(timeout, interval, max_attempts)
    # One deadline for the whole call. ``budget`` bounds each phase's polls,
    # but the consent wait and the cookie poll are sequential, so without a
    # shared deadline a caller asking for 100 s could be made to wait ~200 s.
    deadline = time.monotonic() + timeout if timeout > 0 else None

    consented = state.is_device_consented
    if consented is None:
        # Unknown consent. A request with derivedFromUserAction=False cannot
        # push a prompt, so it is safe to ask Apple what it thinks first.
        status, payload = _request_pcs(api, target, derived=False, workflow=workflow)
        outcome = _classify(status, payload)
        if outcome == _ACQUIRED:
            return _acquired(api, target, state.adp)
        if outcome == _NOT_REQUIRED:
            return PCSResult(
                service=target.key,
                status=NOT_REQUIRED,
                cookies_present=present,
                cookies_missing=missing,
                adp=state.adp,
            )
        if outcome in (_INCOMPLETE, _WEB_ACCESS_OFF, _REJECTED):
            _raise_for(
                outcome,
                status,
                payload,
                target,
                shape=_shape(api, "POST", REQUEST_PCS, _pcs_body(target, False)),
            )
        consented = False

    if not consented:
        waiting()
        if not request_device_consent(api, target.key, workflow=workflow):
            raise ICloudPyPCSRequiredException(
                "Apple did not send the approval prompt to a trusted device.",
                service=target.key,
                app_name=target.app_name,
                web_access=state,
            )
        approved = False
        for _ in range(budget):
            if _interrupted(interrupt):
                return PCSResult(
                    service=target.key,
                    status=ABORTED,
                    cookies_present=present,
                    cookies_missing=missing,
                    adp=state.adp,
                )
            if _past_deadline(deadline):
                break
            _sleep(interval)
            state = web_access_state(api, target.key, workflow=workflow)
            if state.is_device_consented:
                approved = True
                break
        if not approved:
            raise ICloudPyPCSTimeoutException(
                "The device approval was not given in time.",
                attempts=budget,
                service=target.key,
                app_name=target.app_name,
                web_access=state,
            )

    for attempt in range(budget):
        if _interrupted(interrupt):
            return PCSResult(
                service=target.key,
                status=ABORTED,
                cookies_present=present,
                cookies_missing=missing,
                adp=state.adp,
            )
        if _past_deadline(deadline):
            break
        if attempt == 0:
            # The web client mints this between consent and the cookie
            # request. Best effort: it never decides the outcome.
            _generate_session_id_token(api, workflow)
        derived = attempt == 0
        status, payload = _request_pcs(api, target, derived=derived, workflow=workflow)
        outcome = _classify(status, payload)
        if outcome == _ACQUIRED:
            return _acquired(api, target, state.adp)
        if outcome == _NOT_REQUIRED:
            return PCSResult(
                service=target.key,
                status=NOT_REQUIRED,
                cookies_present=present,
                cookies_missing=missing,
                adp=state.adp,
            )
        if outcome in (_INCOMPLETE, _WEB_ACCESS_OFF, _REJECTED):
            _raise_for(
                outcome,
                status,
                payload,
                target,
                shape=_shape(api, "POST", REQUEST_PCS, _pcs_body(target, derived)),
            )
        waiting()
        if attempt + 1 < budget:
            _sleep(interval)

    raise ICloudPyPCSTimeoutException(
        "No data-access cookie was issued before the deadline.",
        attempts=budget,
        service=target.key,
        app_name=target.app_name,
        web_access=state,
    )
