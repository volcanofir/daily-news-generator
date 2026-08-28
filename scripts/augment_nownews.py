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

FEED = {
    "category": "weather",
    "name": "NOWnews・天氣",
    "url": "https://www.nownews.com/cat/life/weatherforecast/",
    "max_candidates": 35,
}

DATE_TIME_RE = re.compile(
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?"
)
TIME_DATE_RE = re.compile(
    r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s+(20\d{2})[/-](\d{1,2})[/-](\d{1,2})"
)
GENERIC_TEXT = {
    "NOWnews今日新聞", "NOWNEWS今日新聞", "NOWnews", "今日新聞", "生活", "天氣預報",
    "天氣", "首頁", "看更多新聞", "看更多", "更多", "熱門", "上一篇", "下一篇",
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


def canonical_story_url(href: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    if host != "nownews.com":
        return None
    if not re.match(r"^/news/\d+$", path):
        return None
    return f"https://www.nownews.com{path}"


def clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = DATE_TIME_RE.sub("", text)
    text = TIME_DATE_RE.sub("", text)
    return text.strip(" ｜|—-•·")


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


def extract_candidates(html: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict] = {}

    for anchor in soup.find_all("a", href=True):
        canonical = canonical_story_url(anchor["href"], source_url)
        if not canonical:
            continue

        options: list[str] = []
        for selector in ("h1", "h2", "h3", "h4", ".title", ".news-title"):
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
            and not title.lower().startswith("image:")
        ]
        title = min(options, key=len) if options else ""

        item = found.setdefault(canonical, {"url": canonical, "title": ""})
        if title and (not item["title"] or len(title) < len(item["title"])):
            item["title"] = title

    return list(found.values())


def clean_summary(text: str, title: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(
        r"^(?:NOWnews今日新聞|NOWNEWS今日新聞|NOWnews|NOWNEWS)\s*[|｜\-—]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
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

    for pattern in (
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"published_time"\s*:\s*"([^"]+)"',
        r'"publish_date"\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, html)
        if match:
            dt = parse_datetime(match.group(1))
            if dt:
                return dt

    return parse_datetime(soup.get_text(" ", strip=True)[:15000])


def fetch_article_details(url: str, title: str) -> tuple[str, datetime | None, str]:
    try:
        html = fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        published = extract_article_datetime(soup, html)

        resolved_title = title
        if not resolved_title:
            heading = soup.find("h1")
            if heading:
                resolved_title = clean_title(heading.get_text(" ", strip=True))

        for attrs in (
            {"property": "og:description"},
            {"name": "description"},
            {"name": "twitter:description"},
        ):
            meta = soup.find("meta", attrs=attrs)
            if meta and meta.get("content"):
                summary = clean_summary(str(meta["content"]), resolved_title)
                if len(summary) >= 25:
                    return summary, published, resolved_title

        paragraphs: list[str] = []
        for selector in (
            "article p", ".article-body p", ".article-content p", ".content p", "main p",
        ):
            for p in soup.select(selector):
                text = p.get_text(" ", strip=True)
                if len(text) >= 25 and "我是廣告" not in text and "NOWNEWS APP" not in text:
                    paragraphs.append(text)
                if len("".join(paragraphs)) >= 240:
                    break
            if paragraphs:
                break

        return clean_summary("".join(paragraphs[:2]), resolved_title), published, resolved_title
    except Exception as exc:
        print(f"[nownews-article] {url}: {exc}")
        return "", None, title


def item_id(canonical: str) -> str:
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def add_source_metadata(payload: dict) -> None:
    sources = payload.setdefault("sources", {})
    group = sources.setdefault("weather", {"label": "天氣", "feeds": []})
    feeds = group.setdefault("feeds", [])
    if not any(item.get("url") == FEED["url"] for item in feeds if isinstance(item, dict)):
        feeds.append({"name": FEED["name"], "url": FEED["url"]})


def main() -> None:
    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    today = datetime.now(TZ).date()
    categories = payload.setdefault("categories", {})
    add_source_metadata(payload)

    print(f"[nownews-source] {FEED['name']} {FEED['url']}")
    try:
        html = fetch(FEED["url"])
        candidates = extract_candidates(html, FEED["url"])
        candidates = candidates[: int(FEED.get("max_candidates", 35))]
        print(f"[nownews-candidates] {len(candidates)}")
    except Exception as exc:
        print(f"[nownews-source-error] {exc}")
        candidates = []

    added = 0
    weather = categories.setdefault("weather", [])

    for candidate in candidates:
        canonical = candidate["url"]
        title = candidate.get("title", "")
        summary, published, resolved_title = fetch_article_details(canonical, title)
        title = title or resolved_title
        time.sleep(0.08)

        if not published or published.astimezone(TZ).date() != today or not title:
            continue

        weather.append(
            {
                "id": item_id(canonical),
                "title": title,
                "published_at": published.isoformat(),
                "time": published.strftime("%H:%M"),
                "url": canonical,
                "canonical_url": canonical,
                "summary": summary,
                "source": FEED["name"],
                "source_url": FEED["url"],
            }
        )
        added += 1

    before = len(weather)
    categories["weather"] = dedupe_items(weather)
    after = len(categories["weather"])
    print(f"[nownews-result] added {added}, weather {before} -> {after} after dedupe")

    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
