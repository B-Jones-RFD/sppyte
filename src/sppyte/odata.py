"""Helpers for building SharePoint REST / OData URLs and reading collection responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypeAlias
from urllib.parse import quote

from sppyte.errors import ResponseFormatError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

JSON_NOMETADATA = "application/json;odata=nometadata"
"""`Accept` value that makes SharePoint return plain JSON (no `d` wrapper, no `__metadata`)."""

JSON_VERBOSE = "application/json;odata=verbose"
"""`Content-Type` SharePoint requires for JSON request bodies."""

ParamValue: TypeAlias = str | int
Params: TypeAlias = Mapping[str, ParamValue] | Sequence[tuple[str, ParamValue]] | None
"""OData query options such as `{"$select": "Id,Title", "$top": 5}`."""


def build_path(*parts: str | None) -> str:
    """Join path segments into a normalized server-relative path.

    Empty and `None` segments are skipped; surrounding slashes are trimmed.

    Example:
        `build_path("sites/demo", "Shared Documents", "Reports")`
        returns `"/sites/demo/Shared Documents/Reports"`.
    """
    segments = [p.strip("/") for p in parts if p]
    path = "/".join(segment for segment in segments if segment)
    return f"/{path}" if path else "/"


def odata_literal(value: str) -> str:
    """Escape a value for use inside an OData string literal (`'...'`) in a URL path.

    Apostrophes are doubled per OData and the result is percent-encoded so that
    spaces, `#`, `%`, `?` and `&` cannot break the URL. The doubled apostrophes
    survive encoding because SharePoint expects them literally.

    Example:
        `odata_literal("O'Brien's #1 Report")` returns `"O''Brien''s%20%231%20Report"`.
    """
    return quote(value.replace("'", "''"), safe="'")


def odata_path(path: str) -> str:
    """Escape a server-relative path for use inside an OData string literal.

    Each `/`-separated segment is passed through `odata_literal`, so slashes are
    preserved while everything else is escaped.

    Example:
        `odata_path("/sites/demo/Shared Documents/Q1 '25")`
        returns `"/sites/demo/Shared%20Documents/Q1%20''25"`.
    """
    return "/".join(odata_literal(segment) for segment in path.split("/"))


class Page(list[dict[str, Any]]):
    """One page of results: a `list` of items plus the link to the next page.

    `next_link` is the URL of the following page when SharePoint has more items,
    and `None` otherwise. A `Page` behaves exactly like a list, so
    `for item in site.list("Tasks").get_contents()` keeps working. Follow
    `next_link` with `Site.get_page`, or use the `iter_*` / `get_all_*` helpers.
    """

    __slots__ = ("next_link",)

    def __init__(self, items: Iterable[dict[str, Any]] = (), next_link: str | None = None):
        super().__init__(items)
        self.next_link = next_link

    def __repr__(self) -> str:
        more = f", next_link={self.next_link!r}" if self.next_link else ""
        return f"Page({list.__repr__(self)}{more})"


def parse_page(payload: Any) -> Page:
    """Build a `Page` from an OData collection response (`odata=nometadata`).

    Reads the `value` array and `odata.nextLink` (or `@odata.nextLink`). A
    missing `value` yields an empty page.

    Raises:
        ResponseFormatError: if the payload is not an object or `value` is not a list.
    """
    if not isinstance(payload, dict):
        msg = "Collection response"
        raise ResponseFormatError(msg)
    items = payload.get("value", [])
    if not isinstance(items, list):
        msg = "Collection 'value'"
        raise ResponseFormatError(msg)
    link = payload.get("odata.nextLink", payload.get("@odata.nextLink"))
    return Page(items, link if isinstance(link, str) and link else None)


def follow_pages(
    first: Page,
    fetch_next: Callable[[str], Page],
    max_pages: int | None = None,
) -> Iterator[Page]:
    """Yield `first`, then each following page until `next_link` runs out or `max_pages` is reached.

    Args:
        first: The page to start from.
        fetch_next: Fetches the page a `next_link` points at (normally `Site.get_page`).
        max_pages: Stop after this many pages even if more remain; `None` for no limit.
    """
    page = first
    count = 1
    while True:
        yield page
        if page.next_link is None or (max_pages is not None and count >= max_pages):
            return
        page = fetch_next(page.next_link)
        count += 1
