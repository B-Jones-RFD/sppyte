"""Tests for Site: validation, session options, the managed digest, and retries."""

from __future__ import annotations

import io

import pytest
import responses
from requests import HTTPError, Session

from sppyte import AuthError, ConfigurationError, SharePointError, Site
from sppyte.site import _rewinder
from tests.conftest import ANY_URL, BASE, CONTEXTINFO, DIGEST, HOST, SITE_REL, add_contextinfo

WEB = f"{BASE}/_api/web"


# ---------------------------------------------------------- validation ----
def test_normalizes_host_and_relative_url():
    s = Site(f"{HOST}/", "/sites/parrots/", "u", "p")
    assert s.host == HOST
    assert s.relative_url == SITE_REL
    assert s.site_path == BASE


@pytest.mark.parametrize("rel", ["", "/"])
def test_root_site(rel):
    s = Site(HOST, rel, "u", "p")
    assert s.relative_url == ""
    assert s.site_path == HOST


@pytest.mark.parametrize(
    ("host", "rel"),
    [
        ("sp.example.com", SITE_REL),  # no scheme
        ("ftp://sp.example.com", SITE_REL),  # wrong scheme
        (f"{HOST}/sites/parrots", ""),  # path in host
        (HOST, "sites/parrots"),  # no leading slash
        (HOST, BASE),  # full URL as relative
        ("", SITE_REL),
    ],
)
def test_rejects_malformed_location(host, rel):
    with pytest.raises(ConfigurationError):
        Site(host, rel, "u", "p")


def test_configuration_error_is_value_error():
    with pytest.raises(ValueError, match="scheme"):
        Site("sp.example.com", SITE_REL, "u", "p")


def test_rejects_empty_username():
    with pytest.raises(ConfigurationError):
        Site(HOST, SITE_REL, "", "p")


def test_repr_hides_password():
    s = Site(HOST, SITE_REL, "u", "secret")
    assert "secret" not in repr(s)
    assert "u" in repr(s)


# ------------------------------------------------------------- session ----
def test_construction_does_no_io(mocked):
    s = Site(HOST, SITE_REL, "u", "p")
    assert s.session is None
    assert s.form_digest is None
    assert len(mocked.calls) == 0


def test_request_connects_lazily_without_digest(mocked):
    mocked.add(responses.GET, WEB, json={"Title": "Parrots"})
    s = Site(HOST, SITE_REL, "u", "p")
    assert s.request("get", "/_api/web").json()["Title"] == "Parrots"
    assert [c.request.url for c in mocked.calls] == [WEB]
    assert s.form_digest is None


def test_connect_fetches_form_digest(site, mocked):
    assert site.form_digest == DIGEST
    call = mocked.calls[0]
    assert call.request.url == CONTEXTINFO
    assert call.request.headers["Accept"] == "application/json;odata=nometadata"
    assert call.request.headers["Content-Type"] == "application/json;odata=verbose"


def test_context_manager_connects_and_closes(mocked):
    add_contextinfo(mocked)
    with Site(HOST, SITE_REL, "u", "p") as s:
        assert s.session is not None
        assert s.form_digest == DIGEST
    assert s.session is None
    assert s.form_digest is None
    assert len(mocked.calls) == 1


def test_close_keeps_user_session(mocked):
    session = Session()
    s = Site(HOST, SITE_REL, "u", "p", session=session)
    mocked.add(responses.GET, WEB, json={})
    s.request("get", "/_api/web")
    assert s.session is session
    s.close()
    assert s.session is session


def test_ntlm_principal_includes_domain():
    assert Site(HOST, SITE_REL, "jsmith", "p").principal == "jsmith"
    assert Site(HOST, SITE_REL, "jsmith", "p", domain="CONTOSO").principal == "CONTOSO\\jsmith"


def test_session_gets_auth_verify_and_cert(mocked):
    mocked.add(responses.GET, WEB, json={})
    s = Site(HOST, SITE_REL, "u", "p", verify="/etc/corp-ca.pem", cert=("c.pem", "k.pem"))
    s.request("get", "/_api/web")
    assert s.session is not None
    assert s.session.auth is not None
    assert s.session.verify == "/etc/corp-ca.pem"
    assert s.session.cert == ("c.pem", "k.pem")


def test_user_session_auth_is_respected(mocked):
    session = Session()

    def sentinel(prepared):
        return prepared

    session.auth = sentinel
    mocked.add(responses.GET, WEB, json={})
    s = Site(HOST, SITE_REL, "u", "p", session=session)
    s.request("get", "/_api/web")
    assert session.auth is sentinel


def test_default_timeout_is_applied(site, mocked):
    mocked.add(responses.GET, WEB, json={})
    site.request("get", "/_api/web")
    assert mocked.calls[-1].request.req_kwargs["timeout"] == site.timeout
    assert site.timeout == 30.0


