from repository.database import SessionLocal
from repository.models.settings_model import SettingsModel


class SettingsRepository:

    @staticmethod
    def get(key: str, default: str = "") -> str:
        with SessionLocal() as session:
            row = session.get(SettingsModel, key)
            return row.value if row else default

    @staticmethod
    def set(key: str, value: str) -> None:
        with SessionLocal() as session:
            connection = None
            if key == "daily_briefing_scan_status" and session.bind.dialect.name == "sqlite":
                connection = session.connection()
                connection.exec_driver_sql("PRAGMA busy_timeout=1500")
            try:
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
