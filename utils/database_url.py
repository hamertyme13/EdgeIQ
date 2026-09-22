def normalize_database_url(value: str) -> str:
    """Use the installed psycopg3 driver for platform-provided PostgreSQL URLs."""
    for prefix in ("postgres://", "postgresql://"):
        if value.startswith(prefix):
            return "postgresql+psycopg://" + value[len(prefix):]
    return value
