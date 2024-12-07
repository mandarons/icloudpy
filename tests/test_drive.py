"""Drive service tests."""
from unittest import TestCase

import pytest

from . import ICloudPyServiceMock
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
