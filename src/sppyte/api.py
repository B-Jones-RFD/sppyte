from requests import Session
from requests_ntlm import HttpNtlmAuth


def session(username: str, password: str) -> Session:
    session = Session()
    session.auth = HttpNtlmAuth(username, password)
    return session
