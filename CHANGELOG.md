# Changelog

All notable changes to iCloudPy are documented here. Release notes for every
release, including older ones, are on the
[GitHub Releases page](https://github.com/mandarons/icloudpy/releases).

## [Unreleased]

### Added

- Drive: `api.drive.get_recent_docs()` lists the recently opened iCloud Drive
  documents, newest first, as `DriveNode` objects, so `name`, `size`, the date
  properties and `open()` work as they do for any other drive node. Apple caps
  the listing and reports `MORE_AVAILABLE` when it does; the returned
  `RecentDocs` list exposes `status`, `more_available` and a `next_page` cursor,
  and `get_recent_docs(next_page=...)` continues from it
  ([#135](https://github.com/mandarons/icloudpy/issues/135)).

### Fixed

- Photos: `PhotoAsset.versions` now reads each version from the `CPLAsset`
  record first and falls back to `CPLMaster` per version. Apple stores the
  edited rendition (`resJPEGFull*`) on the asset record and the
  originals/alternates on the master record, so consulting only the master hid
  every edit: an edited photo reported `original`/`medium`/`thumb` and no
  `full` version, and consumers could not download the edit at all
  ([icloud-docker#292](https://github.com/mandarons/icloud-docker/issues/292)).
  Unedited photos are unchanged (no `full` version). Because the lookup is per
  version key, an edited asset's `medium`, `thumb` and Live Photo
  `live_video_*` renditions also come from the asset record and therefore
  describe the edit; edited movies expose the edited video as the video
  `full`.

## [0.11.0] - 2026-10-17

### Added

- Photos: `ICloudPyService(..., photos_require_finished_index=False)` opens
  Photos while Apple is still indexing a library, instead of raising
  `ICloudPyServiceNotActivatedException`. Apple can report a library as
  indexing for weeks while listing it in full, and until now a consumer could
  not open it at all and backed up nothing meanwhile. The option covers the
  primary library and every library from `libraries`; each exposes
  `indexing_state` (`RUNNING`, `FINISHED`, ...) so a consumer can keep
  downloading while treating the listing as possibly incomplete. The default
  is unchanged (`True`), and `indexing_state` is a snapshot taken when the
  library is opened, not refreshed (#202).
- Photos: `PhotoAsset.zone_id` -- the CloudKit zone an asset belongs to, so a
  consumer re-fetching an asset's records can address the right library. An
  asset built without one falls back to the service's zone, as before (#201).

### Changed

- `ZONE_NOT_FOUND` now raises `ICloudPyLibraryUnavailableException` instead of
  `ICloudPyServiceNotActivatedException` -- including for the primary library
  (`api.photos`). Handlers catching `ICloudPyServiceNotActivatedException`
  specifically no longer see that code; both types remain subclasses of
  `ICloudPyAPIResponseException`, so broad handlers are unaffected. See the
  isolation entry under Fixed (#192).
- CI: Allure report generation no longer builds a Docker image from
  `public.ecr.aws` on every job. Anonymous pulls there are quota-limited per
  IP, and GitHub's shared runner IPs exhausted that quota, failing the report
  step after the tests had already passed. A local composite action downloads
  the same pinned Allure CLI (2.44.0) from Maven Central and reproduces the
  output contract; when the tests died before writing results, report
  generation is skipped with a warning instead of masking the failure with an
  infrastructure error (#203).
- Runtime dependency bump: `pytz` 2026.5.
- Development tooling bumps: `ruff` 0.17.0, `black` 26.10.1, `coverage` 7.16.2,
  `allure-pytest` 2.16.2.

### Fixed

- Photos: one broken library (CloudKit zone) no longer takes down the others.
  Library enumeration now skips zones Apple rejects outright (`400 Index has
  invalid data`, `ZONE_NOT_FOUND`) and non-photo `CMM-*` zones, logging a
  warning instead of crashing the whole call. Any later zone-scoped failure
  raises the new `ICloudPyLibraryUnavailableException` (a subclass of
  `ICloudPyAPIResponseException`, naming the zone), so consumers can skip the
  failing library and continue with the rest. A failed `zones/list` now
  surfaces the original error instead of `UnboundLocalError` (#179).
  One boundary of that isolation is worth stating explicitly:
  - A library that is still *indexing* is not covered: it keeps raising
    `ICloudPyServiceNotActivatedException` from the first access, so one
    unfinished index still fails the whole `libraries` call (an unfinished
    index is an account-wide wait, unchanged from previous releases). Pass
    `photos_require_finished_index=False` to open it anyway.
- Photos: `PhotoAsset.delete()` now addresses the photo's own library. Every
  asset was handed the `PhotosService`, whose zone is always `PrimarySync`, so
  deleting a photo from any other library (a Shared Library, say) targeted a
  record that does not exist there (#201).
- Photos: an album with no zone now falls back to `{"zoneName": "PrimarySync"}`
  rather than the bare string `"PrimarySync"`, the shape its zone lookups and
  `delete()` expect (#201).

## [0.10.0] - 2026-09-29

### Added

- Sign-in for Apple IDs protected by a hardware security key (#174). Once
  security keys are enrolled, Apple stops issuing 6-digit codes and returns a
  WebAuthn challenge instead; the new API completes it:
  - `ICloudPyService.security_key_challenge` -- the pending challenge, or `None`
  - `ICloudPyService.confirm_security_key(assertion=None, device=None)` --
    sign with an attached FIDO2 key (or submit an assertion built elsewhere)
  - `ICloudPyService.sign_security_key_challenge(challenge, device)` -- sign
    without submitting
  - `ICloudPyService.fido2_devices` -- attached FIDO2 devices
  - `icloudpy.base.build_security_key_assertion(response, rp_id, request_id=None)`
    -- turn a WebAuthn `AuthenticatorAssertionResponse` into Apple's payload
  - New optional extra: `pip install "icloudpy[security-key]"` installs `fido2`.
    The dependency stays optional -- it is only imported when a challenge is
    signed locally.
- README: new "Hardware security keys" section, and the 2SA/2FA example now
  branches between a security key and a 6-digit code.

### Fixed

- Drive downloads now forward `timeout` to the `by_id` metadata lookup as well
  as to the data transfer, so a stalled lookup can no longer hang a worker
  thread forever (#186). `stream` is intentionally not forwarded to the lookup.

### Changed

- Minimum supported Python version is now 3.10, matching the CI runtime and the
  README badge. `python_requires` previously declared `>=3.8`, but the pinned
  runtime dependencies already required 3.10 (`requests` 2.34, `click` 8.5,
  `tzlocal` 5.4), and pyupgrade now enforces `--py310-plus` instead of
  `--py39-plus`.
- CI now also runs on changes to `setup.py`, `MANIFEST.in`, `README.md` and
  `CHANGELOG.md`; those paths were filtered out before, so packaging and
  documentation changes shipped without a test run.
- Documentation: `DriveNode.open()`'s `timeout` support is now documented; the
  README's 2SA/2FA sample was modernized to Python 3, and it now notes that the
  `icloud` CLI does not support security-key accounts yet.
- Runtime dependency bumps: `requests` 2.34.2, `click` 8.5.0, `tzlocal` 5.4.4,
  `pytz` 2026.4, `certifi` 2026.7.22.
- Development: `AGENTS.md` added; CI tooling updates (ruff, black, coverage,
  pre-commit, setuptools, build, allure-pytest, pytest).

## [0.9.0] - 2026-05-31

### Added

- Surface the Live Photo `.mov` pair via `versions` (#139).
- `PhotoAlbum.iter_chunks` -- fixed-size batches for bounded-memory bulk
  download (#140).

### Fixed

- Trigger the 2FA push notification on iOS 26.4+, resolving an auth stall
  (#138).

**Full changelog**: https://github.com/mandarons/icloudpy/compare/v0.9.0...HEAD
