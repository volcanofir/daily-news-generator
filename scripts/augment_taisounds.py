from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "news.json"
TAISOUNDS_HOST = "taisounds.com"


def is_taisounds_item(item: dict) -> bool:
    source = str(item.get("source", ""))
    source_url = str(item.get("source_url", ""))
    canonical_url = str(item.get("canonical_url", ""))
    url = str(item.get("url", ""))
    return (
        source.startswith("太報")
        or TAISOUNDS_HOST in source_url
        or TAISOUNDS_HOST in canonical_url
        or TAISOUNDS_HOST in url
    )


def main() -> None:
    if not OUTPUT.exists():
        raise SystemExit("news.json not found; run fetch_news.py first")

    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    removed_items = 0
    removed_feeds = 0

    categories = payload.setdefault("categories", {})
    for category, items in list(categories.items()):
        if not isinstance(items, list):
            continue
        filtered = [item for item in items if not is_taisounds_item(item)]
        removed_items += len(items) - len(filtered)
        categories[category] = filtered

    sources = payload.setdefault("sources", {})
    for group in sources.values():
        if not isinstance(group, dict):
            continue
        feeds = group.get("feeds", [])
        if not isinstance(feeds, list):
            continue
        filtered_feeds = []
        for feed in feeds:
            if not isinstance(feed, dict):
                filtered_feeds.append(feed)
                continue
            name = str(feed.get("name", ""))
            url = str(feed.get("url", ""))
            if name.startswith("太報") or TAISOUNDS_HOST in url:
                removed_feeds += 1
                continue
            filtered_feeds.append(feed)
        group["feeds"] = filtered_feeds

    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[taisounds-cleanup] removed {removed_items} article(s), {removed_feeds} source feed(s)")


if __name__ == "__main__":
    main()
