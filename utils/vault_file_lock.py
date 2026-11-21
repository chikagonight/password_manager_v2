"""Non-blocking OS lock; the lock file itself must never be removed."""

import errno
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class FileLockBusy(Exception):
    pass


@contextmanager
def vault_file_lock(vault: Path) -> Iterator[None]:
    vault.parent.mkdir(parents=True, exist_ok=True)
    lock_path = vault.with_name(vault.name + ".lock")
    # Windows and POSIX release the lock when the handle closes, even after a crash.
    with lock_path.open("a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise FileLockBusy from exc
            raise
        yield
