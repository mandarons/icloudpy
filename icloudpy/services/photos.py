"""Photo service."""

import base64
import json
import logging
from datetime import datetime

# fmt: off
from urllib.parse import urlencode  # pylint: disable=bad-option-value,relative-import

from pytz import UTC
from six import PY2

# fmt: on
from icloudpy.exceptions import ICloudPyServiceNotActivatedException

LOGGER = logging.getLogger(__name__)


class PhotoLibrary:
    """Represents a library in the user's photos.

    This provides access to all the albums as well as the photos.
    """

    SMART_FOLDERS = {
        "All Photos": {
            "obj_type": "CPLAssetByAddedDate",
            "list_type": "CPLAssetAndMasterByAddedDate",
            "direction": "ASCENDING",
            "query_filter": None,
        },
        "Time-lapse": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Timelapse",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "TIMELAPSE"},
                },
            ],
        },
        "Videos": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Video",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "VIDEO"},
                },
            ],
        },
        "Slo-mo": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Slomo",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "SLOMO"},
                },
            ],
        },
        "Bursts": {
            "obj_type": "CPLAssetBurstStackAssetByAssetDate",
            "list_type": "CPLBurstStackAssetAndMasterByAssetDate",
            "direction": "ASCENDING",
            "query_filter": None,
        },
        "Favorites": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Favorite",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "FAVORITE"},
                },
            ],
        },
        "Panoramas": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Panorama",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "PANORAMA"},
                },
            ],
        },
        "Screenshots": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Screenshot",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "SCREENSHOT"},
                },
            ],
        },
        "Live": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Live",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "LIVE"},
                },
            ],
        },
        "Recently Deleted": {
            "obj_type": "CPLAssetDeletedByExpungedDate",
            "list_type": "CPLAssetAndMasterDeletedByExpungedDate",
            "direction": "ASCENDING",
            "query_filter": None,
        },
        "Hidden": {
            "obj_type": "CPLAssetHiddenByAssetDate",
            "list_type": "CPLAssetAndMasterHiddenByAssetDate",
            "direction": "ASCENDING",
            "query_filter": None,
        },
    }

    def __init__(self, service, zone_id):
        self.service = service
        self.zone_id = zone_id

        self._albums = None

        url = f"{self.service._service_endpoint}/records/query?{urlencode(self.service.params)}"
        json_data = json.dumps(
            {
                "query": {"recordType": "CheckIndexingState"},
                "zoneID": self.zone_id,
            },
        )

        request = self.service.session.post(
            url,
            data=json_data,
            headers={"Content-type": "text/plain"},
        )
        response = request.json()
        indexing_state = response["records"][0]["fields"]["state"]["value"]
        if indexing_state != "FINISHED":
            raise ICloudPyServiceNotActivatedException(
                ("iCloud Photo Library not finished indexing.  Please try " "again in a few minutes"),
                None,
            )

    @property
    def albums(self):
        if not self._albums:
            self._albums = {
                name: PhotoAlbum(self.service, name, zone_id=self.zone_id, **props)
                for (name, props) in self.SMART_FOLDERS.items()
            }

            for folder in self._fetch_folders():
                if folder["recordName"] in (
                    "----Root-Folder----",
                    "----Project-Root-Folder----",
                ) or (folder["fields"].get("isDeleted") and folder["fields"]["isDeleted"]["value"]):
                    continue

                folder_id = folder["recordName"]
                folder_obj_type = f"CPLContainerRelationNotDeletedByAssetDate:{folder_id}"
                folder_name = base64.b64decode(
                    folder["fields"]["albumNameEnc"]["value"],
                ).decode("utf-8")
                query_filter = [
                    {
                        "fieldName": "parentId",
                        "comparator": "EQUALS",
                        "fieldValue": {"type": "STRING", "value": folder_id},
                    },
                ]

                album = PhotoAlbum(
                    self.service,
                    folder_name,
                    "CPLContainerRelationLiveByAssetDate",
                    folder_obj_type,
                    "ASCENDING",
                    query_filter,
                    folder_id=folder_id,
                    zone_id=self.zone_id,
                )
                self._albums[folder_name] = album

        return self._albums

    def _fetch_folders(self):
        url = f"{self.service._service_endpoint}/records/query?{urlencode(self.service.params)}"
        json_data = json.dumps(
            {
                "query": {"recordType": "CPLAlbumByPositionLive"},
                "zoneID": self.zone_id,
            },
        )

        request = self.service.session.post(
            url,
            data=json_data,
            headers={"Content-type": "text/plain"},
        )
        response = request.json()

        return response["records"]

    @property
    def all(self):
        return self.albums["All Photos"]


