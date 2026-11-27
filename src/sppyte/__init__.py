# SPDX-FileCopyrightText: 2025-present B-Jones-RFD
#
# SPDX-License-Identifier: MIT

"""Sppyte: a tiny helper around SharePoint REST endpoints using requests + NTLM.

It purposefully keeps a thin, explicit mapping to REST calls so behaviour
remains transparent and easy to debug. Start with `Site`.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from sppyte.__about__ import __version__
from sppyte.auth import SpPremAuth
from sppyte.batch import Batch, BatchRequest, BatchResponse
from sppyte.errors import (
    _SESSION_ERROR_DEPRECATED,
    AuthError,
    ConfigurationError,
    ResponseFormatError,
    SharePointError,
    SharePointErrorDetails,
    SppyteError,
    _SessionError,
)
from sppyte.libraries import Library
from sppyte.lists import List
from sppyte.odata import Page, Params
from sppyte.retry import RetryOptions, is_transient
from sppyte.site import Site

if TYPE_CHECKING:
    SessionError = _SessionError

__all__ = [
    "AuthError",
    "Batch",
    "BatchRequest",
    "BatchResponse",
    "ConfigurationError",
    "Library",
    "List",
    "Page",
    "Params",
    "ResponseFormatError",
    "RetryOptions",
    "SessionError",
    "SharePointError",
    "SharePointErrorDetails",
    "Site",
    "SpPremAuth",
    "SppyteError",
    "__version__",
    "is_transient",
]


def __getattr__(name: str) -> Any:
    """Warn on access to deprecated names."""
    if name == "SessionError":
        warnings.warn(_SESSION_ERROR_DEPRECATED, DeprecationWarning, stacklevel=2)
        return _SessionError
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
