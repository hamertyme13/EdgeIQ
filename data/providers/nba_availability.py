"""Dated NBA injury-report evidence for research-only participation exclusions."""

from __future__ import annotations

import re
from datetime import date
from io import BytesIO
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

from repository.repositories.final_stats_repository import _game_key
from utils.entity_normalization import canonical_person_key

_REPORT_PATH = re.compile(r"^/referee/injury/Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})(?:_(\d{2}))?(AM|PM)\.pdf$")
_MATCHUP = re.compile(r"\b[A-Z]{2,4}@[A-Z]{2,4}\b")
_ROW_DATE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_STATUS = {"Out", "Doubtful", "Questionable", "Probable", "Available"}


def report_day(url: str) -> date:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "ak-static.cms.nba.com":
        raise ValueError("Only official NBA injury-report URLs are accepted.")
    match = _REPORT_PATH.fullmatch(parsed.path)
    if not match:
        raise ValueError("The URL is not a dated NBA injury-report PDF.")
    return date.fromisoformat(match.group(1))


def parse_report_pages(pages: list[str], *, report_date: date, source_url: str) -> list[dict]:
    """Read explicit rows from the NBA's current fixed-column PDF; fail closed on ambiguity."""
    rows = []
    game_day = ""
    matchup = ""
    for page in pages:
        # pypdf layout extraction traverses these particular NBA pages bottom-up.
        for line in reversed(page.splitlines()):
            date_match = _ROW_DATE.search(line)
            if date_match:
                month, day, year = date_match.group().split("/")
                game_day = f"{year}-{month}-{day}"
            game_match = _MATCHUP.search(line)
            if game_match:
                matchup = game_match.group()
            if game_day != report_date.isoformat() or not matchup:
                continue
            cells = [cell.strip() for cell in re.split(r" {2,}", line.strip()) if cell.strip()]
            for index, cell in enumerate(cells[:-1]):
                if "," not in cell:
                    continue
                name_cell = cell
                status_index = index + 1
                if cells[status_index] not in _STATUS and index + 2 < len(cells) and cells[index + 2] in _STATUS:
                    name_cell = f"{cell} {cells[index + 1]}"
                    status_index = index + 2
                if cells[status_index] not in _STATUS:
                    continue
                if re.fullmatch(r"(?:Jr\.|Sr\.|II|III|IV),.*", cell) and index > 0:
                    name_cell = f"{cells[index - 1]} {name_cell}"
                surname, given = (part.strip() for part in name_cell.split(",", 1))
                if not surname or not given:
                    continue
                rows.append({
                    "player": f"{given} {surname}", "game": matchup,
                    "game_date": game_day, "status": cells[status_index],
                    "source": "nba_official_injury_report", "source_url": source_url,
                })
                break
    return rows


def fetch_report(url: str) -> list[dict]:
    day = report_day(url)
    response = requests.get(url, timeout=12)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF") or len(response.content) > 3_000_000:
        raise ValueError("Official NBA injury report was not a small PDF.")
    reader = PdfReader(BytesIO(response.content))
    if len(reader.pages) > 20:
        raise ValueError("Official NBA injury report had an unexpected page count.")
    header = reader.pages[0].extract_text() or ""
    if day.strftime("%m/%d/%y") not in header:
        raise ValueError("Official NBA injury report header does not match its URL date.")
    pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    return parse_report_pages(pages, report_date=day, source_url=url)


def exact_report_match(offer: dict, report_rows: list[dict]) -> dict | None:
    """Match one dated report row to one player-game; no fuzzy roster inference."""
    player = canonical_person_key(offer.get("player"))
    game = _game_key(offer.get("game"))
    game_day = str(offer.get("game_day") or "")
    if not player or not game or not game_day:
        return None
    matches = [row for row in report_rows
               if row["game_date"] == game_day
               and canonical_person_key(row["player"]) == player and _game_key(row["game"]) == game]
    return matches[0] if len(matches) == 1 else None


def exact_out_match(offer: dict, report_rows: list[dict]) -> dict | None:
    row = exact_report_match(offer, report_rows)
    return row if row and row["status"] == "Out" else None
