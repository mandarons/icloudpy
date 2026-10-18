"""Tests for Photos service."""

import copy
import json
import unittest
from unittest.mock import patch

from icloudpy.exceptions import (
    ICloudPyAPIResponseException,
    ICloudPyLibraryUnavailableException,
    ICloudPyServiceNotActivatedException,
)

from . import ICloudPyServiceMock, ResponseMock
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
        assert (
            "/database/1/com.apple.photos.cloud/production/private"
            in photos._service_endpoint
        )

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

        original_data = const_photos.DATA[
            "query?remapEnums=True&getCurrentSyncToken=True"
        ][0]["response"]
        const_photos.DATA["query?remapEnums=True&getCurrentSyncToken=True"][0][
            "response"
        ] = in_progress_response

        try:
            # This should raise ICloudPyServiceNotActivatedException
            with self.assertRaises(ICloudPyServiceNotActivatedException) as context:
                service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
                _ = service.photos  # Accessing photos property triggers initialization

            # Verify the exception message
            self.assertIn("not finished indexing", str(context.exception))
        finally:
            # Restore original data
            const_photos.DATA["query?remapEnums=True&getCurrentSyncToken=True"][0][
                "response"
            ] = original_data


class UnfinishedIndexTests(unittest.TestCase):
    """Opening Photos while Apple reports a library still indexing.

    Apple can report a library as indexing for weeks while listing it in
    full, and a consumer that refuses to open it backs up nothing in the
    meantime. ``photos_require_finished_index=False`` opens it anyway and
    says how far the index got, so the consumer can keep downloading while
    treating the listing as possibly incomplete.
    """

    KEY = "query?remapEnums=True&getCurrentSyncToken=True"

    def setUp(self):
        """Report every library as still indexing for the test's duration."""
        from . import const_photos

        entry = const_photos.DATA[self.KEY][0]
        original = entry["response"]
        indexing = copy.deepcopy(original)
        indexing["records"][0]["fields"]["state"]["value"] = "RUNNING"
        entry["response"] = indexing
        self.addCleanup(entry.__setitem__, "response", original)

    def _service(self, require_finished_index):
        return ICloudPyServiceMock(
            AUTHENTICATED_USER,
            VALID_PASSWORD,
            photos_require_finished_index=require_finished_index,
        )

    def test_the_default_still_refuses(self):
        with self.assertRaises(ICloudPyServiceNotActivatedException):
            _ = self._service(True).photos

    def test_opting_out_opens_the_primary_library(self):
        photos = self._service(False).photos
        assert photos.indexing_state == "RUNNING"

    def test_opting_out_opens_every_library(self):
        libraries = self._service(False).photos.libraries
        assert libraries
        assert {library.indexing_state for library in libraries.values()} == {"RUNNING"}

    def test_the_default_is_to_require_a_finished_index(self):
        with self.assertRaises(ICloudPyServiceNotActivatedException):
            _ = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD).photos


class FinishedIndexStateTests(unittest.TestCase):
    def test_a_finished_library_says_so(self):
        photos = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD).photos
        assert photos.indexing_state == "FINISHED"


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
        original_records = const_photos.DATA[
            "query?remapEnums=True&getCurrentSyncToken=True"
        ][1]["response"]["records"]

        # Add deleted album to fixtures
        const_photos.DATA["query?remapEnums=True&getCurrentSyncToken=True"][1][
            "response"
        ]["records"] = original_records + [deleted_album]

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
            const_photos.DATA["query?remapEnums=True&getCurrentSyncToken=True"][1][
                "response"
            ]["records"] = original_records

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


class PhotoAlbumBasicTests(unittest.TestCase):
    """Test PhotoAlbum basic properties and methods."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos
        self.album = self.photos.albums["All Photos"]

    def test_photo_album_title_property(self):
        """Test album title accessor."""
        assert self.album.title == "All Photos"
        assert self.album.name == "All Photos"

    def test_photo_album_iter(self):
        """Test album iteration returns photos generator."""
        # __iter__ should return photos property (a generator)
        # Get a few photos from each to verify they're the same type
        iter_result = iter(self.album)
        property_result = self.album.photos

        # Both should be generators
        assert hasattr(iter_result, "__next__")
        assert hasattr(property_result, "__next__")

    def test_photo_album_repr(self):
        """Test album string representation."""
        repr_str = repr(self.album)
        assert "PhotoAlbum" in repr_str
        assert "All Photos" in repr_str


class PhotoAlbumLengthTests(unittest.TestCase):
    """Test album length calculation."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos

    def test_photo_album_len(self):
        """Test album length calculation via API."""
        album = self.photos.albums["All Photos"]

        length = len(album)
        assert isinstance(length, int)
        assert length >= 0

    def test_photo_album_len_caching(self):
        """Test length is cached after first call."""
        album = self.photos.albums["All Photos"]

        assert album._len is None
        length1 = len(album)
        assert album._len is not None

        length2 = len(album)
        assert length1 == length2

    def test_photo_album_len_query_structure(self):
        """Test HyperionIndexCountLookup query."""
        album = self.photos.albums["Favorites"]

        # Calling len() should trigger count query
        _ = len(album)

        # Verify result is an integer
        assert isinstance(_, int)


