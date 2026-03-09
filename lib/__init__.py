from yaml import safe_load

from .constants import LIB_DIR

with open(f'{LIB_DIR}/allowlist.yaml') as f:
    ALLOWLIST: set[str] = set(safe_load(f))

__all__ = [
    'ALLOWLIST',
]
