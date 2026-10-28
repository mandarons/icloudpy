"""Atomic, merge-on-write persistence for session data and cookies.

Two kinds of writer share these files in practice. In ``icloudpy-docker`` the
sync loop and the web UI write them from one process -- the web UI is a daemon
*thread* that builds its own service instances against the same cookie
directory, so :data:`LOCK` serialises it. A second *process* is also ordinary:
the ``icloud`` CLI (``icloudpy/cmdline.py``) points at the same directory, and
the lock cannot serialise that one at all.

Each writer used to rewrite the whole file from its own memory on every
request, so a cookie another had just obtained could be erased by a stale copy,
and a crash mid-write could leave a truncated jar behind.

Everything here is written to a temporary file in the same directory and moved
into place with :func:`os.replace`, so a reader never observes a partial file.
Cookie saves additionally re-read the file on disk first and carry over any
cookie this instance does not hold, which is what keeps a PCS cookie acquired
by one instance from being dropped by another.
"""

import contextlib
import http.cookiejar as cookielib
import json
import logging
import os
import tempfile
import threading

LOGGER = logging.getLogger(__name__)

#: Serialises the load-merge-save cycle. Re-entrant because a caller may
#: already hold it when a helper takes it again.
LOCK = threading.RLock()

#: Every file written here carries credentials (session and trust tokens, PCS
#: and web-auth cookies), so none of them may be group- or world-readable.
FILE_MODE = 0o600


def _atomic_write(path: str, text: str, mode: int = FILE_MODE) -> None:
    """Write ``text`` to ``path`` without ever exposing a partial file."""
    directory = os.path.dirname(path) or "."
    handle, temp_path = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as outfile:
            outfile.write(text)
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_path)
        raise


def save_session_data(service) -> None:
    """Persist the session tokens atomically, owner-readable only.

    No merge here on purpose: :attr:`session_data` is a flat map of header
    values, and carrying a stale ``session_token`` over from disk is worse
    than letting the most recent successful response win.
    """
    path = service.session_path
    payload = json.dumps(service.session_data)
    with LOCK:
        _atomic_write(path, payload)


def _merge_cookies_from_disk(service, path: str) -> None:
    """Carry over cookies this instance does not hold from the saved jar.

    Only cookies that are still valid are carried over, and only when this
    instance has no cookie with the same name/domain/path -- the value in
    memory comes from a request that just succeeded, so it wins.

    Trade-off worth knowing: in the narrow window where another instance has
    deleted a cookie that the on-disk file still carries, this can restore it.
    The alternative -- letting the last writer silently drop a freshly
    acquired PCS cookie -- is the failure this exists to prevent, and it is
    the common one.
    """
    if not os.path.exists(path):
        return
    jar = service.session.cookies
    on_disk = cookielib.LWPCookieJar()
    try:
        on_disk.load(path, ignore_discard=True, ignore_expires=True)
    except OSError, cookielib.LoadError:
        # A truncated or foreign-format jar is not worth failing a request
        # over; the save that follows replaces it.
        LOGGER.debug("Could not read the saved cookie jar at %s; replacing it", path)
        return
    held = {(cookie.name, cookie.domain, cookie.path) for cookie in jar}
    now = None
    for cookie in on_disk:
        key = (cookie.name, cookie.domain, cookie.path)
        if key in held:
            continue
        if cookie.is_expired(now):
            continue
        jar.set_cookie(cookie)
        held.add(key)


def save_cookies(service) -> None:
    """Persist the cookie jar atomically, merging what another writer added.

    The temporary file gets a unique name rather than a fixed ``<path>.tmp``:
    the lock only serialises threads, and a second *process* (the ``icloud``
    CLI) writing its own save must not collide with this one.
    """
    jar = service.session.cookies
    path = getattr(jar, "filename", None) or service.cookiejar_path
    if not path:
        return
    with LOCK:
        _merge_cookies_from_disk(service, path)
        directory = os.path.dirname(path) or "."
        handle, temp_path = tempfile.mkstemp(prefix=".cookies-", dir=directory)
        os.close(handle)
        try:
            jar.save(temp_path, ignore_discard=True, ignore_expires=True)
            os.replace(temp_path, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp_path)
            raise
        with contextlib.suppress(OSError):
            os.chmod(path, FILE_MODE)
        if not getattr(jar, "filename", None):
            jar.filename = path


def save_session_files(service) -> None:
    """Persist session data and cookies together, under one lock."""
    with LOCK:
        save_session_data(service)
        save_cookies(service)
