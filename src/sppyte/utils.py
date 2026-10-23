"""Response-parsing helpers.

Each `parse_*` function pulls one value out of a SharePoint JSON payload and
raises `ResponseFormatError` if it is missing. URL helpers live in
`sppyte.odata` and are re-exported here for compatibility with 0.x.
"""

from __future__ import annotations

import warnings
from typing import Any, TypedDict

from sppyte.errors import ResponseFormatError
from sppyte.odata import build_path, odata_literal, odata_path

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
    "parse_form_digest",
    "parse_item_type",
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
def parse_context_info(r: FormDigestResponse) -> ContextInfo:
    """Extract the form digest and its lifetime.

    Falls back to SharePoint's 30-minute default when the lifetime is missing
    or not a positive integer.

    Raises:
        ResponseFormatError: if `FormDigestValue` is missing.
    """
    digest = parse_form_digest(r)
    timeout = r.get("FormDigestTimeoutSeconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        timeout = DEFAULT_DIGEST_TIMEOUT
    return {"digest": digest, "timeout": timeout}


def parse_form_digest(r: FormDigestResponse) -> str:
    """Extract `FormDigestValue`.

    Raises:
        ResponseFormatError: if it is missing.
    """
    val = "Form digest value"
    form_digest = r.get("FormDigestValue", val)
    if form_digest == val:
        raise ResponseFormatError(val)
    return form_digest


def parse_item_type(r: ItemTypeResponse) -> str:
    """Extract `ListItemEntityTypeFullName`.

    Raises:
        ResponseFormatError: if it is missing.
    """
    val = "List item type"
    item_type = r.get("ListItemEntityTypeFullName", val)
    if item_type == val:
        raise ResponseFormatError(val)
    return item_type


def parse_created_item(r: Any) -> dict[str, Any]:
    """Return the created list item from an add-item response, guaranteeing an integer `Id`.

    Accepts both the `nometadata` shape (flat object) and the `verbose` shape
    (`{"d": {...}}`).

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

    Deprecated: use `parse_created_item`, which returns the whole item.

    Raises:
        ResponseFormatError: if `ID` is missing.
    """
    warnings.warn(
        "parse_add_item is deprecated; use parse_created_item",
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

    Deprecated: use `parse_object`, which returns the whole `SP.File`.

    Raises:
        ResponseFormatError: if `UniqueId` is missing.
    """
    warnings.warn(
        "parse_add_document is deprecated; use parse_object",
        DeprecationWarning,
        stacklevel=2,
    )
    val = "Document id"
    item_type = r.get("UniqueId", val)
    if item_type == val:
        raise ResponseFormatError(val)
    return item_type
