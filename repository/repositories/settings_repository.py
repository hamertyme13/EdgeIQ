import logging
import time

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from repository.database import SessionLocal
from repository.models.settings_model import SettingsModel

_log = logging.getLogger(__name__)


class SettingsRepository:

    @staticmethod
    def get(key: str, default: str = "") -> str:
        with SessionLocal() as session:
            row = session.get(SettingsModel, key)
            return row.value if row else default

    @staticmethod
    def set(key: str, value: str) -> None:
        started = time.monotonic()
        with SessionLocal() as session:
            dialect = session.bind.dialect.name
            connection = None
            if key == "daily_briefing_scan_status" and dialect == "sqlite":
                connection = session.connection()
                connection.exec_driver_sql("PRAGMA busy_timeout=1500")
            try:
                if dialect in {"sqlite", "postgresql"}:
                    insert_factory = sqlite_insert if dialect == "sqlite" else postgres_insert
                    statement = insert_factory(SettingsModel).values(key=key, value=value)
                    session.execute(statement.on_conflict_do_update(
                        index_elements=[SettingsModel.key],
                        set_={"value": statement.excluded.value},
                    ))
                else:
                    row = session.get(SettingsModel, key)
                    if row:
                        row.value = value
                    else:
                        session.add(SettingsModel(key=key, value=value))
                    session.flush()
            finally:
                if connection is not None:
                    connection.exec_driver_sql("PRAGMA busy_timeout=30000")
            session.commit()
        elapsed_ms = (time.monotonic() - started) * 1000
        if elapsed_ms >= 2000:
            _log.warning("Settings write took %.1f ms for key %s", elapsed_ms, key)
