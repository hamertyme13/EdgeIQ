import os
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

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

try:
    APP_VERSION: str = _pkg_version("edgeiq")
except PackageNotFoundError:
    APP_VERSION = "0.0.0+dev"
