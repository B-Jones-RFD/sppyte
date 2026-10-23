"""Tests for opt-in retry of transient read failures."""

from __future__ import annotations

import pytest
import responses
from requests import ConnectionError as RequestsConnectionError
from requests import Response, Timeout

from sppyte import AuthError, RetryOptions, SharePointError, Site, is_transient
from sppyte.retry import with_retry
from tests.conftest import ANY_URL, BASE, CONTEXTINFO, HOST, SITE_REL, add_contextinfo

WEB = f"{BASE}/_api/web"
LIST_ITEMS = f"{BASE}/_api/web/lists/GetByTitle('Pets')/items"


@pytest.fixture
def sleeps(monkeypatch):
    """Record sleeps instead of waiting, and make jitter deterministic (always the cap)."""
    waits: list[float] = []
    monkeypatch.setattr("sppyte.retry.time.sleep", waits.append)
    monkeypatch.setattr("sppyte.retry._random.uniform", lambda _a, b: b)
    return waits


def _sp_error(status: int, headers: dict | None = None) -> SharePointError:
    r = Response()
    r.status_code = status
    r.headers.update(headers or {})
    return SharePointError(r)


# --------------------------------------------------------- is_transient ----
@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_is_transient_statuses(status):
    assert is_transient(_sp_error(status)) is True


@pytest.mark.parametrize("status", [400, 404, 500, 501])
def test_is_not_transient_statuses(status):
    assert is_transient(_sp_error(status)) is False


def test_is_transient_transport_errors():
    assert is_transient(RequestsConnectionError("boom")) is True
    assert is_transient(Timeout("slow")) is True
    assert is_transient(ValueError("x")) is False
    assert is_transient(_sp_error(401)) is False


# ----------------------------------------------------------- with_retry ----
def test_with_retry_none_runs_once():
    calls = []

    def attempt():
        calls.append(1)
        return "ok"

    assert with_retry(None, attempt) == "ok"
    assert calls == [1]


def test_with_retry_backoff_and_jitter(sleeps):
    outcomes = iter([Timeout(), Timeout(), "ok"])

    def attempt():
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o

    assert with_retry(RetryOptions(retries=3, base_delay=0.5, max_delay=10), attempt) == "ok"
    assert sleeps == [0.5, 1.0]  # caps for attempts 1 and 2 (jitter patched to the cap)


def test_with_retry_caps_delay(sleeps):
    outcomes = iter([Timeout(), Timeout(), Timeout(), "ok"])

    def attempt():
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o

    with_retry(RetryOptions(retries=3, base_delay=1, max_delay=1.5), attempt)
    assert sleeps == [1, 1.5, 1.5]


def test_with_retry_gives_up_and_reraises_last(sleeps):
    msg = "still slow"

    def attempt():
        raise Timeout(msg)

    with pytest.raises(Timeout, match=msg):
        with_retry(RetryOptions(retries=2), attempt)
    assert len(sleeps) == 2


def test_with_retry_honours_retry_after(sleeps):
    outcomes = iter([_sp_error(429, {"Retry-After": "3"}), "ok"])

    def attempt():
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o

    with_retry(RetryOptions(), attempt)
    assert sleeps == [3.0]


def test_with_retry_stops_when_retry_after_exceeds_max(sleeps):
    def attempt():
        raise _sp_error(503, {"Retry-After": "120"})

    with pytest.raises(SharePointError) as info:
        with_retry(RetryOptions(max_delay=5), attempt)
    assert info.value.retry_after == 120.0
    assert sleeps == []


def test_with_retry_custom_predicate(sleeps):
    seen = []

    def retry_on(exc, n):
        seen.append((type(exc).__name__, n))
        return isinstance(exc, KeyError)

    outcomes = iter([KeyError("a"), ValueError("stop")])

    def attempt():
        raise next(outcomes)

    with pytest.raises(ValueError, match="stop"):
        with_retry(RetryOptions(retries=5, retry_on=retry_on), attempt)
    assert seen == [("KeyError", 1), ("ValueError", 2)]
    assert len(sleeps) == 1


def test_with_retry_zero_retries():
    def attempt():
        raise Timeout

    with pytest.raises(Timeout):
        with_retry(RetryOptions(retries=0), attempt)


# ------------------------------------------------------------- via Site ----
def test_site_retry_option_shapes():
    assert Site(HOST, SITE_REL, "u", "p").retry is None
    assert Site(HOST, SITE_REL, "u", "p", retry=False).retry is None
    assert Site(HOST, SITE_REL, "u", "p", retry=True).retry == RetryOptions()
    opts = RetryOptions(retries=5)
    assert Site(HOST, SITE_REL, "u", "p", retry=opts).retry is opts


