from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from io import BufferedReader

import utils
from error import SessionError
from requests import Response, Session
from requests_ntlm import HttpNtlmAuth


class Site:
    session: Session | None = None
    form_digest: str | None = None

    def __init__(
        self,
        host: str,
        site_relative_url: str,
        username: str,
        password: str,
    ):
        self.site_path = f"{host.rstrip('/')}/{site_relative_url.strip('/')}"
        self.relative_url = site_relative_url
        self.username = username
        self.password = password
        self.connect()

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def request(self, method, path, **kwargs) -> Response:
        url = f"{self.site_path.rstrip('/')}/{path.strip('/')}"
        if type(self.session) is Session:
            r = self.session.request(method, url, **kwargs)
            r.raise_for_status()
            return r

        raise SessionError

    def get_form_digest(self) -> str:
        r = self.request(
            method="post",
            path="/_api/contextinfo",
            headers={
                "Accept": "application/json;odata=verbose",
                "Content-Type": "application/json;odata=verbose",
            },
            data="",
        )
        return utils.parse_form_digest(r)

    def connect(self) -> None:
        session = Session()
        session.auth = HttpNtlmAuth(self.username, self.password)
        self.session = session
        self.form_digest = self.get_form_digest()

    def close(self) -> None:
        if self.session is not None:
            self.session.close()

    def list(self, name: str):
        if self.session is None:
            self.connect()
        return List(name, self)

    def library(self, name: str):
        if self.session is None:
            self.connect()
        return Library(name, self)


class List:
    def __init__(self, name: str, site: Site):
        self.site = site
        self.name = name

    def add_item(self, item: dict[str, Any]) -> int:
        if "__metadata" not in item:
            item_type = self.get_item_type()
            item["__metadata"] = {"type": item_type}

        r = self.site.request(
            method="post",
            path=f"_api/web/lists/GetByTitle('{self.name}')/items",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/json;odata=verbose",
                "X-RequestDigest": self.site.form_digest,
            },
            json=item,
        )
        return utils.parse_add_item(r)

    def add_attachment(self, sp_id: int, file_name: str, attachment) -> int:
        self.site.request(
            method="post",
            path=f"_api/web/lists/GetByTitle('{self.name}')/items('{sp_id}')/AttachmentFiles/add(FileName='{file_name}')",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/json;odata=verbose",
                "X-RequestDigest": self.site.form_digest,
            },
            data=attachment,
        )
        return sp_id

    def delete_item(self, sp_id: int) -> bool:
        self.site.request(
            method="post",
            path=f"_api/web/lists/GetByTitle('{self.name}')/items('{sp_id}')",
            headers={
                "Accept": "application/json;odata=verbose",
                "Content-Type": "application/json;odata=verbose",
                "X-HTTP-Method": "DELETE",
                "If-Match": "*",
                "X-RequestDigest": self.site.form_digest,
            },
        )
        return True

    def get_contents(self, **params):
        r = self.site.request(
            method="get",
            path=f"_api/web/lists/GetByTitle('{self.name}')/items",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
            params=params,
        )
        return r.json()

    def get_item_type(self) -> str:
        r = self.site.request(
            method="get",
            path=f"_api/web/lists/GetByTitle('{self.name}')",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
            params={"$select": "ListItemEntityTypeFullName"},
        )
        return utils.parse_item_type(r)

    def get_item(self, sp_id: int):
        r = self.site.request(
            method="get",
            path=f"_api/web/lists/GetByTitle('{self.name}')/items('{sp_id}')",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
        )
        return r.json()

    def update_item(self, sp_id: int, patch: dict[str, Any]) -> int:
        if "__metadata" not in patch:
            item_type = self.get_item_type()
            patch["__metadata"] = {"type": item_type}

        self.site.request(
            method="post",
            path=f"_api/web/lists/GetByTitle('{self.name}')/items('{sp_id}')",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/json;odata=verbose",
                "X-HTTP-Method": "MERGE",
                "If-Match": "*",
                "X-RequestDigest": self.site.form_digest,
            },
            json=patch,
        )
        return sp_id


class Library:
    def __init__(self, name: str, site: Site):
        self.site = site
        self.name = name

    def add_folder(self, folder: str, *subfolders: str):
        folder_relative_url = utils.build_path(folder, *subfolders)

        r = self.site.request(
            method="post",
            path="_api/web/folders",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/json",
                "X-RequestDigest": self.site.form_digest,
            },
            json={
                "ServerRelativeUrl": self.name + folder_relative_url,
            },
        )
        return r.json().get("Exists", False)

    def add_document(
        self,
        file_name: str,
        document: BufferedReader,
        *subfolders: str,
    ) -> str:
        r = self.site.request(
            method="post",
            path=f"_api/web/GetFolderByServerRelativeUrl('{utils.build_path(self.site.relative_url, self.name, *subfolders)}')/Files/add(url='{file_name}',overwrite=true)",
            headers={
                "Accept": "application/json;odata=nometadata",
                "Content-Type": "application/octet-stream",
                "X-RequestDigest": self.site.form_digest,
            },
            data=document,
        )
        return utils.parse_add_document(r)

    def folder_exists(self, folder, *subfolders: str) -> bool:
        r = self.site.request(
            method="get",
            path=f"_api/web/GetFolderByServerRelativeUrl('{utils.build_path(self.site.relative_url, self.name, folder, *subfolders)}')/Exists",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
        )
        return r.json().get("value", False)

    def delete_document(self, file_name: str, *subfolders: str) -> bool:
        self.site.request(
            method="post",
            path=f"_api/web/GetFileByServerRelativeUrl('{utils.build_path(self.site.relative_url, self.name, *subfolders, file_name)}')",
            headers={
                "If-Match": "*",
                "X-HTTP-Method": "DELETE",
                "X-RequestDigest": self.site.form_digest,
            },
        )
        return True

    def delete_folder(self, folder, *subfolders: str) -> bool:
        self.site.request(
            method="post",
            path=f"_api/web/_api/web/GetFolderByServerRelativeUrl('{utils.build_path(self.site.relative_url, self.name, folder, *subfolders)}')",
            headers={
                "If-Match": "*",
                "X-HTTP-Method": "DELETE",
                "X-RequestDigest": self.site.form_digest,
            },
        )
        return True

    def list_contents(self, *folders: str, **params):
        r = self.site.request(
            method="get",
            path=f"_api/web/GetFolderByServerRelativeUrl('{utils.build_path(self.site.relative_url, self.name, *folders)}')/Files",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
            params=params,
        )
        return r.json().get("value", [])

    def get_document(self, file_name: str, *folders: str):
        r = self.site.request(
            method="get",
            path=f"/_api/web/GetFolderByServerRelativeUrl('{utils.build_path(self.site.relative_url, self.name, *folders)}')/Files('{file_name}')/$value",
            headers={
                "Accept": "application/json;odata=nometadata",
            },
            stream=True,
        )
        return r.content
