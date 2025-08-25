from models import Site


def connection(
    host: str,
    site_relative_url: str,
    username: str,
    password: str,
) -> Site:
    return Site(host, site_relative_url, username, password)
