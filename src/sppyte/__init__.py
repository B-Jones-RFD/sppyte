# SPDX-FileCopyrightText: 2025-present B-Jones-RFD
#
# SPDX-License-Identifier: MIT

"""
Sppyte — a tiny helper around SharePoint REST endpoints using requests + NTLM.

It purposefully keeps a thin, explicit mapping to REST calls so behavior
remains transparent and easy to debug.
"""

from sppyte.__about__ import __version__
from sppyte.errors import (
    AuthError,
    ConfigurationError,
    ResponseFormatError,
    SessionError,
    SharePointError,
    SharePointErrorDetails,
    SppyteError,
)
from sppyte.libraries import Library
from sppyte.lists import List
from sppyte.odata import Page, Params
from sppyte.site import Site

__all__ = [
    "AuthError",
    "ConfigurationError",
    "Library",
    "List",
    "Page",
    "Params",
    "ResponseFormatError",
    "SessionError",
    "SharePointError",
    "SharePointErrorDetails",
    "Site",
    "SppyteError",
    "__version__",
]
