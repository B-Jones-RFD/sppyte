from requests import Response

from .error import ResponseFormatError


def build_path(*parts: str):
    path = "/".join([p.strip("/") for p in parts if p is not None])
    return f"/{path}" if path else "/"


def parse_form_digest(r: Response) -> str:
    default = "Not Found"
    form_digest = (
        r.json()
        .get("d", default)
        .get("GetContextWebInformation", default)
        .get("FormDigestValue", default)
    )
    if form_digest == default:
        raise ResponseFormatError("Unable parse form digest value.")
    return form_digest


def parse_item_type(r: Response) -> str:
    default = "Not Found"
    item_type = r.json().get("ListItemEntityTypeFullName", default)
    if item_type == default:
        raise ResponseFormatError("Unable parse item type value.")
    return item_type


def parse_add_item(r: Response) -> int:
    default = "Not Found"
    item_type = r.json().get("ID", default)
    if item_type == default:
        raise ResponseFormatError("Unable parse item type value.")
    return item_type


def parse_add_document(r: Response) -> str:
    default = "Not Found"
    item_type = r.json().get("UniqueId", default)
    if item_type == default:
        raise ResponseFormatError("Unable parse document id value.")
    return item_type
