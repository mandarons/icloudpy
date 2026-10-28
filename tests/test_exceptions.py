"""Exception message and attribute tests."""

from icloudpy.exceptions import (
    ICloudPyAPIResponseException,
    ICloudPyPCSAppNameMismatchException,
    ICloudPyPCSRequiredException,
    ICloudPyPCSTimeoutException,
    ICloudPyWebAccessDisabledException,
)


class TestAPIResponseMessage:
    """The base exception formats its message from reason, code and retry."""

    def test_reason_only(self):
        assert str(ICloudPyAPIResponseException("boom")) == "boom"

    def test_reason_and_code(self):
        assert str(ICloudPyAPIResponseException("boom", 423)) == "boom (423)"

    def test_reason_code_and_retry(self):
        assert str(ICloudPyAPIResponseException("boom", 500, retry=True)) == "boom (500). Retrying ..."

    def test_empty_reason(self):
        assert str(ICloudPyAPIResponseException(None)) == ""


class TestPCSErrorContext:
    """PCS exceptions carry the service and app name callers need."""

    def test_base_carries_context(self):
        error = ICloudPyPCSRequiredException("nope", service="drive", app_name="iclouddrive")
        assert error.service == "drive"
        assert error.app_name == "iclouddrive"
        assert error.code is None

    def test_timeout_carries_attempts(self):
        error = ICloudPyPCSTimeoutException("nope", attempts=7, service="photos", app_name="photos")
        assert error.attempts == 7
        assert error.service == "photos"

    def test_web_access_disabled_is_a_pcs_error(self):
        assert isinstance(ICloudPyWebAccessDisabledException("off"), ICloudPyPCSRequiredException)

    def test_app_name_mismatch_records_cookies(self):
        error = ICloudPyPCSAppNameMismatchException(
            "missing",
            expected=("A", "B"),
            missing=("B",),
        )
        assert error.expected == ("A", "B")
        assert error.missing == ("B",)
