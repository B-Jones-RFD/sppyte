# SPDX-FileCopyrightText: 2025-present B-Jones-RFD
#
# SPDX-License-Identifier: MIT

"""
Sppyte — a tiny helper around SharePoint REST endpoints using requests + NTLM.

It purposefully keeps a thin, explicit mapping to REST calls so behavior
remains transparent and easy to debug.
"""

from .errors import ResponseFormatError, SessionError  # noqa: F401,TID252
from .models import Library, List, Site  # noqa: F401, TID252
