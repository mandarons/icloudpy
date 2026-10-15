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
