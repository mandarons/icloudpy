# iCloudPy

[![CI - Main](https://github.com/mandarons/icloudpy/actions/workflows/ci-main-test-coverage.yml/badge.svg)](https://github.com/mandarons/icloudpy/actions/workflows/ci-main-test-coverage.yml)
[![Tests](https://mandarons.github.io/icloudpy/badges/tests.svg)](https://mandarons.github.io/icloudpy/test-results/)
[![Coverage](https://mandarons.github.io/icloudpy/badges/coverage.svg)](https://mandarons.github.io/icloudpy/test-coverage/index.html)
![Python Version](https://img.shields.io/badge/python-3.14-blue)
[![Discord](https://img.shields.io/discord/871555550444408883?style=for-the-badge)](https://discord.gg/BnNpJUQ2)
<a href="https://www.buymeacoffee.com/mandarons" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 30px !important;width: 150px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

:love*you_gesture: \*\*\_Please star this repository if you end up using this project. If it has improved your life in any way, consider donating for my effort using 'Buy Me a Coffee' button above. It will help me continue supporting this product.*\*\* :pray:

iCloudPy is a simple iCloud webservices wrapper library written in Python. It is a major reuse of [pyiCloud](https://github.com/picklepete/pyicloud) python library.

iCloudPy connects to iCloud using your `username` and `password`, stores the session locally and then performs various queries to iCloud server.

iCloudPy requires Python 3.14 or newer.

## Authentication

Authentication without using a saved password is as simple as passing your username and password to the `ICloudPyService` class:

```python
from icloudpy import ICloudPyService
api = ICloudPyService('jappleseed@apple.com', 'password')
# For China region
api = ICloudPyService('jappleseed@apple.com', 'password', home_endpoint="https://www.icloud.com.cn",setup_endpoint="https://setup.icloud.com.cn/setup/ws/1",)
```

In the event that the username/password combination is invalid, a `ICloudPyFailedLoginException` exception is thrown.

You can also store your password in the system keyring using the command-line tool:

```bash
> icloud --username=jappleseed@apple.com
ICloud Password for jappleseed@apple.com:
Save password in keyring? (y/N)
# For China region
> icloud --username=jappleseed@apple.com --region=china
ICloud Password for jappleseed@apple.com:
Save password in keyring? (y/N)
```

If you have stored a password in the keyring, you will not be required to provide a password when interacting with the command-line tool or instantiating the `ICloudPyService` class for the username you stored the password for.

```python
api = ICloudPyService('jappleseed@apple.com')
```

If you would like to delete a password stored in your system keyring, you can clear a stored password using the `--delete-from-keyring` command-line option:

```bash
> icloud --username=jappleseed@apple.com --delete-from-keyring
```

**_Note: Authentication will expire after an interval set by Apple, at which point you will have to re-authenticate. This interval is currently two months._**

## Two-step and two-factor authentication (2SA/2FA)

If you have enabled [two-factor authentications (2FA) or two-step authentication (2SA)](https://support.apple.com/en-us/HT204152) for the account you will have to do some extra work:

```python
import sys

if api.requires_2fa:
    if api.security_key_challenge:
        # This Apple ID has hardware security keys enrolled, so Apple issues a
        # WebAuthn challenge instead of a 6-digit code. See the next section.
        if not api.confirm_security_key():
            print("Security key verification failed")
            sys.exit(1)
    else:
        print("Two-factor authentication required.")
        code = input("Enter the code you received on one of your approved devices: ")
        result = api.validate_2fa_code(code)
        print("Code validation result: %s" % result)

        if not result:
            print("Failed to verify security code")
            sys.exit(1)

        if not api.is_trusted_session:
            print("Session is not trusted. Requesting trust...")
            result = api.trust_session()
            print("Session trust result %s" % result)

            if not result:
                print("Failed to request trust. You will likely be prompted for the code again in the coming weeks")
elif api.requires_2sa:
    import click
    print("Two-step authentication required. Your trusted devices are:")

    devices = api.trusted_devices
    for i, device in enumerate(devices):
        print("  %s: %s" % (i, device.get("deviceName", "SMS to %s" % device.get("phoneNumber"))))

    device = click.prompt("Which device would you like to use?", default=0)
    device = devices[device]
    if not api.send_verification_code(device):
        print("Failed to send verification code")
        sys.exit(1)

    code = click.prompt("Please enter validation code")
    if not api.validate_verification_code(device, code):
        print("Failed to verify verification code")
        sys.exit(1)
```

## Hardware security keys

If the Apple ID has [security keys enrolled](https://support.apple.com/en-us/HT213154), Apple stops sending 6-digit codes entirely and returns a WebAuthn challenge instead -- so `validate_2fa_code()` has nothing to validate. iCloudPy can sign that challenge with an attached FIDO2 security key (YubiKey and friends):

```bash
> pip install "icloudpy[security-key]"
# which simply pulls in the optional dependency; equivalently:
> pip install fido2
```

The `fido2` package is optional: it is only imported when a challenge is signed locally, so code that never handles security-key accounts does not need it.

```python
from icloudpy import ICloudPyService

api = ICloudPyService("jappleseed@apple.com", "password")

if api.requires_2fa:
    if api.security_key_challenge:
        if not api.confirm_security_key():  # touch the key when it flashes
            print("Security key verification failed")
            sys.exit(1)
    else:
        code = input("Enter the code you received on one of your approved devices: ")
        api.validate_2fa_code(code)
```

API reference:

- `api.security_key_challenge` -- the pending challenge as a dict carrying `challenge`, `keyHandles`, `rpId` (and `requestId`), or `None` when Apple is not asking for a key. Reading it never requires the `fido2` package.
- `api.confirm_security_key(assertion=None, device=None)` -- fetches the challenge, signs it with `device` (or the first attached key) and submits it. Pass a pre-built `assertion` to submit one signed elsewhere -- then no device or `fido2` package is needed. Returns `True` once the session no longer requires a second factor; raises `ICloudPyFailedLoginException` if Apple is not requesting a key or no FIDO2 device is found.
- `api.fido2_devices` -- attached FIDO2 devices; empty when the `fido2` package is not installed.
- `api.sign_security_key_challenge(challenge, device)` -- signs without submitting, returning the assertion payload that `confirm_security_key()` accepts. Requires `fido2` and a physical touch on the key.
- `icloudpy.base.build_security_key_assertion(response, rp_id, request_id=None)` -- converts a WebAuthn `AuthenticatorAssertionResponse` (e.g. one produced by a browser) into the payload Apple expects, for callers that sign the challenge outside of iCloudPy.

Note: the `icloud` command-line tool does not support security-key accounts yet -- it only prompts for a 6-digit code. Use the library API above.

## Devices

You can list which devices associated with your account by using the `devices` property:

```bash
>>> api.devices
{
u'i9vbKRGIcLYqJnXMd1b257kUWnoyEBcEh6yM+IfmiMLh7BmOpALS+w==': <AppleDevice(iPhone 4S: Johnny Appleseed's iPhone)>,
u'reGYDh9XwqNWTGIhNBuEwP1ds0F/Lg5t/fxNbI4V939hhXawByErk+HYVNSUzmWV': <AppleDevice(MacBook Air 11": Johnny Appleseed's MacBook Air)>
}
```

and you can access individual devices by either their index, or their ID:

```bash
>>> api.devices[0]
<AppleDevice(iPhone 4S: Johnny Appleseed's iPhone)>
>>> api.devices['i9vbKRGIcLYqJnXMd1b257kUWnoyEBcEh6yM+IfmiMLh7BmOpALS+w==']
<AppleDevice(iPhone 4S: Johnny Appleseed's iPhone)>
```

or, as a shorthand if you have only one associated apple device, you can simply use the `iphone` property to access the first device associated with your account:

```bash
>>> api.iphone
<AppleDevice(iPhone 4S: Johnny Appleseed's iPhone)>
```

**_Note: the first device associated with your account may not necessarily be your iPhone._**

## Find My iPhone

Once you have successfully authenticated, you can start querying your data!

### Location

Returns the device's last known location. The Find My iPhone app must have been installed and initialized.

```bash
>>> api.iphone.location()
{u'timeStamp': 1357753796553, u'locationFinished': True, u'longitude': -0.14189, u'positionType': u'GPS', u'locationType': None, u'latitude': 51.501364, u'isOld': False, u'horizontalAccuracy': 5.0}
```

### Status

The Find My iPhone response is quite bloated, so for simplicity's sake this method will return a subset of the properties.

```bash
>>> api.iphone.status()
{'deviceDisplayName': u'iPhone 5', 'deviceStatus': u'200', 'batteryLevel': 0.6166913, 'name': u"Peter's iPhone"}
```

If you wish to request further properties, you may do so by passing in a list of property names.

### Play Sound

Sends a request to the device to play a sound, if you wish pass a custom message you can do so by changing the subject arg.

```bash
>>> api.iphone.play_sound()
```

A few moments later, the device will play a ringtone, display the default notification ("Find My iPhone Alert") and a confirmation email will be sent to you.

### Lost Mode

Lost mode is slightly different to the "Play Sound" functionality in that it allows the person who picks up the phone to call a specific phone number _without having to enter the passcode_. Just like "Play Sound" you may pass a custom message which the device will display, if it's not overridden the custom message of "This iPhone has been lost. Please call me." is used.

```bash
>>> phone_number = '555-373-383'
>>> message = 'Thief! Return my phone immediately.'
>>> api.iphone.lost_device(phone_number, message)
```

## Calendar

The calendar webservice currently only supports fetching events.

### Events

Returns this month's events:

```bash
>>> api.calendar.events()
```

Or, between a specific date range:

```bash
>>> from_dt = datetime(2012, 1, 1)
>>> to_dt = datetime(2012, 1, 31)
>>> api.calendar.events(from_dt, to_dt)
```

Alternatively, you may fetch a single event's details, like so:

```bash
>>> api.calendar.get_event_detail('CALENDAR', 'EVENT_ID')
```

## Contacts

You can access your iCloud contacts/address book through the `contacts` property:

```bash
>>> for c in api.contacts.all():
>>> print c.get('firstName'), c.get('phones')
John [{u'field': u'+1 555-55-5555-5', u'label': u'MOBILE'}]
```

**_Note: These contacts do not include contacts federated from e.g. Facebook, only the ones stored in iCloud._**

## File Storage (iCloud Drive)

You can access your iCloud Drive through the `api.drive` property:

```bash
>>> api.drive.dir()
['Holiday Photos', 'Work Files']
>>> api.drive['Holiday Photos']['2013']['Sicily'].dir()
['DSC08116.JPG', 'DSC08117.JPG']

>>> drive_file = api.drive['Holiday Photos']['2013']['Sicily']['DSC08116.JPG']
>>> drive_file.name
u'DSC08116.JPG'
>>> drive_file.date_modified
datetime.datetime(2013, 3, 21, 12, 28, 12) # NB this is UTC
>>> drive_file.size
2021698
>>> drive_file.type
u'file'
```

The `open` method will return a response object from which you can read the file's contents:

```bash
>>> from shutil import copyfileobj
>>> with drive_file.open(stream=True) as response:
>>>     with open(drive_file.name, 'wb') as file_out:
>>>         copyfileobj(response.raw, file_out)
```

`open` forwards its keyword arguments to the underlying `requests` calls. In particular, pass `timeout` (in seconds, or a `(connect, read)` pair) to bound both requests a download makes -- the `by_id` metadata lookup and the data transfer -- so a stalled download cannot hang its thread forever:

```bash
>>> with drive_file.open(stream=True, timeout=30) as response:
>>>     with open(drive_file.name, 'wb') as file_out:
>>>         copyfileobj(response.raw, file_out)
```

`stream` applies to the transfer only: the lookup is a small JSON reply that is read in full.

### Recently Opened Documents

`get_recent_docs` lists the documents Apple shows under Recent in iCloud Drive, newest first:

```bash
>>> recent = api.drive.get_recent_docs()
>>> [doc.name for doc in recent]
['Quarterly summary.pdf', 'Budget draft.numbers']
>>> recent[0].date_last_open
datetime.datetime(2020, 5, 3, 7, 24, 25) # NB this is UTC
```

The result is a plain list of drive nodes, so everything above applies to it, including `open`.

The listing covers the main Drive zone (`com.apple.CloudDocs`) by default. Pass `zone` to list a
different one: `get_recent_docs(zone="_all_")` asks for every Drive zone, though Apple does not serve
that for every account. Pass the same `zone` on each page request.

Apple caps the listing. When more documents exist the result says so, and the cursor it returns
continues the listing:

```bash
>>> recent = api.drive.get_recent_docs(limit=10)
>>> recent.more_available
True
>>> while recent.more_available and recent.next_page:
>>>     recent = api.drive.get_recent_docs(limit=10, next_page=recent.next_page)
>>>     print([doc.name for doc in recent])
```

`status` carries Apple's raw value (`CONSISTENT` or `MORE_AVAILABLE`) if you would rather react to the
truncation yourself. Each call returns one page; pages are not merged or de-duplicated. The loop
above checks `next_page` as well as the status so a truncated page without a cursor cannot re-request
the first page forever.

To interact with files and directions the `mkdir`, `rename` and `delete` functions are available
for a file or folder:

```bash
>>> api.drive['Holiday Photos'].mkdir('2020')
>>> api.drive['Holiday Photos']['2020'].rename('2020_copy')
>>> api.drive['Holiday Photos']['2020_copy'].delete()
```

The `upload` method can be used to send a file-like object to the iCloud Drive:

```bash
>>> with open('Vacation.jpeg', 'rb') as file_in:
>>>>    api.drive['Holiday Photos'].upload(file_in)
```

It is strongly suggested to open file handles as binary rather than text to prevent decoding errors
further down the line.

### Accessing App Data

The `get_app_node` method can be used to retrieve a node with app data (that is not shown in `api.drive.dir()`). This is where the individual apps store related documents.

```bash
>>> node = api.drive.get_app_node("XXXXXXXXXX.com.apple.iMovie")
```

Ids of individual app data can be found in `~/Library/Mobile Documents` (can only be accessed in Terminal). `~` must be replaced with `.`.

Node can then be used just like any other node, supporting `mkdir`, `rename`, `delete` and so on:

```
>>> node.mkdir('2020')
>>> node.rename('2020_copy')
>>> node.delete()
```

## Photo Library

You can access the iCloud Photo Library through the `photos` property.

```bash
>>> api.photos.all
<PhotoAlbum: 'All Photos'>
```

Individual albums are available through the `albums` property:

```bash
>>> api.photos.albums['Screenshots']
<PhotoAlbum: 'Screenshots'>
```

Which you can iterate to access the photo assets. The 'All Photos' album is sorted by `added_date` so the most recently added photos are returned first. All other albums are sorted by `asset_date` (which represents the exif date) :

```bash
>>> for photo in api.photos.albums['Screenshots']:
        print photo, photo.filename
<PhotoAsset: id=AVbLPCGkp798nTb9KZozCXtO7jds> IMG_6045.JPG
```

To download a photo use the `download` method, which will return a [response object](http://www.python-requests.org/en/latest/api/#classes), initialized with `stream` set to `True`, so you can read from the raw response object:

```bash
>>> photo = next(iter(api.photos.albums['Screenshots']), None)
>>> download = photo.download()
>>> with open(photo.filename, 'wb') as opened_file:
        opened_file.write(download.raw.read())
```

**_Note: Consider using `shutil.copyfile` or another buffered strategy for downloading the file so that the whole file isn't read into memory before writing._**

Information about each version can be accessed through the `versions` property:

```bash
>>> photo.versions.keys()
[u'medium', u'original', u'thumb']
```

Edited photos also expose Apple's rendered edit (crop, filters, portrait
effects, ...) as the `full` version. It is a JPEG rendition of the current
view, not the untouched original, so it appears only for photos that have
been edited:

```bash
>>> photo.versions['full']['type']
u'public.jpeg'
```

To download a specific version of the photo asset, pass the version to `download()`:

```bash
>>> download = photo.download('thumb')
>>> with open(photo.versions['thumb']['filename'], 'wb') as thumb_file:
        thumb_file.write(download.raw.read())
```

### Libraries

`api.photos` is the primary library. Every photo library the account owns -- the primary library and any shared library it created -- is available through the `libraries` property, keyed by zone name. Libraries shared *with* you live in CloudKit's shared database rather than the private one this enumerates, so they are not listed yet ([#115](https://github.com/mandarons/icloudpy/issues/115)).

```bash
>>> sorted(api.photos.libraries)
['PrimarySync']
>>> api.photos.libraries['PrimarySync'].all
<PhotoAlbum: 'All Photos'>
```

`libraries` is built on first access and cached on the service. Enumeration skips zones Apple rejects outright (`400 Index has invalid data`, `ZONE_NOT_FOUND`) and non-photo `CMM-*` zones, logging a warning rather than failing the call; a failed `zones/list` raises instead of returning an empty dict. `library.zone_readable()` probes a single zone: `False` only when Apple definitively rejects it, `True` otherwise, with transient errors propagating rather than being read as "unusable".

### One library that cannot be read

A library Apple rejects cannot be listed by anyone, and without isolation it would fail every other library's sync too. `libraries` leaves those zones out, so a consumer that iterates it simply never sees them. When a zone-scoped query is rejected outright, it raises `ICloudPyLibraryUnavailableException` -- a subclass of `ICloudPyAPIResponseException` carrying `zone_name` -- so a caller can skip that library and carry on:

```python
from icloudpy.exceptions import ICloudPyLibraryUnavailableException

for name, library in api.photos.libraries.items():
    try:
        for photo in library.all:
            ...
    except ICloudPyLibraryUnavailableException as err:
        # Apple rejected this zone mid-walk; skip it, keep the others.
        print(f"skipping {err.zone_name or name}: {err}")
```

Both types remain subclasses of `ICloudPyAPIResponseException`, so existing handlers keep working. Note that `ZONE_NOT_FOUND` now raises `ICloudPyLibraryUnavailableException` rather than `ICloudPyServiceNotActivatedException` -- including for the primary library (`api.photos`) -- so a handler catching the older type specifically no longer sees it.

This is not the same thing as a library that is still indexing: an unfinished index raises `ICloudPyServiceNotActivatedException`, and by default one unfinished library still fails the whole `libraries` call. Pass `photos_require_finished_index=False` (see below) to open it anyway.

### Deleting a photo

`PhotoAsset.delete()` addresses the asset's own library's zone, exposed as `zone_id`, so an asset from a shared library is deleted there rather than in the primary library:

```bash
>>> photo.zone_id
{'zoneName': 'PrimarySync'}
>>> photo.delete()
```

### While Apple is still indexing

Opening a library raises `ICloudPyServiceNotActivatedException` until Apple reports it has finished indexing it. Apple can report a library as indexing for a long time while still listing it, so you can open it anyway and check how far the index got:

```python
>>> api = ICloudPyService('jappleseed@apple.com', 'password', photos_require_finished_index=False)
>>> api.photos.indexing_state
'RUNNING'
>>> {name: library.indexing_state for name, library in api.photos.libraries.items()}
{'PrimarySync': 'RUNNING'}
```

Until a library reads `FINISHED`, its listings may be incomplete. Don't treat a photo missing from one as deleted. The option is read when `api.photos` is first opened, so set it when you create the service. Each `indexing_state` is what Apple reported at that moment and isn't refreshed; create a new service to check again.
