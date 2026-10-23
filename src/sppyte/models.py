"""Compatibility shim for 0.x imports; deprecated.

`Site`, `List` and `Library` now live in `sppyte.site`, `sppyte.lists` and
`sppyte.libraries`. Import them from `sppyte` directly.
"""

import warnings

from sppyte.libraries import Library
from sppyte.lists import List
from sppyte.odata import Page, Params, ParamValue
from sppyte.site import Site

__all__ = ["Library", "List", "Page", "ParamValue", "Params", "Site"]

warnings.warn(
    "sppyte.models is deprecated; import Site, List and Library from sppyte",
    DeprecationWarning,
    stacklevel=2,
)
