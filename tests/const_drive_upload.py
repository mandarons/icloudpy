"""Drive upload and file operation test constants.

This module contains fixtures for drive file operations including:
- File upload URL responses
- Content update responses
- Folder creation responses
- Item rename responses
- Move to trash responses
"""

# Upload URL response - returned by /upload/web endpoint
UPLOAD_URL_RESPONSE = {
    "document_id": "NEW-DOCUMENT-ID-123",
    "url": "https://p31-docws.icloud.com:443/ws/upload/file",
    "owner": "OWNER_ID",
    "zone": "com.apple.CloudDocs",
}

# Content update response - returned by /update/documents endpoint
UPDATE_CONTENTWS_RESPONSE = {
    "results": [
        {
            "document_id": "NEW-DOCUMENT-ID-123",
            "drivewsid": "DOCUMENT::com.apple.CloudDocs::NEW-DOCUMENT-ID-123",
            "etag": "ETAG_VALUE_123",
            "zone": "com.apple.CloudDocs",
        },
    ],
}

# Rename items response - returned by /renameItems endpoint
RENAME_ITEMS_RESPONSE = {
    "items": [
        {
            "drivewsid": "DOCUMENT::com.apple.CloudDocs::516C896C-6AA5-4A30-B30E-5502C2333DAE",
            "docwsid": "516C896C-6AA5-4A30-B30E-5502C2333DAE",
            "zone": "com.apple.CloudDocs",
            "name": "new_name.pdf",
            "parentId": "D5AA0425-E84F-4501-AF5D-60F1D92648CF",
            "etag": "ETAG_VALUE_RENAMED",
            "type": "FILE",
            "assetQuota": 0,
            "fileCount": 0,
            "shareCount": 0,
            "shareAliasCount": 0,
            "directChildrenCount": 0,
        },
    ],
}

# Move to trash response - returned by /moveItemsToTrash endpoint
TRASH_ITEMS_RESPONSE = {
    "items": [
        {
            "drivewsid": "DOCUMENT::com.apple.CloudDocs::516C896C-6AA5-4A30-B30E-5502C2333DAE",
            "docwsid": "516C896C-6AA5-4A30-B30E-5502C2333DAE",
            "zone": "com.apple.CloudDocs",
            "etag": "ETAG_VALUE_TRASHED",
            "status": "OK",
        },
    ],
}

# Folder creation response - returned by /createFolders endpoint
# (This is already handled in DRIVE_SUBFOLDER_WORKING_AFTER_MKDIR in const_drive.py)
