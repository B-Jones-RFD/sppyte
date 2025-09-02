"""
requests.errors
~~~~~~~~~~~~~~~~~~~

This module contains the set of sppyte exceptions.
"""


class ResponseFormatError(Exception):
    """Raised when an expected field is missing from a SharePoint JSON payload."""


class SessionError(Exception):
    """Raised when an HTTP session is not connected/available."""
