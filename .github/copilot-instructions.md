# iCloudPy AI Coding Agent Instructions

## Project Overview
iCloudPy is a Python library wrapping iCloud web services, forked from pyiCloud. It authenticates via username/password, maintains session state locally, and exposes modular services (Drive, Photos, FindMyiPhone, Contacts, Calendar, Reminders, Account).

**Key architectural pattern**: All services inherit from service classes in `icloudpy/services/` and are accessed as properties of `ICloudPyService` (e.g., `api.drive`, `api.photos`). Services use `ICloudPySession` (extends `requests.Session`) for authenticated HTTP requests.

## Critical Testing Pattern: Fixture-Based Mocking
Tests use a **comprehensive mock pattern** via `tests/__init__.py`:
- `ICloudPyServiceMock` replaces real API calls with fixture responses
- Fixtures live in `tests/const_*.py` files (e.g., `const_drive.py`, `const_photos.py`, `const_auth.py`)
- `ICloudPySessionMock.request()` intercepts URLs and returns fixture data based on URL patterns
- **When adding tests**: Create or extend `const_*.py` fixtures, then update `ICloudPySessionMock.request()` to handle new URL patterns
- Example: Drive folder data in `DRIVE_ROOT_WORKING` fixture, returned when URL matches `retrieveItemDetailsInFolders`

## Authentication & Session Management
- Two auth flows: **2FA** (`requires_2fa`) and **2SA** (`requires_2sa`) - handle differently (see `README.md` examples)
- **China region support**: Pass `home_endpoint="https://www.icloud.com.cn"` and `setup_endpoint="https://setup.icloud.com.cn/setup/ws/1"`
- Session data persisted in `<temp>/icloudpy/<username>/` (cookies via `LWPCookieJar`, session tokens via JSON)
- `ICloudPyPasswordFilter` automatically redacts passwords from logs

## Development Workflow
**Run tests**: `pytest` (configured in `pytest.ini` with coverage, allure reports)
**Lint/format**: `ruff check --fix` (must pass before tests in CI)
**Full CI locally**: `./run-ci.sh` (cleans, lints, tests, generates reports, builds distribution)
**Install dev deps**: `pip install -r requirements-test.txt`

## Service Structure
Services initialized lazily via properties in `ICloudPyService`:
```python
@property
def drive(self):
    if not self._drive:
        self._drive = DriveService(service_root, document_root, self.session, self.params)
    return self._drive
```

Each service class receives:
- `session`: Authenticated `ICloudPySession` instance
- `params`: Base query params (clientId, dsid)
- Service-specific roots/endpoints

## Key Files & Patterns
- `icloudpy/base.py`: Core `ICloudPyService` and `ICloudPySession` classes (699 lines)
- `icloudpy/services/*.py`: Individual service implementations (Drive, Photos, etc.)
- `tests/const_*.py`: Mock response fixtures organized by service
- `tests/__init__.py`: `ICloudPyServiceMock` and `ICloudPySessionMock` (260 lines)
- `Coveragerc`: Coverage targets only `icloudpy/*` (exclude tests)

## Common Gotchas
- **Don't mock `requests` directly**: Use `ICloudPyServiceMock` which intercepts at session level
- **Session token validation**: `_validate_token()` checks existing session before re-auth
- **Error handling**: Services raise `ICloudPyAPIResponseException`, `ICloudPyServiceNotActivatedException`, etc. - check `exceptions.py`
- **Drive file downloads**: Two-step process: get token from `/download/by_id`, then fetch from `data_token.url`
- **Photos**: Query-based API with recordType filters (e.g., `CPLAssetAndMasterByAddedDate` for assets)

## CI/CD Requirements
- Tests run on Python 3.8+ (see `setup.py`)
- Must pass `ruff check` (zero violations)
- Coverage tracked with pytest-cov (HTML + XML reports)
- Allure reports generated for test results

## Adding New Features
1. Add service method to appropriate `icloudpy/services/*.py`
2. Create fixture in `tests/const_<service>.py` with expected API response
3. Update `ICloudPySessionMock.request()` to handle new URL pattern
4. Write test in `tests/test_<service>.py` using `ICloudPyServiceMock`
5. Run `./run-ci.sh` to validate locally before pushing
