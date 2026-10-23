import pytest

from sppyte.utils import (
    build_path,
    odata_literal,
    odata_path,
    parse_add_document,
    parse_add_item,
    parse_form_digest,
    parse_item_type,
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
