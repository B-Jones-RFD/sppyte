"""
HTTP-level tests for Site, List and Library using the `responses` mock.

Each test registers the SharePoint responses it expects, calls the sppyte
method, then asserts on the exact URL, headers and body that were sent.
"""

from __future__ import annotations

import io
import json
import re

import pytest
import responses
from requests import HTTPError

from sppyte import Library, List, ResponseFormatError, Site

HOST = "https://sp.example.com"
SITE_REL = "/sites/parrots"
BASE = f"{HOST}{SITE_REL}"
CONTEXTINFO = f"{BASE}/_api/contextinfo"
DIGEST = "0xDIGEST,23 Oct 2026 12:00:00 -0000"
ANY_URL = re.compile(re.escape(HOST) + r"/.*")


def _json_body(call) -> dict:
    body = call.request.body
    if isinstance(body, bytes):
        body = body.decode()
    return json.loads(body)


@pytest.fixture
def mocked():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture
def site(mocked) -> Site:
    """A connected Site. The contextinfo call is the first recorded call."""
    mocked.add(responses.POST, CONTEXTINFO, json={"FormDigestValue": DIGEST})
    s = Site(HOST, SITE_REL, "user", "pass")
    s.connect()
    return s


# ------------------------------- Site ----------------------------------------
def test_site_normalizes_paths():
    s = Site(f"{HOST}/", "sites/parrots/", "u", "p")
    assert s.site_path == BASE


def test_site_attributes_are_per_instance():
    a = Site(HOST, SITE_REL, "u", "p")
    b = Site(HOST, SITE_REL, "u", "p")
    assert a.session is None
    assert a.form_digest is None
    a.form_digest = "x"
    assert b.form_digest is None
    assert "session" not in Site.__dict__
    assert "form_digest" not in Site.__dict__


def test_connect_fetches_form_digest(site, mocked):
    assert site.form_digest == DIGEST
    call = mocked.calls[0]
    assert call.request.url == CONTEXTINFO
    assert call.request.headers["Accept"] == "application/json;odata=nometadata"
    assert call.request.headers["Content-Type"] == "application/json;odata=verbose"


def test_context_manager_connects_and_closes(mocked):
    mocked.add(responses.POST, CONTEXTINFO, json={"FormDigestValue": DIGEST})
    with Site(HOST, SITE_REL, "u", "p") as s:
        assert s.session is not None
        assert s.form_digest == DIGEST
    assert len(mocked.calls) == 1


def test_request_connects_lazily(mocked):
    mocked.add(responses.POST, CONTEXTINFO, json={"FormDigestValue": DIGEST})
    mocked.add(responses.GET, f"{BASE}/_api/web", json={"Title": "Parrots"})
    s = Site(HOST, SITE_REL, "u", "p")
    r = s.request("get", "/_api/web")
    assert r.json()["Title"] == "Parrots"
    assert [c.request.url for c in mocked.calls] == [CONTEXTINFO, f"{BASE}/_api/web"]


def test_request_strips_slashes(site, mocked):
    mocked.add(responses.GET, f"{BASE}/_api/web", json={})
    site.request("get", "///_api/web///")
    assert mocked.calls[-1].request.url == f"{BASE}/_api/web"


def test_request_raises_for_status(site, mocked):
    mocked.add(responses.GET, f"{BASE}/_api/web", status=404, json={"error": "nope"})
    with pytest.raises(HTTPError):
        site.request("get", "/_api/web")


def test_request_replays_once_on_403(site, mocked):
    url = f"{BASE}/_api/web"
    mocked.add(responses.GET, url, status=403)
    mocked.add(responses.POST, CONTEXTINFO, json={"FormDigestValue": "fresh"})
    mocked.add(responses.GET, url, json={"ok": True})
    r = site.request("get", "/_api/web")
    assert r.json() == {"ok": True}
    assert site.form_digest == "fresh"
    assert [c.request.url for c in mocked.calls[1:]] == [url, CONTEXTINFO, url]


def test_site_list_and_library_factories(site):
    pets = site.list("Pets")
    docs = site.library("Shared Documents")
    assert isinstance(pets, List)
    assert pets.site is site
    assert pets.name == "Pets"
    assert isinstance(docs, Library)
    assert docs.site is site
    assert docs.name == "Shared Documents"


# ------------------------------- List ----------------------------------------
LIST_URL = f"{BASE}/_api/web/lists/GetByTitle('Pets')"
ITEM_TYPE = "SP.Data.PetsListItem"


@pytest.fixture
def pets(site) -> List:
    return site.list("Pets")


def test_get_item_type(pets, mocked):
    mocked.add(responses.GET, ANY_URL, json={"ListItemEntityTypeFullName": ITEM_TYPE})
    assert pets.get_item_type() == ITEM_TYPE
    req = mocked.calls[-1].request
    assert req.url == f"{LIST_URL}?%24select=ListItemEntityTypeFullName"
    assert req.headers["Accept"] == "application/json;odata=nometadata"