def test_timeout_override_per_call(mocked):
    mocked.add(responses.GET, WEB, json={})
    s = Site(HOST, SITE_REL, "u", "p", timeout=(5, 60))
    s.request("get", "/_api/web", timeout=1)
    assert mocked.calls[-1].request.req_kwargs["timeout"] == 1


def test_request_strips_slashes(site, mocked):
    mocked.add(responses.GET, WEB, json={})
    site.request("get", "///_api/web///")
    assert mocked.calls[-1].request.url == WEB


# -------------------------------------------------------------- errors ----
def test_request_raises_sharepoint_error_with_details(site, mocked):
    body = {
        "odata.error": {
            "code": "-1, Microsoft.SharePoint.SPException",
            "message": {"value": "Bad column"},
        }
    }
    mocked.add(responses.GET, WEB, status=400, json=body)
    with pytest.raises(SharePointError) as info:
        site.request("get", "/_api/web")
    e = info.value
    assert e.status == 400
    assert e.code == "-1, Microsoft.SharePoint.SPException"
    assert e.message == "Bad column"
    assert str(e) == "HTTP 400: Bad column"
    assert isinstance(e, HTTPError), "existing except HTTPError handlers keep working"
    assert e.response is not None
    assert e.response.status_code == 400


def test_401_raises_auth_error(site, mocked):
    mocked.add(responses.GET, WEB, status=401)
    with pytest.raises(AuthError) as info:
        site.request("get", "/_api/web")
    assert info.value.status == 401
    assert str(info.value) == "HTTP 401: Unauthorized"


def test_403_on_read_is_not_retried(site, mocked):
    mocked.add(responses.GET, WEB, status=403)
    with pytest.raises(AuthError):
        site.request("get", "/_api/web")
    assert len(mocked.calls) == 2  # contextinfo + the one GET


# -------------------------------------------------------------- digest ----
def test_digest_is_cached(site, mocked):
    assert site.digest() == DIGEST
    assert site.digest() == DIGEST
    assert len(mocked.calls) == 1


def test_digest_refresh_bypasses_cache(site, mocked):
    add_contextinfo(mocked, digest="second")
    assert site.get_form_digest() == "second"
    assert site.form_digest == "second"
    assert len(mocked.calls) == 2


