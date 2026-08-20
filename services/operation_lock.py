from __future__ import annotations

import fcntl
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_THREAD_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


@contextmanager
def named_operation_lock(name: str) -> Iterator[bool]:
    """Acquire a nonblocking thread and process lock for one maintenance boundary."""
    with _LOCKS_GUARD:
        thread_lock = _THREAD_LOCKS.setdefault(name, threading.Lock())
    if not thread_lock.acquire(blocking=False):
        yield False
        return

    path = Path(tempfile.gettempdir()) / f"edgeiq-{name}.lock"
    handle = None
    acquired = False
    try:
        handle = path.open("a+", encoding="ascii")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        if handle is not None:
            handle.close()
        thread_lock.release()
