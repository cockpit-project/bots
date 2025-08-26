# This file is part of Cockpit.
#
# Copyright (C) 2025 Red Hat, Inc.
#
# Cockpit is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# Cockpit is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Cockpit; If not, see <http://www.gnu.org/licenses/>.

import importlib
import os
import unittest.mock
from pathlib import Path

import pytest


@pytest.mark.parametrize("file_content,expected_stores", [
    # configured stores
    (
        """https://example.com/store1/
https://example.com/store2/

""",
        ["https://example.com/store1/", "https://example.com/store2/"]
    ),
    # empty config file
    ("", []),
    # whitespace-only
    ("   \n   \n   ", []),
    # absent config file
    (None, [])
])
def test_local_stores(tmp_path: Path, file_content: str | None, expected_stores: list[str]) -> None:
    """Test LOCAL_STORES with different config file scenarios."""
    config_file = tmp_path / "image-stores"

    if file_content is not None:
        config_file.write_text(file_content)

    with unittest.mock.patch.dict(os.environ, {"COCKPIT_IMAGE_STORES_FILE": str(config_file)}):
        # Reload the module to pick up the new environment variable
        import lib.stores
        importlib.reload(lib.stores)

        assert lib.stores.LOCAL_STORES == expected_stores
