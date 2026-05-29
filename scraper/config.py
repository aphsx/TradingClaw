import os
from dataclasses import dataclass
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()

# The Odds API sport keys (only if SCRAPE_SOURCE=odds_api)
FOOTBALL_SPORT_KEYS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_uefa_champs_league",
]

ESPORTS_SPORT_KEYS = [
    "esports_lol",
    "esports_dota2",
    "esports_csgo",
]

ODDS_API_BASE = "https://api.the-odds-api.com/v4"


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_key: str
    odds_api_key: str
    scrape_source: str
    tracking_window: timedelta
    football_count: int
    esports_count: int
    headless: bool
    fetch_match_bookies: bool
    use_local: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        use_local = os.environ.get("LOCAL_STORAGE", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        url = os.environ.get(
            "SUPABASE_URL", "https://bjmqwerbslpdbfrkedqj.supabase.co"
        ).strip()
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        odds = os.environ.get("ODDS_API_KEY", "").strip()
        source = os.environ.get("SCRAPE_SOURCE", "oddsportal").strip().lower()

        if source not in ("oddsportal", "odds_api"):
            raise ValueError("SCRAPE_SOURCE must be oddsportal or odds_api")

        if not use_local and (not url or not key or key == "your_service_role_key"):
            raise ValueError(
                "Set SUPABASE_SERVICE_ROLE_KEY in .env, or LOCAL_STORAGE=1"
            )
        if source == "odds_api" and not odds:
            raise ValueError("SCRAPE_SOURCE=odds_api requires ODDS_API_KEY")

        days = int(os.environ.get("TRACKING_WINDOW_DAYS", "7"))
        return cls(
            supabase_url=url,
            supabase_service_key=key,
            odds_api_key=odds,
            scrape_source=source,
            tracking_window=timedelta(days=days),
            football_count=int(os.environ.get("FOOTBALL_MATCH_COUNT", "10")),
            esports_count=int(os.environ.get("ESPORTS_MATCH_COUNT", "10")),
            headless=os.environ.get("HEADLESS", "true").lower() != "false",
            fetch_match_bookies=os.environ.get("FETCH_MATCH_BOOKIES", "true").lower()
            in ("1", "true", "yes"),
            use_local=use_local,
        )
