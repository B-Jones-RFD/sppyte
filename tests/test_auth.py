"""Tests for the pyspnego-based NTLM / Negotiate handshake."""

from __future__ import annotations

import base64
import datetime
import hashlib
import io

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from requests import PreparedRequest, Request, Session
from requests.auth import AuthBase

from sppyte import ConfigurationError, Site, SpPremAuth
from sppyte.auth import _extract_token, _pick_scheme, _rewind_body, certificate_hash
from tests.conftest import BASE, HOST, SITE_REL
from tests.fake_ntlm import MSG_AUTHENTICATE, FakeNtlmAdapter, message_type


def _session(adapter: FakeNtlmAdapter, auth: AuthBase) -> Session:
    s = Session()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.auth = auth
    return s


# ---------------------------------------------------------- construction ----
def test_username_is_qualified_with_domain():
    assert SpPremAuth("jsmith", "pw").username == "jsmith"
    assert SpPremAuth("jsmith", "pw", domain="CONTOSO").username == "CONTOSO\\jsmith"
    assert SpPremAuth("CONTOSO\\jsmith", "pw", domain="OTHER").username == "CONTOSO\\jsmith"
    assert SpPremAuth("jsmith@contoso.local", "pw").username == "jsmith@contoso.local"


def test_ntlm_requires_credentials():
    with pytest.raises(ValueError, match="username and password"):
        SpPremAuth()
    with pytest.raises(ValueError, match="username and password"):
        SpPremAuth("jsmith")


def test_negotiate_allows_sso():
    auth = SpPremAuth(protocol="negotiate")
    assert auth.username is None
    assert auth.password is None
    assert "negotiate" in repr(auth)


def test_rejects_unknown_protocol():
    with pytest.raises(ValueError, match="protocol must be one of"):
        SpPremAuth("u", "p", protocol="basic")


def test_equality_and_repr_hide_password():
    a = SpPremAuth("u", "secret", domain="D")
    assert a == SpPremAuth("u", "secret", domain="D")
    assert a != SpPremAuth("u", "other", domain="D")
    assert "secret" not in repr(a)


# ------------------------------------------------------------- handshake ----
def test_three_leg_handshake_on_one_connection():
    server = FakeNtlmAdapter()
    s = _session(server, SpPremAuth("jsmith", "Passw0rd!", domain="CONTOSO"))
    r = s.get(f"{BASE}/_api/web")

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert [c.headers.get("Authorization", "")[:5] for c in server.calls] == ["", "NTLM ", "NTLM "]
    assert all(c.headers["Connection"] == "Keep-Alive" for c in server.calls)
    assert [h.status_code for h in r.history] == [401, 401]

    token = server.authenticate_token
    assert token is not None
    assert message_type(token) == MSG_AUTHENTICATE
    assert "jsmith".encode("utf-16-le") in token
    assert "CONTOSO".encode("utf-16-le") in token


def test_handshake_picks_ntlm_when_server_offers_both():
    server = FakeNtlmAdapter(schemes="Negotiate, NTLM")
    s = _session(server, SpPremAuth("u", "p"))
    assert s.get(f"{BASE}/_api/web").status_code == 200
    assert len(server.calls) == 3


def test_handshake_forwards_cookie_from_challenge():
    server = FakeNtlmAdapter(set_cookie="WSS_FullScreenMode=false; path=/")
    s = _session(server, SpPremAuth("u", "p"))
    s.get(f"{BASE}/_api/web")
    assert server.calls[2].headers["Cookie"] == "WSS_FullScreenMode=false; path=/"


def test_handshake_rewinds_file_body():
    server = FakeNtlmAdapter()
    s = _session(server, SpPremAuth("u", "p"))
    body = io.BytesIO(b"payload")
    body.read()  # as if the first attempt had streamed it to the server
    r = s.post(f"{BASE}/_api/web/folders", data=body, headers={"Content-Length": "7"})
    assert r.status_code == 200
    assert server.calls[2].body is body
    assert body.tell() == 0, "body is rewound before the authenticated legs"


def test_401_without_ntlm_offer_is_passed_through():
    server = FakeNtlmAdapter(schemes="Basic realm=x")
    s = _session(server, SpPremAuth("u", "p"))
    r = s.get(f"{BASE}/_api/web")
    assert r.status_code == 401
    assert len(server.calls) == 1


