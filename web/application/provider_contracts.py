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
    supported_sports: tuple[str, ...] = ()


_CONTRACTS = {
    "PrizePicks": ProviderContract(
        "public_undocumented_endpoint",
        "prizepicks-v2",
        False,
        "",
        "Entry lines",
        "Not for settlement",
        ("WNBA", "NBA", "NFL", "NCAAF", "MLB", "NHL", "SOCCER", "TENNIS", "GOLF", "ESPORTS"),
    ),
    "Underdog": ProviderContract(
        "public_undocumented_endpoint",
        "underdog-v2",
        False,
        "",
        "Entry lines",
        "Not for settlement",
        ("WNBA", "NBA", "NFL", "NCAAF", "MLB", "NHL", "SOCCER", "TENNIS", "GOLF", "ESPORTS"),
    ),
    "DraftKings Pick6": ProviderContract(
        "authenticated_marketplace_actor",
        "apify-draftkings-pick6-v1",
        False,
        "https://console.apify.com/actors/zen-studio~draftkings-pick6-player-props",
        "Current Pick6 entry lines supplied by a third-party Apify actor",
        "Not for settlement; ESPN verifies final player stats",
        ("MLB", "NBA", "NHL", "SOCCER", "PGA", "MMA", "CS2", "LOL", "VALORANT", "COD", "NASCAR"),
    ),
    "Sleeper": ProviderContract(
        "official_public_api",
        "sleeper-v1",
        True,
        "https://docs.sleeper.com/",
        "Player metadata and optional entry lines",
        "Context only",
        ("NFL",),
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
        ("NFL", "NCAAF", "NBA", "WNBA", "MLB", "NHL"),
    ),
    "Ball Don't Lie": ProviderContract(
        "official_authenticated_api",
        "balldontlie-v1",
        True,
        "https://docs.balldontlie.io/",
        "Player statistics",
        "Supplemental verification",
        ("NBA", "WNBA", "NFL", "MLB", "NHL"),
    ),
    "ESPN public": ProviderContract(
        "public_undocumented_endpoint",
        "espn-scoreboard-v2",
        False,
        "",
        "Final score and box-score evidence",
        "Settlement with identity and game checks",
        ("WNBA", "NBA", "NFL", "NCAAF", "MLB", "NHL"),
    ),
    "NBA Stats": ProviderContract(
        "public_undocumented_endpoint",
        "nba-stats-v1",
        False,
        "",
        "Summer League final statistics",
        "Settlement with identity and game checks",
        ("NBA",),
    ),
    "PandaScore": ProviderContract(
        "official_authenticated_api",
        "pandascore-v2-match-player-stats",
        True,
        "https://developers.pandascore.co/docs/introduction",
        "Esports match identity and final player statistics",
        "Settlement for supported fields with Historical plan access and exact map scope",
        ("CS2", "LOL", "VALORANT", "DOTA2", "COD"),
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
    contract = provider_contract(str(row.get("name") or ""))
    suitability = str(contract.get("settlement_suitability") or "").lower()
    return {
        **row,
        **contract,
        "settlement_capable": suitability.startswith("settlement"),
        "context_only": "context only" in suitability or "market context" in suitability,
        "supported_sports": list(contract.get("supported_sports") or []),
    }


def provider_supports_sport(name: str, sport: str) -> bool:
    supported = provider_contract(name).get("supported_sports") or ()
    return str(sport or "").upper() in supported
