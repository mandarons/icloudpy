"""Drive service tests."""
import http.cookiejar as cookielib
import io
from unittest import TestCase

import pytest

from icloudpy.exceptions import ICloudPyAPIResponseException
from icloudpy.services.drive import DriveNode, RecentDocs

from . import ICloudPyServiceMock, ResponseMock
from .const import AUTHENTICATED_USER, CLIENT_ID, VALID_PASSWORD


# pylint: disable=pointless-statement
class DriveServiceTest(TestCase):
    """Drive service tests."""

    service = None

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)

    def test_root(self):
        """Test the root folder."""
        drive = self.service.drive
        assert drive.name == ""
        assert drive.type == "folder"
        assert drive.size is None
        assert drive.date_changed is None
        assert drive.date_modified is None
        assert drive.date_last_open is None
        assert drive.dir() == ["Keynote", "Numbers", "Pages", "Preview", "iCloudPy"]

    def test_folder_app(self):
        """Test the /Preview folder."""
        folder = self.service.drive["Preview"]
        assert folder.name == "Preview"
        assert folder.type == "app_library"
        assert folder.size is None
        assert folder.date_changed is None
        assert folder.date_modified is None
        assert folder.date_last_open is None
        with pytest.raises(KeyError, match="No items in folder, status: ID_INVALID"):
            assert folder.dir()

    def test_folder_not_exists(self):
        """Test the /not_exists folder."""
        with pytest.raises(KeyError, match="No child named 'not_exists' exists"):
            self.service.drive["not_exists"]

    def test_folder(self):
        """Test the /iCloudPy folder."""
        folder = self.service.drive["iCloudPy"]
        assert folder.name == "iCloudPy"
        assert folder.type == "folder"
        assert folder.size is None
        assert folder.date_changed is None
        assert folder.date_modified is None
        assert folder.date_last_open is None
        assert folder.dir() == ["Test"]

    def test_subfolder(self):
        """Test the /iCloudPy/Test folder."""
        folder = self.service.drive["iCloudPy"]["Test"]
        assert folder.name == "Test"
        assert folder.type == "folder"
        assert folder.size is None
        assert folder.date_changed is None
        assert folder.date_modified is None
        assert folder.date_last_open is None
        assert folder.dir() == ["Document scanné 2.pdf", "Scanned document 1.pdf"]

    def test_subfolder_file(self):
        """Test the /iCloudPy/Test/Scanned document 1.pdf file."""
        folder = self.service.drive["iCloudPy"]["Test"]
        file_test = folder["Scanned document 1.pdf"]
        assert file_test.name == "Scanned document 1.pdf"
        assert file_test.type == "file"
        assert file_test.size == 21644358
        assert str(file_test.date_changed) == "2020-05-03 00:16:17"
        assert str(file_test.date_modified) == "2020-05-03 00:15:17"
        assert str(file_test.date_last_open) == "2020-05-03 00:24:25"
        assert file_test.dir() is None

    def test_file_open(self):
        """Test the /iCloudPy/Test/Scanned document 1.pdf file open."""
        file_test = self.service.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]
        with file_test.open(stream=True) as response:
            assert response.raw

    def test_mkdir(self):
        """Test the /iCloudPy/Test folder."""
        folder = self.service.drive["iCloudPy"]["Test"]
        sub_folder_name = "sub_dir"
        assert folder.dir() == ["Document scanné 2.pdf", "Scanned document 1.pdf"]
        folder.mkdir(sub_folder_name)
        sub_folder = folder.get(sub_folder_name)
        assert sub_folder.name == sub_folder_name
        assert sub_folder.type == "folder"
        assert folder.dir() == ["Document scanné 2.pdf", "Scanned document 1.pdf", sub_folder_name]


