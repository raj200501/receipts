"""addrcheck: syntax checks and normalization for email addresses.

>>> from addrcheck import check, normalize
>>> check("Ada@Example.ORG").ok
True
>>> normalize(" Ada@Example.ORG. ")
'Ada@example.org'
>>> check("ada@localhost").reason
'domain_one_label'
"""

from addrcheck.errors import REASONS, AddressError
from addrcheck.splitter import split_address
from addrcheck.validator import Verdict, check, is_valid, normalize

__all__ = [
    "REASONS",
    "AddressError",
    "Verdict",
    "check",
    "is_valid",
    "normalize",
    "split_address",
]
