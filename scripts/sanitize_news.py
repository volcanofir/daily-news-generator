from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from augment_myhousing import titles_are_near_duplicates

ROOT = Path(__file__).resolve().parents[1]
NEWS_FILE = ROOT / "news.json"

GENERIC_TITLES = {
    "news photo",
    "news image",
    "photo",
    "image",
    "圖片",
    "照片",
}

COMMON_MOJIBAKE = (
    "ï¼",
    "ï½",
    "â€",
    "Ã",
    "Â",
    "æ–",
    "çš",
    "è‡",
    "é€",
    "é—",
    "ðŸ",
    "�",
)

ODD_SYMBOLS = set("¼½¾¿ŒœŠšŽž€™¤¦¨¬®¯±²³´µ¶·¸¹º»")

CATEGORY_KEYWORDS = {
    "weather": (
        "天氣", "氣象", "颱風", "豪雨", "大雨", "雷雨", "降雨", "雨勢",
        "高溫", "低溫", "冷氣團", "鋒面", "季風", "東北風", "熱浪", "氣溫",
    ),
    "finance": (
        "台股", "美股", "股價", "股東", "股票", "證券", "上市", "上櫃",
        "營收", "財報", "eps", "獲利", "金融", "銀行", "利率", "匯率",
        "投資", "基金", "債券", "控股", "央行", "經濟", "景氣",
    ),
    "housing": (
        "房價", "房市", "房屋", "房地產", "房產", "地產", "不動產", "住宅",
        "建案", "建商", "預售", "成屋", "買房", "購屋", "售屋", "租屋",
        "房貸", "土地", "都更", "危老", "重劃", "社宅", "容積", "房仲",
        "建物買賣移轉", "買賣移轉", "移轉棟數", "交易量",
    ),
}

# Strong enough to identify a weather story from its headline. These are kept
# intentionally specific so a passing weather reference in another topic does
# not move an unrelated story into the weather section.
WEATHER_HEADLINE_KEYWORDS = (
    "豪雨", "大雨", "雷雨", "強降雨", "降雨", "雨勢", "雨彈", "雷雨胞",
    "颱風", "熱帶性低氣壓", "氣象署", "氣象", "天氣", "冷氣團", "寒流",
    "鋒面", "東北季風", "東北風", "高溫", "低溫", "熱浪", "氣溫",
)

# Strong housing-market phrases. These represent the actual subject of a story,
# rather than a passing mention of a house/building. They take precedence over
# incidental weather words such as 「颱風」 in a housing-market headline.
HOUSING_HEADLINE_KEYWORDS = (
    "建物買賣移轉", "買賣移轉量", "買賣移轉", "移轉棟數", "房市交易量",
    "住宅交易量", "房價", "房市", "房地產", "房產", "不動產", "預售屋",
    "預售市場", "成屋市場", "買房", "購屋", "房貸", "都更", "危老",
    "建案", "建商", "重劃區", "社宅", "房仲",
)


