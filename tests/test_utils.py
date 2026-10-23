import pytest

from sppyte.errors import ResponseFormatError
from sppyte.odata import Page, follow_pages, parse_page
from sppyte.utils import (
    build_path,
    odata_literal,
    odata_path,
    parse_add_document,
    parse_add_item,
    parse_context_info,
    parse_created_item,
    parse_form_digest,
    parse_item_type,
    parse_object,
)


# ------------------------- build_path ---------------------------------
@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        ((), "/"),  # no parts
        ((None, None), "/"),  # only None parts
        (
            ("sites/demo", "Shared Documents", "Reports"),
            "/sites/demo/Shared Documents/Reports",
        ),
        (
            ("/sites/demo/", "/Shared Documents/", "/Reports/"),
            "/sites/demo/Shared Documents/Reports",
        ),
        (
            ("sites/demo/", "Shared Documents", "Reports/Q1"),
            "/sites/demo/Shared Documents/Reports/Q1",
        ),
        (
            ("sites/demo", None, "Shared Documents", None, "Reports"),
            "/sites/demo/Shared Documents/Reports",
        ),
        (("", "Docs"), "/Docs"),  # root site: empty relative url
        (("/", "Docs", ""), "/Docs"),
        (("", ""), "/"),
    ],
)
def test_build_path(parts, expected):
    assert build_path(*parts) == expected


def test_build_path_always_leading_slash():
    path = build_path("sites", "demo")
    assert path.startswith("/")
    # and not double leading slashes under normal inputs
    assert not path.startswith("//")


# ------------------------- odata_literal / odata_path -----------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Pets", "Pets"),
        ("Shared Documents", "Shared%20Documents"),
        ("O'Brien", "O''Brien"),
        ("O'Brien's #1 Report", "O''Brien''s%20%231%20Report"),
        ("100% done?", "100%25%20done%3F"),
        ("a&b=c", "a%26b%3Dc"),
        ("sub/dir", "sub%2Fdir"),  # a literal keeps no path structure
        ("naïve café", "na%C3%AFve%20caf%C3%A9"),
        ("", ""),
    ],
)
def test_odata_literal(value, expected):
    assert odata_literal(value) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/sites/demo", "/sites/demo"),
        ("/sites/demo/Shared Documents", "/sites/demo/Shared%20Documents"),
        ("/sites/demo/Q1 '25/100% done", "/sites/demo/Q1%20''25/100%25%20done"),
        ("/", "/"),
        ("", ""),
    ],
)
def test_odata_path(path, expected):
    assert odata_path(path) == expected


def test_odata_path_preserves_slashes_only_as_separators():
    assert odata_path("/a/b'c/d").count("/") == 3
    assert "%2F" not in odata_path("/a/b/c")


# ------------------------- parse_form_digest --------------------------
def test_parse_form_digest_ok():
    r = {"FormDigestValue": "abc123"}
    assert parse_form_digest(r) == "abc123"


def test_parse_form_digest_missing_raises():
    with pytest.raises(Exception, match="Form digest value"):
        parse_form_digest({})


def test_parse_form_digest_allows_empty_string():
    # Present but empty is technically accepted by current implementation
    r = {"FormDigestValue": ""}
    assert parse_form_digest(r) == ""


# ------------------------- parse_item_type ----------------------------
def test_parse_item_type_ok():
    r = {"ListItemEntityTypeFullName": "SP.Data.TasksListItem"}
    assert parse_item_type(r) == "SP.Data.TasksListItem"


def test_parse_item_type_missing_raises():
    with pytest.raises(Exception, match="List item type"):
        parse_item_type({})


def test_parse_item_type_allows_empty_string():
    r = {"ListItemEntityTypeFullName": ""}
    assert parse_item_type(r) == ""


# ------------------------- parse_add_item -----------------------------
@pytest.mark.parametrize("value", [0, 1, 42, 9999])
def test_parse_add_item_ok_values(value):
    r = {"ID": value}
    assert parse_add_item(r) == value


def test_parse_add_item_missing_raises():
    with pytest.raises(Exception, match="Item id"):
        parse_add_item({})


def test_parse_add_item_negative_sentinel_raises():
    # Implementation uses -1 sentinel to detect missing/invalid ID
    with pytest.raises(Exception, match="Item id"):
        parse_add_item({"ID": -1})


