from error import ResponseFormatError
from requests import Response


def build_path(*parts: str):
    path = "/".join([p.strip("/") for p in parts if p is not None])
    return f"/{path}" if path else "/"


def parse_form_digest(r: Response) -> str:
    val = "Form digest value"
    form_digest = r.json().get("d", val).get("GetContextWebInformation", val).get("FormDigestValue", val)
    if form_digest == val:
        raise ResponseFormatError(val)
    return form_digest


def parse_item_type(r: Response) -> str:
    val = "List item type"
    item_type = r.json().get("ListItemEntityTypeFullName", val)
    if item_type == val:
        raise ResponseFormatError(val)
    return item_type


def parse_add_item(r: Response) -> int:
    val = "Item id"
    item_type = r.json().get("ID", val)
    if item_type == val:
        raise ResponseFormatError(val)
    return item_type


def parse_add_document(r: Response) -> str:
    val = "Document id"
    item_type = r.json().get("UniqueId", val)
    if item_type == val:
        raise ResponseFormatError(val)
    return item_type
