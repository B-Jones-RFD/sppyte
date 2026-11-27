"""NTLM / Negotiate (Kerberos) authentication for `requests`, built on pyspnego.

`SpPremAuth` is a `requests.auth.AuthBase` that performs the challenge /
response handshake SharePoint on-premises uses. The handshake authenticates a
TCP connection, not a request, so it runs on one keep-alive connection and
every later request on that connection is already authenticated; `requests`'
connection pooling makes this transparent.

Example:
    ```python
    from sppyte.auth import SpPremAuth

    auth = SpPremAuth("jsmith", "secret", domain="CONTOSO")  # NTLM
    auth = SpPremAuth(protocol="negotiate")  # Kerberos SSO
    ```
"""

from __future__ import annotations

import base64
import contextlib
import functools
import warnings
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

import spnego
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from requests.auth import AuthBase
from spnego.channel_bindings import GssChannelBindings

from sppyte.errors import ConfigurationError

if TYPE_CHECKING:
    from requests import PreparedRequest, Response

Protocol = Literal["ntlm", "negotiate", "kerberos"]
"""Authentication protocol: `ntlm`, `negotiate` (SPNEGO, prefers Kerberos) or `kerberos`."""

UNAUTHORIZED = 401
PROXY_AUTH_REQUIRED = 407

_HEADER_NAMES: dict[str, str] = {"ntlm": "NTLM", "negotiate": "Negotiate", "kerberos": "Negotiate"}
_WEAK_HASHES = frozenset({"md5", "sha1"})


