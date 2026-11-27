"""`Site`: the authenticated session and managed request digest for one SharePoint site."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeGuard
from urllib.parse import urlsplit

from requests import Response, Session

from sppyte.auth import Protocol, SpPremAuth
from sppyte.batch import Batch
from sppyte.errors import FORBIDDEN, AuthError, ConfigurationError, raise_for_status
from sppyte.libraries import Library
from sppyte.lists import List
from sppyte.odata import JSON_NOMETADATA, JSON_VERBOSE, Page, parse_page
from sppyte.retry import RetryOptions, with_retry
from sppyte.utils import parse_context_info, parse_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from requests.auth import AuthBase

DIGEST_REFRESH_MARGIN = 60.0
"""Refresh the digest this many seconds before SharePoint says it expires."""

DEFAULT_TIMEOUT = 30.0
"""Default per-request timeout in seconds (connect and read).

Long enough for a large list read on a busy farm, short enough that a hung connection fails
instead of blocking the caller indefinitely.
"""

Timeout = float | tuple[float, float] | None
"""A `requests` timeout: seconds, a `(connect, read)` pair, or `None` for no timeout."""

_HOST_RE = re.compile(r"^https?://[^/\s?#]+/?$", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_PAIR = 2
"""Length of a `(connect, read)` timeout or a `(cert, key)` pair."""


class Site:
    """A connection to one SharePoint site.

    - Lazily establishes an authenticated `requests.Session` (NTLM or Kerberos) on first use.
    - Obtains, caches and refreshes the form digest required for write operations.
    - Hands out `List` and `Library` helpers bound to this site.

    Use as a context manager to connect eagerly and ensure the session is closed:

    ```python
    with Site(host, "/sites/demo", username, password) as site:
        docs = site.library("Shared Documents")
        docs.add_folder("Reports", "2025")
    ```

    Args:
        host: Scheme and host only, e.g. `"https://sharepoint.example.com"`.
        site_relative_url: Server-relative URL of the site (web), e.g. `"/sites/demo"`;
            `""` or `"/"` for the root site.
        username: Account name without the domain. Required for NTLM; omit with
            `protocol="negotiate"` to use the current user's Kerberos ticket.
        password: Password for `username`; omit for single sign-on.
        domain: NTLM (NetBIOS) domain, e.g. `"CONTOSO"`. Omit for a local account or when
            `username` already contains a domain.
        protocol: `"ntlm"` (default), `"negotiate"` (Kerberos when a ticket is available,
            NTLM otherwise) or `"kerberos"`. See `sppyte.auth`.
        auth: Any `requests` authentication handler to use instead of sppyte's
            `SpPremAuth`; `username`, `password`, `domain` and `protocol` are then ignored.
        timeout: Per-request timeout in seconds, or a `(connect, read)` tuple. `None`
            disables the timeout (not recommended).
        verify: TLS verification; `False` to disable, or a path to a CA bundle for an
            internal certificate authority. Forwarded to `requests.Session.verify`.
        cert: Client certificate (path or `(cert, key)` tuple). Forwarded to
            `requests.Session.cert`.
        session: Pre-configured `requests.Session` to use instead of creating one. sppyte
            attaches its `SpPremAuth` handler only if it has no `auth`, and does not close it.
        retry: Retry transient failures on reads (`GET` requests and CAML queries).
            `True` for the defaults, a `RetryOptions` to tune, `None` (default) for off.
            Writes are never retried. See `sppyte.retry`.

    Attributes:
        host: `host` as given, without a trailing slash.
        relative_url: `site_relative_url` normalised to `""` (root site) or `/path`.
        site_path: `host` + `relative_url`; every request URL starts with it.
        auth: The `requests` authentication handler in use: the `SpPremAuth` sppyte built,
            or the `auth` you passed.
        session: The `requests.Session`; `None` until the first request (or `connect()`) when
            sppyte creates it, and again after `close()`.
        timeout: The default per-request timeout.
        retry: The `RetryOptions` in effect, or `None` when retry is off.

    Raises:
        ConfigurationError: if any option is malformed; the message names the option and
            the value it got (never a password). Specifically:

            - `host` is not scheme and host name only;
            - `site_relative_url` is not a string or not a server-relative path;
            - the NTLM `username` or `password` is missing;
            - `timeout` is not `None`, a positive number or a `(connect, read)` pair of
              positive numbers;
            - `verify` is not `None`, a `bool` or a `str`;
            - `cert` is not `None`, a `str` or a `(cert, key)` pair of `str`;
            - `session` is not `None` or a `requests.Session`;
            - `retry` is not `None`, a `bool` or a `RetryOptions`.
    """

    def __init__(
        self,
        host: str,
        site_relative_url: str,
        username: str | None = None,
        password: str | None = None,
        *,
        domain: str | None = None,
        protocol: Protocol = "ntlm",
        auth: AuthBase | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
        verify: bool | str | None = None,
        cert: str | tuple[str, str] | None = None,
        session: Session | None = None,
        retry: RetryOptions | bool | None = None,
    ):
        self.host = _validate_host(host)
        self.relative_url = _validate_relative_url(site_relative_url)
        self.site_path = f"{self.host}{self.relative_url}"
        self.username = username
        self.password = password
        self.domain = domain
        self.protocol: Protocol = protocol
        if auth is None:
            if protocol == "ntlm" and (not isinstance(username, str) or not username):
                msg = "username must be a non-empty string for NTLM; use protocol='negotiate' for single sign-on"
                raise ConfigurationError(msg)
            if protocol == "ntlm" and not isinstance(password, str):
                msg = "password must be a string for NTLM"
                raise ConfigurationError(msg)
            try:
                auth = SpPremAuth(username, password, domain=domain, protocol=protocol)
            except ValueError as e:
                raise ConfigurationError(str(e)) from e
        self.auth: AuthBase = auth
        self.timeout = _validate_timeout(timeout)
        self.verify = _validate_verify(verify)
        self.cert = _validate_cert(cert)
        self.retry = _validate_retry(retry)

        self.session = _validate_session(session)
        self._owns_session = session is None

        self._digest: str | None = None
        self._digest_expires_at = 0.0
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return f"Site({self.site_path!r}, username={self.username!r})"

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------ session ----
    @property
    def principal(self) -> str | None:
        r"""The account name sent to the server: `DOMAIN\user` when a domain was given.

        `None` when authenticating with the current user's Kerberos ticket or a
        custom `auth` handler.
        """
        if isinstance(self.auth, SpPremAuth):
            return self.auth.username
        return None

    def _ensure_session(self) -> Session:
        """Return the session, creating and configuring it on first use.

        Holds the connection lock, so concurrent first requests share one session.
        """
        with self._lock:
            if self.session is None:
                self.session = Session()
                self._owns_session = True
            session = self.session
            if session.auth is None:
                session.auth = self.auth
            if self.verify is not None:
                session.verify = self.verify
            if self.cert is not None:
                session.cert = self.cert
            return session

    def connect(self) -> None:
        """Create the authenticated session and fetch a form digest eagerly.

        Use it to check the credentials and site up front rather than on the first call.

        Raises:
            AuthError: on 401/403, for example when the credentials are rejected.
            SharePointError: on any other 4xx/5xx.
            ResponseFormatError: if the contextinfo response is not JSON or has no form digest.
        """
        self._ensure_session()
        self.digest(refresh=True)

    def close(self) -> None:
        """Close the HTTP session (if sppyte created it) and forget the cached digest."""
        self.invalidate_digest()
        if self.session is not None and self._owns_session:
            self.session.close()
            self.session = None

    # ------------------------------------------------------------- digest ----
    @property
    def form_digest(self) -> str | None:
        """The currently cached form digest, or `None` if none has been fetched."""
        return self._digest

    def digest(self, *, refresh: bool = False) -> str:
        """Return a valid form digest, fetching or refreshing it as needed.

        The digest is cached until shortly before SharePoint says it expires.
        Concurrent callers share one fetch.

        Args:
            refresh: Fetch a new digest even if the cached one is still valid.

        Returns:
            The form digest value to send as `X-RequestDigest`.

        Raises:
            AuthError: on 401/403.
            SharePointError: on any other 4xx/5xx.
            ResponseFormatError: if the contextinfo response is not JSON or has no form digest.
        """
        with self._lock:
            if not refresh and self._digest is not None and time.monotonic() < self._digest_expires_at:
                return self._digest
            r = self._send(
                "post",
                f"{self.site_path}/_api/contextinfo",
                headers={"Accept": JSON_NOMETADATA, "Content-Type": JSON_VERBOSE},
                data="",
                timeout=self.timeout,
            )
            info = parse_context_info(parse_json(r))
            margin = min(DIGEST_REFRESH_MARGIN, info["timeout"] / 2)
            self._digest = info["digest"]
            self._digest_expires_at = time.monotonic() + info["timeout"] - margin
            return self._digest

    def invalidate_digest(self) -> None:
        """Drop the cached digest so the next write fetches a fresh one."""
        with self._lock:
            self._digest = None
            self._digest_expires_at = 0.0

    def get_form_digest(self) -> str:
        """Fetch a fresh form digest from `/_api/contextinfo`, bypassing the cache.

        Same as `digest(refresh=True)`; the new digest is also cached.

        Returns:
            The form digest value to send as `X-RequestDigest`.

        Raises:
            AuthError: on 401/403.
            SharePointError: on any other 4xx/5xx.
            ResponseFormatError: if the contextinfo response is not JSON or has no form digest.
        """
        return self.digest(refresh=True)

    # ------------------------------------------------------------ request ----
    def _send(self, method: str, url: str, **kwargs: Any) -> Response:
        """Send one request on the session and raise for a non-2xx status."""
        session = self._ensure_session()
        r = session.request(method, url, **kwargs)
        raise_for_status(r)
        return r

    def request(
        self,
        method: str,
        path: str,
        *,
        digest: str | bool | None = None,
        retry: bool | None = None,
        **kwargs: Any,
    ) -> Response:
        """Perform an HTTP request against the site.

        Keyword arguments mirror `requests.Session.request`; `timeout` defaults
        to the Site's timeout.

        Args:
            method: HTTP method.
            path: Path relative to the site root (`_api/web/...`); leading and
                trailing slashes are tolerated.
            digest: `True` to send the managed form digest as `X-RequestDigest`
                (required for writes). If SharePoint rejects it with 403 the digest
                is refreshed and the request retried once, provided the body can
                be re-sent: `json`, or `data` and every file in `files` being
                bytes, str or a seekable file. A `str` sends that digest as-is
                with no retry. `None` / `False` sends none.
            retry: Whether the Site's `retry` policy applies to this call. Defaults
                to `True` for `GET` without a digest (reads) and `False` otherwise.
                Has no effect unless the Site was created with `retry`.
            **kwargs: Passed to `requests.Session.request` (`params`, `headers`,
                `json`, `data`, `files`, `stream`, `timeout`, ...).

        Returns:
            The `requests.Response`.

        Raises:
            AuthError: on 401/403.
            SharePointError: on any other 4xx/5xx.
            ResponseFormatError: with `digest=True`, if the contextinfo response is not JSON or
                has no form digest.
        """
        if retry is None:
            retry = method.upper() == "GET" and not digest
        policy = self.retry if retry else None
        return with_retry(policy, lambda: self._request_once(method, path, digest, kwargs))

    def _request_once(self, method: str, path: str, digest: str | bool | None, kwargs: dict[str, Any]) -> Response:
        """Perform `request` once, handling the digest header and the single 403 refresh."""
        url = f"{self.site_path}/{path.strip('/')}"
        kwargs = {"timeout": self.timeout, **kwargs}

        if not digest:
            return self._send(method, url, **kwargs)

        headers = dict(kwargs.pop("headers", None) or {})
        if isinstance(digest, str):
            headers["X-RequestDigest"] = digest
            return self._send(method, url, headers=headers, **kwargs)

        rewind = _rewinder(kwargs.get("data"), kwargs.get("files"))
        headers["X-RequestDigest"] = self.digest()
        try:
            return self._send(method, url, headers=headers, **kwargs)
        except AuthError as e:
            if e.status != FORBIDDEN or rewind is None:
                raise
            rewind()
            self.invalidate_digest()
            headers["X-RequestDigest"] = self.digest()
            return self._send(method, url, headers=headers, **kwargs)

    def get_page(self, next_link: str, **kwargs: Any) -> Page:
        """Fetch the page a previous `Page.next_link` points at.

        Args:
            next_link: The link from a previous `Page`.
            **kwargs: Passed to `requests.Session.request`.

        Returns:
            The next `Page` of results, with its own `next_link` if more remain.

        Raises:
            ConfigurationError: if the link is not on this site's host, so
                credentials are never sent elsewhere.
            AuthError: on 401/403.
            SharePointError: on any other 4xx/5xx.
            ResponseFormatError: if the response is not a JSON collection.
        """
        wanted = urlsplit(self.host)
        got = urlsplit(next_link)
        if (got.scheme.lower(), got.netloc.lower()) != (wanted.scheme.lower(), wanted.netloc.lower()):
            msg = f"next_link must be on {self.host} (got {next_link!r})"
            raise ConfigurationError(msg)
        kwargs.setdefault("timeout", self.timeout)
        headers = {"Accept": JSON_NOMETADATA, **(kwargs.pop("headers", None) or {})}
        r = with_retry(self.retry, lambda: self._send("get", next_link, headers=headers, **kwargs))
        return parse_page(parse_json(r))

    # ----------------------------------------------------------- helpers ----
    def list(self, name: str) -> List:
        """Return a `List` bound to this site; performs no network I/O.

        Args:
            name: The list title as shown in SharePoint.

        Returns:
            A `List` for `name` on this site.
        """
        return List(name, self)

    def library(self, name: str) -> Library:
        """Return a `Library` bound to this site; performs no network I/O.

        Args:
            name: The library name as it appears in its URL, e.g. `"Shared Documents"`.

        Returns:
            A `Library` for `name` on this site.
        """
        return Library(name, self)

    def batch(self) -> Batch:
        """Return an empty `Batch` to send several requests in one round trip.

        Requires SharePoint 2016 or later. See `sppyte.batch`.

        Returns:
            A new, empty `Batch` bound to this site; nothing is sent until `Batch.send`.
        """
        return Batch(self)


# ------------------------------------------------------------- validation ----
def _validate_host(host: str) -> str:
    """Check `host` is scheme + host name only and return it without a trailing slash."""
    if not isinstance(host, str) or not host:
        msg = f"host must be a non-empty string such as 'https://sharepoint.example.com' (got {host!r})"
        raise ConfigurationError(msg)
    if not _SCHEME_RE.match(host):
        msg = f"host must include the scheme, e.g. 'https://{host}'"
        raise ConfigurationError(msg)
    if not _HOST_RE.match(host):
        msg = f"host must be scheme and host name only (got {host!r}); put the path in site_relative_url"
        raise ConfigurationError(msg)
    return host.rstrip("/")


def _validate_relative_url(url: str) -> str:
    """Normalise `site_relative_url` to `""` or `/path` and reject full URLs."""
    if not isinstance(url, str):
        msg = f"site_relative_url must be a string (got {url!r})"
        raise ConfigurationError(msg)
    if _SCHEME_RE.match(url):
        msg = f"site_relative_url must be a server-relative path, not a full URL (got {url!r})"
        raise ConfigurationError(msg)
    url = url.strip()
    if url in ("", "/"):
        return ""
    if not url.startswith("/"):
        msg = f"site_relative_url must start with '/' (got {url!r})"
        raise ConfigurationError(msg)
    return url.rstrip("/")


def _is_positive_number(value: object) -> TypeGuard[float]:
    """Return whether `value` is an `int` or `float` greater than zero; a `bool` is not a number here."""
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


def _validate_timeout(timeout: object) -> Timeout:
    """Accept `None`, a positive number, or a `(connect, read)` pair of positive numbers."""
    if timeout is None:
        return None
    if _is_positive_number(timeout):
        return timeout
    if isinstance(timeout, tuple) and len(timeout) == _PAIR and all(_is_positive_number(t) for t in timeout):
        return timeout
    msg = f"timeout must be None, a positive number or a (connect, read) pair of positive numbers (got {timeout!r})"
    raise ConfigurationError(msg)


def _validate_retry(retry: object) -> RetryOptions | None:
    """Map `True` to `RetryOptions()`, `False`/`None` to `None`; reject anything else."""
    if retry is True:
        return RetryOptions()
    if retry is None or retry is False:
        return None
    if isinstance(retry, RetryOptions):
        return retry
    msg = f"retry must be None, a bool or a RetryOptions (got {retry!r})"
    raise ConfigurationError(msg)


def _validate_verify(verify: object) -> bool | str | None:
    """Accept `None`, a `bool`, or a CA bundle path as `str`."""
    if verify is None or isinstance(verify, bool | str):
        return verify
    msg = f"verify must be None, a bool or a CA bundle path (got {verify!r})"
    raise ConfigurationError(msg)


def _validate_cert(cert: object) -> str | tuple[str, str] | None:
    """Accept `None`, a certificate path, or a `(cert, key)` pair of paths."""
    if cert is None or isinstance(cert, str):
        return cert
    if isinstance(cert, tuple) and len(cert) == _PAIR and all(isinstance(c, str) for c in cert):
        return cert
    msg = f"cert must be None, a path or a (cert, key) pair of paths (got {cert!r})"
    raise ConfigurationError(msg)


def _validate_session(session: object) -> Session | None:
    """Accept `None` or a `requests.Session`."""
    if session is None or isinstance(session, Session):
        return session
    msg = f"session must be None or a requests.Session (got {session!r})"
    raise ConfigurationError(msg)


def _rewinder(data: Any, files: Any = None) -> Callable[[], None] | None:
    """Return a callable that rewinds the request body so it can be sent again.

    Covers `data` and every file object in `files`. `json` needs no rewinding.
    Returns `None` if any part cannot be re-sent (a non-seekable stream or a
    generator).

    Args:
        data: The `data` argument given to `requests`.
        files: The `files` argument given to `requests`: a mapping or a sequence
            of `(name, value)` pairs, where each value is a file object, `bytes`
            or `str`, or a tuple `(filename, fileobj[, content_type[, headers]])`.
    """
    file_parts = _file_parts(files)
    if file_parts is None:
        return None
    rewinds: list[Callable[[], None]] = []
    for part in [data, *file_parts]:
        if part is None or isinstance(part, str | bytes | bytearray | dict | list | tuple):
            continue
        rewind = _stream_rewinder(part)
        if rewind is None:
            return None
        rewinds.append(rewind)

    def rewind_all() -> None:
        for step in rewinds:
            step()

    return rewind_all


def _file_parts(files: Any) -> list[Any] | None:
    """Return the content of each entry in `files`, or `None` if `files` itself can't be re-read."""
    if not files:
        return []
    if isinstance(files, Mapping):
        entries = list(files.items())
    elif isinstance(files, list | tuple):
        entries = list(files)
    else:
        return None
    parts: list[Any] = []
    for entry in entries:
        try:
            _name, value = entry
        except (TypeError, ValueError):
            return None
        if isinstance(value, list | tuple):
            parts.append(value[1] if len(value) > 1 else None)
        else:
            parts.append(value)
    return parts


def _stream_rewinder(stream: Any) -> Callable[[], None] | None:
    """Return a callable that seeks `stream` back to its current position, or `None` if it can't."""
    if not (hasattr(stream, "seek") and hasattr(stream, "tell")):
        return None
    seekable = getattr(stream, "seekable", None)
    try:
        if callable(seekable) and not seekable():
            return None
        position = stream.tell()
    except (OSError, ValueError):
        return None

    def rewind() -> None:
        stream.seek(position)

    return rewind
