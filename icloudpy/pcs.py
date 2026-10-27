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
import logging
import time

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
    """Query parameters, including ``dsid`` when the account exposes one."""
    params = dict(getattr(api, "params", None) or {})
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


def _post(api, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """One HTTP request to a PCS endpoint, with no retry and no rewriting.

    The cookie jar is saved afterwards because Apple sets the PCS cookies on
    the ``requestPCS`` response itself.
    """
    session = _new_session(api)
    response = session.post(
        f"{api.setup_endpoint}{path}",
        params=_params(api),
        json=body,
        timeout=HTTP_TIMEOUT_SEC,
    )
    payload = _json_payload(response)
    session_store.save_cookies(api)
    return response.status_code, payload


def web_access_state(api, service: str) -> WebAccessState:
    """Ask Apple for the account's web-access state. Read-only."""
    target = _target(service)
    status, payload = _post(api, REQUEST_WEB_ACCESS_STATE)
    if not payload and status >= 400:
        raise ICloudPyPCSRequiredException(
            f"Apple refused the web-access check with HTTP {status}.",
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


def request_device_consent(api, service: str) -> bool:
    """Ask Apple to push the approval prompt. Returns whether it was sent."""
    target = _target(service)
    _, payload = _post(api, ENABLE_DEVICE_CONSENT)
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


def _raise_for(outcome: str, status: int, payload: dict[str, Any], target: PCSTarget) -> None:
    """Raise the specific exception a failed outcome maps to."""
    message = str(payload.get("message") or "") or f"HTTP {status}"
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
        f"Apple refused the data-access request for '{target.app_name}': {message}.",
        service=target.key,
        app_name=target.app_name,
    )


def _request_pcs(api, target: PCSTarget, *, derived: bool) -> tuple[int, dict[str, Any]]:
    """One ``requestPCS`` call.

    ``derivedFromUserAction`` is true only on the first attempt: it is what
    makes Apple notify the phone, and repeating it re-notifies on every poll.
    """
    return _post(
        api,
        REQUEST_PCS,
        {"appName": target.app_name, "derivedFromUserAction": derived},
    )


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

    state = web_access_state(api, target.key)
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

    consented = state.is_device_consented
    if consented is None:
        # Unknown consent. A request with derivedFromUserAction=False cannot
        # push a prompt, so it is safe to ask Apple what it thinks first.
        status, payload = _request_pcs(api, target, derived=False)
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
            _raise_for(outcome, status, payload, target)
        consented = False

    if not consented:
        waiting()
        if not request_device_consent(api, target.key):
            raise ICloudPyPCSRequiredException(
                "Apple did not send the approval prompt to a trusted device.",
                service=target.key,
                app_name=target.app_name,
                web_access=state,
            )
        for _ in range(budget):
            if _interrupted(interrupt):
                return PCSResult(
                    service=target.key,
                    status=ABORTED,
                    cookies_present=present,
                    cookies_missing=missing,
                    adp=state.adp,
                )
            _sleep(interval)
            state = web_access_state(api, target.key)
            if state.is_device_consented:
                break
        else:
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
        status, payload = _request_pcs(api, target, derived=attempt == 0)
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
            _raise_for(outcome, status, payload, target)
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
