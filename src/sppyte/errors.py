"""Exceptions raised by sppyte.

Hierarchy:

    SppyteError
    ├── ConfigurationError  (also a ValueError)
    ├── SessionError        (kept for compatibility; no longer raised)
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
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from requests import HTTPError, Response

UNAUTHORIZED = 401
FORBIDDEN = 403
HTTP_ERROR_MIN = 400


class SppyteError(Exception):
    """Base class for every sppyte exception."""


class ConfigurationError(SppyteError, ValueError):
    """Raised when `Site` is constructed with malformed options."""


class SessionError(SppyteError):
    """Raised when an HTTP session is not available.

    Kept for compatibility with 0.x; sessions are now created on demand, so
    this is no longer raised.
    """


class ResponseFormatError(SppyteError):
    """Raised when an expected field is missing from a SharePoint JSON payload."""


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
    """Raised for 401/403: bad credentials, NTLM rejected, or an expired/missing request digest."""


def raise_for_status(response: Response) -> None:
    """Raise `AuthError` for 401/403 and `SharePointError` for any other 4xx/5xx."""
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
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0.0, (when - now).total_seconds())
