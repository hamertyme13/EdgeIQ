from __future__ import annotations

import fcntl
import os
import re
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_THREAD_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _operation_lock_path(name: str) -> Path:
    namespace = os.getenv("EDGEIQ_OPERATION_LOCK_NAMESPACE", "").strip()
    if not namespace and os.getenv("PYTEST_CURRENT_TEST"):
        namespace = f"pytest-{os.getpid()}"
    safe_namespace = re.sub(r"[^A-Za-z0-9_.-]+", "-", namespace).strip("-")
    prefix = f"{safe_namespace}-" if safe_namespace else ""
    return Path(tempfile.gettempdir()) / f"edgeiq-{prefix}{name}.lock"


@contextmanager
def named_operation_lock(name: str) -> Iterator[bool]:
    """Acquire a nonblocking thread and process lock for one maintenance boundary."""
    with _LOCKS_GUARD:
        thread_lock = _THREAD_LOCKS.setdefault(name, threading.Lock())
    if not thread_lock.acquire(blocking=False):
        yield False
        return

    path = _operation_lock_path(name)
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
