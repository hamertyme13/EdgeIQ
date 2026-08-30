import os
import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


STARTING_BANKROLL = _float_env("STARTING_BANKROLL", 500)

API_KEY = os.getenv("ODDS_API_KEY")

SPORT = "basketball_wnba"

APP_NAME = "EdgeIQ"

APP_SUBTITLE = "Player Prop Intelligence Platform"

def _app_version() -> str:
    pyproject = Path(__file__).resolve().with_name("pyproject.toml")
    if pyproject.exists():
        try:
            return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])
        except (KeyError, OSError, tomllib.TOMLDecodeError):
            pass
    try:
        return _pkg_version("edgeiq")
    except PackageNotFoundError:
        return "0.0.0+dev"


APP_VERSION = _app_version()
