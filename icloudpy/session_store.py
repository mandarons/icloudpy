"""Atomic, merge-on-write persistence for session data and cookies.

Two processes write these files in practice: the sync loop and the web UI of
``icloud-docker``, which runs as a daemon thread and builds its own service
instances against the same cookie directory. Both used to rewrite the whole
file from their own memory on every request, so a cookie another instance had
just obtained could be erased by a stale one, and a crash mid-write could
leave a truncated jar behind.

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
    """Persist the cookie jar atomically, merging what another writer added."""
    jar = service.session.cookies
    path = getattr(jar, "filename", None) or service.cookiejar_path
    if not path:
        return
    with LOCK:
        _merge_cookies_from_disk(service, path)
        temp_path = f"{path}.tmp"
        jar.save(temp_path, ignore_discard=True, ignore_expires=True)
        os.replace(temp_path, path)
        with contextlib.suppress(OSError):
            os.chmod(path, FILE_MODE)
        if not getattr(jar, "filename", None):
            jar.filename = path


def save_session_files(service) -> None:
    """Persist session data and cookies together, under one lock."""
    with LOCK:
        save_session_data(service)
        save_cookies(service)
