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
        "category": "instant",
        "name": "自由時報・即時新聞",
        "url": "https://news.ltn.com.tw/list/breakingnews",
        "max_candidates": 45,
    },
    {
        "category": "housing",
        "name": "自由時報・地產天下",
        "url": "https://estate.ltn.com.tw/news",
        "max_candidates": 30,
    },
    {
        "category": "housing",
        "name": "自由財經・房產資訊",
        "url": "https://ec.ltn.com.tw/list/estate",
        "max_candidates": 30,
    },
]

DATE_TIME_RE = re.compile(
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?"
)
TIME_DATE_RE = re.compile(
    r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s+(20\d{2})[/-](\d{1,2})[/-](\d{1,2})"
)

GENERIC_TEXT = {
    "即時", "熱門", "政治", "社會", "生活", "國際", "地方", "財經", "地產",
    "最新新聞", "房產資訊", "更多", "看更多", "首頁", "自由時報", "自由財經",
    "地產天下", "自由電子報", "上一篇", "下一篇",
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
    host = normalized_host(parsed.netloc)
    path = parsed.path.rstrip("/") or "/"

    if host == "news.ltn.com.tw":
        if not re.match(r"^/news/[^/]+/breakingnews/\d+$", path):
            return None
        return f"https://news.ltn.com.tw{path}"

    if host == "estate.ltn.com.tw":
        if not re.match(r"^/article/\d+$", path):
            return None
        return f"https://estate.ltn.com.tw{path}"

    if host == "ec.ltn.com.tw":
        if not re.match(r"^/article/(?:breakingnews|paper)/\d+$", path):
            return None
        return f"https://ec.ltn.com.tw{path}"

    return None


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
        if len(text) <= 1600:
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
        r"^(?:自由時報|自由財經|地產天下|自由電子報)\s*[|｜\-—]\s*",
        "",
        text,
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
        r'"published_time"\s*:\s*"([^"]+)"',
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

        if not title:
            heading = soup.find("h1")
            if heading:
                title = clean_title(heading.get_text(" ", strip=True))

        for attrs in (
            {"property": "og:description"},
            {"name": "description"},
            {"name": "twitter:description"},
        ):
            meta = soup.find("meta", attrs=attrs)
            if meta and meta.get("content"):
                summary = clean_summary(str(meta["content"]), title)
                if len(summary) >= 25 and "自由時報版權所有" not in summary:
                    return summary, published

        paragraphs: list[str] = []
        for selector in (
            "article p", ".text p", ".content p", ".article-body p",
            ".news_content p", ".whitecon p", "main p",
        ):
            for p in soup.select(selector):
                text = p.get_text(" ", strip=True)
                if (
                    len(text) >= 25
                    and "請繼續往下閱讀" not in text
                    and "不用抽" not in text
                    and "自由時報版權所有" not in text
                ):
                    paragraphs.append(text)
                if len("".join(paragraphs)) >= 240:
                    break
            if paragraphs:
                break

        return clean_summary("".join(paragraphs[:2]), title), published
    except Exception as exc:
        print(f"[ltn-article] {url}: {exc}")
        return "", None


def item_id(canonical: str) -> str:
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def add_source_metadata(payload: dict) -> None:
    sources = payload.setdefault("sources", {})
    for feed in FEEDS:
        category = feed["category"]
        group = sources.setdefault(category, {"label": "即時" if category == "instant" else "房市", "feeds": []})
        feeds = group.setdefault("feeds", [])
        if not any(item.get("url") == feed["url"] for item in feeds if isinstance(item, dict)):
            feeds.append({"name": feed["name"], "url": feed["url"]})


def main() -> None:
    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    today = datetime.now(TZ).date()
    categories = payload.setdefault("categories", {})
    add_source_metadata(payload)

    added_by_category = {"instant": 0, "housing": 0}

    for feed in FEEDS:
        print(f"[ltn-source] {feed['name']} {feed['url']}")
        try:
            html = fetch(feed["url"])
            candidates = extract_candidates(html, feed["url"])
            candidates = candidates[: int(feed.get("max_candidates", 30))]
            print(f"[ltn-candidates] {feed['name']}: {len(candidates)}")
        except Exception as exc:
            print(f"[ltn-source-error] {feed['name']}: {exc}")
            continue

        for candidate in candidates:
            canonical = candidate["url"]
            title = candidate.get("title", "")
            published = candidate.get("published_at")
            summary = ""

            # LTN listing pages do not always expose the complete date, so resolve
            # article metadata when date/title is missing.
            if not published or not title:
                fetched_summary, resolved = fetch_article_details(canonical, title)
                summary = fetched_summary
                published = published or resolved
                time.sleep(0.10)

            if not published or published.astimezone(TZ).date() != today:
                continue

            if not summary:
                summary, resolved = fetch_article_details(canonical, title)
                published = published or resolved
                time.sleep(0.10)

            if not title:
                # If the listing had no usable title, avoid inserting an ambiguous row.
                continue

            category = feed["category"]
            categories.setdefault(category, []).append(
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
            added_by_category[category] += 1

    for category in ("instant", "housing"):
        before = len(categories.get(category, []))
        categories[category] = dedupe_items(categories.get(category, []))
        after = len(categories[category])
        print(
            f"[ltn-result] {category}: added {added_by_category[category]}, "
            f"{before} -> {after} after dedupe"
        )

    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
