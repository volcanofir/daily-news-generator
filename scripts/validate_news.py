#!/usr/bin/env python3
"""Validate generated news before publishing it to GitHub Pages."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
REQUIRED_CATEGORIES = ("weather", "instant", "finance", "housing")


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    return dt.astimezone(TAIPEI)


def main() -> None:
    path = Path("news.json")
    if not path.exists():
        raise SystemExit("news.json does not exist")

    payload = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(TAIPEI)

    if payload.get("date") != now.date().isoformat():
        raise SystemExit(f"news date is not today: {payload.get('date')!r}")

    updated_at = parse_dt(str(payload.get("updated_at", "")))
    age = now - updated_at
    if age < timedelta(minutes=-5) or age > timedelta(minutes=30):
        raise SystemExit(f"updated_at is outside expected range: {updated_at.isoformat()}")

    categories = payload.get("categories")
    if not isinstance(categories, dict):
        raise SystemExit("categories is not an object")

    total = 0
    bad = []
    for category in REQUIRED_CATEGORIES:
        items = categories.get(category)
        if not isinstance(items, list):
            raise SystemExit(f"missing/invalid category: {category}")
        total += len(items)
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                bad.append(f"{category}[{index}] is not an object")
                continue
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            source = str(item.get("source", "")).strip()
            host = urlparse(url).netloc.lower()
            if not title:
                bad.append(f"{category}[{index}] missing title")
            if not url.startswith(("http://", "https://")):
                bad.append(f"{category}[{index}] invalid url")
            if "taisounds.com" in host or "太報" in source:
                bad.append(f"{category}[{index}] contains removed TaiSounds source")

    if total < 3:
        raise SystemExit(f"too few articles to publish: {total}")
    if bad:
        raise SystemExit("; ".join(bad[:10]))

    print(f"[validate] OK: {total} articles, updated {updated_at:%Y-%m-%d %H:%M:%S %Z}")


if __name__ == "__main__":
    main()
