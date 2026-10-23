from __future__ import annotations

import json
import re

import pytest
import responses

from sppyte import Site

HOST = "https://sp.example.com"
SITE_REL = "/sites/parrots"
BASE = f"{HOST}{SITE_REL}"
CONTEXTINFO = f"{BASE}/_api/contextinfo"
DIGEST = "0xDIGEST,23 Oct 2026 12:00:00 -0000"
ANY_URL = re.compile(re.escape(HOST) + r"/.*")


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
