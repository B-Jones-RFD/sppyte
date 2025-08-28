"""
requests.error
~~~~~~~~~~~~~~~~~~~

This module contains the set of sppyte exceptions.
"""


class ResponseFormatError(Exception):
    """Raised when an expected field is missing from a SharePoint JSON payload."""
    pass


class SessionError(Exception):
    """Raised when an HTTP session is not connected/available."""
    pass
