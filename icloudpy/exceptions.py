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
