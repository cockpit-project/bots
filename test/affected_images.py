# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

# This file is used by .github/workflows/machines-api.yml to know which
# TEST_OSes to check with test/test_machines_api.py (which calls
# image-customize).  If any of the relevant non-image files change, we test all
# images.

import json
import sys
from collections.abc import Iterable, Set

from lib import testmap


def affected_images(changed_paths: Iterable[str]) -> Set[str]:
    all_vm_images = {t.image for t in testmap._all_tests() if not t.image.endswith('boot')}

    # rhel images require authenticated downloads; centos covers equivalent functionality
    all_vm_images = {image for image in all_vm_images if not image.startswith('rhel')}

    updated_images = set()

    for path in changed_paths:
        # if any of these files change, test all images
        if path.startswith((
            '.github/workflows/machines-api.yml',
            'test/test_machines_api.py',
            'test/affected_images.py',

            'image-customize',
            'machine/',

            'lib/testmap.py',
        )):
            return all_vm_images

        # otherwise, test any image that gets updated
        elif path.startswith('images/'):
            image = path.removeprefix('images/')
            if image in all_vm_images:
                updated_images.add(image)

    return updated_images


if __name__ == '__main__':
    images = sorted(affected_images(sys.stdin.read().splitlines()))
    print(f'affected_images={json.dumps(images)}')
