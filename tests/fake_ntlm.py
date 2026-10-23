"""A fake NTLM-authenticating server, implemented as a `requests` transport adapter.

It speaks just enough NTLM to drive the client through the three-leg handshake:
a bare request gets 401 + `WWW-Authenticate: NTLM`; a Type 1 (NEGOTIATE) token
gets 401 + a canned Type 2 (CHALLENGE); a Type 3 (AUTHENTICATE) token is
accepted without verification and answered with 200. Every request is recorded.
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


class FakeNtlmAdapter(BaseAdapter):
    """Transport adapter playing the server side of an NTLM handshake."""

    def __init__(self, *, schemes: str = "NTLM", set_cookie: str | None = None, body: bytes = b'{"ok": true}'):
        super().__init__()
        self.schemes = schemes
        self.set_cookie = set_cookie
        self.body = body
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
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "ntlm":
            return self._response(request, 401, {"WWW-Authenticate": self.schemes})
        try:
            data = base64.b64decode(token, validate=True)
        except binascii.Error:
            data = b""
        kind = message_type(data)
        if kind == MSG_NEGOTIATE:
            headers = {"WWW-Authenticate": "NTLM " + base64.b64encode(make_challenge()).decode()}
            if self.set_cookie:
                headers["Set-Cookie"] = self.set_cookie
            return self._response(request, 401, headers)
        if kind == MSG_AUTHENTICATE:
            self.authenticate_token = data
            return self._response(request, 200, {"Content-Type": "application/json"}, self.body)
        # Anything else is rejected with a fresh challenge, as IIS does.
        return self._response(request, 401, {"WWW-Authenticate": self.schemes})

    def close(self) -> None:
        return None

    def _response(self, request: PreparedRequest, status: int, headers: dict[str, str], body: bytes = b"") -> Response:
        r = Response()
        r.status_code = status
        r.reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized"}.get(status, "")
        r.headers = CaseInsensitiveDict(headers)
        r.raw = _Raw(body)
        r.url = request.url or ""
        r.request = request
        r.connection = self  # type: ignore[assignment]
        return r
