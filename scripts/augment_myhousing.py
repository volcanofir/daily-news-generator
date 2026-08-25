from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "news.json"

FEEDS = [
    {
        "name": "住展雜誌・新北市況",
        "url": "https://www.myhousing.com.tw/category/n/n02/n0202/new-taipei-city/",
        "max_candidates": 30,
    },
    {
        "name": "住展雜誌・北部新聞",
        "url": "https://www.myhousing.com.tw/category/n/n01/north-taiwan/",
        "max_candidates": 30,
    },
    {
        "name": "住展雜誌・專題報導",
        "url": "https://www.myhousing.com.tw/category/t/t01/",
        "max_candidates": 30,
    },
    {
        "name": "住展雜誌・房市動態",
        "url": "https://www.myhousing.com.tw/category/n/n01/",
        "max_candidates": 30,
    },
]

MYHOUSING_STORY_RE = re.compile(
    r"^/(?:n|t)/(?:[a-z0-9-]+/)+\d+/?$",
    re.IGNORECASE,
)
DATE_TIME_RE = re.compile(
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?"
)
TIME_DATE_RE = re.compile(
    r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s+(20\d{2})[/-](\d{1,2})[/-](\d{1,2})"
)
DATE_ONLY_RE = re.compile(r"(?<!\d)(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?!\d)")

GENERIC_TEXT = {
    "上一篇",
    "下一篇",
    "看更多",
    "更多",
    "首頁",
    "房市動態",
    "北部新聞",
    "新北市況",
    "專題報導",
    "住展雜誌",
    "住展雜誌 MyHousing",
    "MyHousing",
}

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6",
        "Cache-Control": "no-cache",
    }
)


def fetch(url: str, timeout: int = 25) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError:
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text


def normalized_host(host: str) -> str:
    host = (host or "").lower().split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def canonical_story_url(href: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if normalized_host(parsed.netloc) != "myhousing.com.tw":
        return None
    path = parsed.path.rstrip("/") or "/"
    if not MYHOUSING_STORY_RE.match(path):
        return None
    return f"https://www.myhousing.com.tw{path}/"


def parse_datetime(text: str) -> datetime | None:
    normalized = (text or "").replace("T", " ")

    match = DATE_TIME_RE.search(normalized)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
            tzinfo=TZ,
        )

    match = TIME_DATE_RE.search(normalized)
    if match:
        hour, minute, second, year, month, day = match.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
            tzinfo=TZ,
        )

    match = DATE_ONLY_RE.search(normalized)
    if match:
        year, month, day = match.groups()
        return datetime(int(year), int(month), int(day), tzinfo=TZ)

    return None


def clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = DATE_TIME_RE.sub("", text)
    text = TIME_DATE_RE.sub("", text)
    return text.strip(" ｜|—-•·")


def nearest_datetime(anchor) -> datetime | None:
    node = anchor
    for _ in range(8):
        if node is None:
            break

        if hasattr(node, "find"):
            time_el = node.find("time")
            if time_el:
                for value in (
                    time_el.get("datetime"),
                    time_el.get("data-time"),
                    time_el.get_text(" ", strip=True),
                ):
                    dt = parse_datetime(str(value or ""))
                    if dt:
                        return dt

            for attr in ("datetime", "data-time", "data-date", "data-datetime"):
                value = node.attrs.get(attr) if hasattr(node, "attrs") else None
                if value:
                    dt = parse_datetime(str(value))
                    if dt:
                        return dt

        text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
        if len(text) <= 1800:
            dt = parse_datetime(text)
            if dt:
                return dt
        node = getattr(node, "parent", None)
    return None


def extract_candidates(html: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict] = {}

    for anchor in soup.find_all("a", href=True):
        canonical = canonical_story_url(anchor["href"], source_url)
        if not canonical:
            continue

        options: list[str] = []
        for selector in ("h1", "h2", "h3", "h4", "h5", ".title", ".news-title"):
            el = anchor.select_one(selector)
            if el:
                options.append(clean_title(el.get_text(" ", strip=True)))
        for attr in ("title", "aria-label"):
            if anchor.get(attr):
                options.append(clean_title(str(anchor.get(attr))))
        img = anchor.find("img")
        if img and img.get("alt"):
            options.append(clean_title(str(img.get("alt"))))
        options.append(clean_title(anchor.get_text(" ", strip=True)))

        options = [
            title
            for title in options
            if title
            and title not in GENERIC_TEXT
            and 6 <= len(title) <= 180
            and not title.lower().startswith("image:")
        ]
        title = min(options, key=len) if options else ""
        published = nearest_datetime(anchor)

        item = found.setdefault(
            canonical,
            {"url": canonical, "title": "", "published_at": None},
        )
        if title and (not item["title"] or len(title) < len(item["title"])):
            item["title"] = title
        if published and not item["published_at"]:
            item["published_at"] = published

    return list(found.values())


