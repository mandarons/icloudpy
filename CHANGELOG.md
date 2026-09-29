# Changelog

All notable changes to iCloudPy are documented here. Release notes for every
release, including older ones, are on the
[GitHub Releases page](https://github.com/mandarons/icloudpy/releases).

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
  - New optional extra: `pip install icloudpy[security-key]` installs `fido2`.
    The dependency stays optional -- it is only imported when a challenge is
    signed locally.
- README: new "Hardware security keys" section, and the 2SA/2FA example now
  branches between a security key and a 6-digit code.

### Fixed

- Drive downloads now forward `timeout` to the `by_id` metadata lookup as well
  as to the data transfer, so a stalled lookup can no longer hang a worker
  thread forever (#186). `stream` is intentionally not forwarded to the lookup.

### Changed

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
