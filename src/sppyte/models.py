"""
sppyte.models
~~~~~~~~~~~~~~~

This module contains models that mirror SharePoint objects.

This module exposes three main classes:
- Site: manages NTLM-authenticated session + form digest.
- List: light wrapper to CRUD SharePoint list items and attachments.
- Library: light wrapper to manage document libraries (folders/files).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import IO, Any, TypeAlias

from requests import Response, Session
from requests_ntlm import HttpNtlmAuth

from sppyte.errors import SessionError
from sppyte.utils import (
    build_path,
    odata_literal,
    odata_path,
    parse_add_document,
    parse_add_item,
    parse_form_digest,
    parse_item_type,
)

FORBIDDEN = 403


ParamValue: TypeAlias = str | int
Params: TypeAlias = Mapping[str, ParamValue] | Sequence[tuple[str, ParamValue]] | None


class Site:
    """
    Represents a SharePoint site connection.

    - Establishes an NTLM-authenticated requests Session.
    - Fetches a form digest value (anti-forgery token) required by SharePoint
      for write operations.
    - Access List and Library APIs for this Site.

    Use as a context manager to ensure the HTTP session is closed:

        with Site(host, site_relative_url, username, password) as site:
            docs = site.library("Shared Documents")
            docs.add_folder("Reports", "2025")
    """

    def __init__(
        self,
        host: str,
        site_relative_url: str,
        username: str,
        password: str,
    ):
        # Normalize and store basic connection info.
        self.site_path = f"{host.rstrip('/')}/{site_relative_url.strip('/')}"
        self.relative_url = site_relative_url
        self.username = username
        self.password = password
        self.session: Session | None = None
        self.form_digest: str | None = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _replay(self, method: str, url: str, **kwargs) -> Response:
        self.connect()

        if isinstance(self.session, Session):
            r = self.session.request(method, url, **kwargs)
            r.raise_for_status()
            return r

        msg = "SharePoint session not connected"
        raise SessionError(msg)

    def request(self, method: str, path: str, **kwargs) -> Response:
        """
        Perform an HTTP request against the site, raising for non-2xx responses.

        Parameters mirror requests.Session.request. `path` should be relative to
        the site root. Leading/trailing slashes are handled defensively.
        """
        url = f"{self.site_path.rstrip('/')}/{path.strip('/')}"
        if isinstance(self.session, Session):
            r = self.session.request(method, url, **kwargs)
            if r.status_code == FORBIDDEN:
                return self._replay(method, url, **kwargs)
            r.raise_for_status()
            return r

        return self._replay(method, url, **kwargs)

    def get_form_digest(self) -> str:
        """Request the form digest required for write calls."""
        r = self.request(
            method="post",
            path="/_api/contextinfo",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/json;odata=verbose",
            },
            data="",
        )
        return parse_form_digest(r.json())

    def connect(self) -> None:
        """Create the NTLM-authenticated session and fetch a form digest."""
        session = Session()
        session.auth = HttpNtlmAuth(self.username, self.password)
        self.session = session
        self.form_digest = self.get_form_digest()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        if self.session is not None:
            self.session.close()

    def list(self, name: str) -> List:
        """
        Build a List for this site (connects if needed).
        Example: site.list("Tasks").get_contents()
        """
        if self.session is None:
            self.connect()
        return List(name, self)

    def library(self, name: str) -> Library:
        """
        Build a Library for this site (connects if needed).
        Example: site.library("Shared Documents").list_contents()
        """
        if self.session is None:
            self.connect()
        return Library(name, self)


class List:
    """Thin wrapper for SharePoint List endpoints."""

    def __init__(self, name: str, site: Site):
        self.site = site
        self.name = name

    def __enter__(self):
        self.site.connect()
        return self

    def __exit__(self, *args) -> None:
        self.site.close()

    @property
    def _base_path(self) -> str:
        """Site-relative REST path of this list, with the title escaped."""
        return f"_api/web/lists/GetByTitle('{odata_literal(self.name)}')"

    def connect(self) -> None:
        """Create the NTLM-authenticated session and fetch a form digest."""
        self.site.connect()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.site.close()

    def add_item(self, item: Mapping[str, Any]) -> int:
        """
        Add a list item.

        List item entity type metadata (ie. `__metadata.type`) will be added automatically.
        The `item` mapping is not modified. Returns the SharePoint item ID.
        """
        payload = dict(item)
        if "__metadata" not in payload:
            payload = {"__metadata": {"type": self.get_item_type()}, **payload}

        r = self.site.request(
            method="post",
            path=f"{self._base_path}/items",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/json;odata=verbose",
                "X-RequestDigest": self.site.form_digest,
            },
            json=payload,
        )
        return parse_add_item(r.json())

    def add_attachment(self, sp_id: int, file_name: str, attachment: IO[bytes] | bytes) -> int:
        """
        Add a file attachment to an existing list item.

        `attachment` can be bytes or a file-like object opened in binary mode.
        Returns the original item ID for convenience.
        """
        self.site.request(
            method="post",
            path=f"{self._base_path}/items('{sp_id}')/AttachmentFiles/add(FileName='{odata_literal(file_name)}')",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/json;odata=verbose",
                "X-RequestDigest": self.site.form_digest,
            },
            data=attachment,
        )
        return sp_id

    def delete_item(self, sp_id: int) -> bool:
        """
        Delete a list item by its SharePoint ID.
        Returns True if the request was successful. Failures raise HTTPClient error from Requests.
        """
        self.site.request(
            method="post",
            path=f"{self._base_path}/items('{sp_id}')",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/json;odata=verbose",
                "X-HTTP-Method": "DELETE",
                "If-Match": "*",
                "X-RequestDigest": self.site.form_digest,
            },
        )
        return True

    def get_contents(self, params: Params = None) -> list[dict[str, Any]]:
        """
        Return list items; pass OData params like $select, $filter,
        $top, etc. Example: get_contents({"$select": "Id,Title", "$top": 5})

        SharePoint returns at most 100 items unless `$top` is given.
        """
        r = self.site.request(
            method="get",
            path=f"{self._base_path}/items",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
            params=params,
        )
        return r.json().get("value", [])

    def get_item_type(self) -> str:
        """
        Fetch the ListItemEntityTypeFullName required for typed list writes.
        """
        r = self.site.request(
            method="get",
            path=self._base_path,
            headers={
                "Accept": "application/json;odata=nometadata",
            },
            params={"$select": "ListItemEntityTypeFullName"},
        )
        return parse_item_type(r.json())

    def get_item(self, sp_id: int) -> dict[str, Any]:
        """Fetch a single list item by SharePoint ID."""
        r = self.site.request(
            method="get",
            path=f"{self._base_path}/items('{sp_id}')",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
        )
        return r.json()

    def update_item(self, sp_id: int, patch: Mapping[str, Any]) -> int:
        """
        Merge-update a list item. Provide a patch mapping of fields to be updated.

        List item entity type metadata (ie. `__metadata.type`) will be added automatically.
        The `patch` mapping is not modified. Returns the item ID.
        """
        payload = dict(patch)
        if "__metadata" not in payload:
            payload = {"__metadata": {"type": self.get_item_type()}, **payload}

        self.site.request(
            method="post",
            path=f"{self._base_path}/items('{sp_id}')",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/json;odata=verbose",
                # SharePoint uses MERGE for partial updates.
                "X-HTTP-Method": "MERGE",
                "If-Match": "*",
                "X-RequestDigest": self.site.form_digest,
            },
            json=payload,
        )
        return sp_id


class Library:
    """Thin wrapper for SharePoint Document Library endpoints."""

    def __init__(self, name: str, site: Site):
        self.site = site
        self.name = name

    def __enter__(self):
        self.site.connect()
        return self

    def __exit__(self, *args) -> None:
        self.site.close()

    def connect(self) -> None:
        """Create the NTLM-authenticated session and fetch a form digest."""
        self.site.connect()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.site.close()

    def _server_relative_url(self, *parts: str) -> str:
        """Server-relative URL of a path beneath this library (unescaped)."""
        return build_path(self.site.relative_url, self.name, *parts)

    def _folder_path(self, *parts: str) -> str:
        """Site-relative REST path addressing a folder beneath this library."""
        return f"_api/web/GetFolderByServerRelativeUrl('{odata_path(self._server_relative_url(*parts))}')"

    def _file_path(self, *parts: str) -> str:
        """Site-relative REST path addressing a file beneath this library."""
        return f"_api/web/GetFileByServerRelativeUrl('{odata_path(self._server_relative_url(*parts))}')"

    def add_folder(self, folder: str, *subfolders: str) -> bool:
        """
        Create a (nested) folder path within the library.

        Returns True if the folder already exists (per API) or was created.
        """
        r = self.site.request(
            method="post",
            path="_api/web/folders",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/json",
                "X-RequestDigest": self.site.form_digest,
            },
            json={
                "ServerRelativeUrl": self._server_relative_url(folder, *subfolders),
            },
        )
        return r.json().get("Exists", False)

    def add_document(
        self,
        file_name: str,
        document: IO[bytes] | bytes,
        *subfolders: str,
    ) -> str:
        """
        Upload a document (streamed) into the given subfolder path.

        Returns the document UniqueId. `document` should be bytes or a binary
        file-like object (e.g., open('file.pdf', 'rb')).
        """
        r = self.site.request(
            method="post",
            path=f"{self._folder_path(*subfolders)}/Files/add(url='{odata_literal(file_name)}',overwrite=true)",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/octet-stream",
                "X-RequestDigest": self.site.form_digest,
            },
            # requests will stream file-like objects efficiently.
            data=document,
        )
        return parse_add_document(r.json())

    def folder_exists(self, folder: str, *subfolders: str) -> bool:
        """Return True if a folder path exists beneath this library."""
        r = self.site.request(
            method="get",
            path=f"{self._folder_path(folder, *subfolders)}/Exists",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
        )
        return r.json().get("value", False)

    def delete_document(self, file_name: str, *subfolders: str) -> bool:
        """
        Delete a document by name within an optional nested folder path.
        Returns True if the request succeeded. Failures raise HTTPClient
        error from Requests.
        """
        self.site.request(
            method="post",
            path=self._file_path(*subfolders, file_name),
            headers={
                "If-Match": "*",  # Ignore current ETag; force delete.
                "X-HTTP-Method": "DELETE",
                "X-RequestDigest": self.site.form_digest,
            },
        )
        return True

    def delete_folder(self, folder: str, *subfolders: str) -> bool:
        """
        Delete a folder path. Returns True if the request succeeded.
        Failures raise HTTPClient error from Requests.
        """
        self.site.request(
            method="post",
            path=self._folder_path(folder, *subfolders),
            headers={
                "If-Match": "*",
                "X-HTTP-Method": "DELETE",
                "X-RequestDigest": self.site.form_digest,
            },
        )
        return True

    def list_contents(self, params: Params = None, *subfolders: str) -> list[dict[str, Any]]:
        """
        List file metadata within a folder path. Returns a list of items.
        Accepts OData params such as $select, $top, etc.
        Example: list_contents({"$select": "Name,ServerRelativeUrl", "$top": 5})
        """
        r = self.site.request(
            method="get",
            path=f"{self._folder_path(*subfolders)}/Files",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
            params=params,
        )
        return r.json().get("value", [])

    def get_document(self, file_name: str, *subfolders: str) -> bytes:
        """
        Download a file's binary contents. Returns bytes.

        For large downloads, you may prefer streaming to disk with iter_content;
        here we keep it simple and return r.content. The request uses stream=True
        to avoid preloading the entire body before we access .content.
        """
        r = self.site.request(
            method="get",
            path=f"{self._folder_path(*subfolders)}/Files('{odata_literal(file_name)}')/$value",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
            stream=True,
        )
        return r.content
