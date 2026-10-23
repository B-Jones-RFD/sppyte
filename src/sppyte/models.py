"""
sppyte.models
~~~~~~~~~~~~~

Compatibility shim: `Site`, `List` and `Library` now live in `sppyte.site`,
`sppyte.lists` and `sppyte.libraries`. Import them from `sppyte` directly.
"""

from sppyte.libraries import Library
from sppyte.lists import List
from sppyte.odata import Params, ParamValue
from sppyte.site import Site

__all__ = ["Library", "List", "ParamValue", "Params", "Site"]
