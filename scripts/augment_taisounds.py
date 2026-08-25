from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from augment_myhousing import dedupe_items

TZ = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "news.json"

FEEDS = [
    {
        "name": "太報・房市",
        "url": "https://www.taisounds.com/news/section/81",
        "category": "housing",
        "max_candidates": 35,
    },
    {
        "name": "太報・財經焦點",
        "url": "https://www.taisounds.com/news/section/76",
        "category": "finance",
        "max_candidates": 35,
    },
    {
        "name": "太報・天氣",
        "url": "https://www.taisounds.com/news/section/139",
        "category": "weather",
        "max_candidates": 35,
    },
]

TAISOUNDS_STORY_RE = re.compile(r"^/news/content/\d+/\d+/?$", re.IGNORECASE)
DATE_TIME_RE = re.compile(
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?"
)
TIME_DATE_RE = re.compile(
    r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s+(20\d{2})[/-](\d{1,2})[/-](\d{1,2})"
)

GENERIC_TEXT = {
    "上一篇", "下一篇", "看更多", "更多", "首頁", "熱門", "最新", "快訊",
    "房市", "財經焦點", "天氣", "太報", "TaiSounds",
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
    if normalized_host(parsed.netloc) != "taisounds.com":
        return None
    path = parsed.path.rstrip("/") or "/"
    if not TAISOUNDS_STORY_RE.match(path):
        return None
    return f"https://www.taisounds.com{path}"


def parse_datetime(text: str) -> datetime | None:
    normalized = (text or "").replace("T", " ")
    match = DATE_TIME_RE.search(normalized)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=TZ
        )
    match = TIME_DATE_RE.search(normalized)
    if match:
        hour, minute, second, year, month, day = match.groups()
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=TZ
        )
    return None


def clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = DATE_TIME_RE.sub("", text)
    text = TIME_DATE_RE.sub("", text)
    text = re.sub(r"\s*/\s*作者\s+.*$", "", text)
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
            title for title in options
            if title and title not in GENERIC_TEXT and 6 <= len(title) <= 180
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
    text = re.sub(r"^(?:太報|TaiSounds)\s*[|｜\-—]\s*", "", text, flags=re.IGNORECASE)
    if title and text.startswith(title):
        text = text[len(title):].lstrip(" ｜|—-：:")
    if len(text) > 150:
        cut = max(text.rfind("。", 0, 150), text.rfind("；", 0, 150))
        if cut >= 65:
            text = text[: cut + 1]
        else:
            text = text[:147].rstrip("，、；： ") + "…"
    return text


def extract_article_datetime(soup: BeautifulSoup, html: str) -> datetime | None:
    for attr, value in (
        ("property", "article:published_time"),
        ("property", "article:published"),
        ("name", "article:published_time"),
        ("name", "date"),
        ("name", "pubdate"),
        ("name", "publishdate"),
        ("itemprop", "datePublished"),
    ):
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

    for pattern in (
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"published_at"\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, html)
        if match:
            dt = parse_datetime(match.group(1))
            if dt:
                return dt

    return parse_datetime(soup.get_text(" ", strip=True)[:12000])


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
                if len(summary) >= 25:
                    return summary, published

        paragraphs: list[str] = []
        for selector in (
            "article p", ".article-content p", ".news-content p", ".content p", "main p"
        ):
            for p in soup.select(selector):
                text = p.get_text(" ", strip=True)
                if len(text) >= 25 and "更多太報報導" not in text:
                    paragraphs.append(text)
                if len("".join(paragraphs)) >= 240:
                    break
            if paragraphs:
                break
        return clean_summary("".join(paragraphs[:2]), title), published
    except Exception as exc:
        print(f"[taisounds-article] {url}: {exc}")
        return "", None


def item_id(canonical: str) -> str:
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def add_source_metadata(payload: dict) -> None:
    sources = payload.setdefault("sources", {})
    labels = {"weather": "天氣", "finance": "金融", "housing": "房市"}
    for feed in FEEDS:
        category = feed["category"]
        group = sources.setdefault(category, {"label": labels[category], "feeds": []})
        feeds = group.setdefault("feeds", [])
        existing_urls = {item.get("url") for item in feeds if isinstance(item, dict)}
        if feed["url"] not in existing_urls:
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
    categories = payload.setdefault("categories", {})
    added_counts = {"weather": 0, "finance": 0, "housing": 0}

    for feed in FEEDS:
        category = feed["category"]
        new_items: list[dict] = []
        print(f"[taisounds-source] {category} / {feed['name']} {feed['url']}")
        try:
            html = fetch(feed["url"])
            candidates = extract_candidates(html, feed["url"])
            candidates = candidates[: int(feed["max_candidates"])]
            print(f"[taisounds-candidates] {feed['name']}: {len(candidates)}")
        except Exception as exc:
            print(f"[taisounds-source-error] {feed['name']}: {exc}")
            continue

        for candidate in candidates:
            title = candidate.get("title", "")
            if not title:
                continue

            published = candidate.get("published_at")
            if published and published.astimezone(TZ).date() != today:
                continue

            summary, resolved_date = fetch_article_details(candidate["url"], title)
            if not published and resolved_date:
                published = resolved_date
            time.sleep(0.08)

            if not published or published.astimezone(TZ).date() != today:
                continue

            canonical = candidate["url"]
            new_items.append(
                {
                    "id": item_id(canonical),
                    "title": title,
                    "published_at": published.isoformat(),
                    "time": published.strftime("%H:%M"),
                    "url": canonical,
                    "canonical_url": canonical,
                    "summary": summary,
                    "source": feed["name"],
                    "source_url": feed["url"],
                }
            )

        existing = list(categories.get(category, []))
        categories[category] = dedupe_items(existing + new_items)
        added_counts[category] += len(new_items)
        print(
            f"[taisounds-result] {category}: {len(new_items)} candidate(s) today; "
            f"{len(categories[category])} after dedupe"
        )

    add_source_metadata(payload)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[taisounds-result] added today: {added_counts}")


if __name__ == "__main__":
    main()
