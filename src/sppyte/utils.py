"""
sppyte.utils
~~~~~~~~~~~~

Response-parsing helpers. Each `parse_*` function pulls one value out of a
SharePoint JSON payload and raises `ResponseFormatError` if it is missing.

URL helpers live in `sppyte.odata` and are re-exported here for compatibility.
"""

from __future__ import annotations

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
]

DEFAULT_DIGEST_TIMEOUT = 1800
"""SharePoint's default form digest lifetime in seconds (30 minutes)."""


# ----------------------------- Types -----------------------------------------
class FormDigestResponse(TypedDict, total=False):
    """Minimal shape of the contextinfo JSON response (``odata=nometadata``)."""

    FormDigestValue: str
    FormDigestTimeoutSeconds: int


class ItemTypeResponse(TypedDict):
    """Response shape for list metadata to get the item entity type."""

    ListItemEntityTypeFullName: str


class AddItemResponse(TypedDict):
    """Response shape for adding a list item to return the new ID."""

    ID: int


class AddDocumentResponse(TypedDict):
    """Response shape for adding a document to return the UniqueId."""

    UniqueId: str


class ContextInfo(TypedDict):
    """Parsed ``/_api/contextinfo`` response."""

    digest: str
    timeout: int
    """Lifetime of `digest` in seconds."""


# ----------------------------- Methods ----------------------------------------
def parse_context_info(r: FormDigestResponse) -> ContextInfo:
    """
    Extract the form digest and its lifetime, or raise ResponseFormatError.

    Falls back to SharePoint's 30-minute default when the lifetime is missing
    or not a positive integer.
    """
    digest = parse_form_digest(r)
    timeout = r.get("FormDigestTimeoutSeconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        timeout = DEFAULT_DIGEST_TIMEOUT
    return {"digest": digest, "timeout": timeout}


def parse_form_digest(r: FormDigestResponse) -> str:
    """
    Extract FormDigestValue or raise ResponseFormatError if missing.
    """
    val = "Form digest value"
    form_digest = r.get("FormDigestValue", val)
    if form_digest == val:
        raise ResponseFormatError(val)
    return form_digest


def parse_item_type(r: ItemTypeResponse) -> str:
    """
    Extract ListItemEntityTypeFullName or raise ResponseFormatError if missing.
    """
    val = "List item type"
    item_type = r.get("ListItemEntityTypeFullName", val)
    if item_type == val:
        raise ResponseFormatError(val)
    return item_type


def parse_add_item(r: AddItemResponse) -> int:
    """
    Extract 'ID' from an Add Item response or raise ResponseFormatError.
    """
    msg = "Item id"
    item_type = r.get("ID", -1)
    if item_type == -1:
        raise ResponseFormatError(msg)
    return item_type


def parse_created_item(r: Any) -> dict[str, Any]:
    """
    Return the created list item from an Add Item response, guaranteeing an
    integer ``Id`` key. Accepts both the ``nometadata`` shape (flat object) and
    the ``verbose`` shape (``{"d": {...}}``). Raises ResponseFormatError
    otherwise.
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


def parse_add_document(r: AddDocumentResponse) -> str:
    """
    Extract 'UniqueId' from an Add Document response or raise ResponseFormatError.
    """
    val = "Document id"
    item_type = r.get("UniqueId", val)
    if item_type == val:
        raise ResponseFormatError(val)
    return item_type
