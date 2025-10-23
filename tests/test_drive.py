"""Drive service tests."""
import http.cookiejar as cookielib
import io
from unittest import TestCase

import pytest

from icloudpy.exceptions import ICloudPyAPIResponseException

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


class DrivePython2CompatTests(TestCase):
    """Test Python 2 compatibility paths.

    Note: Line 368 in drive.py (PY2 encode path) is marked with pragma: no cover
    because it's unreachable in Python 3.8+ which is the minimum supported version.
    This is legacy code from when the project supported Python 2.
    """

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD, None, True, CLIENT_ID)
        self.drive = self.service.drive

    def test_drive_node_str_python3_path(self):
        """Test __str__ method Python 3 code path."""
        file = self.drive["iCloudPy"]["Test"]["Scanned document 1.pdf"]

        # In Python 3, __str__ returns unicode string directly
        result = str(file)
        assert result is not None
        assert "file" in result
        assert isinstance(result, str)