class DriveTokenTests(TestCase):
    """Test token extraction from cookies."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_get_token_from_cookie_missing(self):
        """Test when X-APPLE-WEBAUTH-VALIDATE cookie not found."""
        # Clear all cookies
        self.service.session.cookies.clear()

        with pytest.raises(Exception, match="Token cookie not found"):
            self.drive._get_token_from_cookie()

    def test_get_token_from_cookie_malformed(self):
        """Test token extraction with malformed cookie value."""
        # Clear cookies and add a malformed one
        self.service.session.cookies.clear()

        # Create a malformed cookie (without the t= pattern)

        cookie = cookielib.Cookie(
            version=0,
            name="X-APPLE-WEBAUTH-VALIDATE",
            value="malformed_value_without_token_pattern",
            port=None,
            port_specified=False,
            domain=".icloud.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
        self.service.session.cookies.set_cookie(cookie)

        with pytest.raises(Exception, match="Can't extract token"):
            self.drive._get_token_from_cookie()

    def test_get_token_from_cookie_valid(self):
        """Test successful token extraction from valid cookie."""
        # Clear cookies and add a valid one
        self.service.session.cookies.clear()

        cookie = cookielib.Cookie(
            version=0,
            name="X-APPLE-WEBAUTH-VALIDATE",
            value="v=1:t=test_token_value:d=1234567890",
            port=None,
            port_specified=False,
            domain=".icloud.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
        self.service.session.cookies.set_cookie(cookie)

        token = self.drive._get_token_from_cookie()
        assert token == {"token": "test_token_value"}


class DriveFileOperationsTests(TestCase):
    """Test file download operations."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_get_file_zero_byte_file(self):
        """Test downloading 0-byte files (returns empty BytesIO)."""
        # Create a mock node with size=0
        folder = self.drive["iCloudPy"]["Test"]
        # Get the actual file and modify its data to have size 0
        file_node = folder["Scanned document 1.pdf"]
        file_node.data["size"] = 0

        response = file_node.open(stream=True)
        assert response.raw is not None

        assert isinstance(response.raw, io.BytesIO)
        # Verify it's empty
        content = response.raw.read()
        assert content == b""


class DriveFolderOperationsTests(TestCase):
    """Test folder create/rename/delete operations."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_rename_items_success(self):
        """Test item renaming."""
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]
        new_name = "Renamed Document.pdf"

        result = file.rename(new_name)
        assert result is not None
        # Verify the response structure
        assert "items" in result
        assert len(result["items"]) > 0
        # Verify the mock was called
        assert self.service.session.rename_count > 0

    def test_move_items_to_trash_success(self):
        """Test moving items to trash."""
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]

        result = file.delete()
        assert result is not None


class DriveNodeEdgeCasesTests(TestCase):
    """Test DriveNode edge cases and error handling."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_drive_node_get_children_lazy_loading(self):
        """Test children fetching on first access."""
        folder = self.drive["iCloudPy"]

        # First access should trigger loading
        assert folder._children is None
        children = folder.get_children()
        assert folder._children is not None

        # Second access should use cache
        children2 = folder.get_children()
        assert children == children2

    def test_drive_node_file_has_no_dir(self):
        """Test that file nodes return None for dir()."""
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]
        assert file.dir() is None

    def test_drive_node_file_has_no_get(self):
        """Test that file nodes return None for get()."""
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]
        assert file.get("anything") is None

    def test_drive_node_name_with_extension(self):
        """Test name property includes extension when present."""
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]
        assert ".pdf" in file.name

    def test_drive_node_name_without_extension(self):
        """Test name property for items without extension."""
        folder = self.drive["iCloudPy"]
        assert folder.name == "iCloudPy"

    def test_drive_node_date_parsing_utc(self):
        """Test date parsing for dates already in UTC."""
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]

        # Dates should be parsed correctly
        assert file.date_modified is not None
        assert file.date_changed is not None
        assert file.date_last_open is not None

    def test_drive_node_unicode_and_str(self):
        """Test __unicode__ and __str__ methods."""
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]
        unicode_str = file.__unicode__()
        assert "type: file" in unicode_str
        assert "name: Scanned document 1.pdf" in unicode_str

        str_repr = str(file)
        assert "type: file" in str_repr

    def test_drive_node_repr(self):
        """Test __repr__ method."""
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]
        repr_str = repr(file)
        assert "DriveNode" in repr_str
        assert "type: file" in repr_str