def clean_summary(text: str, title: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(
        r"^(?:住展雜誌(?:\s*MyHousing)?|MyHousing)\s*[|｜\-—]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if title and text.startswith(title):
        text = text[len(title) :].lstrip(" ｜|—-：:")
    if len(text) > 150:
        cut = max(text.rfind("。", 0, 150), text.rfind("；", 0, 150))
        if cut >= 65:
            text = text[: cut + 1]
        else:
            text = text[:147].rstrip("，、；： ") + "…"
    return text


def extract_article_datetime(soup: BeautifulSoup, html: str) -> datetime | None:
    meta_keys = (
        ("property", "article:published_time"),
        ("property", "article:published"),
        ("name", "article:published_time"),
        ("name", "date"),
        ("name", "pubdate"),
        ("name", "publishdate"),
        ("itemprop", "datePublished"),
    )
    for attr, value in meta_keys:
        el = soup.find(attrs={attr: value})
        if el:
            candidate = el.get("content") or el.get("datetime") or el.get_text(" ", strip=True)
            dt = parse_datetime(str(candidate or ""))
            if dt:
                return dt

    for time_el in soup.find_all("time"):
        for value in (
            time_el.get("datetime"),
            time_el.get("data-time"),
            time_el.get_text(" ", strip=True),
        ):
            dt = parse_datetime(str(value or ""))
            if dt:
                return dt

    text = soup.get_text(" ", strip=True)
    match = re.search(r"刊登日期\s*[｜|:]?\s*(20\d{2}[/-]\d{1,2}[/-]\d{1,2})", text)
    if match:
        dt = parse_datetime(match.group(1))
        if dt:
            return dt

    for pattern in (
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"published_at"\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, html)
        if match:
            dt = parse_datetime(match.group(1))
            if dt:
                return dt

    return None


def fetch_article_details(url: str, title: str) -> tuple[str, datetime | None]:
    try:
        html = fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        published = extract_article_datetime(soup, html)

        for attrs in (
            {"property": "og:description"},
            {"name": "description"},
            {"name": "twitter:description"},
        ):
            meta = soup.find("meta", attrs=attrs)
            if meta and meta.get("content"):
                summary = clean_summary(str(meta["content"]), title)
                if len(summary) >= 25 and "住展從1985年" not in summary:
                    return summary, published

        paragraphs: list[str] = []
        for selector in (
            "article p",
            ".entry-content p",
            ".article-content p",
            ".article-body p",
            ".content p",
            "main p",
        ):
            for p in soup.select(selector):
                text = p.get_text(" ", strip=True)
                if (
                    len(text) >= 25
                    and "住展從1985年" not in text
                    and "官方網站" not in text
                    and "FB粉絲團" not in text
                ):
                    paragraphs.append(text)
                if len("".join(paragraphs)) >= 240:
                    break
            if paragraphs:
                break

        return clean_summary("".join(paragraphs[:2]), title), published
    except Exception as exc:
        print(f"[myhousing-article] {url}: {exc}")
        return "", None


def item_id(canonical: str) -> str:
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def normalized_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", title or "").lower()


def series_marker(title: str) -> str | None:
    match = re.search(r"(?:^|\s)(\d{1,2})\s*[／/]", title or "")
    return match.group(1) if match else None


def bigrams(value: str) -> set[str]:
    text = normalized_title(value)
    if len(text) < 2:
        return set()
    return {text[index : index + 2] for index in range(len(text) - 1)}


def titles_are_near_duplicates(left: str, right: str) -> bool:
    a = normalized_title(left)
    b = normalized_title(right)
    if not a or not b:
        return False
    if a == b:
        return True

    left_series = series_marker(left)
    right_series = series_marker(right)
    if left_series and right_series and left_series != right_series:
        return False

    shorter, longer = sorted((a, b), key=len)
    if len(shorter) < 12:
        return False

    if shorter in longer and len(shorter) / len(longer) >= 0.76:
        return True

    if SequenceMatcher(None, a, b).ratio() >= 0.88:
        return True

    a_pairs = bigrams(a)
    b_pairs = bigrams(b)
    if not a_pairs or not b_pairs:
        return False
    common = len(a_pairs & b_pairs)
    containment = common / min(len(a_pairs), len(b_pairs))
    return common >= 12 and containment >= 0.80


def item_quality(item: dict) -> int:
    return len(item.get("summary", "")) + len(item.get("title", ""))


def dedupe_items(items: list[dict]) -> list[dict]:
    sorted_items = sorted(
        items,
        key=lambda item: item.get("published_at", ""),
        reverse=True,
    )
    kept: list[dict] = []

    for item in sorted_items:
        duplicate_index: int | None = None
        for index, existing in enumerate(kept):
            same_url = (
                item.get("canonical_url")
                and item.get("canonical_url") == existing.get("canonical_url")
            )
            if same_url or titles_are_near_duplicates(
                item.get("title", ""), existing.get("title", "")
            ):
                duplicate_index = index
                break

        if duplicate_index is None:
            kept.append(item)
            continue

        existing = kept[duplicate_index]
        same_time = item.get("published_at", "") == existing.get("published_at", "")
        if same_time and item_quality(item) > item_quality(existing):
            kept[duplicate_index] = item

    return sorted(
        kept,
        key=lambda item: item.get("published_at", ""),
        reverse=True,
    )


def add_source_metadata(payload: dict) -> None:
    sources = payload.setdefault("sources", {})
    housing = sources.setdefault("housing", {"label": "房市", "feeds": []})
    feeds = housing.setdefault("feeds", [])
    existing_urls = {feed.get("url") for feed in feeds if isinstance(feed, dict)}

    for feed in FEEDS:
        if feed["url"] in existing_urls:
            continue
        feeds.append(
            {
                "name": feed["name"],
                "url": feed["url"],
                "resolve_missing_dates": True,
                "max_candidates": feed["max_candidates"],
            }
        )


def main() -> None:
    if not OUTPUT.exists():
        raise SystemExit("news.json not found; run fetch_news.py first")

    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    now = datetime.now(TZ)
    today = now.date()
    housing_items = list(payload.get("categories", {}).get("housing", []))
    myhousing_items: list[dict] = []

    for feed in FEEDS:
        print(f"[myhousing-source] {feed['name']} {feed['url']}")
        try:
            html = fetch(feed["url"])
            candidates = extract_candidates(html, feed["url"])
            candidates = candidates[: int(feed["max_candidates"])]
            print(f"[myhousing-candidates] {feed['name']}: {len(candidates)}")
        except Exception as exc:
            print(f"[myhousing-source-error] {feed['name']}: {exc}")
            continue

        for candidate in candidates:
            title = candidate.get("title", "")
            if not title:
                continue

            published = candidate.get("published_at")
            if published and published.astimezone(TZ).date() != today:
                continue

            summary = ""
            if not published or published.astimezone(TZ).date() == today:
                summary, resolved_date = fetch_article_details(candidate["url"], title)
                if not published and resolved_date:
                    published = resolved_date
                time.sleep(0.10)

            if not published or published.astimezone(TZ).date() != today:
                continue

            canonical = candidate["url"]
            myhousing_items.append(
                {
                    "id": item_id(canonical),
                    "title": title,
                    "published_at": published.isoformat(),
                    "time": "今日" if published.hour == 0 and published.minute == 0 else published.strftime("%H:%M"),
                    "url": canonical,
                    "canonical_url": canonical,
                    "summary": summary,
                    "source": feed["name"],
                    "source_url": feed["url"],
                }
            )

    merged_housing = dedupe_items(housing_items + myhousing_items)
    payload.setdefault("categories", {})["housing"] = merged_housing

    # Apply the same conservative duplicate filter to all categories. This removes
    # exact/near-exact headlines, while intentionally leaving differently worded
    # articles about the same broad topic visible.
    for category, items in list(payload.get("categories", {}).items()):
        if isinstance(items, list):
            payload["categories"][category] = dedupe_items(items)

    add_source_metadata(payload)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"[myhousing-result] added candidates today: {len(myhousing_items)}")
    print(f"[myhousing-result] housing after dedupe: {len(merged_housing)}")


if __name__ == "__main__":
    main()
