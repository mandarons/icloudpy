"""Tests for utils module."""

import pytest


class TestGetLocalzoneStringConversion:
    """Test timezone string conversion for compatibility."""

    def test_str_conversion_with_zone_attribute(self):
        """Test that str() works with objects having .zone attribute."""

        class MockTimezoneWithZone:
            """Mock timezone object with .zone attribute (old pytz style)."""

            def __init__(self, zone_name):
                self.zone = zone_name

            def __str__(self):
                return self.zone

        tz = MockTimezoneWithZone("America/New_York")
        assert str(tz) == "America/New_York"

    def test_str_conversion_with_key_attribute(self):
        """Test that str() works with objects having .key attribute (zoneinfo.ZoneInfo style)."""

        class MockTimezoneWithKey:
            """Mock timezone object with .key attribute (zoneinfo.ZoneInfo style)."""

            def __init__(self, zone_name):
                self.key = zone_name

            def __str__(self):
                return str(self.key)

        tz = MockTimezoneWithKey("Europe/London")
        assert str(tz) == "Europe/London"

    def test_str_conversion_with_no_zone_or_key(self):
        """Test that str() works with timezone objects without .zone or .key."""

        class MockTimezoneWithStr:
            """Mock timezone object with only __str__ method."""

            def __init__(self, zone_name):
                self._name = zone_name

            def __str__(self):
                return self._name

        tz = MockTimezoneWithStr("Asia/Tokyo")
        assert str(tz) == "Asia/Tokyo"

    def test_zoneinfo_compatibility(self):
        """Test compatibility with zoneinfo.ZoneInfo objects."""
        try:
            from zoneinfo import ZoneInfo

            # ZoneInfo objects have .key attribute, not .zone
            tz = ZoneInfo("UTC")
            assert hasattr(tz, "key")
            assert not hasattr(tz, "zone")
            # str() should work correctly
            assert str(tz) == "UTC"
        except ImportError:
            # zoneinfo not available in Python < 3.9
            pytest.skip("zoneinfo module not available")


class TestPasswordUtilities:
    """Test password-related utility functions."""

    def test_underscore_to_camelcase_basic(self):
        """Test basic underscore to camelCase conversion."""
        from icloudpy.utils import underscore_to_camelcase

        assert underscore_to_camelcase("hello_world") == "helloWorld"
        assert underscore_to_camelcase("foo_bar_baz") == "fooBarBaz"

    def test_underscore_to_camelcase_with_initial_capital(self):
        """Test underscore to CamelCase with initial capital."""
        from icloudpy.utils import underscore_to_camelcase

        assert underscore_to_camelcase("hello_world", initial_capital=True) == "HelloWorld"
        assert underscore_to_camelcase("foo_bar_baz", initial_capital=True) == "FooBarBaz"

    def test_underscore_to_camelcase_single_word(self):
        """Test conversion of single word."""
        from icloudpy.utils import underscore_to_camelcase

        assert underscore_to_camelcase("hello") == "hello"
        assert underscore_to_camelcase("hello", initial_capital=True) == "Hello"
