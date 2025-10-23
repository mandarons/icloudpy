"""Tests for Photos service."""
import unittest
from unittest.mock import patch

from icloudpy.exceptions import ICloudPyServiceNotActivatedException

from . import ICloudPyServiceMock
from .const import AUTHENTICATED_USER, VALID_PASSWORD


class PhotosServiceInitializationTests(unittest.TestCase):
    """Test PhotosService initialization."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)

    def test_photos_service_initialization(self):
        """Test service setup with correct params."""
        photos = self.service.photos

        assert photos is not None
        assert photos._service_root is not None
        assert photos._service_endpoint is not None
        assert photos.params["remapEnums"] is True
        assert photos.params["getCurrentSyncToken"] is True

    def test_photos_service_zone_id(self):
        """Test default zone_id is PrimarySync."""
        photos = self.service.photos
        assert photos.zone_id == {"zoneName": "PrimarySync"}

    def test_photos_service_endpoint_structure(self):
        """Test service endpoint follows correct pattern."""
        photos = self.service.photos
        assert "/database/1/com.apple.photos.cloud/production/private" in photos._service_endpoint

    def test_photos_service_session_and_params(self):
        """Test that session and params are properly set."""
        photos = self.service.photos
        assert photos.session is not None
        assert "remapEnums" in photos.params
        assert "getCurrentSyncToken" in photos.params

    def test_photos_service_photo_assets_initialized(self):
        """Test that _photo_assets dict is initialized."""
        photos = self.service.photos
        assert hasattr(photos, "_photo_assets")
        assert isinstance(photos._photo_assets, dict)


class PhotoLibraryInitializationTests(unittest.TestCase):
    """Test PhotoLibrary initialization and indexing check."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)

    def test_photo_library_indexing_finished(self):
        """Test PhotoLibrary initializes when indexing finished."""
        photos = self.service.photos

        # Should not raise - indexing is finished in mock
        assert photos is not None
        assert photos.zone_id is not None

    def test_photo_library_zone_query(self):
        """Test zone query construction."""
        photos = self.service.photos

        # Verify zone query was made during init
        assert photos.zone_id["zoneName"] == "PrimarySync"

    def test_photo_library_albums_not_fetched_on_init(self):
        """Test that albums are not fetched during initialization (lazy loading)."""
        photos = self.service.photos
        # _albums should be None until accessed
        assert photos._albums is None

    def test_photo_library_indexing_not_finished_raises_exception(self):
        """Test that indexing not finished raises appropriate exception."""
        # Create a mock response with IN_PROGRESS state
        in_progress_response = {
            "records": [
                {
                    "recordName": "_5c82ba39-fa99-4f36-ad2a-1a87028f8fa4",
                    "recordType": "CheckIndexingState",
                    "fields": {
                        "progress": {"value": 50, "type": "INT64"},
                        "state": {"value": "IN_PROGRESS", "type": "STRING"},
                    },
                    "pluginFields": {},
                    "recordChangeTag": "0",
                    "created": {
                        "timestamp": 1629754179814,
                        "userRecordName": "_10",
                        "deviceID": "1",
                    },
                    "modified": {
                        "timestamp": 1629754179814,
                        "userRecordName": "_10",
                        "deviceID": "1",
                    },
                    "deleted": False,
                    "zoneID": {
                        "zoneName": "PrimarySync",
                        "ownerRecordName": "_1d5r3c201b3a4r5daac8ff7e7fbc0c23",
                        "zoneType": "REGULAR_CUSTOM_ZONE",
                    },
                },
            ],
            "syncToken": "AQAAAAAAArKjf//////////fSxWSKv5JfZ34edrt875d",
        }

        # Patch the session's post method to return IN_PROGRESS for CheckIndexingState
        with patch.object(
            ICloudPyServiceMock,
            "__init__",
            side_effect=lambda self, *args, **kwargs: (
                ICloudPyServiceMock.__bases__[0].__init__(self, *args, **kwargs),
                setattr(self.session, "_in_progress_response", in_progress_response),
            )[0],
        ):
            # This approach is complex, let's use a simpler method
            pass

        # Simpler approach: patch the const_photos DATA to return IN_PROGRESS
        from . import const_photos

        original_data = const_photos.DATA["query?remapEnums=True&getCurrentSyncToken=True"][0]["response"]
        const_photos.DATA["query?remapEnums=True&getCurrentSyncToken=True"][0]["response"] = in_progress_response

        try:
            # This should raise ICloudPyServiceNotActivatedException
            with self.assertRaises(ICloudPyServiceNotActivatedException) as context:
                service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
                _ = service.photos  # Accessing photos property triggers initialization

            # Verify the exception message
            self.assertIn("not finished indexing", str(context.exception))
        finally:
            # Restore original data
            const_photos.DATA["query?remapEnums=True&getCurrentSyncToken=True"][0]["response"] = original_data