def test_reads_are_retried(mocked, sleeps):
    mocked.add(responses.GET, WEB, status=503)
    mocked.add(responses.GET, WEB, status=502)
    mocked.add(responses.GET, WEB, json={"ok": True})
    s = Site(HOST, SITE_REL, "u", "p", retry=True)
    assert s.request("get", "/_api/web").json() == {"ok": True}
    assert len(mocked.calls) == 3
    assert len(sleeps) == 2


def test_reads_not_retried_without_option(mocked, sleeps):
    mocked.add(responses.GET, WEB, status=503)
    mocked.add(responses.GET, WEB, json={})
    s = Site(HOST, SITE_REL, "u", "p")
    with pytest.raises(SharePointError):
        s.request("get", "/_api/web")
    assert len(mocked.calls) == 1
    assert sleeps == []


def test_connection_errors_are_retried(mocked, sleeps):
    mocked.add(responses.GET, WEB, body=RequestsConnectionError("reset"))
    mocked.add(responses.GET, WEB, json={"ok": 1})
    s = Site(HOST, SITE_REL, "u", "p", retry=True)
    assert s.request("get", "/_api/web").json() == {"ok": 1}
    assert len(sleeps) == 1


def test_writes_are_never_retried(mocked, sleeps):
    add_contextinfo(mocked)
    mocked.add(responses.POST, WEB, status=503)
    mocked.add(responses.POST, WEB, json={})
    s = Site(HOST, SITE_REL, "u", "p", retry=True)
    with pytest.raises(SharePointError):
        s.request("post", "/_api/web", digest=True, json={})
    assert [c.request.url for c in mocked.calls] == [CONTEXTINFO, WEB]
    assert sleeps == []


def test_auth_errors_are_not_retried(mocked, sleeps):
    mocked.add(responses.GET, WEB, status=401)
    s = Site(HOST, SITE_REL, "u", "p", retry=True)
    with pytest.raises(AuthError):
        s.request("get", "/_api/web")
    assert len(mocked.calls) == 1
    assert sleeps == []


def test_retry_can_be_forced_off_per_call(mocked, sleeps):
    mocked.add(responses.GET, WEB, status=503)
    s = Site(HOST, SITE_REL, "u", "p", retry=True)
    with pytest.raises(SharePointError):
        s.request("get", "/_api/web", retry=False)
    assert len(mocked.calls) == 1
    assert sleeps == []


def test_caml_query_is_retried(mocked, sleeps):
    add_contextinfo(mocked)
    mocked.add(responses.POST, ANY_URL, status=429, headers={"Retry-After": "1"})
    mocked.add(responses.POST, ANY_URL, json={"value": [{"Id": 1}]})
    s = Site(HOST, SITE_REL, "u", "p", retry=True)
    assert s.list("Pets").query("<View/>") == [{"Id": 1}]
    assert sleeps == [1.0]
    posts = [c for c in mocked.calls if c.request.url.endswith("/GetItems")]
    assert len(posts) == 2
    assert posts[1].request.body == posts[0].request.body


def test_get_page_is_retried(mocked, sleeps):
    link = f"{LIST_ITEMS}?%24skiptoken=x"
    mocked.add(responses.GET, ANY_URL, status=504)
    mocked.add(responses.GET, ANY_URL, json={"value": [{"Id": 2}]})
    s = Site(HOST, SITE_REL, "u", "p", retry=True)
    assert s.get_page(link) == [{"Id": 2}]
    assert len(sleeps) == 1


def test_list_reads_are_retried_through_helpers(mocked, sleeps):
    mocked.add(responses.GET, ANY_URL, status=503)
    mocked.add(responses.GET, ANY_URL, json={"value": [{"Id": 1}]})
    s = Site(HOST, SITE_REL, "u", "p", retry=RetryOptions(retries=1))
    assert s.list("Pets").get_contents() == [{"Id": 1}]
    assert len(sleeps) == 1


def test_retry_exhausted_raises_last_error(mocked, sleeps):
    mocked.add(responses.GET, WEB, status=503)
    mocked.add(responses.GET, WEB, status=502)
    mocked.add(responses.GET, WEB, status=504)
    s = Site(HOST, SITE_REL, "u", "p", retry=RetryOptions(retries=2))
    with pytest.raises(SharePointError) as info:
        s.request("get", "/_api/web")
    assert info.value.status == 504
    assert len(mocked.calls) == 3
    assert len(sleeps) == 2
