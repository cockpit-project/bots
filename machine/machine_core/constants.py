# Backwards compatibility shim.  This will go away soon.

from lib.constants import (
    BASE_DIR,
    BOTS_DIR,
    DEFAULT_IDENTITY_FILE,
    DEFAULT_IMAGE,
    GIT_DIR,
    IMAGES_DIR,
    MACHINE_DIR,
    OSTREE_IMAGES,
    SCRIPTS_DIR,
    TEST_DIR,
    TEST_OS_DEFAULT,
)

__all__ = ("OSTREE_IMAGES", "BOTS_DIR", "MACHINE_DIR", "BASE_DIR", "TEST_DIR", "GIT_DIR",
           "IMAGES_DIR", "SCRIPTS_DIR", "DEFAULT_IDENTITY_FILE", "TEST_OS_DEFAULT", "DEFAULT_IMAGE",)

import warnings

warnings.warn('machine_core.constants is deprecated.  Use lib.constants', DeprecationWarning)
