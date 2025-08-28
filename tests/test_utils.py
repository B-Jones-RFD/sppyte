import pytest

from sppyte.utils import (
    build_path,
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
