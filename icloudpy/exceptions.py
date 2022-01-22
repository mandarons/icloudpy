"""Library exceptions."""


class ICloudPyException(Exception):
    """Generic iCloud exception."""

    pass


# API
class ICloudPyAPIResponseException(ICloudPyException):
    """iCloud response exception."""

    def __init__(self, reason, code=None, retry=False):
        self.reason = reason
        self.code = code
        message = reason or ""
        if code:
            message += " (%s)" % code
        if retry:
            message += ". Retrying ..."

        super().__init__(message)


class ICloudPyServiceNotActivatedException(ICloudPyAPIResponseException):
    """iCloud service not activated exception."""

    pass


# Login
class ICloudPyFailedLoginException(ICloudPyException):
    """iCloud failed login exception."""

    pass


class ICloudPy2SARequiredException(ICloudPyException):
    """iCloud 2SA required exception."""

    def __init__(self, apple_id):
        message = "Two-step authentication required for account: %s" % apple_id
        super().__init__(message)


class ICloudPyNoStoredPasswordAvailableException(ICloudPyException):
    """iCloud no stored password exception."""

    pass


# Webservice specific
class ICloudPyNoDevicesException(ICloudPyException):
    """iCloud no device exception."""

    pass
