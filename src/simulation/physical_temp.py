"""Platform-neutral temporary paths for external-evidence regressions.

macOS exposes its temporary root through aliases such as /var -> /private/var.
Production path guards correctly reject symlink-bearing evidence/token paths, so
regressions that need a normal external path must pass the resolved physical path.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def physical_temporary_directory() -> Iterator[str]:
    """Yield the physical path of an ordinary temporary directory.

    Cleanup remains owned by ``TemporaryDirectory``; only the path presented to
    code under test is resolved. This does not weaken symlink rejection tests.
    """

    with tempfile.TemporaryDirectory() as temporary:
        yield str(Path(temporary).resolve(strict=True))
