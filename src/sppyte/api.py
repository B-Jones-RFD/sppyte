from requests import Session
from requests_ntlm import HttpNtlmAuth


def session(username, password, domain: str | None = None):
    session = Session()
    session.auth = HttpNtlmAuth(username, password)
    return session