class AlbumsPropertyTests(unittest.TestCase):
    """Test albums property and lazy loading."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos

    def test_albums_property_lazy_loading(self):
        """Test albums are fetched only once."""
        # First access
        albums1 = self.photos.albums
        assert albums1 is not None
        assert isinstance(albums1, dict)

        # Second access should return cached
        albums2 = self.photos.albums
        assert albums1 is albums2  # Same object

    def test_albums_include_smart_folders(self):
        """Test that all SMART_FOLDERS are created."""
        albums = self.photos.albums

        expected_smart_folders = [
            "All Photos",
            "Time-lapse",
            "Videos",
            "Slo-mo",
            "Bursts",
            "Favorites",
            "Panoramas",
            "Screenshots",
            "Live",
            "Recently Deleted",
            "Hidden",
        ]

        for folder_name in expected_smart_folders:
            assert folder_name in albums, f"{folder_name} not in albums"

    def test_albums_smart_folder_properties(self):
        """Test smart folder objects have correct properties."""
        albums = self.photos.albums
        # Use "Favorites" as it's a smart folder that won't be overwritten by user albums
        favorites = albums["Favorites"]

        assert favorites.name == "Favorites"
        assert favorites.obj_type == "CPLAssetInSmartAlbumByAssetDate:Favorite"
        assert favorites.list_type == "CPLAssetAndMasterInSmartAlbumByAssetDate"
        assert favorites.direction == "ASCENDING"
        assert favorites.query_filter is not None
        assert len(favorites.query_filter) == 1
        assert favorites.query_filter[0]["fieldName"] == "smartAlbum"

    def test_albums_include_user_albums(self):
        """Test user-created albums are included."""
        albums = self.photos.albums

        # Should include albums from CPLAlbumByPositionLive query
        # From fixtures: "All Photos", "album-1", "album 2"
        assert "All Photos" in albums
        assert "album-1" in albums
        assert "album 2" in albums

    def test_albums_filter_deleted_folders(self):
        """Test deleted albums are excluded."""
        from . import const_photos

        # Add a deleted album to the fixture temporarily
        deleted_album = {
            "recordName": "DELETED-ALBUM-ID",
            "recordType": "CPLAlbum",
            "fields": {
                "recordModificationDate": {
                    "value": 1608493440571,
                    "type": "TIMESTAMP",
                },
                "sortAscending": {"value": 1, "type": "INT64"},
                "sortType": {"value": 0, "type": "INT64"},
                "albumType": {"value": 0, "type": "INT64"},
                "albumNameEnc": {
                    "value": "RGVsZXRlZCBBbGJ1bQ==",  # "Deleted Album" in base64
                    "type": "ENCRYPTED_BYTES",
                },
                "position": {"value": 1063936, "type": "INT64"},
                "sortTypeExt": {"value": 0, "type": "INT64"},
                "isDeleted": {"value": True, "type": "BOOL"},  # This album is deleted
            },
            "pluginFields": {},
            "recordChangeTag": "3km2",
            "created": {
                "timestamp": 1608493450571,
                "userRecordName": "_1d5r3c201b3a4r5daac8ff7e7fbc0c23",
                "deviceID": "_1d5r3c201b3a4r5daac8ff7e7fbc0c23_1d5r3c201b3a4r5daac8ff7e7fbc0c23",
            },
            "modified": {
                "timestamp": 1608493460571,
                "userRecordName": "_1d5r3c201b3a4r5daac8ff7e7fbc0c23",
                "deviceID": "D41A228F-D89E-494A-8EEF-853D461B68CF",
            },
            "deleted": False,
            "zoneID": {
                "zoneName": "PrimarySync",
                "ownerRecordName": "_1d5r3c201b3a4r5daac8ff7e7fbc0c23",
                "zoneType": "REGULAR_CUSTOM_ZONE",
            },
        }

        # Store original albums data
        original_records = const_photos.DATA["query?remapEnums=True&getCurrentSyncToken=True"][1]["response"]["records"]

        # Add deleted album to fixtures
        const_photos.DATA["query?remapEnums=True&getCurrentSyncToken=True"][1]["response"]["records"] = (
            original_records + [deleted_album]
        )

        try:
            # Create a new service to pick up the modified fixture
            service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
            photos = service.photos
            albums = photos.albums

            # Verify the deleted album is NOT in the albums dict
            assert "Deleted Album" not in albums, "Deleted album should be filtered out"

            # Verify non-deleted albums are still present
            assert "album-1" in albums
            assert "album 2" in albums
            assert len(albums) > 0
        finally:
            # Restore original data
            const_photos.DATA["query?remapEnums=True&getCurrentSyncToken=True"][1]["response"]["records"] = original_records

    def test_albums_decode_folder_names(self):
        """Test base64 decoding of albumNameEnc."""
        albums = self.photos.albums

        # User albums should have decoded names
        # From fixtures: "album-1" decoded from "YWxidW0tMQ=="
        assert "album-1" in albums
        assert "album 2" in albums

    def test_albums_exclude_root_folders(self):
        """Test that root folders are not included in albums."""
        albums = self.photos.albums

        # Root-Folder and Project-Root-Folder should not appear in albums
        assert "----Root-Folder----" not in albums
        assert "----Project-Root-Folder----" not in albums

    def test_albums_all_have_name_property(self):
        """Test that all albums have a name property."""
        albums = self.photos.albums

        for album_name, album in albums.items():
            assert hasattr(album, "name")
            assert album.name == album_name


class AlbumFetchingTests(unittest.TestCase):
    """Test _fetch_folders method."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos

    def test_fetch_folders_request(self):
        """Test raw folder fetch from API."""
        folders = self.photos._fetch_folders()

        assert isinstance(folders, list)
        assert len(folders) > 0

        # Verify folder structure
        for folder in folders:
            assert "recordName" in folder
            assert "recordType" in folder
            assert folder["recordType"] == "CPLAlbum"

    def test_fetch_folders_includes_root_folders(self):
        """Test that root folders are returned from _fetch_folders."""
        folders = self.photos._fetch_folders()

        folder_names = [f["recordName"] for f in folders]
        # Root folders should be in the raw response
        assert "----Root-Folder----" in folder_names
        assert "----Project-Root-Folder----" in folder_names

    def test_fetch_folders_returns_user_albums(self):
        """Test that user albums are in the raw response."""
        folders = self.photos._fetch_folders()

        # Should contain the album records from fixtures
        assert len(folders) >= 5  # At least root folders + user albums


class PhotosLibrariesTests(unittest.TestCase):
    """Test multi-library support."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos

    def test_libraries_property(self):
        """Test libraries property returns dict."""
        libraries = self.photos.libraries

        assert isinstance(libraries, dict)
        assert "PrimarySync" in libraries

    def test_libraries_lazy_loading(self):
        """Test libraries are cached after first access."""
        libraries1 = self.photos.libraries
        libraries2 = self.photos.libraries

        assert libraries1 is libraries2  # Same object

    def test_libraries_not_fetched_on_init(self):
        """Test that libraries are not fetched on initialization."""
        photos = self.service.photos
        # _libraries should be None until accessed
        assert photos._libraries is None


class PhotoLibraryAllPropertyTests(unittest.TestCase):
    """Test PhotoLibrary.all property."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos

    def test_all_property_returns_all_photos_album(self):
        """Test that .all returns the 'All Photos' album."""
        all_album = self.photos.all

        assert all_album is not None
        assert all_album.name == "All Photos"

    def test_all_property_same_as_albums_dict(self):
        """Test that .all is the same object as albums['All Photos']."""
        all_album = self.photos.all
        all_photos_from_dict = self.photos.albums["All Photos"]

        assert all_album is all_photos_from_dict
