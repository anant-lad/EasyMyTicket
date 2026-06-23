"""
Loads KB articles from the fetched JSON produced by scripts/fetch_kb_data.py.
"""

from __future__ import annotations
import json
import pathlib
import logging

log = logging.getLogger(__name__)

_JSON_PATH = pathlib.Path(__file__).parent.parent.parent / "scripts" / "kb_raw_articles.json"


def load_seed_articles() -> list[dict]:
    """Return all articles from kb_raw_articles.json."""
    if not _JSON_PATH.exists():
        raise FileNotFoundError(
            f"KB articles JSON not found at {_JSON_PATH}. "
            "Run scripts/fetch_kb_data.py first."
        )
    with open(_JSON_PATH, encoding="utf-8") as f:
        articles = json.load(f)
    log.info("Loaded %d KB articles from %s", len(articles), _JSON_PATH)
    return articles
