"""Library exceptions."""


class ICloudPyException(Exception):
    """Generic iCloud exception."""


# API
class ICloudPyAPIResponseException(ICloudPyException):
    """iCloud response exception."""

    def __init__(self, reason, code=None, retry=False):
        self.reason = reason
        self.code = code
        message = reason or ""
        if code:
            message += f" ({code})"
        if retry:
            message += ". Retrying ..."

        super().__init__(message)


class ICloudPyServiceNotActivatedException(ICloudPyAPIResponseException):
    """iCloud service not activated exception."""


class ICloudPyLibraryUnavailableException(ICloudPyAPIResponseException):
    """A single iCloud Photos library (CloudKit zone) is unusable.

    Raised when Apple definitively rejects a zone-scoped query -- e.g.
    ``400 Index has invalid data`` or ``ZONE_NOT_FOUND`` -- while the account
    and the other libraries are fine. Subclassing ``ICloudPyAPIResponseException``
    keeps existing handlers working; callers that want to skip one library and
    carry on with the rest can catch this type on its own.
    """

    def __init__(self, reason, code=None, zone_name=None):
        self.zone_name = zone_name
        if zone_name:
            reason = f"{reason} [{zone_name}]"
        super().__init__(reason, code)


# Login
class ICloudPyFailedLoginException(ICloudPyException):
    """iCloud failed login exception."""


class ICloudPy2SARequiredException(ICloudPyException):
    """iCloud 2SA required exception."""

    def __init__(self, apple_id):
        message = f"Two-step authentication required for account:{apple_id}"
        super().__init__(message)


class ICloudPyNoStoredPasswordAvailableException(ICloudPyException):
    """iCloud no stored password exception."""


# Webservice specific
class ICloudPyNoDevicesException(ICloudPyException):
    """iCloud no device exception."""


# Advanced Data Protection (per-service encryption)
class ICloudPyPCSRequiredException(ICloudPyAPIResponseException):
    """Apple requires a PCS cookie that the session does not hold.

    Raised for every Advanced Data Protection failure that has no more
    specific class, and the base class for the ones that do. Subclassing
    :class:`ICloudPyAPIResponseException` keeps existing ``except`` clauses
    working, so a caller that has not opted into ADP handling still sees an
    API error rather than a crash.
    """

    def __init__(self, reason, code=None, *, service=None, app_name=None, web_access=None):
        self.service = service
        self.app_name = app_name
        self.web_access = web_access
        super().__init__(reason, code)


class ICloudPyPCSTimeoutException(ICloudPyPCSRequiredException):
    """No approval arrived (or no cookie was issued) before the deadline."""

    def __init__(self, reason, code=None, *, attempts=None, **kwargs):
        self.attempts = attempts
        super().__init__(reason, code, **kwargs)


class ICloudPyWebAccessDisabledException(ICloudPyPCSRequiredException):
    """Advanced Data Protection is on but web access to the data is off.

    Apple will not release a PCS cookie while "Access iCloud Data on the
    Web" is disabled. No amount of retrying fixes this: the user has to
    turn the setting back on.
    """


class ICloudPyWebSessionIncompleteException(ICloudPyPCSRequiredException):
    """The session cannot request data access without a fresh sign-in.

    Typically a lapsed ``X-APPLE-WEBAUTH-TOKEN``, or pending iCloud terms:
    the trust token is still valid, so ``/validate`` succeeds, but Apple
    refuses ``requestPCS``.
    """


class ICloudPyPCSAppNameMismatchException(ICloudPyException):
    """``requestPCS`` reported success but the expected cookie was not set.

    Almost always a wrong ``appName``: Apple answers ``status: success`` and
    simply does not issue the cookie.
    """

    def __init__(self, reason, *, expected=(), missing=()):
        self.expected = tuple(expected)
        self.missing = tuple(missing)
        super().__init__(reason)
