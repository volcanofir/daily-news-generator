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

TZ = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "news.json"

SOURCES = {
    "weather": {
        "label": "天氣",
        "feeds": [
            {
                "name": "風傳媒・天氣",
                "url": "https://www.storm.mg/channel/120/",
                "resolve_missing_dates": True,
                "max_candidates": 30,
            },
            {
                "name": "TVBS・天氣",
                "url": "https://news.tvbs.com.tw/search?q=天氣&st=tag",
                "resolve_missing_dates": True,
                "max_candidates": 30,
            },
        ],
    },
    "instant": {
        "label": "即時",
        "feeds": [
            {
                "name": "經濟日報",
                "url": "https://money.udn.com/rank/newest/1001/0/1?from=edn_navibar",
            },
            {
                "name": "聯合新聞網",
                "url": "https://udn.com/news/breaknews/1",
            },
            {
                "name": "中時新聞網・即時",
                "url": "https://www.chinatimes.com/realtimenews/",
                "resolve_missing_dates": True,
                "max_candidates": 35,
            },
        ],
    },
    "finance": {
        "label": "金融",
        "feeds": [
            {
                "name": "經濟日報",
                "url": "https://money.udn.com/money/cate/12017?from=edn_navibar",
            },
            {
                "name": "聯合新聞網・產經",
                "url": "https://udn.com/news/cate/2/6644",
            },
        ],
    },
    "housing": {
        "label": "房市",
        "feeds": [
            {
                "name": "經濟日報",
                "url": "https://money.udn.com/money/cate/5593?from=edn_navibar",
            },
            {
                "name": "udn房地產",
                "url": "https://house.udn.com/house/index",
                "resolve_missing_dates": True,
                "max_candidates": 24,
            },
            {
                "name": "風傳媒・房市",
                "url": "https://www.storm.mg/channel/57/",
                "resolve_missing_dates": True,
                "max_candidates": 30,
            },
            {
                "name": "中時房產",
                "url": "https://house.chinatimes.com",
                "resolve_missing_dates": True,
                "max_candidates": 30,
            },
            {
                "name": "好房網News",
                "url": "https://news.housefun.com.tw/news/#news-list",
                "resolve_missing_dates": True,
                "max_candidates": 30,
            },
        ],
    },
}

UDN_PATH_RE = re.compile(r"^/(?:money|news|house)/story/\d+/\d+/?$")
TVBS_PATH_RE = re.compile(r"^/[A-Za-z0-9_-]+/\d+/?$")
CHINATIMES_REALTIME_RE = re.compile(r"^/realtimenews/\d{14}-\d+/?$")
CHINATIMES_HOUSE_RE = re.compile(r"^/\d{14}-\d+/?$")
HOUSEFUN_RE = re.compile(r"^/news/article/\d+\.html/?$")
STORM_RE = re.compile(r"^/(?!channel(?:/|$))(?:[A-Za-z0-9_-]+/)*\d+/?$")

DATE_RE = re.compile(
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?"
)
TIME_DATE_RE = re.compile(
    r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s+(20\d{2})[/-](\d{1,2})[/-](\d{1,2})"
)

