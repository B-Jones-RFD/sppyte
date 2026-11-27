"""The in-process fake servers, implemented as `requests` transport adapters.

`FakeNtlmAdapter` speaks just enough NTLM to drive the client through the three-leg handshake:
a bare request gets 401 + `WWW-Authenticate: NTLM`; a Type 1 (NEGOTIATE) token
gets 401 + a canned Type 2 (CHALLENGE); a Type 3 (AUTHENTICATE) token is
accepted without verification and answered with 200. Every request is recorded.

Options turn the fake into a server that rejects the credentials (`accept=False`)
or answers the opening token without a challenge token (`challenge=False`) or with a
challenge of its choosing (`challenge_header=`), such as one that is not base64 or not NTLM.
`FakeNegotiateAdapter` plays a Kerberos server that accepts the first token,
`FakeProxyAdapter` an NTLM-authenticating proxy, and `RedirectAdapter` a server
that redirects every request elsewhere.
"""

from __future__ import annotations

import base64
import binascii
import io
import struct
from typing import Any

from requests import PreparedRequest, Response
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

NEGOTIATE_UNICODE = 0x00000001
REQUEST_TARGET = 0x00000004
NEGOTIATE_NTLM = 0x00000200
NEGOTIATE_ALWAYS_SIGN = 0x00008000
TARGET_TYPE_SERVER = 0x00020000
NEGOTIATE_EXTENDED_SESSIONSECURITY = 0x00080000
NEGOTIATE_TARGET_INFO = 0x00800000
NEGOTIATE_128 = 0x20000000
NEGOTIATE_56 = 0x80000000

MSG_NEGOTIATE = 1
MSG_CHALLENGE = 2
MSG_AUTHENTICATE = 3

SERVER_CHALLENGE = bytes.fromhex("0123456789abcdef")


def _av_pair(av_id: int, value: str) -> bytes:
    data = value.encode("utf-16-le")
    return struct.pack("<HH", av_id, len(data)) + data


def make_challenge() -> bytes:
    """Build a Type 2 CHALLENGE_MESSAGE with target info (no Version field)."""
    flags = (
        NEGOTIATE_UNICODE
        | REQUEST_TARGET
        | NEGOTIATE_NTLM
        | NEGOTIATE_ALWAYS_SIGN
        | TARGET_TYPE_SERVER
        | NEGOTIATE_EXTENDED_SESSIONSECURITY
        | NEGOTIATE_TARGET_INFO
        | NEGOTIATE_128
        | NEGOTIATE_56
    )
    target_name = "SERVER".encode("utf-16-le")
    target_info = (
        _av_pair(2, "CONTOSO")  # MsvAvNbDomainName
        + _av_pair(1, "SERVER")  # MsvAvNbComputerName
        + _av_pair(4, "contoso.local")  # MsvAvDnsDomainName
        + _av_pair(3, "server.contoso.local")  # MsvAvDnsComputerName
        + struct.pack("<HH", 0, 0)  # MsvAvEOL
    )
    header_len = 48
    name_offset = header_len
    info_offset = name_offset + len(target_name)
    return (
        b"NTLMSSP\x00"
        + struct.pack("<I", MSG_CHALLENGE)
        + struct.pack("<HHI", len(target_name), len(target_name), name_offset)
        + struct.pack("<I", flags)
        + SERVER_CHALLENGE
        + b"\x00" * 8
        + struct.pack("<HHI", len(target_info), len(target_info), info_offset)
        + target_name
        + target_info
    )


def message_type(token: bytes) -> int:
    """Return the NTLM message type of a raw token, or 0 if it is not NTLMSSP."""
    if not token.startswith(b"NTLMSSP\x00") or len(token) < 12:
        return 0
    return struct.unpack("<I", token[8:12])[0]


class _Raw(io.BytesIO):
    """A body that also offers `release_conn`, as urllib3's response does."""

    def release_conn(self) -> None:
        self.released = True


_REASONS = {200: "OK", 302: "Found", 400: "Bad Request", 401: "Unauthorized", 407: "Proxy Authentication Required"}


def _fake_response(
    adapter: BaseAdapter, request: PreparedRequest, status: int, headers: dict[str, str], body: bytes = b""
) -> Response:
    """Build the `Response` a fake adapter returns for `request`."""
    r = Response()
    r.status_code = status
    r.reason = _REASONS.get(status, "")
    r.headers = CaseInsensitiveDict(headers)
    r.raw = _Raw(body)
    r.url = request.url or ""
    r.request = request
    r.connection = adapter  # type: ignore[assignment]  # types-requests declares an HTTPAdapter; any BaseAdapter works
    return r


