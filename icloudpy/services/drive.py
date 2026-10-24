"""Drive service."""

import io
import json
import mimetypes
import os
import time
from datetime import datetime, timedelta
from re import search

from requests import Response


class DriveService:
    """The 'Drive' iCloud service."""

    def __init__(self, service_root, document_root, session, params):
        self._service_root = service_root
        self._document_root = document_root
        self.session = session
        self.params = dict(params)
        self._root = None

    def _get_token_from_cookie(self):
        for cookie in self.session.cookies:
            if cookie.name == "X-APPLE-WEBAUTH-VALIDATE":
                match = search(r"\bt=([^:]+)", cookie.value)
                if match is None:
                    raise Exception(f"Can't extract token from {cookie.value}")
                return {"token": match.group(1)}
        raise Exception("Token cookie not found")

    def get_node_data(self, drivewsid):
        """Returns the node data."""
        request = self.session.post(
            self._service_root + "/retrieveItemDetailsInFolders",
            params=self.params,
            data=json.dumps(
                [
                    {
                        "drivewsid": drivewsid,
                        "partialData": False,
                    },
                ],
            ),
        )
        if not request.ok:
            self.session.raise_error(request.status_code, request.reason)
        return request.json()[0]

    def get_file(self, file_id, zone="com.apple.CloudDocs", **kwargs):
        """Returns iCloud Drive file."""
        file_params = dict(self.params)
        file_params.update({"document_id": file_id})
        # The lookup and the transfer are separate requests. A timeout given
        # only to the transfer leaves the lookup free to stall its thread
        # forever, so forward it here too. ``stream`` is deliberately not
        # forwarded: the lookup is a small JSON reply read in full.
        lookup_kwargs = {"timeout": kwargs["timeout"]} if "timeout" in kwargs else {}
        response = self.session.get(
            self._document_root + f"/ws/{zone}/download/by_id",
            params=file_params,
            **lookup_kwargs,
        )
        if not response.ok:
            self.session.raise_error(response.status_code, response.reason)
        package_token = response.json().get("package_token")
        data_token = response.json().get("data_token")
        if data_token and data_token.get("url"):
            return self.session.get(data_token["url"], params=self.params, **kwargs)
        elif package_token and package_token.get("url"):
            return self.session.get(package_token["url"], params=self.params, **kwargs)
        else:
            raise KeyError("'data_token' nor 'package_token' found in response.")

    def get_recent_docs(self, limit=20, next_page=None, zone="com.apple.CloudDocs"):
        """Returns the recently opened iCloud Drive documents, newest first.

        Apple returns at most ``limit`` documents. When more exist the result's
        ``status`` is ``MORE_AVAILABLE`` and its ``next_page`` cursor continues
        the listing::

            page = drive.get_recent_docs()
            while page.more_available and page.next_page:
                page = drive.get_recent_docs(next_page=page.next_page)

        Each page is returned as its own list; pages are not merged or
        de-duplicated, so pass the cursor back rather than re-requesting the
        first page. Pass the same ``zone`` on every page. The ordering is
        Apple's: the documents come back newest first, but which timestamp
        orders them is not documented.

        :param limit: maximum documents to return (Apple caps this itself)
        :param next_page: ``next_page`` from a previous result, or ``None``
        :param zone: the Drive zone to list, defaulting to the main Drive
            zone. ``_all_`` asks for every zone, but Apple does not serve
            that for every account, so it is opt-in.
        :returns: :class:`RecentDocs`
        """
        params = dict(self.params)
        params.update({"unified_format": "true", "limit": limit})
        if next_page:
            params["nextPage"] = next_page
        request = self.session.get(
            self._document_root + f"/ws/{zone}/list/enumerate/recentDocs",
            params=params,
        )
        if not request.ok:
            self.session.raise_error(request.status_code, request.reason)
        payload = request.json()
        if not isinstance(payload, dict):
            raise KeyError("Unexpected 'recent documents' response.")
        raw_documents = payload.get("documents")
        documents = [
            DriveNode(self, item)
            for item in (raw_documents if isinstance(raw_documents, list) else [])
            if isinstance(item, dict)
        ]
        return RecentDocs(
            documents,
            status=payload.get("status"),
            next_page=payload.get("continuationMarker"),
        )

    def get_app_data(self):
        """Returns the app library."""
        request = self.session.get(
            self._service_root + "/retrieveAppLibraries",
            params=self.params,
        )
        if not request.ok:
            self.session.raise_error(request.status_code, request.reason)
        return request.json()["items"]

    def get_app_node(self, app_id, folder="documents"):
        """Returns the node of the app."""
        return DriveNode(self, self.get_node_data("FOLDER::" + app_id + "::" + folder))

    def _get_upload_contentws_url(self, file_object, zone="com.apple.CloudDocs"):
        """Get the contentWS endpoint URL to add a new file."""
        content_type = mimetypes.guess_type(file_object.name)[0]
        if content_type is None:
            content_type = ""

        # Get filesize from file object
        orig_pos = file_object.tell()
        file_object.seek(0, os.SEEK_END)
        file_size = file_object.tell()
        file_object.seek(orig_pos, os.SEEK_SET)

        file_params = self.params
        file_params.update(self._get_token_from_cookie())

        request = self.session.post(
            self._document_root + f"/ws/{zone}/upload/web",
            params=file_params,
            headers={"Content-Type": "text/plain"},
            data=json.dumps(
                {
                    "filename": file_object.name,
                    "type": "FILE",
                    "content_type": content_type,
                    "size": file_size,
                },
            ),
        )
        if not request.ok:
            self.session.raise_error(request.status_code, request.reason)
        return (request.json()[0]["document_id"], request.json()[0]["url"])

    def _update_contentws(
        self,
        folder_id,
        sf_info,
        document_id,
        file_object,
        zone="com.apple.CloudDocs",
    ):
        data = {
            "data": {
                "signature": sf_info["fileChecksum"],
                "wrapping_key": sf_info["wrappingKey"],
                "reference_signature": sf_info["referenceChecksum"],
                "size": sf_info["size"],
            },
            "command": "add_file",
            "create_short_guid": True,
            "document_id": document_id,
            "path": {
                "starting_document_id": folder_id,
                "path": os.path.basename(file_object.name),
            },
            "allow_conflict": True,
            "file_flags": {
                "is_writable": True,
                "is_executable": False,
                "is_hidden": False,
            },
            "mtime": int(time.time() * 1000),
            "btime": int(time.time() * 1000),
        }

        # Add the receipt if we have one. Will be absent for 0-sized files
        if sf_info.get("receipt"):
            data["data"].update({"receipt": sf_info["receipt"]})

        request = self.session.post(
            self._document_root + f"/ws/{zone}/update/documents",
            params=self.params,
            headers={"Content-Type": "text/plain"},
            data=json.dumps(data),
        )
        if not request.ok:
            self.session.raise_error(request.status_code, request.reason)
        return request.json()

    def send_file(self, folder_id, file_object, zone="com.apple.CloudDocs"):
        """Send new file to iCloud Drive."""
        document_id, content_url = self._get_upload_contentws_url(file_object, zone)

        request = self.session.post(content_url, files={file_object.name: file_object})
        if not request.ok:
            self.session.raise_error(request.status_code, request.reason)
        content_response = request.json()["singleFile"]

        self._update_contentws(
            folder_id,
            content_response,
            document_id,
            file_object,
            zone,
        )

    def create_folders(self, parent, name):
        """Creates a new iCloud Drive folder"""
        request = self.session.post(
            self._service_root + "/createFolders",
            params=self.params,
            headers={"Content-Type": "text/plain"},
            data=json.dumps(
                {
                    "destinationDrivewsId": parent,
                    "folders": [
                        {
                            "clientId": self.params["clientId"],
                            "name": name,
                        },
                    ],
                },
            ),
        )
        return request.json()

    def rename_items(self, node_id, etag, name):
        """Renames an iCloud Drive node"""
        request = self.session.post(
            self._service_root + "/renameItems",
            params=self.params,
            data=json.dumps(
                {
                    "items": [
                        {
                            "drivewsid": node_id,
                            "etag": etag,
                            "name": name,
                        },
                    ],
                },
            ),
        )
        return request.json()

    def move_items_to_trash(self, node_id, etag):
        """Moves an iCloud Drive node to the trash bin"""
        request = self.session.post(
            self._service_root + "/moveItemsToTrash",
            params=self.params,
            data=json.dumps(
                {
                    "items": [
                        {
                            "drivewsid": node_id,
                            "etag": etag,
                            "clientId": self.params["clientId"],
                        },
                    ],
                },
            ),
        )
        if not request.ok:
            self.session.raise_error(request.status_code, request.reason)
        return request.json()

    @property
    def root(self):
        """Returns the root node."""
        if not self._root:
            self._root = DriveNode(
                self,
                self.get_node_data("FOLDER::com.apple.CloudDocs::root"),
            )
        return self._root

    def __getattr__(self, attr):
        return getattr(self.root, attr)

    def __getitem__(self, key):
        return self.root[key]