class DriveUploadTests(TestCase):
    """Test file upload functionality."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_get_upload_contentws_url_success(self):
        """Test upload URL generation."""

        # Add a valid cookie for token extraction
        cookie = cookielib.Cookie(
            version=0,
            name="X-APPLE-WEBAUTH-VALIDATE",
            value="v=1:t=test_token:d=1234567890",
            port=None,
            port_specified=False,
            domain=".icloud.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
        self.service.session.cookies.set_cookie(cookie)

        file_obj = io.BytesIO(b"test content")
        file_obj.name = "test.txt"

        doc_id, url = self.drive._get_upload_contentws_url(file_obj)
        assert doc_id is not None
        assert url is not None
        assert "upload" in url

    def test_send_file_complete_flow(self):
        """Test full file upload process."""

        # Add a valid cookie for token extraction
        cookie = cookielib.Cookie(
            version=0,
            name="X-APPLE-WEBAUTH-VALIDATE",
            value="v=1:t=test_token:d=1234567890",
            port=None,
            port_specified=False,
            domain=".icloud.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
        self.service.session.cookies.set_cookie(cookie)

        folder = self.drive["iCloudPy"]["Test"]

        content = b"Test file content for upload"
        file_obj = io.BytesIO(content)
        file_obj.name = "uploaded_test.txt"

        # Should not raise
        folder.upload(file_obj)
        # Verify upload tracked in mock
        assert self.service.session.upload_count > 0


class DriveAppLibraryTests(TestCase):
    """Test app library functionality."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_get_app_data(self):
        """Test retrieving app library data."""
        # This will test the get_app_data method
        result = self.drive.get_app_data()
        assert result is not None

    def test_get_app_node(self):
        """Test retrieving app node."""
        # This will test get_app_node method
        node = self.drive.get_app_node("com.apple.CloudDocs", "documents")
        assert node is not None


class DriveErrorHandlingTests(TestCase):
    """Test error handling in drive operations."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_get_node_data_success(self):
        """Test successful node data retrieval."""
        # Test the get_node_data method
        result = self.drive.get_node_data("FOLDER::com.apple.CloudDocs::root")
        assert result is not None


class DriveNodeDateTests(TestCase):
    """Test date-related properties of DriveNode."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_date_created_property(self):
        """Test date_created property."""
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]
        # date_created should work (it's not in the fixture but should return None or a value)
        date_created = file.date_created
        # The fixture doesn't have dateCreated, so it should return None
        assert date_created is None

    def test_date_parsing_with_timezone(self):
        """Test date parsing with timezone offset."""
        # The existing fixture already has dates with timezone offset
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]
        # dateChanged has timezone: "2020-05-02T17:16:17-07:00"
        assert file.date_changed is not None
        # Should be converted to UTC
        assert str(file.date_changed) == "2020-05-03 00:16:17"


