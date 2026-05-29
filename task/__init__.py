"""Backwards compatibility shim.
Older versions of lcov.py do 'from task import github'.
"""

from lib import github

__all__ = ("github",)
