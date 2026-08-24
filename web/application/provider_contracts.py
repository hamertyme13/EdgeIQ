from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProviderContract:
    source_type: str
    contract_version: str
    officially_documented: bool
    documentation_url: str
    data_role: str
    settlement_suitability: str


_CONTRACTS = {
    "PrizePicks": ProviderContract(
        "public_undocumented_endpoint",
        "prizepicks-v2",
        False,
        "",
        "Entry lines",
        "Not for settlement",
    ),
    "Underdog": ProviderContract(
        "public_undocumented_endpoint",
        "underdog-v2",
        False,
        "",
        "Entry lines",
        "Not for settlement",
    ),
    "DraftKings Pick6": ProviderContract(
        "manual_import",
        "draftkings-pick6-manual-v1",
        False,
        "",
        "Manual entry tracking and imported Pick6 offers",
        "Not for settlement; ESPN verifies final player stats",
    ),
    "Sleeper": ProviderContract(
        "official_public_api",
        "sleeper-v1",
        True,
        "https://docs.sleeper.com/",
        "Player metadata and optional entry lines",
        "Context only",
    ),
    "OpenAI": ProviderContract(
        "official_authenticated_api",
        "openai-v1",
        True,
        "https://platform.openai.com/docs/",
        "Assisted analysis and screenshot parsing",
        "Context only",
    ),
    "SportsDataIO": ProviderContract(
        "official_authenticated_api",
        "sportsdataio-v1",
        True,
        "https://sportsdata.io/developers/api-documentation",
        "Supplemental injuries and context",
        "Context only",
    ),
    "NewsAPI": ProviderContract(
        "official_authenticated_api",
        "newsapi-v2",
        True,
        "https://newsapi.org/docs",
        "News context",
        "Context only",
    ),
    "OpenWeather": ProviderContract(
        "official_authenticated_api",
        "openweather-v3",
        True,
        "https://openweathermap.org/api",
        "Outdoor weather context",
        "Context only",
    ),
    "The Odds API": ProviderContract(
        "official_authenticated_api",
        "odds-api-v4",
        True,
        "https://the-odds-api.com/liveapi/guides/v4/",
        "Multi-book prices and no-vig consensus",
        "Market context only",
    ),
    "Ball Don't Lie": ProviderContract(
        "official_authenticated_api",
        "balldontlie-v1",
        True,
        "https://docs.balldontlie.io/",
        "Player statistics",
        "Supplemental verification",
    ),
    "ESPN public": ProviderContract(
        "public_undocumented_endpoint",
        "espn-scoreboard-v2",
        False,
        "",
        "Final score and box-score evidence",
        "Settlement with identity and game checks",
    ),
    "NBA Stats": ProviderContract(
        "public_undocumented_endpoint",
        "nba-stats-v1",
        False,
        "",
        "Summer League final statistics",
        "Settlement with identity and game checks",
    ),
    "PandaScore": ProviderContract(
        "official_authenticated_api",
        "pandascore-v2-match-player-stats",
        True,
        "https://developers.pandascore.co/docs/introduction",
        "Esports match identity and final player statistics",
        "Settlement for supported fields with Historical plan access and exact map scope",
    ),
}

_UNKNOWN = ProviderContract(
    "unknown",
    "unversioned",
    False,
    "",
    "Unclassified",
    "Not for settlement",
)


def provider_contract(name: str) -> dict:
    return asdict(_CONTRACTS.get(name, _UNKNOWN))


def enrich_provider_health(row: dict) -> dict:
    return {**row, **provider_contract(str(row.get("name") or ""))}
