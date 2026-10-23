"""
sppyte.lists
~~~~~~~~~~~~

`List` — a thin wrapper around SharePoint list endpoints.
"""

from __future__ import annotations

from typing import IO, TYPE_CHECKING, Any

from sppyte.odata import Page, Params, follow_pages, odata_literal, parse_page
from sppyte.utils import parse_created_item, parse_item_type, parse_object

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sppyte.site import Site

JSON_NOMETADATA = "application/json;odata=nometadata"
JSON_VERBOSE = "application/json;odata=verbose"


class List:
    """
    Thin wrapper for SharePoint List endpoints.

    Obtain one from `Site.list(name)`. The `Site` owns the HTTP session; a
    `List` holds no resources of its own.
    """

    def __init__(self, name: str, site: Site):
        self.site = site
        self.name = name
        self._item_type: str | None = None

    def __repr__(self) -> str:
        return f"List({self.name!r}, {self.site!r})"

    @property
    def _base_path(self) -> str:
        """Site-relative REST path of this list, with the title escaped."""
        return f"_api/web/lists/GetByTitle('{odata_literal(self.name)}')"

    # ------------------------------------------------------------ metadata ----
    @property
    def item_type(self) -> str:
        """
        The list's ``ListItemEntityTypeFullName`` (e.g. ``SP.Data.TasksListItem``),
        fetched once and cached for the lifetime of this object.
        """
        if self._item_type is None:
            self._item_type = self.get_item_type()
        return self._item_type

    def get_item_type(self) -> str:
        """Fetch ``ListItemEntityTypeFullName`` from SharePoint and refresh the cache."""
        r = self.site.request(
            "get",
            self._base_path,
            headers={"Accept": JSON_NOMETADATA},
            params={"$select": "ListItemEntityTypeFullName"},
        )
        self._item_type = parse_item_type(r.json())
        return self._item_type

    def _with_metadata(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(fields)
        if "__metadata" not in payload:
            payload = {"__metadata": {"type": self.item_type}, **payload}
        return payload

    # --------------------------------------------------------------- reads ----
    def get_contents(self, params: Params = None) -> Page:
        """
        Return one page of list items; pass OData params like ``$select``,
        ``$filter``, ``$top``, etc. Example: ``get_contents({"$select": "Id,Title", "$top": 5})``

        SharePoint returns at most 100 items unless ``$top`` is given. The
        result is a `Page` (a ``list``); its ``next_link`` is set when more
        items remain. Use `iter_items` / `get_all_items` to follow it.
        """
        r = self.site.request(
            "get",
            f"{self._base_path}/items",
            headers={"Accept": JSON_NOMETADATA},
            params=params,
        )
        return parse_page(r.json())

    def iter_pages(self, params: Params = None, *, max_pages: int | None = None) -> Iterator[Page]:
        """Yield each page of items, following ``next_link`` until exhausted or `max_pages`."""
        return follow_pages(self.get_contents(params), self.site.get_page, max_pages)

    def iter_items(self, params: Params = None, *, max_pages: int | None = None) -> Iterator[dict[str, Any]]:
        """
        Yield every item across all pages, one request per page.

        Example: ``for task in tasks.iter_items({"$select": "Id,Title", "$top": 500}): ...``
        """
        for page in self.iter_pages(params, max_pages=max_pages):
            yield from page

    def get_all_items(self, params: Params = None, *, max_pages: int | None = None) -> list[dict[str, Any]]:
        """Collect every item across all pages into one list."""
        return list(self.iter_items(params, max_pages=max_pages))

    def get_item(self, sp_id: int) -> dict[str, Any]:
        """Fetch a single list item by SharePoint ID."""
        r = self.site.request(
            "get",
            f"{self._base_path}/items('{sp_id}')",
            headers={"Accept": JSON_NOMETADATA},
        )
        return r.json()

    # -------------------------------------------------------------- writes ----
    def add_item(self, item: Mapping[str, Any], *, digest: str | None = None) -> dict[str, Any]:
        """
        Add a list item and return it as SharePoint created it (including ``Id``).

        ``__metadata.type`` is added automatically from `item_type` unless the
        mapping already has one. `item` is not modified.

        Args:
            digest: Form digest to send instead of the managed one.
        """
        r = self.site.request(
            "post",
            f"{self._base_path}/items",
            headers={"Accept": JSON_NOMETADATA, "Content-Type": JSON_VERBOSE},
            json=self._with_metadata(item),
            digest=digest or True,
        )
        return parse_created_item(r.json())

    def update_item(self, sp_id: int, patch: Mapping[str, Any], *, digest: str | None = None) -> int:
        """
        Merge-update a list item (OData MERGE; fields you omit are untouched).

        ``__metadata.type`` is added automatically unless present. `patch` is
        not modified. Returns `sp_id`.
        """
        self.site.request(
            "post",
            f"{self._base_path}/items('{sp_id}')",
            headers={
                "Accept": JSON_NOMETADATA,
                "Content-Type": JSON_VERBOSE,
                "X-HTTP-Method": "MERGE",
                "If-Match": "*",
            },
            json=self._with_metadata(patch),
            digest=digest or True,
        )
        return sp_id

    def delete_item(self, sp_id: int, *, digest: str | None = None) -> bool:
        """Delete a list item by its SharePoint ID. Returns True; failures raise."""
        self.site.request(
            "post",
            f"{self._base_path}/items('{sp_id}')",
            headers={
                "Accept": JSON_NOMETADATA,
                "Content-Type": JSON_VERBOSE,
                "X-HTTP-Method": "DELETE",
                "If-Match": "*",
            },
            digest=digest or True,
        )
        return True

    def add_attachment(
        self,
        sp_id: int,
        file_name: str,
        attachment: IO[bytes] | bytes,
        *,
        digest: str | None = None,
    ) -> dict[str, Any]:
        """
        Add a file attachment to an existing list item.

        `attachment` can be bytes or a file-like object opened in binary mode.
        Returns the ``SP.Attachment`` object SharePoint created
        (``FileName``, ``ServerRelativeUrl``).
        """
        r = self.site.request(
            "post",
            f"{self._base_path}/items('{sp_id}')/AttachmentFiles/add(FileName='{odata_literal(file_name)}')",
            headers={"Accept": JSON_NOMETADATA, "Content-Type": "application/octet-stream"},
            data=attachment,
            digest=digest or True,
        )
        return parse_object(r.json())