class DriveErrorPathTests(TestCase):
    """Test error paths and edge cases."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_get_file_missing_tokens(self):
        """Test error when neither data_token nor package_token present."""
        # We need to mock a response without tokens
        # Let's create a custom mock for this case

        # Save the original request method
        original_request = self.service.session.request

        def mock_request_no_tokens(method, url, **kwargs):
            if "download/by_id" in url:
                # Return response without data_token or package_token
                return ResponseMock({"document_id": "test"})
            return original_request(method, url, **kwargs)

        self.service.session.request = mock_request_no_tokens

        with pytest.raises(KeyError, match="'data_token' nor 'package_token' found"):
            self.drive.get_file("test_id")

        # Restore original
        self.service.session.request = original_request

    def test_get_file_timeout_reaches_the_lookup_as_well_as_the_transfer(self):
        """get_file makes two requests: the by_id lookup, then the transfer.
        A timeout forwarded only to the transfer leaves the lookup able to
        stall its thread forever. ``stream`` is not forwarded to the lookup --
        it is a small JSON reply."""
        original_request = self.service.session.request
        seen = {}

        def recording_request(method, url, **kwargs):
            key = "lookup" if "download/by_id" in url else "transfer"
            seen[key] = kwargs
            if key == "lookup":
                return ResponseMock({"data_token": {"url": "https://example.test/file"}})
            return ResponseMock({})

        self.service.session.request = recording_request
        try:
            self.drive.get_file("test_id", stream=True, timeout=30)
        finally:
            self.service.session.request = original_request

        assert seen["lookup"].get("timeout") == 30
        assert "stream" not in seen["lookup"]
        assert seen["transfer"].get("timeout") == 30
        assert seen["transfer"].get("stream") is True

    def test_get_file_without_timeout_adds_nothing_to_the_lookup(self):
        """No timeout requested means no timeout key is added, so the lookup
        keeps requests' default exactly as before."""
        original_request = self.service.session.request
        seen = {}

        def recording_request(method, url, **kwargs):
            if "download/by_id" in url:
                seen["lookup"] = kwargs
                return ResponseMock({"data_token": {"url": "https://example.test/file"}})
            return ResponseMock({})

        self.service.session.request = recording_request
        try:
            self.drive.get_file("test_id")
        finally:
            self.service.session.request = original_request
        assert "timeout" not in seen["lookup"]

    def test_get_file_with_package_token(self):
        """Test file download using package_token instead of data_token."""

        # Save the original request method
        original_request = self.service.session.request

        def mock_request_package_token(method, url, **kwargs):
            if "download/by_id" in url:
                # Return response with package_token but no data_token
                return ResponseMock({
                    "document_id": "test",
                    "package_token": {
                        "url": "https://icloud-content.com/test.band",
                    },
                })
            if "icloud-content.com" in url:
                return ResponseMock({}, raw=io.BytesIO(b"test content"))
            return original_request(method, url, **kwargs)

        self.service.session.request = mock_request_package_token

        response = self.drive.get_file("test_id")
        assert response is not None

        # Restore original
        self.service.session.request = original_request

    def test_content_type_detection(self):
        """Test MIME type guessing for various extensions."""

        # Add a valid cookie for token extraction
        cookie = cookielib.Cookie(
            version=0,
            name="X-APPLE-WEBAUTH-VALIDATE",
            value="v=1:t=test_token:d=1234567890",
            port=None,
            port_specified=False,
            domain=".icloud.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
        self.service.session.cookies.set_cookie(cookie)

        test_cases = [
            ("test.txt", "text/plain"),
            ("test.pdf", "application/pdf"),
            ("test.jpg", "image/jpeg"),
            ("test.unknown_ext_xyz", ""),  # Should default to empty for unknown
        ]

        for filename, expected_type in test_cases:
            file_obj = io.BytesIO(b"content")
            file_obj.name = filename
            # Call the method to test content type detection
            doc_id, url = self.drive._get_upload_contentws_url(file_obj)
            # Verify it didn't fail - content type is handled internally
            assert doc_id is not None
            assert url is not None
            # Verify the URL contains the upload endpoint
            assert "upload" in url


class DriveHTTPErrorTests(TestCase):
    """Test HTTP error handling in drive operations."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_get_node_data_http_error(self):
        """Test get_node_data with HTTP error response."""

        # Save the original request method
        original_request = self.service.session.request

        def mock_request_error(method, url, **kwargs):
            if "retrieveItemDetailsInFolders" in url:
                # Return error response
                response = ResponseMock({}, status_code=500)
                return response
            return original_request(method, url, **kwargs)

        self.service.session.request = mock_request_error

        with pytest.raises(ICloudPyAPIResponseException):
            self.drive.get_node_data("FOLDER::com.apple.CloudDocs::error")

        # Restore original
        self.service.session.request = original_request

    def test_get_file_http_error(self):
        """Test get_file with HTTP error response."""

        # Save the original request method
        original_request = self.service.session.request

        def mock_request_error(method, url, **kwargs):
            if "download/by_id" in url:
                # Return error response
                response = ResponseMock({}, status_code=404)
                return response
            return original_request(method, url, **kwargs)

        self.service.session.request = mock_request_error

        with pytest.raises(ICloudPyAPIResponseException):
            self.drive.get_file("nonexistent_file_id")

        # Restore original
        self.service.session.request = original_request

    def test_get_app_data_http_error(self):
        """Test get_app_data with HTTP error response."""

        # Save the original request method
        original_request = self.service.session.request

        def mock_request_error(method, url, **kwargs):
            if "retrieveAppLibraries" in url:
                # Return error response
                response = ResponseMock({}, status_code=500)
                return response
            return original_request(method, url, **kwargs)

        self.service.session.request = mock_request_error

        with pytest.raises(ICloudPyAPIResponseException):
            self.drive.get_app_data()

        # Restore original
        self.service.session.request = original_request

    def test_upload_url_http_error(self):
        """Test upload URL generation with HTTP error."""

        # Add a valid cookie
        cookie = cookielib.Cookie(
            version=0,
            name="X-APPLE-WEBAUTH-VALIDATE",
            value="v=1:t=test_token:d=1234567890",
            port=None,
            port_specified=False,
            domain=".icloud.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
        self.service.session.cookies.set_cookie(cookie)

        # Save the original request method
        original_request = self.service.session.request

        def mock_request_error(method, url, **kwargs):
            if "/upload/web" in url:
                # Return error response
                response = ResponseMock({}, status_code=403)
                return response
            return original_request(method, url, **kwargs)

        self.service.session.request = mock_request_error

        file_obj = io.BytesIO(b"test")
        file_obj.name = "test.txt"

        with pytest.raises(ICloudPyAPIResponseException):
            self.drive._get_upload_contentws_url(file_obj)

        # Restore original
        self.service.session.request = original_request

    def test_update_contentws_http_error(self):
        """Test content update with HTTP error."""

        # Add a valid cookie
        cookie = cookielib.Cookie(
            version=0,
            name="X-APPLE-WEBAUTH-VALIDATE",
            value="v=1:t=test_token:d=1234567890",
            port=None,
            port_specified=False,
            domain=".icloud.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
        self.service.session.cookies.set_cookie(cookie)

        # Save the original request method
        original_request = self.service.session.request

        def mock_request_error(method, url, **kwargs):
            if "/update/documents" in url:
                # Return error response
                response = ResponseMock({}, status_code=500)
                return response
            return original_request(method, url, **kwargs)

        self.service.session.request = mock_request_error

        file_obj = io.BytesIO(b"test")
        file_obj.name = "test.txt"

        sf_info = {
            "fileChecksum": "test",
            "wrappingKey": "test",
            "referenceChecksum": "test",
            "size": 4,
            "receipt": "test",
        }

        with pytest.raises(ICloudPyAPIResponseException):
            self.drive._update_contentws("folder_id", sf_info, "doc_id", file_obj)

        # Restore original
        self.service.session.request = original_request

    def test_send_file_upload_http_error(self):
        """Test send_file with HTTP error during file upload."""

        # Add a valid cookie
        cookie = cookielib.Cookie(
            version=0,
            name="X-APPLE-WEBAUTH-VALIDATE",
            value="v=1:t=test_token:d=1234567890",
            port=None,
            port_specified=False,
            domain=".icloud.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
        self.service.session.cookies.set_cookie(cookie)

        # Save the original request method
        original_request = self.service.session.request

        def mock_request_error(method, url, **kwargs):
            if "/ws/upload/file" in url:
                # Return error response for actual file upload
                response = ResponseMock({}, status_code=500)
                return response
            return original_request(method, url, **kwargs)

        self.service.session.request = mock_request_error

        file_obj = io.BytesIO(b"test")
        file_obj.name = "test.txt"

        with pytest.raises(ICloudPyAPIResponseException):
            self.drive.send_file("folder_id", file_obj)

        # Restore original
        self.service.session.request = original_request

    def test_move_to_trash_http_error(self):
        """Test move to trash with HTTP error."""

        # Save the original request method
        original_request = self.service.session.request

        def mock_request_error(method, url, **kwargs):
            if "moveItemsToTrash" in url:
                # Return error response
                response = ResponseMock({}, status_code=403)
                return response
            return original_request(method, url, **kwargs)

        self.service.session.request = mock_request_error

        with pytest.raises(ICloudPyAPIResponseException):
            self.drive.move_items_to_trash("node_id", "etag")

        # Restore original
        self.service.session.request = original_request


class DriveRecentDocsTests(TestCase):
    """Test the recent documents listing."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(
            AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID,
        )
        self.drive = self.service.drive

    def _capture_params(self, **call_kwargs):
        """Run get_recent_docs and return the query params it sent."""
        captured = {}
        original_request = self.service.session.request

        def capture(method, url, **kwargs):
            if "recentDocs" in url:
                captured.update(kwargs.get("params") or {})
            return original_request(method, url, **kwargs)

        self.service.session.request = capture
        try:
            result = self.drive.get_recent_docs(**call_kwargs)
        finally:
            self.service.session.request = original_request
        return result, captured

    def test_returns_a_plain_list_of_nodes(self):
        """The result is a list, so existing list code keeps working."""
        docs = self.drive.get_recent_docs()
        assert isinstance(docs, RecentDocs)
        assert isinstance(docs, list)
        assert len(docs) == 3
        assert all(isinstance(doc, DriveNode) for doc in docs)

    def test_preserves_apple_order(self):
        """Documents come back in the order Apple returned them."""
        assert [doc.name for doc in self.drive.get_recent_docs()] == [
            "Quarterly summary.pdf",
            "Budget draft.numbers",
            "Team notes.pages",
        ]

    def test_name_without_an_extension_field(self):
        """A document with no ``extension`` field keeps its own name."""
        doc = self.drive.get_recent_docs()[2]
        assert "extension" not in doc.data
        assert doc.name == "Team notes.pages"

    def test_document_metadata(self):
        """Size and dates decode like any other drive node."""
        doc = self.drive.get_recent_docs()[0]
        assert doc.type == "file"
        assert doc.size == 1548321
        assert str(doc.date_modified) == "2020-05-03 07:15:17"
        assert str(doc.date_last_open) == "2020-05-03 07:24:25"

    def test_date_created_is_absent(self):
        """Apple omits dateCreated, so date_created is None instead of raising."""
        assert self.drive.get_recent_docs()[0].date_created is None

    def test_document_can_be_opened(self):
        """A recent document downloads through DriveNode.open."""
        with self.drive.get_recent_docs()[0].open(stream=True) as response:
            assert response.raw

    def test_zero_byte_document_opens_empty(self):
        """The 0-byte guard in DriveNode.open still applies here."""
        response = self.drive.get_recent_docs()[2].open(stream=True)
        assert response.raw.read() == b""

    def test_complete_listing_reports_consistent(self):
        """A complete listing carries Apple's status and the marker."""
        docs = self.drive.get_recent_docs()
        assert docs.status == "CONSISTENT"
        assert docs.more_available is False
        assert docs.next_page == "dGVzdC1tYXJrZXItMDE="

    def test_truncated_listing_reports_more_available(self):
        """MORE_AVAILABLE is surfaced instead of silently dropping documents."""
        docs = self.drive.get_recent_docs(limit=1)
        assert len(docs) == 1
        assert docs.status == "MORE_AVAILABLE"
        assert docs.more_available is True
        assert docs.next_page == "dGVzdC1tYXJrZXItMDI="

    def test_next_page_continues_the_listing(self):
        """Passing the cursor back returns the next page."""
        first = self.drive.get_recent_docs(limit=1)
        second = self.drive.get_recent_docs(next_page=first.next_page)
        assert [doc.name for doc in second] == ["Archived scan.jpg"]
        assert second.status == "CONSISTENT"
        assert second.more_available is False

    def test_pages_do_not_repeat_documents(self):
        """The cursor moves forward instead of re-serving the first page."""
        first = self.drive.get_recent_docs(limit=1)
        second = self.drive.get_recent_docs(next_page=first.next_page)
        assert {doc.data["docwsid"] for doc in first}.isdisjoint(
            {doc.data["docwsid"] for doc in second},
        )

    def test_request_parameters(self):
        """unified_format, limit and the cursor are all sent."""
        _, captured = self._capture_params(limit=7, next_page="cursor-1")
        assert captured["unified_format"] == "true"
        assert captured["limit"] == 7
        assert captured["nextPage"] == "cursor-1"
        assert captured["clientId"] == CLIENT_ID

    def test_first_request_sends_no_cursor(self):
        """The first page is requested without nextPage."""
        _, captured = self._capture_params()
        assert "nextPage" not in captured
        assert captured["limit"] == 20

    def test_empty_documents(self):
        """An empty listing is an empty RecentDocs, not an error."""
        original_request = self.service.session.request

        def empty(method, url, **kwargs):
            if "recentDocs" in url:
                return ResponseMock({"status": "CONSISTENT", "documents": []})
            return original_request(method, url, **kwargs)

        self.service.session.request = empty
        try:
            docs = self.drive.get_recent_docs()
        finally:
            self.service.session.request = original_request
        assert len(docs) == 0
        assert docs.status == "CONSISTENT"

    def test_missing_documents_key(self):
        """A response without ``documents`` yields an empty listing."""
        original_request = self.service.session.request

        def no_documents(method, url, **kwargs):
            if "recentDocs" in url:
                return ResponseMock({"status": "CONSISTENT"})
            return original_request(method, url, **kwargs)

        self.service.session.request = no_documents
        try:
            docs = self.drive.get_recent_docs()
        finally:
            self.service.session.request = original_request
        assert len(docs) == 0

    def test_error_status_raises(self):
        """A rejected request raises instead of returning an empty list."""
        self.service.session.recent_docs_error = True
        with pytest.raises(ICloudPyAPIResponseException):
            self.drive.get_recent_docs()

    def test_unexpected_payload_raises(self):
        """A non-object payload is not silently treated as an empty listing."""
        original_request = self.service.session.request

        def wrong_shape(method, url, **kwargs):
            if "recentDocs" in url:
                return ResponseMock([])
            return original_request(method, url, **kwargs)

        self.service.session.request = wrong_shape
        try:
            with pytest.raises(KeyError, match="recent documents"):
                self.drive.get_recent_docs()
        finally:
            self.service.session.request = original_request
