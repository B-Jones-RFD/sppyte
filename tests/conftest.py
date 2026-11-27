from __future__ import annotations

import io
import json
import re

import pytest
import responses
from requests import Response

from sppyte import Site

HOST = "https://sp.example.com"
SITE_REL = "/sites/parrots"
BASE = f"{HOST}{SITE_REL}"
CONTEXTINFO = f"{BASE}/_api/contextinfo"
DIGEST = "0xDIGEST,23 Oct 2026 12:00:00 -0000"
ANY_URL = re.compile(re.escape(HOST) + r"/.*")
WEB = f"{BASE}/_api/web"
LOGIN_PAGE = "<html><body>Sign in</body></html>"
"""An HTML sign-in page, as a server answers with when it bounces an unauthenticated request."""


def make_response(status: int, body: str = "", headers: dict[str, str] | None = None, reason: str = "") -> Response:
    """Build a `requests.Response` by hand, without a transport."""
    r = Response()
    r.status_code = status
    r.reason = reason
    r.raw = io.BytesIO(body.encode())
    r.encoding = "utf-8"
    r.headers.update(headers or {})
    return r


def json_body(call) -> dict:
    body = call.request.body
    if isinstance(body, bytes):
        body = body.decode()
    return json.loads(body)


def add_contextinfo(rsps, digest: str = DIGEST, timeout: int = 1800) -> None:
    rsps.add(
        responses.POST,
        CONTEXTINFO,
        json={"FormDigestValue": digest, "FormDigestTimeoutSeconds": timeout},
    )


@pytest.fixture
def mocked():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture
def site(mocked) -> Site:
    """A connected Site. The contextinfo call is the first recorded call."""
    add_contextinfo(mocked)
    s = Site(HOST, SITE_REL, "user", "pass")
    s.connect()
    return s