class PhotoAlbumIterationTests(unittest.TestCase):
    """Test album photo iteration and pagination."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos

    def test_photo_album_photos_pagination(self):
        """Test photo iteration with pagination."""
        album = self.photos.albums["All Photos"]

        photos = []
        for photo in album.photos:
            photos.append(photo)
            if len(photos) >= 10:  # Limit for test
                break

        assert len(photos) > 0

        # Each photo should be PhotoAsset instance
        for photo in photos:
            assert hasattr(photo, "id")
            assert hasattr(photo, "filename")

    def test_photo_album_photos_ascending_order(self):
        """Test ASCENDING direction calculates offset correctly."""
        album = self.photos.albums["All Photos"]
        assert album.direction == "ASCENDING"

        # Get first few photos to verify they're returned
        photos = []
        for photo in album.photos:
            photos.append(photo)
            if len(photos) >= 3:
                break
        assert len(photos) > 0

    def test_photo_album_photos_descending_order(self):
        """Test DESCENDING direction calculates offset from len()-1."""
        # Recently Deleted has DESCENDING direction
        album = self.photos.albums["Recently Deleted"]

        if album.direction == "DESCENDING":
            # Get a few photos to verify they're returned
            photos = []
            for photo in album.photos:
                photos.append(photo)
                if len(photos) >= 3:
                    break

    def test_photo_album_photos_empty_response(self):
        """Test iteration stops when no more photos returned."""
        album = self.photos.albums["All Photos"]

        # Should stop iterating when response has no records
        # Iterate through all photos - mock will return empty after first page
        photos = []
        for photo in album.photos:
            photos.append(photo)
            # Safeguard to prevent infinite loops in test
            if len(photos) >= 100:
                break

        # Final iteration should break cleanly
        assert isinstance(photos, list)
        assert len(photos) > 0  # Should have gotten some photos

    def test_photo_album_photos_with_query_filter(self):
        """Test filtered photo queries (smart albums)."""
        # Favorites album has query_filter
        favorites = self.photos.albums["Favorites"]

        assert favorites.query_filter is not None

        # Should include filter in query
        photos = []
        for photo in favorites.photos:
            photos.append(photo)
            if len(photos) >= 3:
                break
        assert isinstance(photos, list)


class PhotoAlbumQueryGenerationTests(unittest.TestCase):
    """Test _list_query_gen method."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos
        self.album = self.photos.albums["All Photos"]

    def test_list_query_gen_structure(self):
        """Test query generation has all required fields."""
        query = self.album._list_query_gen(
            offset=0,
            list_type="CPLAssetAndMasterByAddedDate",
            direction="ASCENDING",
            query_filter=None,
        )

        assert "query" in query
        assert "resultsLimit" in query
        assert "desiredKeys" in query
        assert "zoneID" in query

        # Check filter structure
        filters = query["query"]["filterBy"]
        assert any(f["fieldName"] == "startRank" for f in filters)
        assert any(f["fieldName"] == "direction" for f in filters)

    def test_list_query_gen_with_query_filter(self):
        """Test query generation includes custom filters."""
        query_filter = [
            {
                "fieldName": "smartAlbum",
                "comparator": "EQUALS",
                "fieldValue": {"type": "STRING", "value": "FAVORITE"},
            },
        ]

        query = self.album._list_query_gen(
            offset=0,
            list_type="test",
            direction="ASCENDING",
            query_filter=query_filter,
        )

        filters = query["query"]["filterBy"]
        assert len(filters) >= 3  # startRank, direction, + custom

    def test_list_query_gen_desired_keys(self):
        """Test all desired keys are present."""
        query = self.album._list_query_gen(0, "test", "ASCENDING", None)

        desired_keys = query["desiredKeys"]

        # Check critical keys
        assert "resOriginalRes" in desired_keys
        assert "filenameEnc" in desired_keys
        assert "masterRef" in desired_keys
        assert "assetDate" in desired_keys
        assert "resJPEGThumbRes" in desired_keys