def test_digest_expires_with_margin(mocked, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("sppyte.site.time.monotonic", lambda: clock[0])
    add_contextinfo(mocked, digest="first", timeout=600)
    add_contextinfo(mocked, digest="second", timeout=600)
    s = Site(HOST, SITE_REL, "u", "p")
    assert s.digest() == "first"
    clock[0] += 539  # still inside 600 - 60s margin
    assert s.digest() == "first"
    clock[0] += 2  # past the margin
    assert s.digest() == "second"
    assert len(mocked.calls) == 2


def test_short_digest_lifetime_keeps_half(mocked, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("sppyte.site.time.monotonic", lambda: clock[0])
    add_contextinfo(mocked, digest="a", timeout=20)
    add_contextinfo(mocked, digest="b", timeout=20)
    s = Site(HOST, SITE_REL, "u", "p")
    s.digest()
    clock[0] += 9
    assert s.digest() == "a"
    clock[0] += 2
    assert s.digest() == "b"


def test_digest_defaults_lifetime_when_missing(mocked, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("sppyte.site.time.monotonic", lambda: clock[0])
    mocked.add(responses.POST, CONTEXTINFO, json={"FormDigestValue": "x"})
    mocked.add(responses.POST, CONTEXTINFO, json={"FormDigestValue": "y"})
    s = Site(HOST, SITE_REL, "u", "p")
    assert s.digest() == "x"
    clock[0] = 1800 - 61  # inside the default 30-minute lifetime minus the margin
    assert s.digest() == "x"
    clock[0] = 1800 - 59
    assert s.digest() == "y"


def test_invalidate_digest(site, mocked):
    site.invalidate_digest()
    assert site.form_digest is None
    add_contextinfo(mocked, digest="again")
    assert site.digest() == "again"


def test_write_sends_managed_digest_fetched_at_send_time(mocked):
    add_contextinfo(mocked)
    mocked.add(responses.POST, WEB, json={})
    s = Site(HOST, SITE_REL, "u", "p")
    s.request("post", "/_api/web", digest=True, json={"a": 1})
    assert [c.request.url for c in mocked.calls] == [CONTEXTINFO, WEB]
    assert mocked.calls[-1].request.headers["X-RequestDigest"] == DIGEST


def test_explicit_digest_is_sent_as_is(mocked):
    mocked.add(responses.POST, WEB, json={})
    s = Site(HOST, SITE_REL, "u", "p")
    s.request("post", "/_api/web", digest="mine", json={})
    assert len(mocked.calls) == 1
    assert mocked.calls[-1].request.headers["X-RequestDigest"] == "mine"


def test_explicit_digest_is_not_retried_on_403(mocked):
    mocked.add(responses.POST, WEB, status=403)
    s = Site(HOST, SITE_REL, "u", "p")
    with pytest.raises(AuthError):
        s.request("post", "/_api/web", digest="stale", json={})
    assert len(mocked.calls) == 1


def test_stale_managed_digest_is_refreshed_and_retried_once(site, mocked):
    mocked.add(responses.POST, WEB, status=403)
    add_contextinfo(mocked, digest="fresh")
    mocked.add(responses.POST, WEB, json={"ok": True})
    r = site.request("post", "/_api/web", digest=True, json={"a": 1})
    assert r.json() == {"ok": True}
    calls = mocked.calls[1:]
    assert [c.request.url for c in calls] == [WEB, CONTEXTINFO, WEB]
    assert calls[0].request.headers["X-RequestDigest"] == DIGEST
    assert calls[2].request.headers["X-RequestDigest"] == "fresh", "retry must carry the new digest"
    assert calls[2].request.body == calls[0].request.body


def test_second_403_is_raised(site, mocked):
    mocked.add(responses.POST, WEB, status=403)
    add_contextinfo(mocked, digest="fresh")
    mocked.add(responses.POST, WEB, status=403)
    with pytest.raises(AuthError):
        site.request("post", "/_api/web", digest=True, json={})
    assert len(mocked.calls) == 4


def test_seekable_stream_is_rewound_before_retry(site, mocked):
    mocked.add(responses.POST, WEB, status=403)
    add_contextinfo(mocked, digest="fresh")
    mocked.add(responses.POST, WEB, json={})

    class Spy(io.BytesIO):
        """Records the position of every read so we can see each attempt start."""

        def __init__(self, data: bytes):
            super().__init__(data)
            self.read_positions: list[int] = []

        def read(self, size=-1):
            self.read_positions.append(self.tell())
            return super().read(size)

    fh = Spy(b"payload")
    fh.read(3)  # simulate a partially consumed stream being handed in
    fh.read_positions.clear()
    site.request("post", "/_api/web", digest=True, data=fh)
    posts = [c for c in mocked.calls if c.request.method == "POST" and c.request.url == WEB]
    assert len(posts) == 2
    assert posts[1].request.headers["X-RequestDigest"] == "fresh"
    assert fh.read_positions.count(3) >= 2, "both attempts must read from the original position"


def test_non_seekable_stream_is_not_retried(site, mocked):
    mocked.add(responses.POST, WEB, status=403)

    def chunks():
        yield b"a"
        yield b"b"

    with pytest.raises(AuthError):
        site.request("post", "/_api/web", digest=True, data=chunks())
    assert [c.request.url for c in mocked.calls] == [CONTEXTINFO, WEB]


def test_404_during_write_is_not_retried(site, mocked):
    mocked.add(responses.POST, WEB, status=404)
    with pytest.raises(SharePointError) as info:
        site.request("post", "/_api/web", digest=True, json={})
    assert info.value.status == 404
    assert len(mocked.calls) == 2


@pytest.mark.parametrize("data", [None, "s", b"b", bytearray(b"x"), {"a": 1}, [1], (1,)])
def test_rewinder_accepts_simple_bodies(data):
    assert _rewinder(data) is not None


def test_rewinder_seekable_restores_position():
    fh = io.BytesIO(b"0123456789")
    fh.seek(3)
    rewind = _rewinder(fh)
    assert rewind is not None
    fh.read()
    rewind()
    assert fh.tell() == 3


def test_rewinder_rejects_generator():
    assert _rewinder(iter([b"a"])) is None


# ------------------------------------------------------------ get_page ----
def test_get_page_fetches_link_on_same_host(site, mocked):
    link = f"{BASE}/_api/web/lists/GetByTitle('Pets')/items?%24skiptoken=Paged%3DTRUE%26p_ID%3D100"
    mocked.add(responses.GET, ANY_URL, json={"value": [{"Id": 101}]})
    page = site.get_page(link)
    assert page == [{"Id": 101}]
    assert page.next_link is None
    req = mocked.calls[-1].request
    assert req.url == link
    assert req.headers["Accept"] == "application/json;odata=nometadata"
    assert req.req_kwargs["timeout"] == site.timeout


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example.com/sites/parrots/_api/web/lists",
        "http://sp.example.com/sites/parrots/_api/web/lists",  # scheme differs
        "https://sp.example.com:8443/_api/web/lists",  # port differs
        "/sites/parrots/_api/web/lists",  # relative
    ],
)
def test_get_page_rejects_other_origins(site, mocked, link):
    with pytest.raises(ConfigurationError, match="next_link must be on"):
        site.get_page(link)
    assert len(mocked.calls) == 1  # contextinfo only; nothing was sent


def test_get_page_host_match_is_case_insensitive(site, mocked):
    mocked.add(responses.GET, ANY_URL, json={"value": []})
    site.get_page("HTTPS://SP.EXAMPLE.COM/sites/parrots/_api/web/lists")
    assert len(mocked.calls) == 2