# ------------------------- parse_add_document -------------------------
def test_parse_add_document_ok():
    r = {"UniqueId": "f0e1d2c3-b4a5-6789-abcd-ef0011223344"}
    assert parse_add_document(r) == "f0e1d2c3-b4a5-6789-abcd-ef0011223344"


def test_parse_add_document_missing_raises():
    with pytest.raises(Exception, match="Document id"):
        parse_add_document({})


def test_parse_add_document_allows_empty_string():
    r = {"UniqueId": ""}
    assert parse_add_document(r) == ""


# ------------------------- parse_context_info ---------------------------
def test_parse_context_info_ok():
    r = {"FormDigestValue": "abc", "FormDigestTimeoutSeconds": 900}
    assert parse_context_info(r) == {"digest": "abc", "timeout": 900}


@pytest.mark.parametrize("timeout", [None, 0, -5, "900", True])
def test_parse_context_info_defaults_timeout(timeout):
    r = {"FormDigestValue": "abc"}
    if timeout is not None:
        r["FormDigestTimeoutSeconds"] = timeout
    assert parse_context_info(r)["timeout"] == 1800


def test_parse_context_info_missing_digest_raises():
    with pytest.raises(Exception, match="Form digest value"):
        parse_context_info({"FormDigestTimeoutSeconds": 900})


# ------------------------- parse_created_item ---------------------------
def test_parse_created_item_nometadata():
    assert parse_created_item({"Id": 3, "ID": 3, "Title": "t"}) == {"Id": 3, "ID": 3, "Title": "t"}


def test_parse_created_item_verbose():
    assert parse_created_item({"d": {"ID": 4, "Title": "t"}}) == {"ID": 4, "Title": "t", "Id": 4}


@pytest.mark.parametrize("r", [{}, {"Title": "x"}, {"Id": "3"}, {"Id": True}, [], None, {"d": []}])
def test_parse_created_item_invalid_raises(r):
    with pytest.raises(Exception, match=r"Created item|Item id"):
        parse_created_item(r)


# ------------------------- parse_object ----------------------------------
def test_parse_object_shapes():
    assert parse_object({"Name": "x"}) == {"Name": "x"}
    assert parse_object({"d": {"Name": "x"}}) == {"Name": "x"}


@pytest.mark.parametrize("r", [[], None, "s", {"d": []}])
def test_parse_object_invalid_raises(r):
    with pytest.raises(ResponseFormatError):
        parse_object(r)


# ------------------------- Page / parse_page / follow_pages ---------------
def test_page_is_a_list_with_next_link():
    page = Page([{"Id": 1}], "https://x/next")
    assert page == [{"Id": 1}]
    assert isinstance(page, list)
    assert page.next_link == "https://x/next"
    assert "next_link=" in repr(page)
    assert repr(Page()) == "Page([])"
    assert Page().next_link is None


@pytest.mark.parametrize(
    ("payload", "items", "link"),
    [
        ({"value": [1, 2]}, [1, 2], None),
        ({"value": [], "odata.nextLink": "https://x/n"}, [], "https://x/n"),
        ({"value": [1], "@odata.nextLink": "https://x/n"}, [1], "https://x/n"),
        ({"value": [1], "odata.nextLink": ""}, [1], None),
        ({}, [], None),
    ],
)
def test_parse_page(payload, items, link):
    page = parse_page(payload)
    assert page == items
    assert page.next_link == link


INVALID_PAGES: list[object] = [[], None, {"value": "nope"}, {"value": {}}]


@pytest.mark.parametrize("payload", INVALID_PAGES)
def test_parse_page_invalid_raises(payload):
    with pytest.raises(ResponseFormatError):
        parse_page(payload)


def test_follow_pages():
    pages = {"L2": Page([2], "L3"), "L3": Page([3])}
    fetched = []

    def fetch(link):
        fetched.append(link)
        return pages[link]

    assert [list(p) for p in follow_pages(Page([1], "L2"), fetch)] == [[1], [2], [3]]
    assert fetched == ["L2", "L3"]


def test_follow_pages_max_pages_and_single_page():
    assert len(list(follow_pages(Page([1], "L2"), lambda _: Page([2], "L3"), max_pages=2))) == 2
    assert len(list(follow_pages(Page([1]), lambda _: Page([2])))) == 1
