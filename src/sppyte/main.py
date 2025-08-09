from models import Site


def site_connection(
    host: str,
    site_relative_url: str,
    username: str,
    password: str,
) -> Site:
    manager = Site(host, site_relative_url, username, password)
    manager.connect()
    return manager