def test_no_second_attempt_when_already_authorized():
    server = FakeNtlmAdapter(schemes="NTLM")
    s = _session(server, SpPremAuth("u", "p"))
    bogus = base64.b64encode(b"not an NTLM token").decode()
    r = s.get(f"{BASE}/_api/web", headers={"Authorization": f"NTLM {bogus}"})
    assert r.status_code == 401
    assert len(server.calls) == 1


# --------------------------------------------------------------- helpers ----
def test_pick_scheme():
    assert _pick_scheme("NTLM", "ntlm") == "NTLM"
    assert _pick_scheme("Negotiate, NTLM", "ntlm") == "NTLM"
    assert _pick_scheme("Negotiate, NTLM", "negotiate") == "Negotiate"
    assert _pick_scheme("negotiate", "kerberos") == "Negotiate"
    assert _pick_scheme("Basic realm=x", "ntlm") is None
    assert _pick_scheme("", "ntlm") is None


def test_extract_token():
    token = base64.b64encode(b"abc").decode()
    assert _extract_token(f"NTLM {token}", "NTLM") == b"abc"
    assert _extract_token(f"Negotiate x, NTLM {token}", "NTLM") == b"abc"
    assert _extract_token(f"ntlm {token}", "NTLM") == b"abc"
    assert _extract_token("NTLM", "NTLM") is None
    assert _extract_token("Basic xyz", "NTLM") is None


def test_rewind_body_seeks_back_by_content_length():
    body = io.BytesIO(b"0123456789")
    body.read()  # consumed
    req = Request("POST", f"{BASE}/x", data=body, headers={"Content-Length": "10"}).prepare()
    _rewind_body(req)
    assert body.tell() == 0


def test_rewind_body_without_length_seeks_to_start():
    body = io.BytesIO(b"abc")
    body.read()
    req = PreparedRequest()
    req.prepare(method="POST", url=f"{BASE}/x", data=body)
    req.headers.pop("Content-Length", None)
    _rewind_body(req)
    assert body.tell() == 0


def test_rewind_body_ignores_bytes():
    req = Request("POST", f"{BASE}/x", data=b"abc").prepare()
    _rewind_body(req)  # no exception


def _self_signed_der(algorithm: hashes.SHA256 | hashes.SHA384) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sp.example.com")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, algorithm)
    )
    return cert.public_bytes(serialization.Encoding.DER)


def test_certificate_hash_uses_signature_algorithm():
    der = _self_signed_der(hashes.SHA256())
    assert certificate_hash(der) == hashlib.sha256(der).digest()
    der384 = _self_signed_der(hashes.SHA384())
    assert certificate_hash(der384) == hashlib.sha384(der384).digest()


# ------------------------------------------------------------- via Site ----
def test_site_authenticates_through_fake_server():
    server = FakeNtlmAdapter(body=b'{"Title": "Parrots"}')
    session = Session()
    session.mount("https://", server)
    site = Site(HOST, SITE_REL, "jsmith", "pw", domain="CONTOSO", session=session)
    assert site.request("get", "_api/web").json() == {"Title": "Parrots"}
    assert len(server.calls) == 3
    assert isinstance(site.auth, SpPremAuth)
    assert site.principal == "CONTOSO\\jsmith"


def test_site_negotiate_sso_needs_no_credentials():
    site = Site(HOST, SITE_REL, protocol="negotiate")
    assert isinstance(site.auth, SpPremAuth)
    assert site.auth.protocol == "negotiate"
    assert site.principal is None


def test_site_ntlm_requires_credentials():
    with pytest.raises(ConfigurationError, match="single sign-on"):
        Site(HOST, SITE_REL)
    with pytest.raises(ConfigurationError, match="password"):
        Site(HOST, SITE_REL, "jsmith")


def test_site_accepts_custom_auth():
    class Marker(AuthBase):
        def __call__(self, r):
            return r

    marker = Marker()
    site = Site(HOST, SITE_REL, auth=marker)
    assert site.auth is marker
    assert site.principal is None
    assert site._ensure_session().auth is marker  # noqa: SLF001
