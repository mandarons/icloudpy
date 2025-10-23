"""Library tests."""

import json

from requests import Response

from icloudpy import base

from .const import (
    AUTHENTICATED_USER,
    CLIENT_ID,
    REQUIRES_2FA_TOKEN,
    REQUIRES_2FA_USER,
    VALID_2FA_CODE,
    VALID_COOKIE,
    VALID_TOKEN,
    VALID_TOKENS,
    VALID_USERS,
)
from .const_account import ACCOUNT_DEVICES_WORKING, ACCOUNT_STORAGE_WORKING
from .const_account_family import ACCOUNT_FAMILY_WORKING
from .const_auth import (
    AUTH_OK,
    SRP_INIT_OK,
    TRUSTED_DEVICE_1,
    TRUSTED_DEVICES,
    VERIFICATION_CODE_KO,
    VERIFICATION_CODE_OK,
)
from .const_drive import (
    DRIVE_FILE_DOWNLOAD_WORKING,
    DRIVE_FOLDER_WORKING,
    DRIVE_ROOT_INVALID,
    DRIVE_ROOT_WORKING,
    DRIVE_SUBFOLDER_WORKING,
    DRIVE_SUBFOLDER_WORKING_AFTER_MKDIR,
)
from .const_drive_upload import (
    RENAME_ITEMS_RESPONSE,
    TRASH_ITEMS_RESPONSE,
    UPDATE_CONTENTWS_RESPONSE,
    UPLOAD_URL_RESPONSE,
)
from .const_findmyiphone import FMI_FAMILY_WORKING
from .const_login import LOGIN_2FA, LOGIN_WORKING
from .const_photos import DATA as PHOTOS_DATA


class ResponseMock(Response):
    """Mocked Response."""

    def __init__(self, result, status_code=200, **kwargs):
        """Init the object."""
        Response.__init__(self)
        self.result = result
        self.status_code = status_code
        self.raw = kwargs.get("raw")
        self.headers = kwargs.get("headers", {})

    @property
    def text(self):
        """Text result."""
        return json.dumps(self.result)


