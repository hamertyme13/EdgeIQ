from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_TEST_DATABASE_DIR = Path(tempfile.mkdtemp(prefix="edgeiq-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DATABASE_DIR / 'edgeiq-test.db'}"

from repository.database import initialize_database

initialize_database()


def pytest_sessionfinish(session, exitstatus) -> None:
    from repository.database import engine

    engine.dispose()
    shutil.rmtree(_TEST_DATABASE_DIR, ignore_errors=True)