def test_add_item_adds_metadata_without_mutating_input(pets, mocked):
    mocked.add(responses.GET, ANY_URL, json={"ListItemEntityTypeFullName": ITEM_TYPE})
    mocked.add(responses.POST, ANY_URL, json={"ID": 42, "Title": "Polly"})
    item = {"Title": "Polly"}
    assert pets.add_item(item) == 42
    assert item == {"Title": "Polly"}, "caller's dict must not be modified"

    req = mocked.calls[-1].request
    assert req.url == f"{LIST_URL}/items"
    assert req.headers["X-RequestDigest"] == DIGEST
    assert req.headers["Content-Type"] == "application/json;odata=verbose"
    assert _json_body(mocked.calls[-1]) == {"__metadata": {"type": ITEM_TYPE}, "Title": "Polly"}


def test_add_item_skips_lookup_when_metadata_given(pets, mocked):
    mocked.add(responses.POST, ANY_URL, json={"ID": 7})
    pets.add_item({"__metadata": {"type": ITEM_TYPE}, "Title": "x"})
    # contextinfo + POST only; no GET for the item type
    assert [c.request.method for c in mocked.calls] == ["POST", "POST"]


def test_add_item_missing_id_raises(pets, mocked):
    mocked.add(responses.POST, ANY_URL, json={"Title": "no id"})
    with pytest.raises(ResponseFormatError):
        pets.add_item({"__metadata": {"type": ITEM_TYPE}})


def test_update_item_merges_without_mutating_input(pets, mocked):
    mocked.add(responses.GET, ANY_URL, json={"ListItemEntityTypeFullName": ITEM_TYPE})
    mocked.add(responses.POST, ANY_URL, status=204)
    patch = {"Title": "Renamed"}
    assert pets.update_item(5, patch) == 5
    assert patch == {"Title": "Renamed"}

    req = mocked.calls[-1].request
    assert req.url == f"{LIST_URL}/items('5')"
    assert req.headers["X-HTTP-Method"] == "MERGE"
    assert req.headers["If-Match"] == "*"
    assert req.headers["X-RequestDigest"] == DIGEST
    assert _json_body(mocked.calls[-1]) == {"__metadata": {"type": ITEM_TYPE}, "Title": "Renamed"}


def test_delete_item(pets, mocked):
    mocked.add(responses.POST, ANY_URL, status=200)
    assert pets.delete_item(9) is True
    req = mocked.calls[-1].request
    assert req.url == f"{LIST_URL}/items('9')"
    assert req.headers["X-HTTP-Method"] == "DELETE"
    assert req.headers["If-Match"] == "*"
    assert req.headers["X-RequestDigest"] == DIGEST


def test_get_item(pets, mocked):
    mocked.add(responses.GET, ANY_URL, json={"Id": 3, "Title": "Sonny"})
    assert pets.get_item(3) == {"Id": 3, "Title": "Sonny"}
    assert mocked.calls[-1].request.url == f"{LIST_URL}/items('3')"


def test_get_contents_with_params(pets, mocked):
    mocked.add(responses.GET, ANY_URL, json={"value": [{"Id": 1}, {"Id": 2}]})
    items = pets.get_contents({"$select": "Id,Title", "$top": 5})
    assert items == [{"Id": 1}, {"Id": 2}]
    url = mocked.calls[-1].request.url
    assert url.startswith(f"{LIST_URL}/items?")
    assert "%24select=Id%2CTitle" in url
    assert "%24top=5" in url


def test_get_contents_accepts_sequence_of_pairs(pets, mocked):
    mocked.add(responses.GET, ANY_URL, json={"value": []})
    assert pets.get_contents([("$top", 1)]) == []
    assert mocked.calls[-1].request.url == f"{LIST_URL}/items?%24top=1"


def test_get_contents_empty_when_value_missing(pets, mocked):
    mocked.add(responses.GET, ANY_URL, json={})
    assert pets.get_contents() == []


def test_add_attachment_bytes(pets, mocked):
    mocked.add(responses.POST, ANY_URL, json={})
    assert pets.add_attachment(4, "notes.txt", b"hello") == 4
    req = mocked.calls[-1].request
    assert req.url == f"{LIST_URL}/items('4')/AttachmentFiles/add(FileName='notes.txt')"
    assert req.body == b"hello"
    assert req.headers["X-RequestDigest"] == DIGEST


def test_add_attachment_file_like(pets, mocked):
    mocked.add(responses.POST, ANY_URL, json={})
    fh = io.BytesIO(b"stream")
    pets.add_attachment(4, "a b.txt", fh)
    req = mocked.calls[-1].request
    assert req.url.endswith("/AttachmentFiles/add(FileName='a%20b.txt')")


def test_list_title_is_escaped(site, mocked):
    mocked.add(responses.GET, ANY_URL, json={"value": []})
    site.list("O'Brien's #1 Pets").get_contents()
    assert mocked.calls[-1].request.url == (f"{BASE}/_api/web/lists/GetByTitle('O''Brien''s%20%231%20Pets')/items")


# ------------------------------ Library --------------------------------------
LIB = "Shared Documents"
LIB_SRU = f"{SITE_REL}/Shared%20Documents"  # server-relative URL, escaped