class PhotosService(PhotoLibrary):
    """The 'Photos' iCloud service.

    This also acts as a way to access the user's primary library.
    """

    def __init__(self, service_root, session, params):
        self.session = session
        self.params = dict(params)
        self._service_root = service_root
        self._service_endpoint = f"{self._service_root}/database/1/com.apple.photos.cloud/production/private"

        self._libraries = None

        self.params.update({"remapEnums": True, "getCurrentSyncToken": True})

        self._photo_assets = {}

        super().__init__(service=self, zone_id={"zoneName": "PrimarySync"})

    @property
    def libraries(self):
        if not self._libraries:
            try:
                url = f"{self._service_endpoint}/zones/list"
                request = self.session.post(
                    url,
                    data="{}",
                    headers={"Content-type": "text/plain"},
                )
                response = request.json()
                zones = response["zones"]
            except Exception as e:
                LOGGER.error(f"library exception: {str(e)}")

            libraries = {}
            for zone in zones:
                if not zone.get("deleted"):
                    zone_name = zone["zoneID"]["zoneName"]
                    libraries[zone_name] = PhotoLibrary(self, zone_id=zone["zoneID"])
                    # obj_type='CPLAssetByAssetDateWithoutHiddenOrDeleted',
                    # list_type="CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted",
                    # direction="ASCENDING", query_filter=None,
                    # zone_id=zone['zoneID'])

            self._libraries = libraries

        return self._libraries