class ICloudPySessionMock(base.ICloudPySession):
    """Mocked ICloudPySession."""

    # State tracking for multi-step operations
    mkdir_called = False
    upload_count = 0
    rename_count = 0

    def request(self, method, url, **kwargs):
        """Mock request."""
        params = kwargs.get("params")
        headers = kwargs.get("headers")
        # Only parse data if it exists and is not a file upload
        data_str = kwargs.get("data", "{}")
        # Only parse JSON if data_str is a string and not the default '{}'
        if isinstance(data_str, str) and data_str != '{}':
            data = json.loads(data_str)
        else:
            data = {}

        # Login
        if self.service.setup_endpoint in url:
            if "accountLogin" in url and method == "POST":
                if data.get("dsWebAuthToken") not in VALID_TOKENS:
                    self._raise_error(None, "Unknown reason")
                if data.get("dsWebAuthToken") == REQUIRES_2FA_TOKEN:
                    return ResponseMock(LOGIN_2FA)
                return ResponseMock(LOGIN_WORKING)

            if "listDevices" in url and method == "GET":
                return ResponseMock(TRUSTED_DEVICES)

            if "sendVerificationCode" in url and method == "POST":
                if data == TRUSTED_DEVICE_1:
                    return ResponseMock(VERIFICATION_CODE_OK)
                return ResponseMock(VERIFICATION_CODE_KO)

            if "validateVerificationCode" in url and method == "POST":
                TRUSTED_DEVICE_1.update({"verificationCode": "0", "trustBrowser": True})
                if data == TRUSTED_DEVICE_1:
                    self.service.user["apple_id"] = AUTHENTICATED_USER
                    return ResponseMock(VERIFICATION_CODE_OK)
                self._raise_error(None, "FOUND_CODE")

            if "validate" in url and method == "POST":
                # Either a valid cookie in headers or a valid session token is sufficient for login
                if (
                    (headers and headers.get("X-APPLE-WEBAUTH-TOKEN") == VALID_COOKIE)
                    or (self.service.session_data.get("session_token") in [VALID_TOKEN, REQUIRES_2FA_TOKEN])
                ):
                    return ResponseMock(LOGIN_WORKING)
                self._raise_error(None, "Session expired")

        if self.service.auth_endpoint in url:
            if "signin" in url and method == "POST":
                if (
                    data.get("accountName") not in VALID_USERS
                    # or data.get("password") != VALID_PASSWORD
                ):
                    self._raise_error(None, "Unknown reason")
                if url.endswith("/init"):
                    return ResponseMock(SRP_INIT_OK)
                if data.get("accountName") == REQUIRES_2FA_USER:
                    self.service.session_data["session_token"] = REQUIRES_2FA_TOKEN
                    return ResponseMock(AUTH_OK)

                self.service.session_data["session_token"] = VALID_TOKEN
                self.service.session_data["client_id"] = CLIENT_ID
                return ResponseMock(AUTH_OK)

            if "securitycode" in url and method == "POST":
                if data.get("securityCode", {}).get("code") != VALID_2FA_CODE:
                    self._raise_error(-21669, "Incorrect verification code")

                self.service.session_data["session_token"] = VALID_TOKEN
                return ResponseMock("", status_code=204)

            if "trust" in url and method == "GET":
                return ResponseMock("", status_code=204)

        # Account
        if "device/getDevices" in url and method == "GET":
            return ResponseMock(ACCOUNT_DEVICES_WORKING)
        if "family/getFamilyDetails" in url and method == "GET":
            return ResponseMock(ACCOUNT_FAMILY_WORKING)
        if "setup/ws/1/storageUsageInfo" in url and method == "GET":
            return ResponseMock(ACCOUNT_STORAGE_WORKING)

        # Drive
        if "retrieveItemDetailsInFolders" in url and method == "POST" and data[0].get("drivewsid"):
            if data[0].get("drivewsid") == "FOLDER::com.apple.CloudDocs::root":
                return ResponseMock(DRIVE_ROOT_WORKING)
            if data[0].get("drivewsid") == "FOLDER::com.apple.CloudDocs::documents":
                return ResponseMock(DRIVE_ROOT_INVALID)
            if data[0].get("drivewsid") == "FOLDER::com.apple.Preview::documents":
                return ResponseMock(DRIVE_ROOT_INVALID)
            if data[0].get("drivewsid") == "FOLDER::com.apple.CloudDocs::1C7F1760-D940-480F-8C4F-005824A4E05B":
                return ResponseMock(DRIVE_FOLDER_WORKING)
            if data[0].get("drivewsid") == "FOLDER::com.apple.CloudDocs::D5AA0425-E84F-4501-AF5D-60F1D92648CF":
                print("getFolder params:", self.params, self.mkdir_called)
                if self.mkdir_called:
                    return ResponseMock(DRIVE_SUBFOLDER_WORKING_AFTER_MKDIR)
                else:
                    return ResponseMock(DRIVE_SUBFOLDER_WORKING)
        if "/createFolders" in url and method == "POST":
            self.mkdir_called = True
            return ResponseMock(DRIVE_SUBFOLDER_WORKING_AFTER_MKDIR)
        # Drive app library
        if "retrieveAppLibraries" in url and method == "GET":
            return ResponseMock({"items": []})
        # Drive upload endpoints
        if "/upload/web" in url and method == "POST":
            self.upload_count += 1
            return ResponseMock(UPLOAD_URL_RESPONSE)
        if "/ws/upload/file" in url and method == "POST":
            # Mock the actual file upload endpoint
            return ResponseMock({
                "singleFile": {
                    "fileChecksum": "test_checksum",
                    "wrappingKey": "test_wrapping_key",
                    "referenceChecksum": "test_ref_checksum",
                    "size": 123,
                    "receipt": "test_receipt",
                },
            })
        if "/update/documents" in url and method == "POST":
            return ResponseMock(UPDATE_CONTENTWS_RESPONSE)
        # Drive rename/delete operations
        if "/renameItems" in url and method == "POST":
            self.rename_count += 1
            return ResponseMock(RENAME_ITEMS_RESPONSE)
        if "/moveItemsToTrash" in url and method == "POST":
            return ResponseMock(TRASH_ITEMS_RESPONSE)
        # Drive download
        if "com.apple.CloudDocs/download/by_id" in url and method == "GET":
            if params.get("document_id") == "516C896C-6AA5-4A30-B30E-5502C2333DAE":
                return ResponseMock(DRIVE_FILE_DOWNLOAD_WORKING)
        if "icloud-content.com" in url and method == "GET":
            if "Scanned+document+1.pdf" in url:
                return ResponseMock({}, raw=open(".gitignore", "rb"))

        # Find My iPhone
        if "fmi" in url and method == "POST":
            return ResponseMock(FMI_FAMILY_WORKING)

        # Photos query endpoints
        if "com.apple.photos.cloud" in url:
            if "zones/list" in url and method == "POST":
                # Return zones list for photos
                return ResponseMock(
                    {
                        "zones": [
                            {
                                "zoneID": {
                                    "zoneName": "PrimarySync",
                                    "ownerRecordName": "_fvhhqlzef1uvsgxnrw119mylkpjut1a0",
                                    "zoneType": "REGULAR_CUSTOM_ZONE",
                                },
                                "syncToken": "HwoECJGaGRgAIhYI/ZL516KyxaXfARDm2sbu7KeQiZABKAA=",
                                "atomic": True,
                            },
                        ],
                    },
                )

            if "records/query" in url and method == "POST":
                query_type = data.get("query", {}).get("recordType")

                # Check indexing state
                if query_type == "CheckIndexingState":
                    return ResponseMock(
                        PHOTOS_DATA["query?remapEnums=True&getCurrentSyncToken=True"][0]["response"],
                    )

                # Album queries
                if query_type == "CPLAlbumByPositionLive":
                    return ResponseMock(
                        PHOTOS_DATA["query?remapEnums=True&getCurrentSyncToken=True"][1]["response"],
                    )

                # Asset queries
                if query_type == "CPLAssetAndMasterByAddedDate":
                    return ResponseMock(
                        PHOTOS_DATA["query?remapEnums=True&getCurrentSyncToken=True"][9]["response"],
                    )

                # Smart album queries (Videos, Favorites, etc.)
                if query_type == "CPLAssetAndMasterInSmartAlbumByAssetDate":
                    return ResponseMock(
                        PHOTOS_DATA["query?remapEnums=True&getCurrentSyncToken=True"][5]["response"],
                    )

        return None


class ICloudPyServiceMock(base.ICloudPyService):
    """Mocked ICloudPyService."""

    def __init__(
        self,
        apple_id,
        password=None,
        cookie_directory=None,
        verify=True,
        client_id=None,
        with_family=True,
    ):
        """Init the object."""
        base.ICloudPySession = ICloudPySessionMock
        base.ICloudPyService.__init__(
            self,
            apple_id,
            password,
            cookie_directory,
            verify,
            client_id,
            with_family,
        )