class RecentDocs(list):
    """Recently opened iCloud Drive documents, plus Apple's paging state.

    A plain list of :class:`DriveNode` objects, so iteration, indexing and
    slicing behave as usual. ``status`` is Apple's list status —
    ``"CONSISTENT"`` when the list is complete, ``"MORE_AVAILABLE"`` when more
    documents exist beyond the requested limit — and ``next_page`` is the
    cursor to pass back to :meth:`DriveService.get_recent_docs`.
    """

    def __init__(self, documents, status=None, next_page=None):
        super().__init__(documents)
        self.status = status
        self.next_page = next_page

    @property
    def more_available(self):
        """True when Apple reported more documents than were returned."""
        return self.status == "MORE_AVAILABLE"


class DriveNode:
    """Drive node."""

    def __init__(self, conn, data):
        self.data = data
        self.connection = conn
        self._children = None

    @property
    def name(self):
        """Gets the node name."""
        if "extension" in self.data:
            return f"{self.data['name']}.{self.data['extension']}"
        return self.data["name"]

    @property
    def type(self):
        """Gets the node type."""
        node_type = self.data.get("type")
        return node_type and node_type.lower()

    def get_children(self):
        """Gets the node children."""
        if not self._children:
            if "items" not in self.data:
                self.data.update(self.connection.get_node_data(self.data["drivewsid"]))
            if "items" not in self.data:
                raise KeyError(f"No items in folder, status: {self.data['status']}")
            self._children = [DriveNode(self.connection, item_data) for item_data in self.data["items"]]
        return self._children

    @property
    def size(self):
        """Gets the node size."""
        size = self.data.get("size")  # Folder does not have size
        if not size:
            return None
        return int(size)

    @property
    def date_created(self):
        """Gets the node created date (in UTC)."""
        return _date_to_utc(self.data.get("dateCreated"))

    @property
    def date_changed(self):
        """Gets the node changed date (in UTC)."""
        return _date_to_utc(self.data.get("dateChanged"))  # Folder does not have date

    @property
    def date_modified(self):
        """Gets the node modified date (in UTC)."""
        return _date_to_utc(self.data.get("dateModified"))  # Folder does not have date

    @property
    def date_last_open(self):
        """Gets the node last open date (in UTC)."""
        return _date_to_utc(self.data.get("lastOpenTime"))  # Folder does not have date

    def open(self, **kwargs):
        """Gets the node file."""
        # iCloud returns 400 Bad Request for 0-byte files
        if self.data["size"] == 0:
            response = Response()
            response.raw = io.BytesIO()
            return response
        return self.connection.get_file(
            self.data["docwsid"],
            zone=self.data["zone"],
            **kwargs,
        )

    def upload(self, file_object, **kwargs):
        """ "Upload a new file."""
        return self.connection.send_file(
            self.data["docwsid"],
            file_object,
            zone=self.data["zone"],
            **kwargs,
        )

    def dir(self):
        """Gets the node list of directories."""
        if self.type == "file":
            return None
        return [child.name for child in self.get_children()]

    def mkdir(self, folder):
        """Create a new directory directory."""
        # remove cached entries information first so that it will be re-read on next get_children()
        self._children = None
        if "items" in self.data:
            self.data.pop("items")
        return self.connection.create_folders(self.data["drivewsid"], folder)

    def rename(self, name):
        """Rename an iCloud Drive item."""
        return self.connection.rename_items(
            self.data["drivewsid"],
            self.data["etag"],
            name,
        )

    def delete(self):
        """Delete an iCloud Drive item."""
        return self.connection.move_items_to_trash(
            self.data["drivewsid"],
            self.data["etag"],
        )

    def get(self, name):
        """Gets the node child."""
        if self.type == "file":
            return None
        return [child for child in self.get_children() if child.name == name][0]

    def __getitem__(self, key):
        try:
            return self.get(key)
        except IndexError as error:
            raise KeyError(f"No child named '{key}' exists") from error

    def __unicode__(self):
        return f"{{type: {self.type}, name: {self.name}}}"

    def __str__(self):
        return self.__unicode__()

    def __repr__(self):
        return f"<{type(self).__name__}: {str(self)}>"


def _date_to_utc(date):
    if not date:
        return None
    # jump through hoops to return time in UTC rather than California time
    match = search(r"^(.+?)([\+\-]\d+):(\d\d)$", date)
    if not match:
        # Already in UTC
        return datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ")
    base = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
    diff = timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))
    return base - diff
