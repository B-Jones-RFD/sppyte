"""`Site`: the NTLM session and managed request digest for one SharePoint site."""

from __future__ import annotations

import re
import threading
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from requests import Response, Session
from requests_ntlm import HttpNtlmAuth

from sppyte.batch import Batch
from sppyte.errors import FORBIDDEN, AuthError, ConfigurationError, raise_for_status
from sppyte.libraries import Library
from sppyte.lists import List
from sppyte.odata import JSON_NOMETADATA, JSON_VERBOSE, Page, parse_page
from sppyte.retry import RetryOptions, with_retry
from sppyte.utils import parse_context_info

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

DIGEST_REFRESH_MARGIN = 60.0
"""Refresh the digest this many seconds before SharePoint says it expires."""

DEFAULT_TIMEOUT = 30.0
"""Default per-request timeout in seconds (connect and read)."""

Timeout = float | tuple[float, float] | None
"""A `requests` timeout: seconds, a `(connect, read)` pair, or `None` for no timeout."""

_HOST_RE = re.compile(r"^https?://[^/\s?#]+/?$", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


class Site:
    """A connection to one SharePoint site.

    - Lazily establishes an NTLM-authenticated `requests.Session` on first use.
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
        username: Account name without the domain.
        password: Password for `username`.
        domain: NTLM (NetBIOS) domain, e.g. `"CONTOSO"`. Omit for a local account or when
            `username` already contains a domain.
        timeout: Per-request timeout in seconds, or a `(connect, read)` tuple. `None`
            disables the timeout (not recommended).
        verify: TLS verification; `False` to disable, or a path to a CA bundle for an
            internal certificate authority. Forwarded to `requests.Session.verify`.
        cert: Client certificate (path or `(cert, key)` tuple). Forwarded to
            `requests.Session.cert`.
        session: Pre-configured `requests.Session` to use instead of creating one. sppyte
            sets NTLM auth on it only if it has no `auth`, and does not close it.
        retry: Retry transient failures on reads (`GET` requests and CAML queries).
            `True` for the defaults, a `RetryOptions` to tune, `None` (default) for off.
            Writes are never retried. See `sppyte.retry`.

    Raises:
        ConfigurationError: if `host`, `site_relative_url` or the credentials are malformed.
    """

    def __init__(
        self,
        host: str,
        site_relative_url: str,
        username: str,
        password: str,
        *,
        domain: str | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
        verify: bool | str | None = None,
        cert: str | tuple[str, str] | None = None,
        session: Session | None = None,
        retry: RetryOptions | bool | None = None,
    ):
        self.host = _validate_host(host)
        self.relative_url = _validate_relative_url(site_relative_url)
        if not isinstance(username, str) or not username:
            msg = "username must be a non-empty string"
            raise ConfigurationError(msg)
        if not isinstance(password, str):
            msg = "password must be a string"
            raise ConfigurationError(msg)

        self.site_path = f"{self.host}{self.relative_url}"
        self.username = username
        self.password = password
        self.domain = domain
        self.timeout = timeout
        self.verify = verify
        self.cert = cert
        self.retry: RetryOptions | None
        if retry is True:
            self.retry = RetryOptions()
        elif isinstance(retry, RetryOptions):
            self.retry = retry
        else:
            self.retry = None

        self.session: Session | None = session
        self._owns_session = session is None

        self._digest: str | None = None
        self._digest_expires_at = 0.0
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return f"Site({self.site_path!r}, username={self.username!r})"

    def __enter__(self) -> Site:  # noqa: PYI034 - typing.Self needs 3.11+
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
    def principal(self) -> str:
        r"""The NTLM account name: `DOMAIN\user` when a domain was given, else `username`."""
        return f"{self.domain}\\{self.username}" if self.domain else self.username

    def _ensure_session(self) -> Session:
        """Return the session, creating and configuring it on first use."""
        if self.session is None:
            self.session = Session()
            self._owns_session = True
        session = self.session
        if session.auth is None:
            session.auth = HttpNtlmAuth(self.principal, self.password)
        if self.verify is not None:
            session.verify = self.verify
        if self.cert is not None:
            session.cert = self.cert
        return session

    def connect(self) -> None:
        """Create the NTLM-authenticated session and fetch a form digest eagerly."""
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
            info = parse_context_info(r.json())
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
        """Fetch a fresh form digest from `/_api/contextinfo`, bypassing the cache."""
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
                be re-sent (bytes, str, JSON, or a seekable file). A `str` sends
                that digest as-is with no retry. `None` / `False` sends none.
            retry: Whether the Site's `retry` policy applies to this call. Defaults
                to `True` for `GET` without a digest (reads) and `False` otherwise.
                Has no effect unless the Site was created with `retry`.
            **kwargs: Passed to `requests.Session.request` (`params`, `headers`,
                `json`, `data`, `stream`, `timeout`, ...).

        Returns:
            The `requests.Response`.

        Raises:
            AuthError: on 401/403.
            SharePointError: on any other 4xx/5xx.
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

        rewind = _rewinder(kwargs.get("data"))
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

        Raises:
            ConfigurationError: if the link is not on this site's host, so
                credentials are never sent elsewhere.
        """
        wanted = urlsplit(self.host)
        got = urlsplit(next_link)
        if (got.scheme.lower(), got.netloc.lower()) != (wanted.scheme.lower(), wanted.netloc.lower()):
            msg = f"next_link must be on {self.host} (got {next_link!r})"
            raise ConfigurationError(msg)
        kwargs.setdefault("timeout", self.timeout)
        headers = {"Accept": JSON_NOMETADATA, **(kwargs.pop("headers", None) or {})}
        r = with_retry(self.retry, lambda: self._send("get", next_link, headers=headers, **kwargs))
        return parse_page(r.json())

    # ----------------------------------------------------------- helpers ----
    def list(self, name: str) -> List:
        """Return a `List` bound to this site; performs no network I/O.

        Args:
            name: The list title as shown in SharePoint.
        """
        return List(name, self)

    def library(self, name: str) -> Library:
        """Return a `Library` bound to this site; performs no network I/O.

        Args:
            name: The library name as it appears in its URL, e.g. `"Shared Documents"`.
        """
        return Library(name, self)

    def batch(self) -> Batch:
        """Return an empty `Batch` to send several requests in one round trip.

        Requires SharePoint 2016 or later. See `sppyte.batch`.
        """
        return Batch(self)


# ------------------------------------------------------------- validation ----
def _validate_host(host: str) -> str:
    """Check `host` is scheme + host name only and return it without a trailing slash."""
    if not isinstance(host, str) or not host:
        msg = "host must be a non-empty string such as 'https://sharepoint.example.com'"
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
        msg = "site_relative_url must be a string"
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


def _rewinder(data: Any) -> Callable[[], None] | None:
    """Return a callable that rewinds `data` so it can be sent again.

    Returns `None` if the body cannot be re-sent (a non-seekable stream or a
    generator).
    """
    if data is None or isinstance(data, str | bytes | bytearray | dict | list | tuple):
        return lambda: None
    if hasattr(data, "seek") and hasattr(data, "tell"):
        try:
            position = data.tell()
        except (OSError, ValueError):
            return None

        def rewind() -> None:
            data.seek(position)

        return rewind
    return None