GENERIC_TEXT = {
    "上一篇", "下一篇", "看更多", "更多", "即時", "金融", "房市", "產經", "天氣",
    "經濟日報", "聯合新聞網", "udn房地產", "風傳媒", "TVBS", "中時新聞網",
    "中時房產", "好房網News", "首頁", "最新新聞", "熱門新聞",
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
    host = host.lower().split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def canonical_story_url(href: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    host = normalized_host(parsed.netloc)
    path = parsed.path.rstrip("/") or "/"
    canonical_host = host
    valid = False

    if host in {"money.udn.com", "udn.com", "house.udn.com"}:
        valid = bool(UDN_PATH_RE.match(path))
    elif host == "news.tvbs.com.tw":
        valid = bool(TVBS_PATH_RE.match(path))
    elif host == "chinatimes.com":
        valid = bool(CHINATIMES_REALTIME_RE.match(path))
        canonical_host = "www.chinatimes.com"
    elif host == "house.chinatimes.com":
        valid = bool(CHINATIMES_HOUSE_RE.match(path))
    elif host == "news.housefun.com.tw":
        valid = bool(HOUSEFUN_RE.match(path))
    elif host == "storm.mg":
        valid = bool(STORM_RE.match(path))
        canonical_host = "www.storm.mg"

    if not valid:
        return None
    return f"https://{canonical_host}{path}"


def share_url(canonical: str) -> str:
    if urlparse(canonical).netloc == "money.udn.com":
        return canonical + "?from=ednappsharing"
    return canonical


def clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = DATE_RE.sub("", text)
    text = TIME_DATE_RE.sub("", text)
    return text.strip(" ｜|—-•·")


def parse_datetime(text: str) -> datetime | None:
    normalized = (text or "").replace("T", " ")
    match = DATE_RE.search(normalized)
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
    for _ in range(7):
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
        if len(text) <= 1200:
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
    text = re.sub(
        r"^(?:經濟日報|聯合新聞網|udn房地產|風傳媒|TVBS|中時新聞網|好房網News)\s*[|｜\-—]\s*",
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


def looks_mojibake(text: str) -> bool:
    suspicious = ("ï¼", "ه", "وˆ", "ç‡", "è²", "گ", "وœ", "ن»")
    return any(token in (text or "") for token in suspicious)


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
        for value in (time_el.get("datetime"), time_el.get("data-time"), time_el.get_text(" ", strip=True)):
            dt = parse_datetime(str(value or ""))
            if dt:
                return dt

    for pattern in (
        r'"datePublished"\s*:\s*"(20\d{2}-\d{1,2}-\d{1,2}[T ][^"]+)"',
        r'"datePublished"\s*:\s*"(20\d{2}/\d{1,2}/\d{1,2}\s+[^"]+)"',
        r'"published_at"\s*:\s*"(20\d{2}-\d{1,2}-\d{1,2}[T ][^"]+)"',
    ):
        match = re.search(pattern, html)
        if match:
            dt = parse_datetime(match.group(1))
            if dt:
                return dt

    return parse_datetime(soup.get_text(" ", strip=True)[:15000])


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
            "article p", ".article-body p", ".article-content p", "#story_body_content p",
            ".story_body_content p", ".article-content__paragraph p", ".article_content p",
            ".article-main p", ".main-article p", ".story p", ".content p",
        ):
            for p in soup.select(selector):
                text = p.get_text(" ", strip=True)
                if len(text) >= 25 and "歡迎用「轉貼」" not in text:
                    paragraphs.append(text)
                if len("".join(paragraphs)) >= 220:
                    break
            if paragraphs:
                break
        return clean_summary("".join(paragraphs[:2]), title), published
    except Exception as exc:
        print(f"[article] {url}: {exc}")
        return "", None


def load_previous() -> dict[str, dict]:
    if not OUTPUT.exists():
        return {}
    try:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except Exception:
        return {}

    previous: dict[str, dict] = {}
    for items in payload.get("categories", {}).values():
        for item in items:
            if item.get("canonical_url"):
                previous[item["canonical_url"]] = item
    return previous


def item_id(canonical: str) -> str:
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    now = datetime.now(TZ)
    today = now.date()
    previous = load_previous()
    categories: dict[str, list[dict]] = {}

    for key, group in SOURCES.items():
        today_items: list[dict] = []

        for feed in group["feeds"]:
            print(f"[source] {group['label']} / {feed['name']} {feed['url']}")
            try:
                html = fetch(feed["url"])
                candidates = extract_candidates(html, feed["url"])
                max_candidates = int(feed.get("max_candidates", 0) or 0)
                if max_candidates:
                    candidates = candidates[:max_candidates]
                print(f"[candidates] {feed['name']}: {len(candidates)}")
            except Exception as exc:
                print(f"[source-error] {key} / {feed['name']}: {exc}")
                continue

            for candidate in candidates:
                if not candidate.get("title"):
                    continue

                canonical = candidate["url"]
                old = previous.get(canonical, {})
                published = candidate.get("published_at")
                if not published and old.get("published_at"):
                    published = parse_datetime(str(old["published_at"]))

                summary = old.get("summary", "")
                if looks_mojibake(summary):
                    summary = ""

                if not published and feed.get("resolve_missing_dates"):
                    fetched_summary, published = fetch_article_details(canonical, candidate["title"])
                    summary = fetched_summary or summary
                    time.sleep(0.12)

                if not published or published.astimezone(TZ).date() != today:
                    continue

                if not summary:
                    summary, resolved_date = fetch_article_details(canonical, candidate["title"])
                    if not published and resolved_date:
                        published = resolved_date
                    time.sleep(0.12)

                if not published or published.astimezone(TZ).date() != today:
                    continue

                today_items.append(
                    {
                        "id": item_id(canonical),
                        "title": candidate["title"],
                        "published_at": published.isoformat(),
                        "time": published.strftime("%H:%M"),
                        "url": share_url(canonical),
                        "canonical_url": canonical,
                        "summary": summary,
                        "source": feed["name"],
                        "source_url": feed["url"],
                    }
                )

        deduped: dict[str, dict] = {}
        for item in today_items:
            title_key = re.sub(r"[\W_]+", "", item["title"]).lower()[:90]
            existing = deduped.get(title_key)
            if not existing:
                deduped[title_key] = item
                continue
            current_score = len(item.get("summary", "")) + len(item.get("title", ""))
            old_score = len(existing.get("summary", "")) + len(existing.get("title", ""))
            if current_score > old_score:
                deduped[title_key] = item

        categories[key] = sorted(
            deduped.values(),
            key=lambda item: item["published_at"],
            reverse=True,
        )
        print(f"[result] {key}: {len(categories[key])} article(s) today")

    payload = {
        "date": today.isoformat(),
        "updated_at": now.isoformat(),
        "timezone": "Asia/Taipei",
        "sources": SOURCES,
        "categories": categories,
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
