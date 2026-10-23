"""
sppyte.libraries
~~~~~~~~~~~~~~~~

`Library` — a thin wrapper around SharePoint document library endpoints.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from sppyte.odata import Page, Params, build_path, follow_pages, odata_literal, odata_path, parse_page
from sppyte.utils import parse_object

if TYPE_CHECKING:
    from collections.abc import Iterator

    from requests import Response

    from sppyte.site import Site

JSON_NOMETADATA = "application/json;odata=nometadata"
DEFAULT_CHUNK_SIZE = 64 * 1024

Document = bytes | IO[bytes] | str | os.PathLike[str]
"""Upload payload: raw bytes, a binary file object, or a path to open and stream."""


class Library:
    """
    Thin wrapper for SharePoint Document Library endpoints.

    Obtain one from `Site.library(name)`. The `Site` owns the HTTP session; a
    `Library` holds no resources of its own. Folder arguments are given as
    path segments: ``docs.add_folder("Reports", "2025")``.
    """

    def __init__(self, name: str, site: Site):
        self.site = site
        self.name = name

    def __repr__(self) -> str:
        return f"Library({self.name!r}, {self.site!r})"

    # --------------------------------------------------------------- paths ----
    def server_relative_url(self, *parts: str) -> str:
        """Server-relative URL of a path beneath this library (unescaped)."""
        return build_path(self.site.relative_url, self.name, *parts)

    def folder_path(self, *subfolders: str) -> str:
        """
        Site-relative REST path addressing a folder beneath this library
        (``_api/web/GetFolderByServerRelativeUrl('...')``, escaped). Useful
        for `Site.request` and `Batch` sub-requests.
        """
        return f"_api/web/GetFolderByServerRelativeUrl('{odata_path(self.server_relative_url(*subfolders))}')"

    def file_path(self, file_name: str, *subfolders: str) -> str:
        """
        Site-relative REST path addressing a file beneath this library
        (``_api/web/GetFileByServerRelativeUrl('...')``, escaped).
        """
        return f"_api/web/GetFileByServerRelativeUrl('{odata_path(self.server_relative_url(*subfolders, file_name))}')"

    # --------------------------------------------------------------- reads ----
    def folder_exists(self, folder: str, *subfolders: str) -> bool:
        """Return True if a folder path exists beneath this library."""
        r = self.site.request(
            "get",
            f"{self.folder_path(folder, *subfolders)}/Exists",
            headers={"Accept": JSON_NOMETADATA},
        )
        return r.json().get("value", False)

    def _collection(self, kind: str, subfolders: tuple[str, ...], params: Params) -> Page:
        r = self.site.request(
            "get",
            f"{self.folder_path(*subfolders)}/{kind}",
            headers={"Accept": JSON_NOMETADATA},
            params=params,
        )
        return parse_page(r.json())

    def list_contents(self, *subfolders: str, params: Params = None) -> Page:
        """
        List the files directly inside a folder (subfolders are not included).

        Each item is an ``SP.File`` object (``Name``, ``ServerRelativeUrl``,
        ``Length``, ``TimeLastModified``, …). Accepts OData params such as
        ``$select``, ``$top``, ``$filter``. The result is a `Page`; its
        ``next_link`` is set when more files remain.

        Example: ``list_contents("Reports", "2025", params={"$select": "Name"})``
        """
        return self._collection("Files", subfolders, params)

    def list_folders(self, *subfolders: str, params: Params = None) -> Page:
        """
        List the folders directly inside a folder.

        Each item is an ``SP.Folder`` object (``Name``, ``ServerRelativeUrl``,
        ``ItemCount``, …). Accepts OData params. Returns a `Page`.
        """
        return self._collection("Folders", subfolders, params)

    def iter_pages(self, *subfolders: str, params: Params = None, max_pages: int | None = None) -> Iterator[Page]:
        """Yield each page of files in a folder, following ``next_link``."""
        return follow_pages(self.list_contents(*subfolders, params=params), self.site.get_page, max_pages)

    def iter_files(
        self, *subfolders: str, params: Params = None, max_pages: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield every file in a folder across all pages, one request per page."""
        for page in self.iter_pages(*subfolders, params=params, max_pages=max_pages):
            yield from page

    def get_all_files(
        self, *subfolders: str, params: Params = None, max_pages: int | None = None
    ) -> list[dict[str, Any]]:
        """Collect every file in a folder across all pages into one list."""
        return list(self.iter_files(*subfolders, params=params, max_pages=max_pages))

    def _open_document(self, file_name: str, subfolders: tuple[str, ...]) -> Response:
        return self.site.request(
            "get",
            f"{self.folder_path(*subfolders)}/Files('{odata_literal(file_name)}')/$value",
            headers={"Accept": "application/octet-stream"},
            stream=True,
        )

    def get_document(self, file_name: str, *subfolders: str) -> bytes:
        """Download a file's binary contents into memory and return them."""
        with self._open_document(file_name, subfolders) as r:
            return r.content

    def iter_document(self, file_name: str, *subfolders: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
        """
        Stream a file's contents as chunks of bytes without holding the whole
        file in memory. HTTP errors are raised before the first chunk.

        Example: ``for chunk in docs.iter_document("big.iso", "ISOs"): out.write(chunk)``
        """
        with self._open_document(file_name, subfolders) as r:
            yield from r.iter_content(chunk_size=chunk_size)

    def download(
        self,
        file_name: str,
        dest: str | os.PathLike[str] | IO[bytes],
        *subfolders: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> int:
        """
        Stream a file to `dest` — a path (created or overwritten) or a binary
        file object (written at its current position, left open). Returns the
        number of bytes written.

        Example: ``docs.download("report.pdf", Path("~/report.pdf").expanduser(), "Reports")``
        """
        chunks = self.iter_document(file_name, *subfolders, chunk_size=chunk_size)
        if isinstance(dest, str | os.PathLike):
            with Path(dest).open("wb") as fh:
                return _write_all(fh, chunks)
        return _write_all(dest, chunks)

    # -------------------------------------------------------------- writes ----
    def add_folder(self, folder: str, *subfolders: str, digest: str | None = None) -> dict[str, Any]:
        """
        Create a (nested) folder path within the library. The parent must exist.

        Returns the ``SP.Folder`` object (``Name``, ``ServerRelativeUrl``,
        ``UniqueId``, ``Exists``, …). Creating a folder that already exists is
        not an error.
        """
        r = self.site.request(
            "post",
            "_api/web/folders",
            headers={"Accept": JSON_NOMETADATA, "Content-Type": "application/json"},
            json={"ServerRelativeUrl": self.server_relative_url(folder, *subfolders)},
            digest=digest or True,
        )
        return parse_object(r.json())

    def add_document(
        self,
        file_name: str,
        document: Document,
        *subfolders: str,
        overwrite: bool = True,
        digest: str | None = None,
    ) -> dict[str, Any]:
        """
        Upload a document into the given subfolder path.

        `document` is bytes, a binary file object (streamed), or a path to a
        file to open and stream. Returns the ``SP.File`` object SharePoint
        created (``Name``, ``ServerRelativeUrl``, ``UniqueId``, ``Length``, …).

        Args:
            overwrite: Replace an existing file with the same name (default). With
                ``False`` SharePoint answers 400 (`SharePointError`) if it exists.
            digest: Form digest to send instead of the managed one.
        """
        flag = "true" if overwrite else "false"
        path = f"{self.folder_path(*subfolders)}/Files/add(url='{odata_literal(file_name)}',overwrite={flag})"
        headers = {"Accept": JSON_NOMETADATA, "Content-Type": "application/octet-stream"}
        if isinstance(document, str | os.PathLike):
            with Path(document).open("rb") as fh:
                r = self.site.request("post", path, headers=headers, data=fh, digest=digest or True)
        else:
            r = self.site.request("post", path, headers=headers, data=document, digest=digest or True)
        return parse_object(r.json())

    def delete_document(self, file_name: str, *subfolders: str, digest: str | None = None) -> bool:
        """Delete a document by name within an optional nested folder path. Returns True."""
        self.site.request(
            "post",
            self.file_path(file_name, *subfolders),
            headers={"If-Match": "*", "X-HTTP-Method": "DELETE"},
            digest=digest or True,
        )
        return True

    def delete_folder(self, folder: str, *subfolders: str, digest: str | None = None) -> bool:
        """Delete a folder path. Returns True; failures raise."""
        self.site.request(
            "post",
            self.folder_path(folder, *subfolders),
            headers={"If-Match": "*", "X-HTTP-Method": "DELETE"},
            digest=digest or True,
        )
        return True


def _write_all(fh: IO[bytes], chunks: Iterator[bytes]) -> int:
    written = 0
    for chunk in chunks:
        if chunk:
            fh.write(chunk)
            written += len(chunk)
    return written