class FakeNtlmAdapter(BaseAdapter):
    """Transport adapter playing the server side of an NTLM handshake."""

    def __init__(
        self,
        *,
        schemes: str = "NTLM",
        set_cookie: str | None = None,
        body: bytes = b'{"ok": true}',
        accept: bool = True,
        challenge: bool = True,
        challenge_header: str | None = None,
    ):
        """Configure the fake server.

        Args:
            schemes: `WWW-Authenticate` value sent with a bare 401.
            set_cookie: `Set-Cookie` value sent with the challenge, if any.
            body: Body of the 200 that ends a successful handshake.
            accept: `False` answers the AUTHENTICATE token with 401 + `WWW-Authenticate: NTLM`,
                as a server does for a wrong password.
            challenge: `False` answers the NEGOTIATE token with 401 + a bare `WWW-Authenticate: NTLM`
                that carries no challenge token.
            challenge_header: `WWW-Authenticate` value sent instead of the real challenge in answer
                to the NEGOTIATE token, for example `NTLM !!!notbase64!!!`.
        """
        super().__init__()
        self.schemes = schemes
        self.set_cookie = set_cookie
        self.body = body
        self.accept = accept
        self.challenge = challenge
        self.challenge_header = challenge_header
        self.calls: list[PreparedRequest] = []
        self.authenticate_token: bytes | None = None

    def send(
        self,
        request: PreparedRequest,
        stream: Any = None,
        timeout: Any = None,
        verify: Any = None,
        cert: Any = None,
        proxies: Any = None,
    ) -> Response:
        del stream, timeout, verify, cert, proxies  # transport options are irrelevant to the fake
        self.calls.append(request.copy())
        auth = request.headers.get("Authorization")
        if auth is None:
            return self._response(request, 401, {"WWW-Authenticate": self.schemes})
        if isinstance(auth, bytes):
            auth = auth.decode("ascii")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "ntlm":
            return self._response(request, 401, {"WWW-Authenticate": self.schemes})
        try:
            data = base64.b64decode(token, validate=True)
        except binascii.Error:
            data = b""
        kind = message_type(data)
        if kind == MSG_NEGOTIATE:
            if not self.challenge:
                return self._response(request, 401, {"WWW-Authenticate": "NTLM"})
            if self.challenge_header is not None:
                return self._response(request, 401, {"WWW-Authenticate": self.challenge_header})
            headers = {"WWW-Authenticate": "NTLM " + base64.b64encode(make_challenge()).decode()}
            if self.set_cookie:
                headers["Set-Cookie"] = self.set_cookie
            return self._response(request, 401, headers)
        if kind == MSG_AUTHENTICATE:
            self.authenticate_token = data
            if not self.accept:
                return self._response(request, 401, {"WWW-Authenticate": "NTLM"})
            return self._response(request, 200, {"Content-Type": "application/json"}, self.body)
        # Anything else is rejected with a fresh challenge, as IIS does.
        return self._response(request, 401, {"WWW-Authenticate": self.schemes})

    def close(self) -> None:
        return None

    def _response(self, request: PreparedRequest, status: int, headers: dict[str, str], body: bytes = b"") -> Response:
        return _fake_response(self, request, status, headers, body)


class FakeNegotiateAdapter(FakeNtlmAdapter):
    """Transport adapter playing a Kerberos server that accepts the opening token.

    A bare request gets 401 + `WWW-Authenticate: Negotiate`; any `Negotiate` token
    is answered with 200, so the handshake ends after one leg.
    """

    def __init__(self, *, body: bytes = b'{"ok": true}'):
        super().__init__(schemes="Negotiate", body=body)

    def send(
        self,
        request: PreparedRequest,
        stream: Any = None,
        timeout: Any = None,
        verify: Any = None,
        cert: Any = None,
        proxies: Any = None,
    ) -> Response:
        del stream, timeout, verify, cert, proxies  # transport options are irrelevant to the fake
        self.calls.append(request.copy())
        auth = request.headers.get("Authorization")
        if isinstance(auth, bytes):
            auth = auth.decode("ascii")
        if auth is None or auth.partition(" ")[0].lower() != "negotiate":
            return self._response(request, 401, {"WWW-Authenticate": self.schemes})
        return self._response(request, 200, {"Content-Type": "application/json"}, self.body)


class FakeProxyAdapter(BaseAdapter):
    """Plays an NTLM-authenticating proxy: 407 + `Proxy-Authenticate` until a Type 3 token arrives."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[PreparedRequest] = []
        self.authenticate_token: bytes | None = None

    def send(
        self,
        request: PreparedRequest,
        stream: Any = None,
        timeout: Any = None,
        verify: Any = None,
        cert: Any = None,
        proxies: Any = None,
    ) -> Response:
        del stream, timeout, verify, cert, proxies  # transport options are irrelevant to the fake
        self.calls.append(request.copy())
        auth = request.headers.get("Proxy-Authorization")
        if isinstance(auth, bytes):
            auth = auth.decode("ascii")
        token = base64.b64decode(auth.partition(" ")[2]) if auth else b""
        kind = message_type(token)
        if kind == MSG_NEGOTIATE:
            challenge = "NTLM " + base64.b64encode(make_challenge()).decode()
            return _fake_response(self, request, 407, {"Proxy-Authenticate": challenge})
        if kind == MSG_AUTHENTICATE:
            self.authenticate_token = token
            return _fake_response(self, request, 200, {"Content-Type": "application/json"}, b'{"ok": true}')
        return _fake_response(self, request, 407, {"Proxy-Authenticate": "NTLM"})

    def close(self) -> None:
        return None


class RedirectAdapter(BaseAdapter):
    """Answers every request with a 302 to `location`."""

    def __init__(self, location: str) -> None:
        super().__init__()
        self.location = location
        self.calls: list[PreparedRequest] = []

    def send(
        self,
        request: PreparedRequest,
        stream: Any = None,
        timeout: Any = None,
        verify: Any = None,
        cert: Any = None,
        proxies: Any = None,
    ) -> Response:
        del stream, timeout, verify, cert, proxies  # transport options are irrelevant to the fake
        self.calls.append(request.copy())
        return _fake_response(self, request, 302, {"Location": self.location})

    def close(self) -> None:
        return None
