from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from requests import HTTPError, Response

from sppyte import AuthError, SharePointError, SppyteError
from sppyte.errors import (
    SharePointErrorDetails,
    parse_retry_after,
    parse_sharepoint_error,
    raise_for_status,
)


def _response(status: int, body: str = "", headers: dict | None = None, reason: str = "") -> Response:
    r = Response()
    r.status_code = status
    r.reason = reason
    r.raw = io.BytesIO(body.encode())
    r.encoding = "utf-8"
    r.headers.update(headers or {})
    return r


# ------------------------------------------------- parse_sharepoint_error ----
NOMETA = '{"odata.error": {"code": "-1, X", "message": {"lang": "en-US", "value": "Boom"}}}'
VERBOSE = '{"error": {"code": "-1, X", "message": {"value": "Boom"}}}'


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (NOMETA, SharePointErrorDetails("-1, X", "Boom")),
        (VERBOSE, SharePointErrorDetails("-1, X", "Boom")),
        ('{"error": {"code": "-1, X", "message": "plain"}}', SharePointErrorDetails("-1, X", "plain")),
        ('{"odata.error": {"message": {"value": "no code"}}}', SharePointErrorDetails(None, "no code")),
        ('{"error": {"code": 5}}', SharePointErrorDetails(None, None)),
    ],
)
def test_parse_sharepoint_error(body, expected):
    assert parse_sharepoint_error(body) == expected


@pytest.mark.parametrize("body", ["", "not json", "[]", "42", '{"other": 1}', '{"error": "str"}', None, b"x"])
def test_parse_sharepoint_error_returns_none(body):
    assert parse_sharepoint_error(body) is None


# ------------------------------------------------------- parse_retry_after ----
def test_parse_retry_after_seconds():
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after(" 0 ") == 0.0


def test_parse_retry_after_http_date():
    now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after("Fri, 23 Oct 2026 12:00:30 GMT", now=now) == 30.0


def test_parse_retry_after_past_date_is_zero():
    now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after("Fri, 23 Oct 2026 11:00:00 GMT", now=now) == 0.0


@pytest.mark.parametrize("value", [None, "", "soon", "-5", "1.5"])
def test_parse_retry_after_invalid(value):
    assert parse_retry_after(value) is None


# -------------------------------------------------------- SharePointError ----
def test_sharepoint_error_fields_and_hierarchy():
    body = '{"odata.error": {"code": "c", "message": {"value": "Busy"}}}'
    r = _response(503, body, {"Retry-After": "7"})
    e = SharePointError(r)
    assert e.status == 503
    assert e.code == "c"
    assert e.message == "Busy"
    assert e.retry_after == 7.0
    assert e.response is r
    assert str(e) == "HTTP 503: Busy"
    assert isinstance(e, SppyteError)
    assert isinstance(e, HTTPError)


def test_sharepoint_error_falls_back_to_reason_then_body():
    assert str(SharePointError(_response(500, "", reason="Server Error"))) == "HTTP 500: Server Error"
    assert str(SharePointError(_response(500, "<html>oops</html>"))) == "HTTP 500: <html>oops</html>"
    assert str(SharePointError(_response(500))) == "HTTP 500"


def test_raise_for_status():
    raise_for_status(_response(200))
    raise_for_status(_response(204))
    with pytest.raises(AuthError):
        raise_for_status(_response(401))
    with pytest.raises(AuthError):
        raise_for_status(_response(403))
    with pytest.raises(SharePointError) as info:
        raise_for_status(_response(500))
    assert not isinstance(info.value, AuthError)
