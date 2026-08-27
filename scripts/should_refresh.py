#!/usr/bin/env python3
"""Decide whether a scheduled workflow should perform a full news refresh.

GitHub Actions scheduled events are best-effort and can be delayed or dropped.
This gate lets us schedule a lightweight check every 5 minutes, while only doing
expensive scraping when the live site is stale enough or within a one-shot
refresh window.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
LIVE_NEWS_URL = "https://volcanofir.github.io/daily-news-generator/news.json"
FRESH_FOR_MINUTES = 13
SINGLE_RUN_HOURS = {6, 7, 12, 15, 18, 21}
CONTINUOUS_HOURS = {8, 9, 10, 11}
SINGLE_RUN_WINDOW_MINUTES = 25


def output(value: bool, reason: str) -> None:
    run = "true" if value else "false"
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"run={run}\n")
            fh.write(f"reason={reason}\n")
    print(f"refresh={run}: {reason}")


def parse_updated_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def live_updated_at() -> datetime | None:
    try:
        req = Request(
            f"{LIVE_NEWS_URL}?gate={int(datetime.now().timestamp())}",
            headers={"User-Agent": "daily-news-generator-refresh-gate/1.0"},
        )
        with urlopen(req, timeout=8) as response:
            payload = json.load(response)
        return parse_updated_at(payload.get("updated_at", ""))
    except Exception as exc:  # Network failure should fail open and refresh.
        print(f"Could not read live news timestamp: {exc}", file=sys.stderr)
        return None


def main() -> None:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name in {"workflow_dispatch", "push"}:
        output(True, f"forced by {event_name}")
        return

    now = datetime.now(TAIPEI)

    if now.hour in SINGLE_RUN_HOURS:
        if now.minute >= SINGLE_RUN_WINDOW_MINUTES:
            output(False, f"outside {now.hour:02d}:00 one-shot refresh window")
            return
    elif now.hour not in CONTINUOUS_HOURS:
        output(False, f"outside active refresh hours ({now:%H:%M})")
        return

    updated = live_updated_at()
    if updated is None:
        output(True, "live timestamp unavailable; fail open")
        return

    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=TAIPEI)
    updated = updated.astimezone(TAIPEI)

    if updated.date() != now.date():
        output(True, f"live data is from {updated.date()}, not today")
        return

    age = now - updated
    if age < timedelta(minutes=FRESH_FOR_MINUTES):
        mins = max(0, int(age.total_seconds() // 60))
        output(False, f"live data is fresh ({mins} min old)")
        return

    mins = int(age.total_seconds() // 60)
    output(True, f"live data is stale ({mins} min old)")


if __name__ == "__main__":
    main()
