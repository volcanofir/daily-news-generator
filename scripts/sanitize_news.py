from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

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


def main() -> None:
    if not NEWS_FILE.exists():
        raise SystemExit("news.json not found")

    payload = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    removed = 0

    for category, items in payload.get("categories", {}).items():
        clean_items = []
        for item in items:
            title = str(item.get("title", ""))
            summary = str(item.get("summary", ""))

            if bad_title(title) or looks_mojibake(summary):
                removed += 1
                print(
                    f"[sanitize] remove {category}: "
                    f"{item.get('source', '')} / {title[:80]!r}"
                )
                continue

            clean_items.append(item)

        payload["categories"][category] = clean_items

    NEWS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[sanitize] removed {removed} malformed item(s)")


if __name__ == "__main__":
    main()
