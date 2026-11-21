"""Stage bytes beside their destination and publish by atomic replacement."""

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def staged_write(target: Path, data: bytes) -> Iterator[Path]:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write(target: Path, data: bytes) -> None:
    with staged_write(target, data) as temporary:
        os.replace(temporary, target)