def folder_url(*parts: str) -> str:
    path = "/".join([LIB_SRU, *parts])
    return f"{BASE}/_api/web/GetFolderByServerRelativeUrl('{path}')"


def file_url(*parts: str) -> str:
    path = "/".join([LIB_SRU, *parts])
    return f"{BASE}/_api/web/GetFileByServerRelativeUrl('{path}')"


@pytest.fixture
def docs(site) -> Library:
    return site.library(LIB)


def test_add_folder_uses_site_relative_url(docs, mocked):
    mocked.add(responses.POST, ANY_URL, json={"Exists": True})
    assert docs.add_folder("Reports", "2025") is True
    req = mocked.calls[-1].request
    assert req.url == f"{BASE}/_api/web/folders"
    assert req.headers["X-RequestDigest"] == DIGEST
    assert _json_body(mocked.calls[-1]) == {"ServerRelativeUrl": "/sites/parrots/Shared Documents/Reports/2025"}


def test_add_document_streams_file(docs, mocked):
    mocked.add(responses.POST, ANY_URL, json={"UniqueId": "abc-123"})
    fh = io.BytesIO(b"%PDF-1.4")
    assert docs.add_document("report.pdf", fh, "Reports", "2025") == "abc-123"
    req = mocked.calls[-1].request
    assert req.url == f"{folder_url('Reports', '2025')}/Files/add(url='report.pdf',overwrite=true)"
    assert req.headers["Content-Type"] == "application/octet-stream"
    assert req.headers["X-RequestDigest"] == DIGEST


def test_add_document_to_library_root(docs, mocked):
    mocked.add(responses.POST, ANY_URL, json={"UniqueId": "root"})
    docs.add_document("a.txt", b"x")
    assert mocked.calls[-1].request.url == f"{folder_url()}/Files/add(url='a.txt',overwrite=true)"


def test_add_document_missing_unique_id_raises(docs, mocked):
    mocked.add(responses.POST, ANY_URL, json={})
    with pytest.raises(ResponseFormatError):
        docs.add_document("a.txt", b"x")


def test_folder_exists(docs, mocked):
    mocked.add(responses.GET, ANY_URL, json={"value": True})
    assert docs.folder_exists("Reports", "2025") is True
    assert mocked.calls[-1].request.url == f"{folder_url('Reports', '2025')}/Exists"


def test_folder_exists_false(docs, mocked):
    mocked.add(responses.GET, ANY_URL, json={"value": False})
    assert docs.folder_exists("Missing") is False


def test_delete_document(docs, mocked):
    mocked.add(responses.POST, ANY_URL, status=200)
    assert docs.delete_document("report.pdf", "Reports", "2025") is True
    req = mocked.calls[-1].request
    assert req.url == file_url("Reports", "2025", "report.pdf")
    assert req.headers["X-HTTP-Method"] == "DELETE"
    assert req.headers["If-Match"] == "*"
    assert req.headers["X-RequestDigest"] == DIGEST


def test_delete_folder_path_is_not_doubled(docs, mocked):
    mocked.add(responses.POST, ANY_URL, status=200)
    assert docs.delete_folder("Reports", "2025") is True
    req = mocked.calls[-1].request
    assert req.url == folder_url("Reports", "2025")
    assert "_api/web/_api" not in req.url
    assert req.headers["X-HTTP-Method"] == "DELETE"
    assert req.headers["If-Match"] == "*"


def test_list_contents(docs, mocked):
    mocked.add(responses.GET, ANY_URL, json={"value": [{"Name": "a.txt"}]})
    files = docs.list_contents({"$select": "Name"}, "Reports")
    assert files == [{"Name": "a.txt"}]
    url = mocked.calls[-1].request.url
    assert url == f"{folder_url('Reports')}/Files?%24select=Name"


def test_list_contents_root_no_params(docs, mocked):
    mocked.add(responses.GET, ANY_URL, json={"value": []})
    assert docs.list_contents() == []
    assert mocked.calls[-1].request.url == f"{folder_url()}/Files"


def test_get_document(docs, mocked):
    mocked.add(responses.GET, ANY_URL, body=b"binary\x00data")
    assert docs.get_document("report.pdf", "Reports") == b"binary\x00data"
    assert mocked.calls[-1].request.url == f"{folder_url('Reports')}/Files('report.pdf')/$value"


def test_library_paths_are_escaped(site, mocked):
    mocked.add(responses.GET, ANY_URL, json={"value": []})
    site.library("Bob's Files").list_contents(None, "Q1 '25", "100% done")
    assert mocked.calls[-1].request.url == (
        f"{BASE}/_api/web/GetFolderByServerRelativeUrl("
        f"'/sites/parrots/Bob''s%20Files/Q1%20''25/100%25%20done')/Files"
    )


def test_library_context_manager_closes_site(mocked):
    mocked.add(responses.POST, CONTEXTINFO, json={"FormDigestValue": DIGEST})
    s = Site(HOST, SITE_REL, "u", "p")
    with Library(LIB, s) as lib:
        assert lib.site.session is not None
