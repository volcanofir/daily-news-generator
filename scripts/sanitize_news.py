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

SPECIALIZED_CATEGORIES = ("weather", "finance", "housing")
CATEGORY_PRIORITY = {
    "weather": 1,
    "finance": 2,
    "housing": 3,
}
MIN_TOPIC_SCORE = 4

TOPIC_STRONG_KEYWORDS = {
    "weather": (
        "天氣", "氣象署", "氣象", "颱風", "熱帶性低氣壓", "豪雨", "大雨", "暴雨",
        "強降雨", "降雨", "雨勢", "雨彈", "雷雨", "雷雨胞", "陣雨", "下雨", "有雨",
        "鋒面", "東北季風", "冷氣團", "寒流", "高溫", "低溫", "熱浪", "氣溫",
        "土石流", "山洪", "洪水", "淹水", "水災", "積淹水", "梅雨",
    ),
    "finance": (
        "台股", "美股", "股市", "股價", "股票", "證券", "etf", "基金", "債券",
        "匯率", "利率", "央行", "財報", "eps", "營收", "獲利", "法說會", "除權息",
        "大盤", "外資", "投信", "自營商", "金控", "金融股", "新台幣", "美元",
        "殖利率", "通膨", "cpi", "gdp", "經濟成長", "關稅", "出口", "進口", "pmi",
    ),
    "housing": (
        "建物買賣移轉", "買賣移轉量", "買賣移轉", "移轉棟數", "房市交易量",
        "住宅交易量", "房價", "房市", "房地產", "房產", "不動產", "預售屋",
        "預售市場", "成屋市場", "買房", "購屋", "售屋", "租屋", "房貸", "都更",
        "危老", "建案", "建商", "重劃區", "社宅", "房仲", "實價登錄", "租金",
        "房租", "囤房稅", "房屋稅", "地價", "容積率", "容積獎勵", "推案量",
    ),
}

TOPIC_SUPPORT_KEYWORDS = {
    "weather": (
        "東北風", "季風", "低壓", "雲系", "水氣", "對流", "降溫", "升溫", "濕冷",
        "乾冷", "紫外線", "體感", "風雨", "雨區", "焚風", "天候",
    ),
    "finance": (
        "股東", "上市", "上櫃", "市值", "投資", "法人", "銀行", "金融", "經濟",
        "景氣", "企業", "產業", "半導體", "ai晶片", "台積電", "融資", "融券",
        "存款", "放款", "失業率", "薪資", "控股", "訂單", "大單", "採購合約",
        "併購", "收購",
    ),
    "housing": (
        "住宅", "房屋", "土地", "建築", "推案", "買氣", "成交", "坪價", "單價",
        "地政", "地價稅", "交易量", "移轉", "餘屋", "空屋", "交屋", "房型",
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


def keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    lowered = str(text or "").lower()
    return sum(1 for keyword in keywords if keyword in lowered)


def topic_features(category: str, item: dict) -> tuple[int, int, int, int]:
    title = str(item.get("title", ""))
    summary = str(item.get("summary", ""))
    strong = TOPIC_STRONG_KEYWORDS[category]
    support = TOPIC_SUPPORT_KEYWORDS[category]
    return (
        keyword_hits(title, strong),
        keyword_hits(title, support),
        keyword_hits(summary, strong),
        keyword_hits(summary, support),
    )


def has_enough_topic_evidence(category: str, features: tuple[int, int, int, int]) -> bool:
    title_strong, title_support, summary_strong, _ = features
    if category == "weather":
        return (
            title_strong >= 1
            or title_support >= 2
            or summary_strong >= 3
            or (title_support >= 1 and summary_strong >= 1)
        )
    return (
        title_strong >= 1
        or title_support >= 2
        or summary_strong >= 2
        or (title_support >= 1 and summary_strong >= 1)
    )


def topic_score(category: str, item: dict, current_category: str | None = None) -> int:
    features = topic_features(category, item)
    if not has_enough_topic_evidence(category, features):
        return 0
    title_strong, title_support, summary_strong, summary_support = features
    score = (
        title_strong * 4
        + title_support * 2
        + summary_strong * 2
        + summary_support
    )
    if current_category == category:
        score += 1
    return score


def classify_item(current_category: str, item: dict) -> tuple[str, dict[str, int]]:
    scores = {
        category: topic_score(category, item, current_category)
        for category in SPECIALIZED_CATEGORIES
    }
    best_category = max(
        SPECIALIZED_CATEGORIES,
        key=lambda category: (scores[category], CATEGORY_PRIORITY[category]),
    )
    if scores[best_category] < MIN_TOPIC_SCORE:
        return "instant", scores
    return best_category, scores


def item_quality(item: dict) -> int:
    summary = str(item.get("summary", "")).strip()
    title = str(item.get("title", "")).strip()
    return len(summary) + len(title)


def duplicate_preference(category: str, item: dict) -> tuple[int, int, int, int, str]:
    if category in SPECIALIZED_CATEGORIES:
        relevance = topic_score(category, item)
        bucket = 2 if relevance >= MIN_TOPIC_SCORE else 0
        priority = CATEGORY_PRIORITY[category]
    elif category == "instant":
        relevance = 0
        bucket = 1
        priority = 0
    else:
        relevance = 0
        bucket = 0
        priority = 0
    return (
        bucket,
        relevance,
        priority,
        item_quality(item),
        str(item.get("published_at", "")),
    )


def reclassify_topics(payload: dict) -> dict[str, int]:
    categories = payload.setdefault("categories", {})
    for category in ("weather", "instant", "finance", "housing"):
        categories.setdefault(category, [])

    rebuilt = {
        "weather": [],
        "instant": [],
        "finance": [],
        "housing": [],
    }
    moved = {
        "weather": 0,
        "instant": 0,
        "finance": 0,
        "housing": 0,
    }

    for current_category, items in list(categories.items()):
        for item in items:
            target_category, scores = classify_item(current_category, item)
            rebuilt[target_category].append(item)

            if target_category != current_category:
                moved[target_category] += 1
                print(
                    f"[reclassify] {current_category} -> {target_category}: "
                    f"{item.get('title', '')[:100]} "
                    f"(weather={scores['weather']}, "
                    f"finance={scores['finance']}, housing={scores['housing']})"
                )

    for category, items in rebuilt.items():
        items.sort(
            key=lambda item: str(item.get("published_at", "")),
            reverse=True,
        )
        categories[category] = items

    return moved


def dedupe_across_categories(payload: dict) -> int:
    categories = payload.setdefault("categories", {})
    records: list[tuple[str, dict]] = []
    for category, items in categories.items():
        for item in items:
            records.append((category, item))

    records.sort(
        key=lambda pair: str(pair[1].get("published_at", "")),
        reverse=True,
    )

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
            existing_category,
            existing_item,
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
        items.sort(
            key=lambda item: str(item.get("published_at", "")),
            reverse=True,
        )
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

    moved = reclassify_topics(payload)
    duplicate_removed = dedupe_across_categories(payload)

    NEWS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[sanitize] removed {malformed_removed} malformed item(s), "
        f"moved to weather={moved['weather']}, "
        f"finance={moved['finance']}, "
        f"housing={moved['housing']}, "
        f"instant={moved['instant']}, "
        f"{duplicate_removed} duplicate(s)"
    )


if __name__ == "__main__":
    main()
