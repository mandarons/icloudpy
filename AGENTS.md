# iCloudPy

Python library wrapping iCloud web services (derived from pyiCloud). Single package `icloudpy/`, tests in `tests/`.

## Quick reference

```bash
# Install test deps (use uv for speed)
pip install -r requirements-test.txt
# or in devcontainer: uv pip install -r requirements-test.txt

# Lint and format
ruff check --fix
ruff format

# Test (all, with coverage)
pytest

# Test single file
pytest tests/test_auth.py

# Full CI pipeline (clean, lint, test, build)
./run-ci.sh
```

## Verification order

`ruff check` → `pytest` → build. The `run-ci.sh` script does exactly this.

## Key config

| Tool | Config | Notes |
|------|--------|-------|
| ruff | `.ruff.toml` | Lint + format, line length 120 |
| pylint | `pylintrc` | Runs via `run-in-env.sh pylint -j 0` on `icloudpy/` only |
| pytest | `pytest.ini` | Coverage minimum 78%, `--cov-fail-under=78` |
| bandit | `tests/bandit.yaml` | Security checks via pre-commit |

## Pre-commit hooks

```bash
pre-commit install
pre-commit run --all-files
```

Includes: ruff (lint + format), codespell, bandit, yamllint, prettier, no-commit-to-branch (blocks direct commits to `main`).

## Project structure

- `icloudpy/__init__.py` → exports `ICloudPyService`
- `icloudpy/base.py` → main service class
- `icloudpy/cmdline.py` → CLI entry point (`icloud` command)
- `icloudpy/services/` → service submodules (drive, photos, findmyiphone, etc.)
- `tests/const_*.py` → test fixture data (constants, not live API calls)

## Testing notes

- Tests use mock data from `tests/const_*.py` files, no live iCloud calls
- Markers available: `unit`, `integration`, `slow`
- Allure reporting configured (results in `allure-results/`)
- Coverage report: `htmlcov/` and `coverage.xml`

## Gotchas

- `Coveragerc` (note capital C) configures coverage for `icloudpy/*`
- Pre-commit pylint runs through `run-in-env.sh` which activates virtualenvs automatically
- Line length is 120 everywhere (ruff, pylint)
- `no-commit-to-branch` hook blocks direct commits to `main` — create a feature branch first
