import api

from urllib.parse import urljoin
from utils import get_hostname

hostname = get_hostname()


class Connection:
    def __init__(
        self,
        host: str,
        relative_url: str,
        username: str,
        password: str,
        domain: str | None = None,
    ):
        self.site_path = urljoin(host, relative_url)
        self.domain = domain
        self.hostname = hostname
        self.session = api.session(username, password, domain)

    def __del__(self) -> None:
        self.session.close()

    def list(self, name: str):
        return List(name, self)

    def library(self, name: str):
        return Library(name, self)

    def get_token(self) -> str:
        return "some_token"

    def get_form_digest(self) -> str:
        return "some_digest_value"


class List:
    def __init__(self, name: str, connection: Connection):
        self.connection = connection
        self.name = name

    def add(self, item: str) -> int:
        return 1

    def add_attachment(self, id: int, attachment) -> int:
        return 1

    def delete(self, id: int) -> None:
        pass

    def update(self, id: int, item: str) -> int:
        return 1


class Library:
    def __init__(self, name: str, connection: Connection):
        self.connection = connection
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