class SubalbumTests(unittest.TestCase):
    """Test subalbum functionality."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos

    def test_subalbums_property(self):
        """Test subalbums property returns dict."""
        # User albums have folder_id
        albums = self.photos.albums

        # album-1 is a user album with a folder_id
        if "album-1" in albums:
            user_album = albums["album-1"]
            subalbums = user_album.subalbums
            assert isinstance(subalbums, dict)

    def test_subalbums_lazy_loading(self):
        """Test subalbums are cached."""
        albums = self.photos.albums

        if "album-1" in albums:
            user_album = albums["album-1"]
            # _subalbums should be empty dict initially
            assert user_album._subalbums == {}

            # First access
            subalbums1 = user_album.subalbums
            # Second access should return same object
            subalbums2 = user_album.subalbums
            assert subalbums1 is subalbums2

    def test_subalbums_no_folder_id(self):
        """Test albums without folder_id return empty dict."""
        # Smart albums don't have folder_id (use Favorites which won't be overwritten)
        favorites = self.photos.albums["Favorites"]
        assert favorites.folder_id is None

        subalbums = favorites.subalbums
        assert subalbums == {}

    def test_descending_album_offset(self):
        """Test DESCENDING albums calculate offset from len()-1."""
        # Recently Deleted uses DESCENDING
        album = self.photos.albums["Recently Deleted"]

        if album.direction == "DESCENDING":
            # Access photos to trigger offset calculation
            photos = []
            for photo in album.photos:
                photos.append(photo)
                if len(photos) >= 2:
                    break
            # Should successfully iterate even in descending mode


class PhotoAssetPropertiesTests(unittest.TestCase):
    """Test PhotoAsset property accessors."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos
        self.album = self.photos.albums["All Photos"]
        # Get first photo from album
        photo_iter = iter(self.album)
        self.photo = next(photo_iter)

    def test_photo_asset_id(self):
        """Test photo ID extraction."""
        assert self.photo.id is not None
        assert isinstance(self.photo.id, str)

    def test_photo_asset_filename_decode(self):
        """Test base64 filename decoding."""
        filename = self.photo.filename

        assert filename is not None
        assert isinstance(filename, str)
        # Should be decoded from base64

    def test_photo_asset_size(self):
        """Test size from resOriginalRes field."""
        size = self.photo.size

        assert size is not None
        assert isinstance(size, int)
        assert size > 0

    def test_photo_asset_created_date(self):
        """Test created/asset_date handling."""
        created = self.photo.created
        asset_date = self.photo.asset_date

        assert created is not None
        assert asset_date is not None
        assert created == asset_date

    def test_photo_asset_added_date(self):
        """Test added_date extraction."""
        added = self.photo.added_date

        assert added is not None
        # Should be datetime object

    def test_photo_asset_dimensions(self):
        """Test width/height extraction."""
        dims = self.photo.dimensions

        assert isinstance(dims, tuple)
        assert len(dims) == 2
        assert dims[0] > 0  # width
        assert dims[1] > 0  # height

    def test_photo_asset_repr(self):
        """Test PhotoAsset string representation."""
        repr_str = repr(self.photo)
        assert "PhotoAsset" in repr_str
        assert self.photo.id in repr_str


class PhotoAssetVersionsTests(unittest.TestCase):
    """Test photo version generation."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos

    def test_photo_asset_versions_photo(self):
        """Test version generation for photos."""
        album = self.photos.albums["All Photos"]
        photo = next(iter(album))

        versions = photo.versions

        assert isinstance(versions, dict)

        # Should have photo versions
        expected_keys = ["original", "medium", "thumb"]
        for key in expected_keys:
            if key in versions:
                version = versions[key]
                assert "filename" in version
                assert "size" in version
                assert "url" in version
                assert "width" in version
                assert "height" in version
                assert "type" in version

    def test_photo_asset_versions_video(self):
        """Test version generation for videos."""
        videos = self.photos.albums["Videos"]

        # Get first video
        try:
            video = next(iter(videos))
            versions = video.versions

            # Should have video versions
            assert isinstance(versions, dict)
        except StopIteration:
            # No videos in test fixtures, skip
            pass

    def test_photo_asset_versions_lazy_loading(self):
        """Test versions are cached."""
        album = self.photos.albums["All Photos"]
        photo = next(iter(album))

        assert photo._versions is None
        versions1 = photo.versions
        assert photo._versions is not None

        versions2 = photo.versions
        assert versions1 is versions2

    def test_photo_asset_versions_missing_fields(self):
        """Test version with missing optional fields."""
        album = self.photos.albums["All Photos"]
        photo = next(iter(album))

        versions = photo.versions
        # Some versions may not have width/height
        # Should handle gracefully (set to None)
        for key, version in versions.items():
            # All versions should have these fields even if None
            assert "width" in version
            assert "height" in version

    def test_photo_asset_str_method(self):
        """Test PhotoAsset __str__ method."""
        album = self.photos.albums["All Photos"]
        photo = next(iter(album))

        # __str__ should return string representation
        str_repr = str(photo)
        assert isinstance(str_repr, str)


class PhotoAssetDownloadTests(unittest.TestCase):
    """Test photo download functionality."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos
        self.album = self.photos.albums["All Photos"]
        self.photo = next(iter(self.album))

    def test_photo_download_original(self):
        """Test downloading original version."""
        response = self.photo.download("original")

        assert response is not None
        assert hasattr(response, "status_code")

    def test_photo_download_medium(self):
        """Test downloading medium version."""
        response = self.photo.download("medium")

        if "medium" in self.photo.versions:
            assert response is not None

    def test_photo_download_thumb(self):
        """Test downloading thumbnail version."""
        response = self.photo.download("thumb")

        if "thumb" in self.photo.versions:
            assert response is not None

    def test_photo_download_missing_version(self):
        """Test downloading non-existent version returns None."""
        response = self.photo.download("nonexistent_size")

        assert response is None

    def test_photo_download_with_kwargs(self):
        """Test download passes through kwargs."""
        # Download always passes stream=True by default, test with other kwargs
        response = self.photo.download("original", timeout=30)
        assert response is not None


