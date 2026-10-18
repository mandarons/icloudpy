# Changelog

All notable changes to iCloudPy are documented here. Release notes for every
release, including older ones, are on the
[GitHub Releases page](https://github.com/mandarons/icloudpy/releases).

## [Unreleased]

### Fixed

- Photos: one broken library (CloudKit zone) no longer takes down the others.
  Library enumeration now skips zones Apple rejects outright (`400 Index has
  invalid data`, `ZONE_NOT_FOUND`) and non-photo `CMM-*` zones, logging a
  warning instead of crashing the whole call. Any later zone-scoped failure
  raises the new `ICloudPyLibraryUnavailableException` (a subclass of
  `ICloudPyAPIResponseException`, naming the zone), so consumers can skip the
  failing library and continue with the rest. A failed `zones/list` now
  surfaces the original error instead of `UnboundLocalError` (#179).
  Two boundaries of that isolation are worth stating explicitly:
  - `ZONE_NOT_FOUND` now raises `ICloudPyLibraryUnavailableException`
    instead of `ICloudPyServiceNotActivatedException` -- including for the
    primary library (`api.photos`). Handlers catching
    `ICloudPyServiceNotActivatedException` specifically no longer see that
    code; both types remain subclasses of `ICloudPyAPIResponseException`.
  - A library that is still *indexing* is not covered: it keeps raising
    `ICloudPyServiceNotActivatedException` from the first access, so one
    unfinished index still fails the whole `libraries` call (an unfinished
    index is an account-wide wait, unchanged from previous releases).
- Photos: `PhotoAsset.delete()` now addresses the photo's own library. Every
  asset was handed the `PhotosService`, whose zone is always `PrimarySync`, so
  deleting a photo from any other library (a Shared Library, say) targeted a
  record that does not exist there. Assets now carry their library's zone,
  exposed as `PhotoAsset.zone_id`.

### Added

- Photos: `ICloudPyService(..., photos_require_finished_index=False)` opens
  Photos while Apple is still indexing a library, instead of raising
  `ICloudPyServiceNotActivatedException`. Each library's `indexing_state`
  says how far Apple got; until it reads `FINISHED`, a listing may be
  incomplete. The default is unchanged.

## [0.10.0] - Unreleased

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