class PhotoAlbum:
    """A photo album."""

    def __init__(
        self,
        service,
        name,
        list_type,
        obj_type,
        direction,
        query_filter=None,
        page_size=100,
        folder_id=None,
        zone_id=None,
    ):
        self.name = name
        self.service = service
        self.list_type = list_type
        self.obj_type = obj_type
        self.direction = direction
        self.query_filter = query_filter
        self.page_size = page_size
        self.folder_id = folder_id

        if zone_id:
            self._zone_id = zone_id
        else:
            self._zone_id = "PrimarySync"

        self._len = None

        self._subalbums = {}

    @property
    def title(self):
        """Gets the album name."""
        return self.name

    def __iter__(self):
        return self.photos

    def __len__(self):
        if self._len is None:
            url = f"{self.service._service_endpoint}/internal/records/query/batch?{urlencode(self.service.params)}"
            request = self.service.session.post(
                url,
                data=json.dumps(
                    {
                        "batch": [
                            {
                                "resultsLimit": 1,
                                "query": {
                                    "filterBy": {
                                        "fieldName": "indexCountID",
                                        "fieldValue": {
                                            "type": "STRING_LIST",
                                            "value": [self.obj_type],
                                        },
                                        "comparator": "IN",
                                    },
                                    "recordType": "HyperionIndexCountLookup",
                                },
                                "zoneWide": True,
                                "zoneID": {"zoneName": self._zone_id["zoneName"]},
                            },
                        ],
                    },
                ),
                headers={"Content-type": "text/plain"},
            )
            response = request.json()

            self._len = response["batch"][0]["records"][0]["fields"]["itemCount"]["value"]

        return self._len

    def _fetch_subalbums(self):
        url = (f"{self.service._service_endpoint}/records/query?") + urlencode(
            self.service.params,
        )
        # pylint: disable=consider-using-f-string
        query = """{{
                "query": {{
                    "recordType":"CPLAlbumByPositionLive",
                    "filterBy": [
                        {{
                            "fieldName": "parentId",
                            "comparator": "EQUALS",
                            "fieldValue": {{
                                "value": "{}",
                                "type": "STRING"
                            }}
                        }}
                    ]
                }},
                "zoneID": {{
                    "zoneName":"{}"
                }}
            }}""".format(
            self.folder_id,
            self._zone_id["zoneName"],
        )
        json_data = query
        request = self.service.session.post(
            url,
            data=json_data,
            headers={"Content-type": "text/plain"},
        )
        response = request.json()

        return response["records"]

    @property
    def subalbums(self):
        """Returns the subalbums"""
        if not self._subalbums and self.folder_id:
            for folder in self._fetch_subalbums():
                if folder["fields"].get("isDeleted") and folder["fields"]["isDeleted"]["value"]:
                    continue

                folder_id = folder["recordName"]
                folder_obj_type = f"CPLContainerRelationNotDeletedByAssetDate:{folder_id}"
                folder_name = base64.b64decode(
                    folder["fields"]["albumNameEnc"]["value"],
                ).decode("utf-8")
                query_filter = [
                    {
                        "fieldName": "parentId",
                        "comparator": "EQUALS",
                        "fieldValue": {"type": "STRING", "value": folder_id},
                    },
                ]

                album = PhotoAlbum(
                    self.service,
                    name=folder_name,
                    list_type="CPLContainerRelationLiveByAssetDate",
                    obj_type=folder_obj_type,
                    direction="ASCENDING",
                    query_filter=query_filter,
                    folder_id=folder_id,
                    zone_id=self._zone_id,
                )
                self._subalbums[folder_name] = album
        return self._subalbums

    @property
    def photos(self):
        """Returns the album photos."""
        if self.direction == "DESCENDING":
            offset = len(self) - 1
        else:
            offset = 0

        while True:
            url = (f"{self.service._service_endpoint}/records/query?") + urlencode(
                self.service.params,
            )
            request = self.service.session.post(
                url,
                data=json.dumps(
                    self._list_query_gen(
                        offset,
                        self.list_type,
                        self.direction,
                        self.query_filter,
                    ),
                ),
                headers={"Content-type": "text/plain"},
            )
            response = request.json()

            asset_records = {}
            master_records = []
            for rec in response["records"]:
                if rec["recordType"] == "CPLAsset":
                    master_id = rec["fields"]["masterRef"]["value"]["recordName"]
                    asset_records[master_id] = rec
                elif rec["recordType"] == "CPLMaster":
                    master_records.append(rec)

            master_records_len = len(master_records)
            if master_records_len:
                if self.direction == "DESCENDING":
                    offset = offset - master_records_len
                else:
                    offset = offset + master_records_len

                for master_record in master_records:
                    record_name = master_record["recordName"]
                    yield PhotoAsset(
                        self.service,
                        master_record,
                        asset_records[record_name],
                    )
            else:
                break

    def _list_query_gen(self, offset, list_type, direction, query_filter=None):
        query = {
            "query": {
                "filterBy": [
                    {
                        "fieldName": "startRank",
                        "fieldValue": {"type": "INT64", "value": offset},
                        "comparator": "EQUALS",
                    },
                    {
                        "fieldName": "direction",
                        "fieldValue": {"type": "STRING", "value": direction},
                        "comparator": "EQUALS",
                    },
                ],
                "recordType": list_type,
            },
            "resultsLimit": self.page_size * 2,
            "desiredKeys": [
                "resJPEGFullWidth",
                "resJPEGFullHeight",
                "resJPEGFullFileType",
                "resJPEGFullFingerprint",
                "resJPEGFullRes",
                "resJPEGLargeWidth",
                "resJPEGLargeHeight",
                "resJPEGLargeFileType",
                "resJPEGLargeFingerprint",
                "resJPEGLargeRes",
                "resJPEGMedWidth",
                "resJPEGMedHeight",
                "resJPEGMedFileType",
                "resJPEGMedFingerprint",
                "resJPEGMedRes",
                "resJPEGThumbWidth",
                "resJPEGThumbHeight",
                "resJPEGThumbFileType",
                "resJPEGThumbFingerprint",
                "resJPEGThumbRes",
                "resVidFullWidth",
                "resVidFullHeight",
                "resVidFullFileType",
                "resVidFullFingerprint",
                "resVidFullRes",
                "resVidMedWidth",
                "resVidMedHeight",
                "resVidMedFileType",
                "resVidMedFingerprint",
                "resVidMedRes",
                "resVidSmallWidth",
                "resVidSmallHeight",
                "resVidSmallFileType",
                "resVidSmallFingerprint",
                "resVidSmallRes",
                "resSidecarWidth",
                "resSidecarHeight",
                "resSidecarFileType",
                "resSidecarFingerprint",
                "resSidecarRes",
                "itemType",
                "dataClassType",
                "filenameEnc",
                "originalOrientation",
                "resOriginalWidth",
                "resOriginalHeight",
                "resOriginalFileType",
                "resOriginalFingerprint",
                "resOriginalRes",
                "resOriginalAltWidth",
                "resOriginalAltHeight",
                "resOriginalAltFileType",
                "resOriginalAltFingerprint",
                "resOriginalAltRes",
                "resOriginalVidComplWidth",
                "resOriginalVidComplHeight",
                "resOriginalVidComplFileType",
                "resOriginalVidComplFingerprint",
                "resOriginalVidComplRes",
                "isDeleted",
                "isExpunged",
                "dateExpunged",
                "remappedRef",
                "recordName",
                "recordType",
                "recordChangeTag",
                "masterRef",
                "adjustmentRenderType",
                "assetDate",
                "addedDate",
                "isFavorite",
                "isHidden",
                "orientation",
                "duration",
                "assetSubtype",
                "assetSubtypeV2",
                "assetHDRType",
                "burstFlags",
                "burstFlagsExt",
                "burstId",
                "captionEnc",
                "extendedDescEnc",
                "locationEnc",
                "locationV2Enc",
                "locationLatitude",
                "locationLongitude",
                "adjustmentType",
                "timeZoneOffset",
                "vidComplDurValue",
                "vidComplDurScale",
                "vidComplDispValue",
                "vidComplDispScale",
                "vidComplVisibilityState",
                "customRenderedValue",
                "containerId",
                "itemId",
                "position",
                "isKeyAsset",
                "importedByBundleIdentifierEnc",
                "importedByDisplayNameEnc",
                "importedBy",
            ],
            "zoneID": self._zone_id,
        }

        if query_filter:
            query["query"]["filterBy"].extend(query_filter)

        return query

    def __unicode__(self):
        return self.title

    def __str__(self):
        as_unicode = self.__unicode__()
        if PY2:
            return as_unicode.encode("utf-8", "ignore")
        return as_unicode

    def __repr__(self):
        return f"<{type(self).__name__}: '{self}'>"