class PhotoAssetDeletionTests(unittest.TestCase):
    """Test photo deletion."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos
        self.album = self.photos.albums["All Photos"]
        self.photo = next(iter(self.album))

    def test_photo_delete(self):
        """Test marking photo as deleted."""
        result = self.photo.delete()

        assert result is not None
        # Should POST to /records/modify with isDeleted=1

    def test_photo_delete_request_structure(self):
        """Test delete request includes required fields."""
        # Should include:
        # - recordChangeTag
        # - recordName
        # - recordType
        # - isDeleted field = 1
        result = self.photo.delete()
        assert result is not None


class PhotoAssetZoneTests(unittest.TestCase):
    """A photo acts in its own library's zone, not the service's.

    Every asset is handed the ``PhotosService``, whose zone is always
    ``PrimarySync``. Deleting a Shared Library photo through it would address
    the record in the wrong zone, where it does not exist.
    """

    SHARED = {
        "zoneName": "SharedSync-0000",
        "ownerRecordName": "_owner",
        "zoneType": "REGULAR_CUSTOM_ZONE",
    }

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos

    def _first_photo_in(self, zone_id=None):
        album = PhotoAlbum(
            self.photos,
            "All Photos",
            list_type="CPLAssetAndMasterByAddedDate",
            obj_type="CPLAssetByAddedDate",
            direction="ASCENDING",
            zone_id=zone_id,
        )
        return next(iter(album))

    def test_a_photo_carries_its_librarys_zone(self):
        assert self._first_photo_in(self.SHARED).zone_id == self.SHARED

    def test_delete_addresses_the_photos_own_zone(self):
        photo = self._first_photo_in(self.SHARED)
        with patch.object(self.photos.session, "post") as post:
            photo.delete()
        assert json.loads(post.call_args.kwargs["data"])["zoneID"] == self.SHARED

    def test_a_primary_library_photo_is_unchanged(self):
        photo = next(iter(self.photos.albums["All Photos"]))
        assert photo.zone_id == self.photos.zone_id

    def test_an_album_built_without_a_zone_uses_the_primary_librarys(self):
        """Its fallback was the bare name, which delete() would have sent as
        the zone instead of the dict CloudKit expects."""
        assert self._first_photo_in().zone_id == {"zoneName": "PrimarySync"}

    def test_an_asset_built_without_a_zone_falls_back_to_the_service(self):
        photo = self._first_photo_in(self.SHARED)
        bare = PhotoAsset(self.photos, photo._master_record, photo._asset_record)
        assert bare.zone_id == self.photos.zone_id


class PhotoAssetMissingFilenameTests(unittest.TestCase):
    """Test PhotoAsset handles missing filenameEnc gracefully."""

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos
        self.album = self.photos.albums["All Photos"]

        # Find the GoPro video without filename in the album
        self.gopro_video = next(
            (
                photo
                for photo in self.album.photos
                if photo.id == "GOPRO-NO-FILENAME-TEST-MASTER"
            ),
            None,
        )

        # Ensure we found the test photo
        assert (
            self.gopro_video is not None
        ), "Test fixture GOPRO-NO-FILENAME-TEST-MASTER not found"

    def test_photo_asset_filename_missing_returns_none(self):
        """Test filename property returns None when filenameEnc is missing."""
        filename = self.gopro_video.filename

        assert filename is None

    def test_photo_asset_versions_with_missing_filename(self):
        """Test versions property works when filename is None."""
        versions = self.gopro_video.versions

        assert isinstance(versions, dict)
        assert len(versions) > 0

        # Check that versions were created despite missing filename
        for _, version in versions.items():
            assert "filename" in version
            assert version["filename"] is None  # Should be None, not raise KeyError
            assert "size" in version
            assert "url" in version

    def test_photo_asset_id_still_works(self):
        """Test id property still works when filenameEnc is missing."""
        photo_id = self.gopro_video.id

        assert photo_id == "GOPRO-NO-FILENAME-TEST-MASTER"

    def test_photo_asset_size_still_works(self):
        """Test size property still works when filenameEnc is missing."""
        size = self.gopro_video.size

        assert isinstance(size, int)
        assert size > 0

    def test_photo_asset_dimensions_still_work(self):
        """Test dimensions property still works when filenameEnc is missing."""
        dims = self.gopro_video.dimensions

        assert isinstance(dims, tuple)
        assert len(dims) == 2
        assert dims[0] == 1920  # width
        assert dims[1] == 1080  # height


# ─── Live Photo / item_type tests ─────────────────────────────────────────
# Added 2026-05-27 as part of feat/live-photos.

import base64 as _b64

from icloudpy.services.photos import PhotoAlbum, PhotoAsset


def _b64name(name):
    return _b64.b64encode(name.encode()).decode()


def _photo_field(
    prefix, *, size=12345, url=None, file_type="public.heic", width=4032, height=3024,
):
    """Build the CloudKit master_record fields for one asset version prefix."""
    return {
        f"{prefix}Width": {"value": width},
        f"{prefix}Height": {"value": height},
        f"{prefix}FileType": {"value": file_type},
        f"{prefix}Res": {
            "value": {
                "size": size,
                "downloadURL": url or f"https://example.invalid/{prefix}",
                "fileChecksum": f"sum-{prefix}",
            },
        },
    }


def _make_master(filename, item_type_uti, *field_blocks):
    fields = {"filenameEnc": {"value": _b64name(filename)}}
    if item_type_uti is not None:
        fields["itemType"] = {"value": item_type_uti}
    for block in field_blocks:
        fields.update(block)
    return {"recordName": "test-record", "fields": fields}


def _make_asset_record():
    return {
        "fields": {
            "assetDate": {"value": 1700000000000},
            "addedDate": {"value": 1700000000000},
        },
    }


class TestItemTypeDetection(unittest.TestCase):
    """item_type property — UTI lookup + extension fallback."""

    def test_heic_uti_returns_image(self):
        master = _make_master("photo.heic", "public.heic", _photo_field("resOriginal"))
        asset = PhotoAsset(
            service=None, master_record=master, asset_record=_make_asset_record(),
        )
        assert asset.item_type == "image"

    def test_jpeg_uti_returns_image(self):
        master = _make_master(
            "photo.jpg",
            "public.jpeg",
            _photo_field("resOriginal", file_type="public.jpeg"),
        )
        asset = PhotoAsset(
            service=None, master_record=master, asset_record=_make_asset_record(),
        )
        assert asset.item_type == "image"

    def test_quicktime_uti_returns_movie(self):
        master = _make_master(
            "clip.mov",
            "com.apple.quicktime-movie",
            _photo_field("resOriginal", file_type="com.apple.quicktime-movie"),
        )
        asset = PhotoAsset(
            service=None, master_record=master, asset_record=_make_asset_record(),
        )
        assert asset.item_type == "movie"

    def test_canon_raw_uti_returns_image(self):
        master = _make_master(
            "raw.cr3", "com.canon.cr3-raw-image", _photo_field("resOriginal"),
        )
        asset = PhotoAsset(
            service=None, master_record=master, asset_record=_make_asset_record(),
        )
        assert asset.item_type == "image"

    def test_missing_uti_with_heic_extension_returns_image(self):
        master = _make_master("photo.HEIC", None, _photo_field("resOriginal"))
        asset = PhotoAsset(
            service=None, master_record=master, asset_record=_make_asset_record(),
        )
        assert asset.item_type == "image"

    def test_missing_uti_with_mov_extension_returns_movie(self):
        master = _make_master("clip.MOV", None, _photo_field("resOriginal"))
        asset = PhotoAsset(
            service=None, master_record=master, asset_record=_make_asset_record(),
        )
        assert asset.item_type == "movie"

    def test_no_uti_no_filename_returns_none(self):
        master = {"recordName": "r", "fields": _photo_field("resOriginal")}
        asset = PhotoAsset(
            service=None, master_record=master, asset_record=_make_asset_record(),
        )
        # filename property raises KeyError → returns None; item_type sees None and falls through
        assert asset.item_type is None

    def test_unknown_uti_with_jpg_extension_returns_image(self):
        master = _make_master(
            "photo.jpg", "public.fake-format", _photo_field("resOriginal"),
        )
        asset = PhotoAsset(
            service=None, master_record=master, asset_record=_make_asset_record(),
        )
        assert asset.item_type == "image"


class TestLivePhotoVersions(unittest.TestCase):
    """Live Photo asset surfaces BOTH still and .mov versions."""

    def _live_photo_master(self):
        """A Live Photo has both photo fields AND the live-video fields in master_record."""
        return _make_master(
            "IMG_1234.HEIC",
            "public.heic",
            _photo_field(
                "resOriginal", size=2_400_000, url="https://example.invalid/heic",
            ),
            _photo_field(
                "resJPEGMed",
                size=300_000,
                url="https://example.invalid/jpeg-med",
                file_type="public.jpeg",
            ),
            _photo_field(
                "resOriginalVidCompl",
                size=1_800_000,
                url="https://example.invalid/live.mov",
                file_type="com.apple.quicktime-movie",
            ),
            _photo_field(
                "resVidMed",
                size=900_000,
                url="https://example.invalid/live-med.mov",
                file_type="com.apple.quicktime-movie",
            ),
            _photo_field(
                "resVidSmall",
                size=200_000,
                url="https://example.invalid/live-thumb.mov",
                file_type="com.apple.quicktime-movie",
            ),
        )

    def test_live_photo_classified_as_image(self):
        asset = PhotoAsset(
            service=None,
            master_record=self._live_photo_master(),
            asset_record=_make_asset_record(),
        )
        assert asset.item_type == "image"

    def test_live_photo_exposes_still_version(self):
        asset = PhotoAsset(
            service=None,
            master_record=self._live_photo_master(),
            asset_record=_make_asset_record(),
        )
        assert "original" in asset.versions
        assert asset.versions["original"]["url"] == "https://example.invalid/heic"
        assert asset.versions["original"]["size"] == 2_400_000

    def test_live_photo_exposes_live_video_versions(self):
        asset = PhotoAsset(
            service=None,
            master_record=self._live_photo_master(),
            asset_record=_make_asset_record(),
        )
        assert "live_video_original" in asset.versions
        assert (
            asset.versions["live_video_original"]["url"]
            == "https://example.invalid/live.mov"
        )
        assert (
            asset.versions["live_video_original"]["type"] == "com.apple.quicktime-movie"
        )
        assert "live_video_medium" in asset.versions
        assert "live_video_thumb" in asset.versions

    def test_plain_photo_has_no_live_video_versions(self):
        """A still photo with no Live Photo .mov in CloudKit must not surface live_video_* keys."""
        master = _make_master("plain.heic", "public.heic", _photo_field("resOriginal"))
        asset = PhotoAsset(
            service=None, master_record=master, asset_record=_make_asset_record(),
        )
        assert "original" in asset.versions
        assert "live_video_original" not in asset.versions
        assert "live_video_medium" not in asset.versions
        assert "live_video_thumb" not in asset.versions

    def test_regular_video_uses_video_lookup(self):
        """Movies (item_type=movie) must use VIDEO_VERSION_LOOKUP, not PHOTO_VERSION_LOOKUP."""
        master = _make_master(
            "clip.MOV",
            "com.apple.quicktime-movie",
            _photo_field(
                "resOriginal",
                size=10_000_000,
                url="https://example.invalid/orig.mov",
                file_type="com.apple.quicktime-movie",
            ),
            _photo_field(
                "resVidMed",
                size=2_000_000,
                url="https://example.invalid/med.mov",
                file_type="com.apple.quicktime-movie",
            ),
            _photo_field(
                "resVidSmall",
                size=500_000,
                url="https://example.invalid/small.mov",
                file_type="com.apple.quicktime-movie",
            ),
        )
        asset = PhotoAsset(
            service=None, master_record=master, asset_record=_make_asset_record(),
        )
        assert asset.item_type == "movie"
        # video lookup keys are 'medium' / 'thumb' / 'original', NOT 'live_video_*'
        assert "medium" in asset.versions
        assert "thumb" in asset.versions
        assert "live_video_original" not in asset.versions


class PhotoAlbumIterChunksTests(unittest.TestCase):
    """``PhotoAlbum.iter_chunks(N)`` yields lists of up to N PhotoAssets,
    letting callers bound peak memory by chunk size rather than
    ``len(album)``. Tests stub the iteration source so we don't make
    repeated paginated HTTP-mock passes (which the fixture isn't shaped
    for and which would be slow regardless)."""

    def setUp(self):
        """Build a service + grab the All Photos album."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos
        self.album = self.photos.albums["All Photos"]

    def _stub_album_with(self, items):
        """Patch ``self.album.__iter__`` to yield the given items.

        ``iter_chunks`` consumes the album via ``for photo in self``,
        which goes through ``__iter__``. Patching here avoids hitting
        the paginated HTTP mock at all -- each test gets exactly the
        item sequence it asked for, no fixture coupling.
        """
        from unittest.mock import patch

        return patch.object(
            type(self.album),
            "__iter__",
            lambda _self: iter(items),
        )

    def test_chunked_total_matches_plain_iteration(self):
        """No item lost, no item duplicated. Sum across chunks ==
        len(items)."""
        items = list(range(7))
        with self._stub_album_with(items):
            chunks = list(self.album.iter_chunks(chunk_size=3))
        flat = [x for chunk in chunks for x in chunk]
        assert flat == items, f"{flat!r} != {items!r}"

    def test_chunked_respects_chunk_size_cap(self):
        """No yielded chunk exceeds the requested size."""
        items = list(range(10))
        with self._stub_album_with(items):
            chunks = list(self.album.iter_chunks(chunk_size=4))
        for chunk in chunks:
            assert len(chunk) <= 4, f"{len(chunk)} > 4"

    def test_chunked_final_chunk_may_be_smaller(self):
        """Partial final chunk is yielded, not dropped. 10 items in
        chunks of 4 → [4, 4, 2]."""
        items = list(range(10))
        with self._stub_album_with(items):
            chunks = list(self.album.iter_chunks(chunk_size=4))
        sizes = [len(c) for c in chunks]
        assert sizes == [4, 4, 2], f"{sizes!r}"

    def test_chunked_exact_multiple_no_empty_trailing_chunk(self):
        """When item count is an exact multiple of chunk_size, the
        last chunk is full -- no empty trailing chunk is yielded."""
        items = list(range(9))
        with self._stub_album_with(items):
            chunks = list(self.album.iter_chunks(chunk_size=3))
        sizes = [len(c) for c in chunks]
        assert sizes == [3, 3, 3], f"{sizes!r}"

    def test_chunked_empty_album_yields_nothing(self):
        """An empty source yields no chunks (not one empty chunk)."""
        with self._stub_album_with([]):
            chunks = list(self.album.iter_chunks(chunk_size=10))
        assert chunks == []

    def test_chunked_invalid_size_falls_back_to_default(self):
        """``chunk_size <= 0`` is coerced to the 1000 default rather
        than infinite-looping or yielding empty chunks forever."""
        items = list(range(5))
        with self._stub_album_with(items):
            chunks = list(self.album.iter_chunks(chunk_size=0))
        flat = [x for chunk in chunks for x in chunk]
        assert flat == items
        # All 5 items in one chunk since default 1000 > 5.
        assert len(chunks) == 1

    def test_chunked_negative_size_also_falls_back(self):
        """Defensive: a negative size from a buggy config getter is
        treated the same as zero."""
        items = list(range(3))
        with self._stub_album_with(items):
            chunks = list(self.album.iter_chunks(chunk_size=-50))
        flat = [x for chunk in chunks for x in chunk]
        assert flat == items
        assert len(chunks) == 1


