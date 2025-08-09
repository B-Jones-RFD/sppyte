from requests import Session
from urllib.parse import urljoin
import typing


import api
from error import ConnectionError


class Site:
    session: Session | None = None

    def __init__(
        self,
        host: str,
        site_relative_url: str,
        username: str,
        password: str,
    ):
        self.site_path = urljoin(host, site_relative_url)
        self.username = username
        self.password = password

    def __enter__(self) -> None:
        self.session = api.session(self.username, self.password, self.site_path)

    def __exit__(self) -> None:
        if self.session is not None:
            self.session.close()

    def __del__(self) -> None:
        if self.session is not None:
            self.session.close()

    def connect(self) -> None:
        self.session = api.session(self.username, self.password)

    def list(self, name: str):
        return List(name, self)

    def library(self, name: str):
        return Library(name, self)

    def get_form_digest(self) -> str:
        try:
            if self.session is None:
                raise ConnectionError(
                    "Session not started. Call connect or use with statement."
                )
            headers = {
                "Accept": "application/json;odata=verbose",
                "Content-Type": "application/json;odata=verbose",
            }
            resource = urljoin(self.site_path, "/_api/contextinfo")
            res = self.session.post(
                url=resource,
                data="",
                headers=headers,
            )
            res.json().get()
            return "some_digest_value"
        except Exception as e:
            print(e)


class List:
    def __init__(self, name: str, site: Site):
        self.site = site
        self.name = name

    def add(self, item: str) -> int:
        return 1

    def add_attachment(self, id: int, attachment) -> int:
        return 1

    def delete(self, id: int) -> None:
        pass

    def get_contents(self) -> typing.List:
        pass

    def get(self, id: int):
        pass

    def update(self, id: int, item: str) -> int:
        return 1


class Library:
    def __init__(self, name: str, site: Site):
        self.site = site
        self.name = name

    def add_folder(self, folder: str):
        pass

    def add(self, folder: str, file_name: str, document):
        pass

    def folder_exists(self, folder: str):
        pass

    def delete_document(self, folder: str, file_name: str):
        pass

    def get_contents(self, folder: str):
        pass

    def get(self, folder: str, file_name: str):
        pass