class PhotoAsset:
    """A photo."""

    def __init__(self, service, master_record, asset_record):
        self._service = service
        self._master_record = master_record
        self._asset_record = asset_record

        self._versions = None

    PHOTO_VERSION_LOOKUP = {
        "full": "resJPEGFull",
        "large": "resJPEGLarge",
        "medium": "resJPEGMed",
        "thumb": "resJPEGThumb",
        "sidecar": "resSidecar",
        "original": "resOriginal",
        "original_alt": "resOriginalAlt",
    }

    VIDEO_VERSION_LOOKUP = {
        "full": "resVidFull",
        "medium": "resVidMed",
        "thumb": "resVidSmall",
        "original": "resOriginal",
        "original_compl": "resOriginalVidCompl",
    }

    @property
    def id(self):
        """Gets the photo id."""
        return self._master_record["recordName"]

    @property
    def filename(self):
        """Gets the photo file name."""
        return base64.b64decode(
            self._master_record["fields"]["filenameEnc"]["value"],
        ).decode("utf-8")

    @property
    def size(self):
        """Gets the photo size."""
        return self._master_record["fields"]["resOriginalRes"]["value"]["size"]

    @property
    def created(self):
        """Gets the photo created date."""
        return self.asset_date

    @property
    def asset_date(self):
        """Gets the photo asset date."""
        try:
            return datetime.fromtimestamp(
                self._asset_record["fields"]["assetDate"]["value"] / 1000.0,
                tz=UTC,
            )
        except KeyError:
            return datetime.fromtimestamp(0)

    @property
    def added_date(self):
        """Gets the photo added date."""
        return datetime.fromtimestamp(
            self._asset_record["fields"]["addedDate"]["value"] / 1000.0,
            tz=UTC,
        )

    @property
    def dimensions(self):
        """Gets the photo dimensions."""
        return (
            self._master_record["fields"]["resOriginalWidth"]["value"],
            self._master_record["fields"]["resOriginalHeight"]["value"],
        )

    @property
    def versions(self):
        """Gets the photo versions."""
        if not self._versions:
            self._versions = {}
            if "resVidSmallRes" in self._master_record["fields"]:
                typed_version_lookup = self.VIDEO_VERSION_LOOKUP
            else:
                typed_version_lookup = self.PHOTO_VERSION_LOOKUP

            for key, prefix in typed_version_lookup.items():
                if f"{prefix}Res" in self._master_record["fields"]:
                    fields = self._master_record["fields"]
                    version = {"filename": self.filename}

                    width_entry = fields.get(f"{prefix}Width")
                    if width_entry:
                        version["width"] = width_entry["value"]
                    else:
                        version["width"] = None

                    height_entry = fields.get(f"{prefix}Height")
                    if height_entry:
                        version["height"] = height_entry["value"]
                    else:
                        version["height"] = None

                    size_entry = fields.get(f"{prefix}Res")
                    if size_entry:
                        version["size"] = size_entry["value"]["size"]
                        version["url"] = size_entry["value"]["downloadURL"]
                    else:
                        version["size"] = None
                        version["url"] = None

                    type_entry = fields.get(f"{prefix}FileType")
                    if type_entry:
                        version["type"] = type_entry["value"]
                    else:
                        version["type"] = None

                    self._versions[key] = version

        return self._versions

    def download(self, version="original", **kwargs):
        """Returns the photo file."""
        if version not in self.versions:
            return None

        return self._service.session.get(
            self.versions[version]["url"],
            stream=True,
            **kwargs,
        )

    def delete(self):
        """Deletes the photo."""
        json_data = (
            f'{{"operations":[{{'
            f'"operationType":"update",'
            f'"record":{{'
            f'"recordName":"{self._asset_record["recordName"]}",'
            f'"recordType":"{self._asset_record["recordType"]}",'
            f'"recordChangeTag":"{self._master_record["recordChangeTag"]}",'
            f'"fields":{{"isDeleted":{{"value":1}}'
            f'}}}}],'
            f'"zoneID":{{'
            f'"zoneName":"PrimarySync"'
            f'}},"atomic":true}}'
        )

        endpoint = self._service._service_endpoint
        params = urlencode(self._service.params)
        url = f"{endpoint}/records/modify?{params}"

        return self._service.session.post(
            url,
            data=json_data,
            headers={"Content-type": "text/plain"},
        )

    def __repr__(self):
        return f"<{type(self).__name__}: id={self.id}>"