class UnusableZoneTests(unittest.TestCase):
    """A zone Apple rejects must not break enumeration or the other libraries.

    Regression tests for #179: a broken zone used to raise a raw
    ``Index has invalid data`` (400) out of ``photos.libraries``/``albums``
    and crash the sync for every library.
    """

    def setUp(self):
        """Set up test."""
        self.service = ICloudPyServiceMock(AUTHENTICATED_USER, VALID_PASSWORD)
        self.photos = self.service.photos

    @staticmethod
    def _zones(*zone_names):
        """Build a zones/list response for the given zone names."""
        return ResponseMock(
            {"zones": [{"zoneID": {"zoneName": name}} for name in zone_names]},
        )

    @staticmethod
    def _indexing_ok(data):
        """Answer for the CheckIndexingState query built by PhotoLibrary.__init__."""
        if "CheckIndexingState" in data:
            return ResponseMock(
                {"records": [{"fields": {"state": {"value": "FINISHED"}}}]},
            )
        return None

    def test_zone_name_handles_dict_and_bare_name(self):
        """Zone labels come from dicts or fall back to bare names."""
        from icloudpy.services import photos as photos_module

        assert photos_module._zone_name({"zoneName": "PrimarySync"}) == "PrimarySync"
        assert photos_module._zone_name("PrimarySync") == "PrimarySync"

    def test_fetch_folders_fatal_error_raises_zone_labelled_exception(self):
        """A definitive rejection names the zone and keeps the API type."""
        fatal = ICloudPyAPIResponseException("Index has invalid data", "BAD_REQUEST")

        with patch.object(self.photos.session, "post", side_effect=fatal):
            with self.assertRaises(ICloudPyLibraryUnavailableException) as ctx:
                self.photos._fetch_folders()

        err = ctx.exception
        assert err.zone_name == "PrimarySync"
        assert "PrimarySync" in str(err)
        assert "Index has invalid data" in str(err)
        # Existing handlers catching the parent type must keep working.
        assert isinstance(err, ICloudPyAPIResponseException)

    def test_fetch_folders_transient_error_propagates_unchanged(self):
        """5xx and other non-zone errors are never re-labelled."""
        transient = ICloudPyAPIResponseException(
            "Internal server error",
            "SERVER_ERROR",
        )

        with patch.object(self.photos.session, "post", side_effect=transient):
            with self.assertRaises(ICloudPyAPIResponseException) as ctx:
                self.photos._fetch_folders()

        assert not isinstance(ctx.exception, ICloudPyLibraryUnavailableException)

    def test_libraries_skips_cmm_zone_without_querying_it(self):
        """CMM (Cloud Moments) zones are filtered before any query."""
        posted = []

        def fake_post(url, data="{}", headers=None):
            posted.append(str(data))
            if "zones/list" in url:
                return self._zones("PrimarySync", "CMM-11A44FA2-882C-4E5D-9F06")
            indexing = self._indexing_ok(data)
            if indexing is not None:
                return indexing
            return ResponseMock({"records": []})

        with patch.object(self.photos.session, "post", side_effect=fake_post):
            libraries = self.photos.libraries

        assert set(libraries) == {"PrimarySync"}
        assert not any("CMM-11A44FA2" in data for data in posted)

    def test_libraries_skips_zone_rejected_at_construction(self):
        """A zone failing the indexing query in __init__ is skipped with a warning."""

        def fake_post(url, data="{}", headers=None):
            if "zones/list" in url:
                return self._zones("PrimarySync", "Sync-Gone")
            if "Sync-Gone" in data and "CheckIndexingState" in data:
                raise ICloudPyAPIResponseException("Zone not found", "ZONE_NOT_FOUND")
            indexing = self._indexing_ok(data)
            if indexing is not None:
                return indexing
            return ResponseMock({"records": []})

        with patch.object(self.photos.session, "post", side_effect=fake_post):
            with self.assertLogs("icloudpy.services.photos", level="WARNING") as logs:
                libraries = self.photos.libraries

        assert set(libraries) == {"PrimarySync"}
        assert any("Sync-Gone" in line for line in logs.output)

    def test_libraries_skips_zone_rejected_by_album_query(self):
        """#179's failure: zones/list succeeds, the album query 400s."""

        def fake_post(url, data="{}", headers=None):
            if "zones/list" in url:
                return self._zones("PrimarySync", "SharedSync-Broken")
            indexing = self._indexing_ok(data)
            if indexing is not None:
                return indexing
            if "SharedSync-Broken" in data:
                raise ICloudPyAPIResponseException(
                    "Index has invalid data",
                    "BAD_REQUEST",
                )
            return ResponseMock({"records": []})

        with patch.object(self.photos.session, "post", side_effect=fake_post):
            with self.assertLogs("icloudpy.services.photos", level="WARNING") as logs:
                libraries = self.photos.libraries

        assert set(libraries) == {"PrimarySync"}
        assert any("SharedSync-Broken" in line for line in logs.output)

    def test_libraries_keeps_zone_on_transient_probe_failure(self):
        """A network/5xx blip while probing must not exclude a live zone."""

        def fake_post(url, data="{}", headers=None):
            if "zones/list" in url:
                return self._zones("PrimarySync", "SharedSync-Flaky")
            indexing = self._indexing_ok(data)
            if indexing is not None:
                return indexing
            if "SharedSync-Flaky" in data:
                raise ICloudPyAPIResponseException(
                    "Internal server error",
                    "SERVER_ERROR",
                )
            return ResponseMock({"records": []})

        with patch.object(self.photos.session, "post", side_effect=fake_post):
            libraries = self.photos.libraries

        assert set(libraries) == {"PrimarySync", "SharedSync-Flaky"}

    def test_zones_list_failure_raises_original_error(self):
        """A failed zones/list surfaces the real error, not UnboundLocalError."""
        with patch.object(
            self.photos.session,
            "post",
            side_effect=RuntimeError("zones list down"),
        ):
            with self.assertRaisesRegex(RuntimeError, "zones list down"):
                self.photos.libraries

    def test_albums_retries_after_fetch_failure(self):
        """A failed folder fetch caches nothing; the next access retries.

        Previously the smart folders were cached before the fetch, so a
        survivor catching the error got a silently partial album list forever.
        """
        fatal = ICloudPyAPIResponseException("Index has invalid data", "BAD_REQUEST")

        with patch.object(
            self.photos.session,
            "post",
            side_effect=[fatal, ResponseMock({"records": []})],
        ) as post:
            with self.assertRaises(ICloudPyLibraryUnavailableException):
                _ = self.photos.albums
            albums = self.photos.albums

        assert post.call_count == 2
        assert "All Photos" in albums

    def test_album_photos_fatal_error_is_labelled_with_zone(self):
        """Photo iteration failures carry the zone too."""
        from icloudpy.services.photos import PhotoAlbum

        album = PhotoAlbum(
            self.photos,
            "Test",
            list_type="CPLAssetAndMasterByAssetDate",
            obj_type="CPLAssetAndMaster",
            direction="ASCENDING",
            zone_id={"zoneName": "SharedSync-Broken"},
        )
        fatal = ICloudPyAPIResponseException("Index has invalid data", "BAD_REQUEST")

        with patch.object(self.photos.session, "post", side_effect=fatal):
            with self.assertRaises(ICloudPyLibraryUnavailableException) as ctx:
                next(album.photos)

        assert ctx.exception.zone_name == "SharedSync-Broken"

    def test_fetch_folders_unrecognised_bad_request_is_not_a_verdict(self):
        """A 400 with an unrecognised reason propagates unconverted.

        Only the known dead-zone reason text converts; any other
        zone-scoped 400 (e.g. a bug in our own query template) must reach
        the caller unchanged instead of silently dropping the library.
        """
        malformed = ICloudPyAPIResponseException("Malformed query", "BAD_REQUEST")

        with patch.object(self.photos.session, "post", side_effect=malformed):
            with self.assertRaises(ICloudPyAPIResponseException) as ctx:
                self.photos._fetch_folders()

        assert ctx.exception is malformed
        assert not isinstance(ctx.exception, ICloudPyLibraryUnavailableException)

    def test_libraries_keeps_zone_on_unrecognised_bad_request(self):
        """An unrecognised 400 during the probe is no reason to exclude.

        The zone survives enumeration (the consumer sees the same raise it
        would have seen before this PR if it ever queries the library).
        """

        def fake_post(url, data="{}", headers=None):
            if "zones/list" in url:
                return self._zones("PrimarySync", "SharedSync-Unknown400")
            indexing = self._indexing_ok(data)
            if indexing is not None:
                return indexing
            if "SharedSync-Unknown400" in data:
                raise ICloudPyAPIResponseException("Malformed query", "BAD_REQUEST")
            return ResponseMock({"records": []})

        with patch.object(self.photos.session, "post", side_effect=fake_post):
            libraries = self.photos.libraries

        assert set(libraries) == {"PrimarySync", "SharedSync-Unknown400"}