def looks_mojibake(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False

    if any(token in text for token in COMMON_MOJIBAKE):
        return True

    arabic = sum(1 for ch in text if "ARABIC" in unicodedata.name(ch, ""))
    odd = sum(1 for ch in text if ch in ODD_SYMBOLS)
    replacement = text.count("\ufffd")
    control = sum(
        1 for ch in text
        if unicodedata.category(ch) in {"Cc", "Cs"} and ch not in "\n\r\t"
    )

    if arabic >= 3:
        return True
    if replacement or control:
        return True
    if odd >= 5 and odd / max(len(text), 1) >= 0.04:
        return True

    latin1_weird = sum(1 for ch in text if 0x00C0 <= ord(ch) <= 0x00FF)
    if latin1_weird >= 6 and latin1_weird / max(len(text), 1) >= 0.05:
        return True

    return False


def bad_title(title: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(title or "")).strip().lower()
    return not cleaned or cleaned in GENERIC_TITLES or looks_mojibake(cleaned)


def series_marker(title: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{1,2})\s*[》〉／/]", str(title or ""))
    return match.group(1) if match else None


def near_duplicate_titles(left: str, right: str) -> bool:
    left_marker = series_marker(left)
    right_marker = series_marker(right)
    if left_marker and right_marker and left_marker != right_marker:
        return False
    return titles_are_near_duplicates(left, right)


def same_story(left: dict, right: dict) -> bool:
    left_url = str(left.get("canonical_url") or left.get("url") or "").strip()
    right_url = str(right.get("canonical_url") or right.get("url") or "").strip()
    if left_url and right_url and left_url == right_url:
        return True
    return near_duplicate_titles(
        str(left.get("title", "")),
        str(right.get("title", "")),
    )


def category_relevance(category: str, item: dict) -> int:
    keywords = CATEGORY_KEYWORDS.get(category, ())
    if not keywords:
        return 0
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return sum(1 for keyword in keywords if keyword in text)


def item_quality(item: dict) -> int:
    summary = str(item.get("summary", "")).strip()
    title = str(item.get("title", "")).strip()
    return len(summary) + len(title)


def duplicate_preference(category: str, item: dict) -> tuple[int, int, int, str]:
    relevance = category_relevance(category, item)

    if category != "instant" and relevance > 0:
        bucket = 2
    elif category == "instant":
        bucket = 1
    else:
        bucket = 0

    return (
        bucket,
        relevance,
        item_quality(item),
        str(item.get("published_at", "")),
    )


def should_be_housing(item: dict) -> bool:
    title = str(item.get("title", "")).lower()
    summary = str(item.get("summary", "")).lower()

    title_hits = sum(1 for keyword in HOUSING_HEADLINE_KEYWORDS if keyword in title)
    if title_hits >= 1:
        return True

    summary_hits = sum(1 for keyword in HOUSING_HEADLINE_KEYWORDS if keyword in summary)
    return summary_hits >= 2


def should_be_weather(item: dict) -> bool:
    # When the headline clearly describes the housing market, an incidental
    # weather word must not hijack the story into the weather category.
    if should_be_housing(item):
        return False

    title = str(item.get("title", "")).lower()
    summary = str(item.get("summary", "")).lower()

    title_hits = sum(1 for keyword in WEATHER_HEADLINE_KEYWORDS if keyword in title)
    if title_hits >= 1:
        return True

    summary_hits = sum(1 for keyword in WEATHER_HEADLINE_KEYWORDS if keyword in summary)
    return summary_hits >= 2


def reclassify_topics(payload: dict) -> tuple[int, int]:
    categories = payload.setdefault("categories", {})
    weather_items = categories.setdefault("weather", [])
    housing_items = categories.setdefault("housing", [])
    weather_moved = 0
    housing_moved = 0

    # First move strong housing-market stories. This ensures that a headline
    # such as 「颱風效應！六都建物買賣移轉量月減...」 remains a housing story.
    for category in list(categories.keys()):
        if category == "housing":
            continue

        remaining: list[dict] = []
        for item in categories.get(category, []):
            if should_be_housing(item):
                print(
                    f"[reclassify] {category} -> housing: "
                    f"{item.get('title', '')[:100]}"
                )
                housing_items.append(item)
                housing_moved += 1
            else:
                remaining.append(item)

        categories[category] = remaining

    # Then classify weather among the remaining stories.
    for category in list(categories.keys()):
        if category in {"weather", "housing"}:
            continue

        remaining = []
        for item in categories.get(category, []):
            if should_be_weather(item):
                print(
                    f"[reclassify] {category} -> weather: "
                    f"{item.get('title', '')[:100]}"
                )
                weather_items.append(item)
                weather_moved += 1
            else:
                remaining.append(item)

        categories[category] = remaining

    # A previously source-classified weather item can also turn out to be an
    # unmistakable housing-market story; move it back to housing if necessary.
    remaining_weather: list[dict] = []
    for item in categories.get("weather", []):
        if should_be_housing(item):
            print(
                f"[reclassify] weather -> housing: "
                f"{item.get('title', '')[:100]}"
            )
            housing_items.append(item)
            housing_moved += 1
        else:
            remaining_weather.append(item)
    categories["weather"] = remaining_weather

    return weather_moved, housing_moved


def dedupe_across_categories(payload: dict) -> int:
    categories = payload.setdefault("categories", {})
    records: list[tuple[str, dict]] = []
    for category, items in categories.items():
        for item in items:
            records.append((category, item))

    records.sort(key=lambda pair: str(pair[1].get("published_at", "")), reverse=True)

    kept: list[tuple[str, dict]] = []
    removed = 0

    for category, item in records:
        duplicate_index: int | None = None
        for index, (_, existing) in enumerate(kept):
            if same_story(item, existing):
                duplicate_index = index
                break

        if duplicate_index is None:
            kept.append((category, item))
            continue

        existing_category, existing_item = kept[duplicate_index]
        if duplicate_preference(category, item) > duplicate_preference(
            existing_category, existing_item
        ):
            print(
                f"[cross-dedupe] replace {existing_category} -> {category}: "
                f"{item.get('title', '')[:90]}"
            )
            kept[duplicate_index] = (category, item)
        else:
            print(
                f"[cross-dedupe] remove {category}, keep {existing_category}: "
                f"{item.get('title', '')[:90]}"
            )
        removed += 1

    rebuilt = {category: [] for category in categories}
    for category, item in kept:
        rebuilt.setdefault(category, []).append(item)

    for category, items in rebuilt.items():
        items.sort(key=lambda item: str(item.get("published_at", "")), reverse=True)
        categories[category] = items

    return removed


def main() -> None:
    if not NEWS_FILE.exists():
        raise SystemExit("news.json not found")

    payload = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    malformed_removed = 0

    for category, items in payload.get("categories", {}).items():
        clean_items = []
        for item in items:
            title = str(item.get("title", ""))
            summary = str(item.get("summary", ""))

            if bad_title(title) or looks_mojibake(summary):
                malformed_removed += 1
                print(
                    f"[sanitize] remove {category}: "
                    f"{item.get('source', '')} / {title[:80]!r}"
                )
                continue

            clean_items.append(item)

        payload["categories"][category] = clean_items

    weather_moved, housing_moved = reclassify_topics(payload)
    duplicate_removed = dedupe_across_categories(payload)

    NEWS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[sanitize] removed {malformed_removed} malformed item(s), "
        f"moved {weather_moved} weather item(s), "
        f"moved {housing_moved} housing item(s), "
        f"{duplicate_removed} duplicate(s)"
    )


if __name__ == "__main__":
    main()
