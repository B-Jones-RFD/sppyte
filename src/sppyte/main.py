from models import Connection


def connect(
    host: str,
    relative_url: str,
    username: str,
    password: str,
    domain: str | None = None,
) -> Connection:
    return Connection(host, relative_url, username, password, domain)
