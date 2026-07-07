from dotenv import load_dotenv
import os

load_dotenv()

def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


STARTING_BANKROLL = _float_env("STARTING_BANKROLL", 500)

API_KEY = os.getenv("ODDS_API_KEY")

SPORT = "basketball_wnba"

DATA_FILE = "data/bets.csv"

APP_NAME = "EdgeIQ"

APP_SUBTITLE = "Player Prop Intelligence Platform"

APP_VERSION = "V2.0 Alpha"
