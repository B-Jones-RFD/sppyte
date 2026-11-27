"""Response-parsing helpers.

`parse_json` decodes a response body; each other `parse_*` function pulls one
value out of the decoded payload. Both raise `ResponseFormatError` when the
body is not in the expected shape. URL helpers live in
`sppyte.odata` and are re-exported here for compatibility with 0.x.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, TypedDict

from sppyte.errors import ResponseFormatError
from sppyte.odata import build_path, odata_literal, odata_path

if TYPE_CHECKING:
    from requests import Response

__all__ = [
    "AddDocumentResponse",
    "AddItemResponse",
    "ContextInfo",
    "FormDigestResponse",
    "ItemTypeResponse",
    "build_path",
    "odata_literal",
    "odata_path",
    "parse_add_document",
    "parse_add_item",
    "parse_context_info",
    "parse_created_item",
    "parse_exists",
    "parse_form_digest",
    "parse_item_type",
    "parse_json",
    "parse_object",
]

DEFAULT_DIGEST_TIMEOUT = 1800
"""SharePoint's default form digest lifetime in seconds (30 minutes)."""


# ----------------------------- Types -----------------------------------------
class FormDigestResponse(TypedDict, total=False):
    """Minimal shape of the `/_api/contextinfo` response (`odata=nometadata`)."""

    FormDigestValue: str
    FormDigestTimeoutSeconds: int


class ItemTypeResponse(TypedDict):
    """Response shape for list metadata carrying the item entity type."""

    ListItemEntityTypeFullName: str


class AddItemResponse(TypedDict):
    """Response shape for adding a list item (legacy; see `parse_created_item`)."""

    ID: int


class AddDocumentResponse(TypedDict):
    """Response shape for adding a document (legacy; see `parse_object`)."""

    UniqueId: str


class ContextInfo(TypedDict):
    """Parsed `/_api/contextinfo` response."""

    digest: str
    timeout: int
    """Lifetime of `digest` in seconds."""


# ----------------------------- Parsers ----------------------------------------
def parse_json(response: Response) -> Any:
    """Decode a response body as JSON.

    Args:
        response: The HTTP response whose body to decode.

    Returns:
        The decoded JSON value (usually a `dict`).

    Raises:
        ResponseFormatError: if the body is not JSON (for example an HTML login
            page returned with status 200 by a proxy).
    """
    try:
        return response.json()
    except ValueError as e:  # requests.JSONDecodeError is a ValueError
        msg = f"Response body is not JSON (Content-Type {response.headers.get('Content-Type')!r})"
        raise ResponseFormatError(msg) from e


def _required_str(r: Any, field: str, msg: str) -> str:
    """Return the non-empty string `r[field]`, raising `ResponseFormatError(msg)` otherwise."""
    if not isinstance(r, dict):
        raise ResponseFormatError(msg)
    value = r.get(field)
    if not isinstance(value, str) or not value:
        raise ResponseFormatError(msg)
    return value


