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
    ),
}


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

    # The sources in this project are Traditional-Chinese news sites. A cluster
    # of Arabic/extended mojibake characters is a reliable sign of a bad decode.
    if arabic >= 3:
        return True
    if replacement or control:
        return True
    if odd >= 5 and odd / max(len(text), 1) >= 0.04:
        return True

    # Typical UTF-8 bytes decoded with the wrong legacy encoding often create
    # many Latin-1 supplement characters mixed with punctuation.
    latin1_weird = sum(1 for ch in text if 0x00C0 <= ord(ch) <= 0x00FF)
    if latin1_weird >= 6 and latin1_weird / max(len(text), 1) >= 0.05:
        return True

    return False


def bad_title(title: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(title or "")).strip().lower()
    return not cleaned or cleaned in GENERIC_TITLES or looks_mojibake(cleaned)


def series_marker(title: str) -> str | None:
    # Protect numbered series such as 「醫院大股東3》」 and 「醫院大股東4》」
    # from being treated as the same story merely because most words overlap.
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

    # A topic-specific category wins only when the story itself contains clear
    # signals for that category. Otherwise "instant" is the safer fallback.
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


def dedupe_across_categories(payload: dict) -> int:
    categories = payload.setdefault("categories", {})
    records: list[tuple[str, dict]] = []
    for category, items in categories.items():
        for item in items:
            records.append((category, item))

    # Newer rows are considered first, while duplicate_preference decides which
    # category should own a story when the same/near-identical headline appears
    # in more than one section.
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

    duplicate_removed = dedupe_across_categories(payload)

    NEWS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[sanitize] removed {malformed_removed} malformed item(s), "
        f"{duplicate_removed} cross-category duplicate(s)"
    )


if __name__ == "__main__":
    main()
