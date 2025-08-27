"""
requests.error
~~~~~~~~~~~~~~~~~~~

This module contains the set of sppyte exceptions.
"""


class Error(Exception):
    """Base error for Sppyte exceptions."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ResponseFormatError(Error):
    """Raised when an expected field is missing from a SharePoint JSON payload."""


class SessionError(Error):
    """Raised when an HTTP session is not connected/available."""