def parse_context_info(r: Any) -> ContextInfo:
    """Extract the form digest and its lifetime from a `FormDigestResponse`.

    Falls back to SharePoint's 30-minute default when the lifetime is missing
    or not a positive integer.

    Args:
        r: The decoded `/_api/contextinfo` payload.

    Returns:
        A `ContextInfo` with the digest and its lifetime in seconds.

    Raises:
        ResponseFormatError: if the body is not an object or `FormDigestValue`
            is missing or not a non-empty string.
    """
    digest = parse_form_digest(r)
    timeout = r.get("FormDigestTimeoutSeconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        timeout = DEFAULT_DIGEST_TIMEOUT
    return {"digest": digest, "timeout": timeout}


def parse_form_digest(r: Any) -> str:
    """Extract `FormDigestValue` from a `FormDigestResponse`.

    Args:
        r: The decoded `/_api/contextinfo` payload.

    Returns:
        The form digest value.

    Raises:
        ResponseFormatError: if the body is not an object or the value is
            missing or not a non-empty string.
    """
    return _required_str(r, "FormDigestValue", "Form digest value")


def parse_item_type(r: Any) -> str:
    """Extract `ListItemEntityTypeFullName` from an `ItemTypeResponse`.

    Args:
        r: The decoded list metadata payload.

    Returns:
        The list item entity type full name, for example `SP.Data.TasksListItem`.

    Raises:
        ResponseFormatError: if the body is not an object or the value is
            missing or not a non-empty string.
    """
    return _required_str(r, "ListItemEntityTypeFullName", "List item type")


def parse_exists(r: Any) -> bool:
    """Extract the boolean `value` of an `.../Exists` response.

    Args:
        r: The decoded `.../Exists` payload.

    Returns:
        `True` if the resource exists, otherwise `False`.

    Raises:
        ResponseFormatError: if the body is not an object with a boolean `value`.
    """
    value = r.get("value") if isinstance(r, dict) else None
    if not isinstance(value, bool):
        msg = "Exists 'value'"
        raise ResponseFormatError(msg)
    return value


def parse_created_item(r: Any) -> dict[str, Any]:
    """Return the created list item from an add-item response, guaranteeing an integer `Id`.

    Accepts both the `nometadata` shape (flat object) and the `verbose` shape
    (`{"d": {...}}`).

    Args:
        r: The decoded add-item payload.

    Returns:
        The created item's fields, with `Id` set to its integer id (taken from `Id` or `ID`).

    Raises:
        ResponseFormatError: if the body is not an object or has no integer `Id`.
    """
    msg = "Created item"
    item = r.get("d", r) if isinstance(r, dict) else None
    if not isinstance(item, dict):
        raise ResponseFormatError(msg)
    sp_id = item.get("Id", item.get("ID"))
    if not isinstance(sp_id, int) or isinstance(sp_id, bool):
        msg = "Item id"
        raise ResponseFormatError(msg)
    return {**item, "Id": sp_id}


def parse_object(r: Any) -> dict[str, Any]:
    """Return a single SharePoint object from a response.

    Accepts both the `nometadata` shape (flat object) and the `verbose` shape
    (`{"d": {...}}`).

    Args:
        r: The decoded object payload.

    Returns:
        The object's fields, unwrapped from `d` when present.

    Raises:
        ResponseFormatError: if the body is not an object.
    """
    item = r.get("d", r) if isinstance(r, dict) else None
    if not isinstance(item, dict):
        msg = "Object response"
        raise ResponseFormatError(msg)
    return item


# ----------------------------- Legacy ----------------------------------------
def parse_add_item(r: AddItemResponse) -> int:
    """Extract `ID` from an add-item response.

    Deprecated: use `parse_created_item`, which returns the whole item. Removed in 2.0.

    Args:
        r: The decoded add-item payload.

    Returns:
        The new item's `ID`.

    Raises:
        ResponseFormatError: if `ID` is missing.
    """
    warnings.warn(
        "parse_add_item is deprecated and will be removed in sppyte 2.0; use parse_created_item",
        DeprecationWarning,
        stacklevel=2,
    )
    msg = "Item id"
    item_type = r.get("ID", -1)
    if item_type == -1:
        raise ResponseFormatError(msg)
    return item_type


def parse_add_document(r: AddDocumentResponse) -> str:
    """Extract `UniqueId` from an add-document response.

    Deprecated: use `parse_object`, which returns the whole `SP.File`. Removed in 2.0.

    Args:
        r: The decoded add-document payload.

    Returns:
        The new document's `UniqueId`.

    Raises:
        ResponseFormatError: if `UniqueId` is missing.
    """
    warnings.warn(
        "parse_add_document is deprecated and will be removed in sppyte 2.0; use parse_object",
        DeprecationWarning,
        stacklevel=2,
    )
    val = "Document id"
    item_type = r.get("UniqueId", val)
    if item_type == val:
        raise ResponseFormatError(val)
    return item_type
