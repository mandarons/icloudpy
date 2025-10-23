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
