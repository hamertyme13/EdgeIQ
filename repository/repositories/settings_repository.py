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
            row = session.get(SettingsModel, key)
            if row:
                row.value = value
            else:
                session.add(SettingsModel(key=key, value=value))
            session.commit()
