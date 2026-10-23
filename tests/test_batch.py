"""Tests for $batch encoding, decoding and the Batch builder."""

from __future__ import annotations

import re

import pytest
import responses

from sppyte import Batch, BatchRequest, BatchResponse, ConfigurationError, ResponseFormatError, Site
from sppyte.batch import build_batch_body, multipart_boundary, parse_batch_response
from tests.conftest import ANY_URL, BASE, DIGEST, HOST, SITE_REL

CRLF = "\r\n"


# ------------------------------------------------------- build_batch_body ----
def test_build_body_groups_consecutive_writes_in_one_changeset():
    body = build_batch_body(
        [
            BatchRequest("GET", "https://sp/_api/a"),
            BatchRequest("POST", "https://sp/_api/b", body='{"T": 1}'),
            BatchRequest("MERGE", "https://sp/_api/c", headers={"If-Match": '"3"'}, body='{"T":2}'),
            BatchRequest("GET", "https://sp/_api/d"),
            BatchRequest("DELETE", "https://sp/_api/e"),
        ],
        "batch_1",
    )
    top = body.split("--batch_1")
    # preamble, GET, changeset(POST+MERGE), GET, changeset(DELETE), closing "--"
    assert len(top) == 6
    assert top[5] == f"--{CRLF}"

    assert "Content-Type: application/http" in top[1]
    assert f"GET https://sp/_api/a HTTP/1.1{CRLF}" in top[1]
    assert "Accept: application/json;odata=nometadata" in top[1]
    assert "If-Match" not in top[1]

    changeset = re.search(r"boundary=(changeset_[\w-]+)", top[2])
    assert changeset is not None
    inner = top[2].split(f"--{changeset.group(1)}")
    assert len(inner) == 4  # header, POST, MERGE, closing
    assert "POST https://sp/_api/b HTTP/1.1" in inner[1]
    assert "Content-Type: application/json;odata=verbose" in inner[1]
    assert f'{CRLF}{CRLF}{{"T": 1}}{CRLF}' in inner[1]
    assert "MERGE https://sp/_api/c HTTP/1.1" in inner[2]
    assert 'If-Match: "3"' in inner[2]  # caller override wins
    assert "If-Match: *" not in inner[2]

    assert "DELETE https://sp/_api/e HTTP/1.1" in top[4]
    assert "If-Match: *" in top[4]
    # Every line break is CRLF, as the multipart spec requires.
    assert "\n" not in body.replace(CRLF, "")


# ----------------------------------------------------- multipart_boundary ----
def test_multipart_boundary():
    assert multipart_boundary("multipart/mixed; boundary=batchresponse_abc") == "batchresponse_abc"
    assert multipart_boundary('multipart/mixed; boundary="b 1"; charset=utf-8') == "b 1"
    assert multipart_boundary("application/json") is None
    assert multipart_boundary(None) is None


# --------------------------------------------------- parse_batch_response ----
def part(status: str, headers: str, body: str) -> str:
    return CRLF.join(
        [
            "Content-Type: application/http",
            "Content-Transfer-Encoding: binary",
            "",
            f"HTTP/1.1 {status}",
            headers,
            "",
            body,
            "",
        ]
    )


NOPE = '{"odata.error":{"message":{"value":"nope"}}}'


def test_parse_flat_parts_in_order():
    b = "batchresponse_1"
    text = (
        f"--{b}{CRLF}"
        + part("200 OK", "CONTENT-TYPE: application/json;odata=nometadata;streaming=true", '{"value":[1,2]}')
        + f"--{b}{CRLF}"
        + part("404 Not Found", "CONTENT-TYPE: application/json;odata=nometadata", NOPE)
        + f"--{b}{CRLF}"
        + part("204 No Content", "X-Foo: bar", "")
        + f"--{b}--{CRLF}"
    )
    out = parse_batch_response(text, f"multipart/mixed; boundary={b}")
    assert [r.status for r in out] == [200, 404, 204]
    assert out[0].ok is True
    assert out[0].json == {"value": [1, 2]}
    assert "application/json" in out[0].headers["content-type"]
    assert out[0].error is None
    assert out[1].ok is False
    assert out[1].json == {"odata.error": {"message": {"value": "nope"}}}
    assert out[1].error is not None
    assert out[1].error.message == "nope"
    assert out[2] == BatchResponse(status=204, headers={"x-foo": "bar"}, body="", json=None)


def test_parse_flattens_changesets_and_tolerates_lf():
    b = "batchresponse_outer"
    c = "changesetresponse_inner"
    text = "\n".join(
        [
            f"--{b}",
            f"Content-Type: multipart/mixed; boundary={c}",
            "",
            f"--{c}",
            part("201 Created", "Content-Type: application/json;odata=nometadata", '{"Id":9}').replace(CRLF, "\n"),
            f"--{c}",
            part("204 No Content", "", "").replace(CRLF, "\n"),
            f"--{c}--",
            f"--{b}",
            part("200 OK", "Content-Type: application/json", '{"value":[]}').replace(CRLF, "\n"),
            f"--{b}--",
            "",
        ]
    )
    out = parse_batch_response(text, f"multipart/mixed; boundary={b}")
    assert [r.status for r in out] == [201, 204, 200]
    assert out[0].json == {"Id": 9}
    assert out[2].json == {"value": []}