class SpPremAuth(AuthBase):
    r"""`requests` authentication handler for NTLM and Negotiate (Kerberos).

    Args:
        username: Account name, with or without the domain (`"jsmith"`, `"CONTOSO\jsmith"`
            or `"jsmith@contoso.local"`). Omit with `protocol="negotiate"` or `"kerberos"`
            to use the current user's Kerberos ticket (single sign-on).
        password: Password for `username`; omit for single sign-on.
        domain: NTLM (NetBIOS) domain, prepended to a bare `username`.
        protocol: `"ntlm"` (default), `"negotiate"` (SPNEGO: Kerberos when a ticket is
            available, NTLM otherwise) or `"kerberos"`.
        service: Service part of the Kerberos SPN; `"HTTP"` for SharePoint.
        send_cbt: Send TLS channel bindings (`tls-server-end-point`) over HTTPS, which
            servers with Extended Protection require. On by default; harmless otherwise.

    The handler also answers a proxy's `407 Proxy Authentication Required` with
    these credentials. That is deprecated: it emits a `DeprecationWarning` and is
    removed in sppyte 2.0. Set proxy credentials on the `requests.Session` you
    pass to `Site` instead.

    Raises:
        ConfigurationError: if `protocol` is not one of the supported protocols, or
            `protocol="ntlm"` is given without a username and password.
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        domain: str | None = None,
        protocol: Protocol = "ntlm",
        service: str = "HTTP",
        send_cbt: bool = True,
    ):
        if protocol not in _HEADER_NAMES:
            msg = f"protocol must be one of {sorted(_HEADER_NAMES)} (got {protocol!r})"
            raise ConfigurationError(msg)
        if protocol == "ntlm" and (not username or password is None):
            msg = "NTLM needs a username and password; use protocol='negotiate' for single sign-on"
            raise ConfigurationError(msg)
        self.username = f"{domain}\\{username}" if domain and username and "\\" not in username else username
        self.password = password
        self.protocol: Protocol = protocol
        self.service = service
        self.send_cbt = send_cbt

    def __repr__(self) -> str:
        return f"SpPremAuth(username={self.username!r}, protocol={self.protocol!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SpPremAuth) and (
            self.username,
            self.password,
            self.protocol,
            self.service,
            self.send_cbt,
        ) == (other.username, other.password, other.protocol, other.service, other.send_cbt)

    def __hash__(self) -> int:
        return hash((self.username, self.protocol, self.service, self.send_cbt))

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        """Attach the response hook that performs the handshake on a 401 from this request's origin.

        `requests` copies hooks onto the request it sends for a redirect, so the
        origin is bound here, from the request the handler was first applied to.
        """
        request.headers["Connection"] = "Keep-Alive"
        request.register_hook("response", functools.partial(self.handle_response, origin=_origin(request.url)))
        return request

    # ------------------------------------------------------------ handshake ----
    def handle_response(self, response: Response, *, origin: tuple[str, str] | None = None, **kwargs: Any) -> Response:
        """Complete the handshake when the server challenges with 401 or 407.

        A challenge from another origin than the one the request was first sent to
        (a redirect to another host) is returned unanswered, so credentials never
        leave the configured host.

        Answering a proxy's 407 is deprecated and removed in sppyte 2.0: it still
        runs the handshake, but emits a `DeprecationWarning` first. Configure proxy
        credentials on the session instead.

        Args:
            response: The response to inspect.
            origin: `(scheme, netloc)` of the request the handler was attached to;
                `None` skips the same-origin check.
            **kwargs: Send options, reused for the handshake legs.

        Returns:
            The final response of the handshake, or `response` unchanged.
        """
        if origin is not None and _origin(response.url) != origin:
            return response
        if response.status_code == UNAUTHORIZED:
            return self._authenticate(response, "www-authenticate", "Authorization", kwargs)
        if response.status_code == PROXY_AUTH_REQUIRED:
            # The proxy is a different host from the one the Site was created for, so sending it
            # the SharePoint credentials breaks the rule that credentials go only to that host.
            warnings.warn(
                "Answering a proxy's 407 with the SharePoint credentials is deprecated and will be "
                "removed in sppyte 2.0; configure proxy credentials on the session instead",
                DeprecationWarning,
                stacklevel=2,
            )
            return self._authenticate(response, "proxy-authenticate", "Proxy-Authorization", kwargs)
        return response

    def _authenticate(
        self,
        response: Response,
        challenge_header: str,
        auth_header: str,
        send_kwargs: dict[str, Any],
    ) -> Response:
        """Run the three-leg handshake on the connection that issued `response`."""
        scheme = _pick_scheme(response.headers.get(challenge_header, ""), self.protocol)
        if scheme is None or auth_header in response.request.headers:
            return response  # not our challenge, or we already tried once

        context = spnego.client(
            self.username,
            self.password,
            hostname=_hostname(response.url),
            service=self.service,
            protocol=self.protocol,
            channel_bindings=self._channel_bindings(response),
        )

        # Consume the body and release the socket so the next leg reuses it.
        _rewind_body(response.request)
        _drain(response)

        # Leg 1: our opening token.
        request = response.request.copy()
        token = context.step()
        request.headers[auth_header] = f"{scheme} {_b64(token)}"
        challenge_response = response.connection.send(request, **send_kwargs)
        _drain(challenge_response)

        if challenge_response.status_code not in (UNAUTHORIZED, PROXY_AUTH_REQUIRED):
            challenge_response.history.append(response)
            return challenge_response  # Kerberos: a single token may suffice

        challenge = _extract_token(challenge_response.headers.get(challenge_header, ""), scheme)
        if challenge is None:
            challenge_response.history.append(response)
            return challenge_response

        # Leg 2: answer the server's challenge.
        request = challenge_response.request.copy()
        cookie = challenge_response.headers.get("set-cookie")
        if cookie:
            request.headers["Cookie"] = cookie  # some servers bind the handshake to a cookie
        token = context.step(challenge)
        request.headers[auth_header] = f"{scheme} {_b64(token)}"
        final = response.connection.send(request, **send_kwargs)
        final.history.extend([response, challenge_response])
        return final

    def _channel_bindings(self, response: Response) -> GssChannelBindings | None:
        """Build `tls-server-end-point` channel bindings from the peer certificate, if any."""
        if not self.send_cbt or not response.url.lower().startswith("https://"):
            return None
        cert = _peer_certificate(response)
        if cert is None:
            return None
        return GssChannelBindings(application_data=b"tls-server-end-point:" + certificate_hash(cert))


# ---------------------------------------------------------------- helpers ----
def certificate_hash(certificate_der: bytes) -> bytes:
    """Hash a DER certificate per RFC 5929 (its signature hash, or SHA-256 for MD5/SHA-1)."""
    cert = x509.load_der_x509_certificate(certificate_der)
    algorithm = cert.signature_hash_algorithm
    if algorithm is None or algorithm.name.lower() in _WEAK_HASHES:
        algorithm = hashes.SHA256()
    digest = hashes.Hash(algorithm)
    digest.update(certificate_der)
    return digest.finalize()


def _peer_certificate(response: Response) -> bytes | None:
    """Return the DER peer certificate of the socket behind `response`, if reachable."""
    raw: Any = response.raw
    with contextlib.suppress(AttributeError, OSError, ValueError):
        sock = raw._fp.fp.raw._sock  # noqa: SLF001 - urllib3 keeps the socket private
        return sock.getpeercert(True)
    return None


def _pick_scheme(header: str, protocol: str) -> str | None:
    """Choose the auth scheme to answer from a `WWW-Authenticate` header, or `None`."""
    offered = {part.strip().split(" ", 1)[0].lower() for part in header.split(",") if part.strip()}
    wanted = _HEADER_NAMES[protocol]
    return wanted if wanted.lower() in offered else None


def _extract_token(header: str, scheme: str) -> bytes | None:
    """Return the decoded token for `scheme` from a challenge header, or `None`."""
    prefix = f"{scheme} ".lower()
    for part in (p.strip() for p in header.split(",")):
        if part.lower().startswith(prefix):
            return base64.b64decode(part[len(prefix) :])
    return None


def _hostname(url: str) -> str:
    """Return the host name part of `url`, for the Kerberos SPN."""
    return urlsplit(url).hostname or "unspecified"


def _origin(url: str | None) -> tuple[str, str]:
    """Return `(scheme, netloc)` of `url`, lower-cased, for the same-origin check."""
    parts = urlsplit(url or "")
    return parts.scheme.lower(), parts.netloc.lower()


def _rewind_body(request: PreparedRequest) -> None:
    """Seek a file-like request body back to its start so it can be re-sent."""
    body: Any = request.body
    if hasattr(body, "seek"):
        length = int(request.headers.get("Content-Length", "0") or 0)
        with contextlib.suppress(OSError, ValueError):
            if length > 0:
                body.seek(-length, 1)
            else:
                body.seek(0)


def _drain(response: Response) -> None:
    """Read the body and release the connection so the next leg reuses the same socket."""
    _ = response.content
    response.raw.release_conn()


def _b64(token: bytes | None) -> str:
    """Base64-encode a token for an `Authorization` header."""
    return base64.b64encode(token or b"").decode("ascii")
