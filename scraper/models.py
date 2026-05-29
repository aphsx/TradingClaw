from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RawEvent:
    id: str
    sport_key: str
    sport_category: str
    home_team: str
    away_team: str
    commence_at: datetime
    bookmakers: list[dict[str, Any]] = field(default_factory=list)
    match_url: str = ""
    source: str = "oddsportal"
