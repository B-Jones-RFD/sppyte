from __future__ import annotations

import importlib
import warnings
from datetime import UTC, datetime

import pytest
from requests import HTTPError

import sppyte
import sppyte.errors
from sppyte import AuthError, SharePointError, SppyteError
from sppyte.errors import (
    SharePointErrorDetails,
    parse_retry_after,
    parse_sharepoint_error,
    raise_for_status,
)
from tests.conftest import make_response

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
    now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("Fri, 23 Oct 2026 12:00:30 GMT", now=now) == 30.0


def test_parse_retry_after_past_date_is_zero():
    now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("Fri, 23 Oct 2026 11:00:00 GMT", now=now) == 0.0


class _FixedDatetime(datetime):
    """A `datetime` whose `now()` is pinned, so the default-clock path never reads the real clock."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 23, 12, 0, 0, tzinfo=tz)


def test_parse_retry_after_uses_current_time(monkeypatch):
    monkeypatch.setattr("sppyte.errors.datetime", _FixedDatetime)
    assert parse_retry_after("Fri, 23 Oct 2026 12:00:30 GMT") == 30.0


def test_parse_retry_after_naive_date_is_utc():
    now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("Fri, 23 Oct 2026 12:00:30 -0000", now=now) == 30.0
    assert parse_retry_after("Fri, 23 Oct 2026 12:00:30 GMT", now=now) == 30.0


@pytest.mark.parametrize("value", [None, "", "soon", "-5", "1.5"])
def test_parse_retry_after_invalid(value):
    assert parse_retry_after(value) is None


# -------------------------------------------------------- SharePointError ----
def test_sharepoint_error_fields_and_hierarchy():
    body = '{"odata.error": {"code": "c", "message": {"value": "Busy"}}}'
    r = make_response(503, body, {"Retry-After": "7"})
    e = SharePointError(r)
    assert e.status == 503
    assert e.code == "c"
    assert e.message == "Busy"
    assert e.retry_after == 7.0
    assert e.response is r
    assert str(e) == "HTTP 503: Busy"
    assert isinstance(e, SppyteError)
    assert isinstance(e, HTTPError)


def test_sharepoint_error_retry_after_http_date(monkeypatch):
    monkeypatch.setattr("sppyte.errors.datetime", _FixedDatetime)
    e = SharePointError(make_response(503, headers={"Retry-After": "Fri, 23 Oct 2026 12:00:30 GMT"}))
    assert e.retry_after == 30.0


def test_sharepoint_error_falls_back_to_reason_then_body():
    assert str(SharePointError(make_response(500, "", reason="Server Error"))) == "HTTP 500: Server Error"
    assert str(SharePointError(make_response(500, "<html>oops</html>"))) == "HTTP 500: <html>oops</html>"
    assert str(SharePointError(make_response(500))) == "HTTP 500"


def test_raise_for_status():
    raise_for_status(make_response(200))
    raise_for_status(make_response(204))
    with pytest.raises(AuthError):
        raise_for_status(make_response(401))
    with pytest.raises(AuthError):
        raise_for_status(make_response(403))
    with pytest.raises(SharePointError) as info:
        raise_for_status(make_response(500))
    assert not isinstance(info.value, AuthError)


# --------------------------------------------------- SessionError (deprecated) ----
def test_session_error_warns_from_package():
    with pytest.warns(DeprecationWarning, match="sppyte 2.0"):
        cls = sppyte.SessionError
    assert cls.__name__ == "SessionError"
    assert issubclass(cls, SppyteError)


def test_session_error_warns_from_errors_module():
    with pytest.warns(DeprecationWarning, match="sppyte 2.0"):
        cls = sppyte.errors.SessionError
    with pytest.warns(DeprecationWarning, match="sppyte 2.0"):
        assert cls is sppyte.SessionError


def test_session_error_from_import_warns():
    with pytest.warns(DeprecationWarning, match="sppyte 2.0"):
        from sppyte import SessionError
    assert issubclass(SessionError, SppyteError)


def test_session_error_still_catchable():
    with pytest.warns(DeprecationWarning, match="sppyte 2.0"):
        expected = sppyte.SessionError
        error = sppyte.errors.SessionError("no session")
    with pytest.raises(expected):
        raise error


def test_unknown_attribute_raises():
    with pytest.raises(AttributeError, match="no attribute 'Nope'"):
        _ = sppyte.Nope
    with pytest.raises(AttributeError, match="no attribute 'Nope'"):
        _ = sppyte.errors.Nope


def test_import_sppyte_does_not_warn():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(sppyte)
    assert [w for w in caught if issubclass(w.category, DeprecationWarning)] == []