def test_parse_leaves_json_none_for_unparsable_body():
    text = f"--x{CRLF}" + part("500 Error", "Content-Type: application/json", "not json") + f"--x--{CRLF}"
    (r,) = parse_batch_response(text, "multipart/mixed; boundary=x")
    assert r.status == 500
    assert r.ok is False
    assert r.body == "not json"
    assert r.json is None
    assert r.error is None


def test_parse_rejects_non_multipart():
    with pytest.raises(ResponseFormatError, match="not multipart"):
        parse_batch_response("{}", "application/json")


# ----------------------------------------------------------------- Batch ----
def test_site_batch_builder_resolves_paths(site):
    b = site.batch()
    assert isinstance(b, Batch)
    assert len(b) == 0
    b.get("_api/web/lists", params={"$top": 5}).get("/_api/web").get(f"{HOST}/other?x=1", params=[("y", 2)])
    assert [r.url for r in b.requests] == [
        f"{BASE}/_api/web/lists?%24top=5",
        f"{BASE}/_api/web",
        f"{HOST}/other?x=1&y=2",
    ]
    assert len(b) == 3


def test_batch_rejects_other_origin(site):
    with pytest.raises(ConfigurationError, match="must be on"):
        site.batch().get("https://evil.example.com/_api/web")


def test_batch_add_serialises_json_and_rejects_both_bodies(site):
    b = site.batch()
    b.post("_api/web/lists/GetByTitle('Pets')/items", {"Title": "A"})
    b.merge("_api/x", body='{"raw":1}', headers={"If-Match": '"2"'})
    b.patch("_api/y", {"Title": "B"})
    b.delete("_api/z")
    methods = [(r.method, r.body) for r in b.requests]
    assert methods == [
        ("POST", '{"Title": "A"}'),
        ("MERGE", '{"raw":1}'),
        ("PATCH", '{"Title": "B"}'),
        ("DELETE", None),
    ]
    assert b.requests[1].headers == {"If-Match": '"2"'}
    with pytest.raises(ValueError, match="either json or body"):
        b.add("POST", "_api/w", json={}, body="{}")


def test_empty_batch_sends_nothing(site, mocked):
    assert site.batch().send() == []
    assert len(mocked.calls) == 1  # contextinfo only


def test_batch_send_round_trip(site, mocked):
    b = "batchresponse_42"
    reply = (
        f"--{b}{CRLF}"
        + part("200 OK", "Content-Type: application/json;odata=nometadata", '{"value":[{"Id":1}]}')
        + f"--{b}{CRLF}"
        + f"Content-Type: multipart/mixed; boundary=cs{CRLF}{CRLF}"
        + f"--cs{CRLF}"
        + part("201 Created", "Content-Type: application/json;odata=nometadata", '{"Id":2,"Title":"A"}')
        + f"--cs--{CRLF}"
        + f"--{b}--{CRLF}"
    )
    mocked.add(
        responses.POST,
        f"{BASE}/_api/$batch",
        body=reply,
        content_type=f"multipart/mixed; boundary={b}",
    )
    batch = site.batch()
    batch.get("_api/web/lists/GetByTitle('Pets')/items", params={"$top": 1})
    batch.post("_api/web/lists/GetByTitle('Pets')/items", {"__metadata": {"type": "T"}, "Title": "A"})
    out = batch.send()

    assert [r.status for r in out] == [200, 201]
    assert out[0].json == {"value": [{"Id": 1}]}
    assert out[1].json["Id"] == 2

    req = mocked.calls[-1].request
    assert req.url == f"{BASE}/_api/$batch"
    assert req.headers["X-RequestDigest"] == DIGEST
    assert req.headers["Accept"] == "application/json;odata=nometadata"
    boundary = multipart_boundary(req.headers["Content-Type"])
    assert boundary is not None
    sent = req.body.decode()
    assert sent.startswith(f"--{boundary}{CRLF}")
    assert f"GET {BASE}/_api/web/lists/GetByTitle('Pets')/items?%24top=1 HTTP/1.1" in sent
    assert f"POST {BASE}/_api/web/lists/GetByTitle('Pets')/items HTTP/1.1" in sent
    assert '{"__metadata": {"type": "T"}, "Title": "A"}' in sent


def test_batch_send_count_mismatch_raises(site, mocked):
    reply = f"--b{CRLF}" + part("200 OK", "Content-Type: application/json", "{}") + f"--b--{CRLF}"
    mocked.add(responses.POST, ANY_URL, body=reply, content_type="multipart/mixed; boundary=b")
    batch = site.batch().get("_api/a").get("_api/b")
    with pytest.raises(ResponseFormatError, match="expected 2"):
        batch.send()


def test_batch_send_uses_explicit_digest(mocked):
    reply = f"--b{CRLF}" + part("200 OK", "", "") + f"--b--{CRLF}"
    mocked.add(responses.POST, ANY_URL, body=reply, content_type="multipart/mixed; boundary=b")
    s = Site(HOST, SITE_REL, "u", "p")
    s.batch().get("_api/a").send(digest="mine")
    assert len(mocked.calls) == 1
    assert mocked.calls[-1].request.headers["X-RequestDigest"] == "mine"
