"""Exceptions raised by sppyte.

Hierarchy:

    SppyteError
    ├── ConfigurationError  (also a ValueError)
    ├── SessionError        (deprecated, removed in 2.0; no longer raised)
    ├── ResponseFormatError
    └── SharePointError     (also a requests.HTTPError)
        └── AuthError

`SharePointError` carries the parsed SharePoint error body, so a failed call
reads `HTTP 400: Column 'Foo' does not exist` instead of
`400 Client Error: Bad Request for url: ...`. Because it subclasses
`requests.HTTPError`, existing `except HTTPError` handlers keep working.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any

from requests import HTTPError, Response

UNAUTHORIZED = 401
FORBIDDEN = 403
HTTP_ERROR_MIN = 400


class SppyteError(Exception):
    """Base class for every sppyte exception."""


class ConfigurationError(SppyteError, ValueError):
    """Raised for a malformed option or argument, or a link to another host.

    For example a bad `Site` option, conflicting `Batch.add` arguments, or a
    `next_link` that is not on the site's host.
    """


class _SessionError(SppyteError):
    """Deprecated; kept for compatibility with 0.x and no longer raised. Removed in 2.0.

    Sessions are now created on demand. Reach it as `SessionError`; access
    emits a `DeprecationWarning`.
    """


_SessionError.__name__ = _SessionError.__qualname__ = "SessionError"

_SESSION_ERROR_DEPRECATED = "SessionError is deprecated and will be removed in sppyte 2.0; it is no longer raised"

if TYPE_CHECKING:
    SessionError = _SessionError


def __getattr__(name: str) -> Any:
    """Warn on access to deprecated names.

    Args:
        name: The attribute being looked up on the module.

    Returns:
        `SessionError`, after emitting a `DeprecationWarning`.

    Raises:
        AttributeError: for any other name.
    """
    if name == "SessionError":
        warnings.warn(_SESSION_ERROR_DEPRECATED, DeprecationWarning, stacklevel=2)
        return _SessionError
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


class ResponseFormatError(SppyteError):
    """Raised when a 2xx response body is not JSON, is not in the expected shape, or lacks an expected field."""


@dataclass(frozen=True)
class SharePointErrorDetails:
    """The `error` object SharePoint returns in a failed response body."""

    code: str | None = None
    """SharePoint error code, e.g. `-2130575338, Microsoft.SharePoint.SPException`."""
    message: str | None = None
    """Human-readable message from SharePoint."""


class SharePointError(SppyteError, HTTPError):
    """Raised when SharePoint answers with a non-2xx status.

    Attributes:
        status: HTTP status code.
        code: SharePoint error code from the response body, if present.
        message: SharePoint error message from the response body, if present.
        retry_after: Seconds the server asked clients to wait (`Retry-After`), if sent.
        response: The underlying `requests.Response` (inherited from `HTTPError`).

    Args:
        response: The failed response; its body, status and `Retry-After` header fill the attributes.
    """

    status: int
    code: str | None
    message: str | None
    retry_after: float | None

    def __init__(self, response: Response):
        details = parse_sharepoint_error(response.text)
        self.status = response.status_code
        self.code = details.code if details else None
        self.message = details.message if details else None
        self.retry_after = parse_retry_after(response.headers.get("Retry-After"))

        summary = self.message or response.reason or response.text[:200]
        text = f"HTTP {self.status}: {summary}" if summary else f"HTTP {self.status}"
        super().__init__(text, response=response, request=response.request)


class AuthError(SharePointError):
    """Raised for 401/403: bad credentials, a rejected handshake, or an expired/missing request digest."""


def raise_for_status(response: Response) -> None:
    """Raise `AuthError` for 401/403 and `SharePointError` for any other 4xx/5xx.

    Args:
        response: The response to check; a status below 400 returns without raising.

    Raises:
        AuthError: on 401/403.
        SharePointError: on any other 4xx/5xx.
    """
    if response.status_code < HTTP_ERROR_MIN:
        return
    if response.status_code in (UNAUTHORIZED, FORBIDDEN):
        raise AuthError(response)
    raise SharePointError(response)


def parse_sharepoint_error(body: Any) -> SharePointErrorDetails | None:
    """Extract SharePoint's error object from a response body.

    Handles both the `odata=verbose` shape
    (`{"error": {"code": ..., "message": {"value": ...}}}`) and the
    `odata=nometadata` / `minimalmetadata` shape (`{"odata.error": ...}`).

    Args:
        body: The raw response text; anything other than a non-empty string yields `None`.

    Returns:
        The parsed details, or `None` when the body is not a SharePoint error.
    """
    if not isinstance(body, str) or not body:
        return None
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    err = parsed.get("odata.error", parsed.get("error"))
    if not isinstance(err, dict):
        return None

    code = err.get("code")
    message: Any = err.get("message")
    if isinstance(message, dict):
        message = message.get("value")
    return SharePointErrorDetails(
        code=code if isinstance(code, str) else None,
        message=message if isinstance(message, str) else None,
    )


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Parse a `Retry-After` header given as delay-seconds or an HTTP date.

    Args:
        value: The raw header value, or `None` if absent.
        now: Reference time for HTTP dates; defaults to the current UTC time.

    Returns:
        Seconds to wait (never negative), or `None` when absent or invalid.
    """
    if value is None:
        return None
    text = value.strip()
    if text.isdigit():
        return float(text)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    return max(0.0, (when - now).total_seconds())
