"""Scrape the public Telegram channel @mofidot into Astro content JSON files.

Only post metadata and the public t.me link are stored; media files are never
downloaded. Each post becomes ``src/content/posts/<id>.json``. Scraping is
incremental and existing files are never overwritten, so the script is safe to
run repeatedly.

tgscraper stores its incremental state in ``~/.tgscraper/state.json`` by
default (override the location with ``TGSCRAPER_STATE``). The GitHub Actions
workflow caches that file between runs. Set ``SCRAPER_INCREMENTAL=false`` to
force a full-history scan, for example after clearing the cache.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import tgscraper as tg

CHANNEL = "mofidot"
INCREMENTAL = os.environ.get("SCRAPER_INCREMENTAL", "true").lower() != "false"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = PROJECT_ROOT / "src" / "content" / "posts"

# Priority: voice > video > photo > document > text.
_MEDIA_TYPE_MAP = {
    "voice": "voice",
    "video": "video",
    "round_video": "video",
    "photo": "photo",
    "document": "document",
    "audio": "document",
}


def _iso_utc(value: Optional[datetime]) -> Optional[str]:
    """Return an ISO 8601 string in UTC (or None if the post has no date)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _duration_seconds(value: Any) -> Optional[int]:
    """Convert Telegram durations such as ``"0:42"`` or ``"1:02:03"`` to seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = 0
        for part in text.split(":"):
            seconds = seconds * 60 + int(part)
        return seconds
    except ValueError:
        digits = re.sub(r"\D", "", text)
        return int(digits) if digits else None


def _media_info(post: Any) -> tuple[str, Optional[int]]:
    """Infer the archive media type and duration (voice/video only)."""
    media = post.media or []
    present = {item.type for item in media}

    media_type = "text"
    for kind in ("voice", "video", "round_video", "photo", "document", "audio"):
        if kind in present:
            media_type = _MEDIA_TYPE_MAP[kind]
            break

    duration = None
    if media_type in ("voice", "video"):
        for item in media:
            if item.type in ("voice", "video", "round_video"):
                duration = _duration_seconds(item.duration)
                if duration is not None:
                    break
    return media_type, duration


def _post_to_dict(post: Any) -> dict[str, Any]:
    media_type, duration = _media_info(post)
    return {
        "id": int(post.id),
        "date": _iso_utc(post.date),
        "text": post.text or "",
        "media_type": media_type,
        "duration_sec": duration,
        "views": int(post.views or 0),
        "reactions": int(sum(value or 0 for value in (post.reactions or {}).values())),
        "telegram_link": f"https://t.me/{CHANNEL}/{post.id}",
        "category": None,
    }


def main() -> None:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    # With no saved incremental state the first run fetches the full history;
    # afterwards tgscraper's state limits the result to newer posts only.
    posts = tg.scrape(CHANNEL, limit=None, incremental=INCREMENTAL)

    saved = 0
    skipped = 0
    for post in posts:
        path = POSTS_DIR / f"{post.id}.json"
        if path.exists():
            skipped += 1
            continue
        path.write_text(
            json.dumps(_post_to_dict(post), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        saved += 1

    print(f"Saved {saved} new post(s); skipped {skipped} existing post(s).")
    print(f"Posts directory: {POSTS_DIR}")


if __name__ == "__main__":
    main()
