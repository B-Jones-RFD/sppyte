"""
sppyte.libraries
~~~~~~~~~~~~~~~~

`Library` — a thin wrapper around SharePoint document library endpoints.
"""

from __future__ import annotations

from typing import IO, TYPE_CHECKING, Any

from sppyte.odata import Params, build_path, odata_literal, odata_path
from sppyte.utils import parse_add_document

if TYPE_CHECKING:
    from sppyte.site import Site

JSON_NOMETADATA = "application/json;odata=nometadata"


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

    def _folder_path(self, *parts: str) -> str:
        """Site-relative REST path addressing a folder beneath this library."""
        return f"_api/web/GetFolderByServerRelativeUrl('{odata_path(self.server_relative_url(*parts))}')"

    def _file_path(self, *parts: str) -> str:
        """Site-relative REST path addressing a file beneath this library."""
        return f"_api/web/GetFileByServerRelativeUrl('{odata_path(self.server_relative_url(*parts))}')"

    # --------------------------------------------------------------- reads ----
    def folder_exists(self, folder: str, *subfolders: str) -> bool:
        """Return True if a folder path exists beneath this library."""
        r = self.site.request(
            "get",
            f"{self._folder_path(folder, *subfolders)}/Exists",
            headers={"Accept": JSON_NOMETADATA},
        )
        return r.json().get("value", False)

    def list_contents(self, *subfolders: str, params: Params = None) -> list[dict[str, Any]]:
        """
        List file metadata within a folder path (files only, not subfolders).

        Accepts OData params such as ``$select``, ``$top``, etc.
        Example: ``list_contents("Reports", "2025", params={"$select": "Name"})``
        """
        r = self.site.request(
            "get",
            f"{self._folder_path(*subfolders)}/Files",
            headers={"Accept": JSON_NOMETADATA},
            params=params,
        )
        return r.json().get("value", [])

    def get_document(self, file_name: str, *subfolders: str) -> bytes:
        """Download a file's binary contents into memory and return them."""
        r = self.site.request(
            "get",
            f"{self._folder_path(*subfolders)}/Files('{odata_literal(file_name)}')/$value",
            headers={"Accept": JSON_NOMETADATA},
            stream=True,
        )
        return r.content

    # -------------------------------------------------------------- writes ----
    def add_folder(self, folder: str, *subfolders: str, digest: str | None = None) -> bool:
        """
        Create a (nested) folder path within the library. The parent must exist.

        Returns True if the folder exists after the call (created or pre-existing).
        """
        r = self.site.request(
            "post",
            "_api/web/folders",
            headers={"Accept": JSON_NOMETADATA, "Content-Type": "application/json"},
            json={"ServerRelativeUrl": self.server_relative_url(folder, *subfolders)},
            digest=digest or True,
        )
        return r.json().get("Exists", False)

    def add_document(
        self,
        file_name: str,
        document: IO[bytes] | bytes,
        *subfolders: str,
        digest: str | None = None,
    ) -> str:
        """
        Upload a document into the given subfolder path, overwriting any existing
        file with the same name. Returns the document ``UniqueId``.

        `document` is bytes or a binary file-like object (e.g. ``open(path, "rb")``).
        File objects are streamed; a seekable one can be re-sent if the digest
        has to be refreshed, a non-seekable one cannot.
        """
        r = self.site.request(
            "post",
            f"{self._folder_path(*subfolders)}/Files/add(url='{odata_literal(file_name)}',overwrite=true)",
            headers={"Accept": JSON_NOMETADATA, "Content-Type": "application/octet-stream"},
            data=document,
            digest=digest or True,
        )
        return parse_add_document(r.json())

    def delete_document(self, file_name: str, *subfolders: str, digest: str | None = None) -> bool:
        """Delete a document by name within an optional nested folder path. Returns True."""
        self.site.request(
            "post",
            self._file_path(*subfolders, file_name),
            headers={"If-Match": "*", "X-HTTP-Method": "DELETE"},
            digest=digest or True,
        )
        return True

    def delete_folder(self, folder: str, *subfolders: str, digest: str | None = None) -> bool:
        """Delete a folder path. Returns True; failures raise."""
        self.site.request(
            "post",
            self._folder_path(folder, *subfolders),
            headers={"If-Match": "*", "X-HTTP-Method": "DELETE"},
            digest=digest or True,
        )
        return True
