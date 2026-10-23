"""`List`: a thin wrapper around SharePoint list endpoints."""

from __future__ import annotations

import re
from typing import IO, TYPE_CHECKING, Any

from sppyte.errors import ResponseFormatError
from sppyte.odata import JSON_NOMETADATA, JSON_VERBOSE, Page, Params, follow_pages, odata_literal, parse_page
from sppyte.utils import parse_created_item, parse_item_type, parse_object

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sppyte.site import Site

_ROW_LIMIT_RE = re.compile(r"<RowLimit(?:\s[^>]*)?>\s*(\d+)\s*</RowLimit>", re.IGNORECASE)


class List:
    """Thin wrapper for SharePoint list endpoints.

    Obtain one from `Site.list(name)`. The `Site` owns the HTTP session; a
    `List` holds no resources of its own.

    Args:
        name: The list **title** as shown in SharePoint (not the URL segment).
        site: The site the list belongs to.
    """

    def __init__(self, name: str, site: Site):
        self.site = site
        self.name = name
        self._item_type: str | None = None

    def __repr__(self) -> str:
        return f"List({self.name!r}, {self.site!r})"

    @property
    def path(self) -> str:
        """Site-relative REST path of this list, with the title escaped.

        For example `_api/web/lists/GetByTitle('Tasks')`. Useful for `Site.request`
        and `Batch` sub-requests: `f"{tasks.path}/items"`.
        """
        return f"_api/web/lists/GetByTitle('{odata_literal(self.name)}')"

    # ------------------------------------------------------------ metadata ----
    @property
    def item_type(self) -> str:
        """The list's `ListItemEntityTypeFullName`, e.g. `SP.Data.TasksListItem`.

        Fetched once and cached for the lifetime of this object.
        """
        if self._item_type is None:
            self._item_type = self.get_item_type()
        return self._item_type

    def get_item_type(self) -> str:
        """Fetch `ListItemEntityTypeFullName` from SharePoint and refresh the cache."""
        r = self.site.request(
            "get",
            self.path,
            headers={"Accept": JSON_NOMETADATA},
            params={"$select": "ListItemEntityTypeFullName"},
        )
        self._item_type = parse_item_type(r.json())
        return self._item_type

    def _with_metadata(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        """Return a copy of `fields` with `__metadata.type` added unless already present."""
        payload = dict(fields)
        if "__metadata" not in payload:
            payload = {"__metadata": {"type": self.item_type}, **payload}
        return payload

    # --------------------------------------------------------------- reads ----
    def get_contents(self, params: Params = None) -> Page:
        """Return one page of list items.

        SharePoint returns at most 100 items unless `$top` is given. The result
        is a `Page` (a `list`) whose `next_link` is set when more items remain;
        use `iter_items` or `get_all_items` to follow it.

        Args:
            params: OData options, e.g. `{"$select": "Id,Title", "$top": 5}`.
        """
        r = self.site.request(
            "get",
            f"{self.path}/items",
            headers={"Accept": JSON_NOMETADATA},
            params=params,
        )
        return parse_page(r.json())

    def iter_pages(self, params: Params = None, *, max_pages: int | None = None) -> Iterator[Page]:
        """Yield each page of items, following `next_link` until exhausted or `max_pages`.

        Args:
            params: OData options for the first page.
            max_pages: Stop after this many pages; `None` for no limit.
        """
        return follow_pages(self.get_contents(params), self.site.get_page, max_pages)

    def iter_items(self, params: Params = None, *, max_pages: int | None = None) -> Iterator[dict[str, Any]]:
        """Yield every item across all pages, one request per page.

        Args:
            params: OData options for the first page.
            max_pages: Stop after this many pages; `None` for no limit.

        Example:
            `for task in tasks.iter_items({"$select": "Id,Title", "$top": 500}): ...`
        """
        for page in self.iter_pages(params, max_pages=max_pages):
            yield from page

    def get_all_items(self, params: Params = None, *, max_pages: int | None = None) -> list[dict[str, Any]]:
        """Collect every item across all pages into one list.

        Args:
            params: OData options for the first page.
            max_pages: Stop after this many pages; `None` for no limit.
        """
        return list(self.iter_items(params, max_pages=max_pages))

    def get_item(self, sp_id: int) -> dict[str, Any]:
        """Fetch a single list item by its SharePoint `Id`."""
        r = self.site.request(
            "get",
            f"{self.path}/items('{sp_id}')",
            headers={"Accept": JSON_NOMETADATA},
        )
        return r.json()

    # ---------------------------------------------------------------- CAML ----
    def query(
        self,
        view_xml: str,
        *,
        paging_info: str | None = None,
        params: Params = None,
        digest: str | None = None,
    ) -> Page:
        """Run a CAML query (`POST .../GetItems`) and return the matching items.

        Use this instead of `$filter` on lists above the 5,000-item view
        threshold: a `<Where>` on an indexed column is evaluated by SQL Server
        and is not subject to it. Page with `<RowLimit>` in the view and
        `paging_info` (`"Paged=TRUE&p_ID=<last Id>"`), or let `iter_query` do it.

        Args:
            view_xml: CAML `<View>` XML, e.g. `<View><Query><Where><Eq><FieldRef Name='Status'/>
                <Value Type='Text'>Open</Value></Eq></Where></Query><RowLimit>500</RowLimit></View>`.
            paging_info: Position token for the next page; omit for the first.
            params: OData options such as `$select` / `$expand` (`$filter` and `$top`
                belong in the CAML).
            digest: Form digest to send instead of the managed one (`GetItems` is a POST).
        """
        query: dict[str, Any] = {"__metadata": {"type": "SP.CamlQuery"}, "ViewXml": view_xml}
        if paging_info is not None:
            query["ListItemCollectionPosition"] = {"PagingInfo": paging_info}
        r = self.site.request(
            "post",
            f"{self.path}/GetItems",
            headers={"Accept": JSON_NOMETADATA, "Content-Type": JSON_VERBOSE},
            params=params,
            json={"query": query},
            digest=digest or True,
            retry=True,  # GetItems is a POST but idempotent, so the read policy applies
        )
        return parse_page(r.json())

    def iter_query(
        self,
        view_xml: str,
        *,
        params: Params = None,
        max_pages: int | None = None,
        digest: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield every item matching a CAML query, one `GetItems` request per page.

        `view_xml` must contain a `<RowLimit>`; each page is requested with
        `Paged=TRUE&p_ID=<Id of the last item>`, which assumes the view is
        ordered by ID ascending (the default when no `<OrderBy>` is given).
        Include `Id` in `$select` if you restrict the columns.

        Args:
            view_xml: CAML `<View>` XML containing a `<RowLimit>`.
            params: OData options such as `$select` / `$expand`.
            max_pages: Stop after this many pages; `None` for no limit.
            digest: Form digest to send instead of the managed one.

        Raises:
            ValueError: if `view_xml` has no `<RowLimit>`.
            ResponseFormatError: if a page's last item has no integer `Id`.
        """
        match = _ROW_LIMIT_RE.search(view_xml)
        if not match:
            msg = "iter_query needs a <RowLimit> in view_xml to page"
            raise ValueError(msg)
        row_limit = int(match.group(1))
        paging_info: str | None = None
        count = 0
        while True:
            page = self.query(view_xml, paging_info=paging_info, params=params, digest=digest)
            yield from page
            count += 1
            if len(page) < row_limit or (max_pages is not None and count >= max_pages):
                return
            last = page[-1]
            sp_id = last.get("Id", last.get("ID"))
            if not isinstance(sp_id, int) or isinstance(sp_id, bool):
                msg = "Item id (include Id in $select to page a CAML query)"
                raise ResponseFormatError(msg)
            paging_info = f"Paged=TRUE&p_ID={sp_id}"

    def query_all(
        self,
        view_xml: str,
        *,
        params: Params = None,
        max_pages: int | None = None,
        digest: str | None = None,
    ) -> list[dict[str, Any]]:
        """Collect every item matching a CAML query across pages (see `iter_query`).

        Args:
            view_xml: CAML `<View>` XML containing a `<RowLimit>`.
            params: OData options such as `$select` / `$expand`.
            max_pages: Stop after this many pages; `None` for no limit.
            digest: Form digest to send instead of the managed one.
        """
        return list(self.iter_query(view_xml, params=params, max_pages=max_pages, digest=digest))

    # -------------------------------------------------------------- writes ----
    def add_item(self, item: Mapping[str, Any], *, digest: str | None = None) -> dict[str, Any]:
        """Add a list item and return it as SharePoint created it (including `Id`).

        `__metadata.type` is added automatically from `item_type` unless the
        mapping already has one. `item` is not modified.

        Args:
            item: Field values for the new item.
            digest: Form digest to send instead of the managed one.
        """
        r = self.site.request(
            "post",
            f"{self.path}/items",
            headers={"Accept": JSON_NOMETADATA, "Content-Type": JSON_VERBOSE},
            json=self._with_metadata(item),
            digest=digest or True,
        )
        return parse_created_item(r.json())

    def update_item(self, sp_id: int, patch: Mapping[str, Any], *, digest: str | None = None) -> int:
        """Merge-update a list item (OData MERGE; fields you omit are untouched).

        `__metadata.type` is added automatically unless present. `patch` is not
        modified.

        Args:
            sp_id: SharePoint `Id` of the item.
            patch: Fields to change.
            digest: Form digest to send instead of the managed one.

        Returns:
            `sp_id`, for convenience.
        """
        self.site.request(
            "post",
            f"{self.path}/items('{sp_id}')",
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
        """Delete a list item by its SharePoint `Id`.

        Args:
            sp_id: SharePoint `Id` of the item.
            digest: Form digest to send instead of the managed one.

        Returns:
            `True`; failures raise.
        """
        self.site.request(
            "post",
            f"{self.path}/items('{sp_id}')",
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
        """Add a file attachment to an existing list item.

        Args:
            sp_id: SharePoint `Id` of the item.
            file_name: Attachment file name, including extension.
            attachment: Bytes or a file-like object opened in binary mode.
            digest: Form digest to send instead of the managed one.

        Returns:
            The `SP.Attachment` object SharePoint created (`FileName`, `ServerRelativeUrl`).
        """
        r = self.site.request(
            "post",
            f"{self.path}/items('{sp_id}')/AttachmentFiles/add(FileName='{odata_literal(file_name)}')",
            headers={"Accept": JSON_NOMETADATA, "Content-Type": "application/octet-stream"},
            data=attachment,
            digest=digest or True,
        )
        return parse_object(r.json())
