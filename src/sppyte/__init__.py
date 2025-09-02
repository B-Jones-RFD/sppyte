# SPDX-FileCopyrightText: 2025-present B-Jones-RFD
#
# SPDX-License-Identifier: MIT

"""
Sppyte — a tiny helper around SharePoint REST endpoints using requests + NTLM.

It purposefully keeps a thin, explicit mapping to REST calls so behavior
remains transparent and easy to debug.
"""

from errors import ResponseFormatError as ResponseFormatError  # noqa: PLC0414
from errors import SessionError as SessionError  # noqa: PLC0414
from models import Library as Library  # noqa: PLC0414
from models import List as List  # noqa: PLC0414
from models import Site as Site  # noqa: PLC0414
