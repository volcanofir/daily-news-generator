from __future__ import annotations

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

# Each website section can merge multiple sources. The frontend still renders
# only the three user-facing groups: 即時 / 金融 / 房市.
SOURCES = {
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
        ],
    },
}

STORY_PATH_RE = re.compile(r"^/(?:money|news|house)/story/\d+/\d+/?$")
DATE_RE = re.compile(
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?"
)
GENERIC_TEXT = {
    "上一篇", "下一篇", "看更多", "更多", "即時", "金融", "房市", "產經",
    "經濟日報", "聯合新聞網", "udn房地產",
}

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0 Safari/537.36"
        ),
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6",
        "Cache-Control": "no-cache",
    }
)


def fetch(url: str, timeout: int = 20) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    # UDN pages are UTF-8. Charset auto-detection can misidentify some
    # Traditional Chinese article pages and produce mojibake.
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError:
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text


def canonical_story_url(href: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host not in {"money.udn.com", "udn.com", "www.udn.com", "house.udn.com"}:
        return None
    if not STORY_PATH_RE.match(parsed.path):
        return None

    if host == "www.udn.com":
        host = "udn.com"
    return f"https://{host}{parsed.path.rstrip('/')}"


def share_url(canonical: str) -> str:
    parsed = urlparse(canonical)
    if parsed.netloc == "money.udn.com":
        return canonical + "?from=ednappsharing"
    return canonical


def clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = DATE_RE.sub("", text).strip(" ｜|—-")
    return text


def parse_datetime(text: str) -> datetime | None:
    normalized = (text or "").replace("T", " ")
    match = DATE_RE.search(normalized)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    return datetime(
        int(year), int(month), int(day),
        int(hour), int(minute), int(second or 0),
        tzinfo=TZ,
    )


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
        if len(text) <= 900:
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

        title_options: list[str] = []
        for selector in ("h1", "h2", "h3", "h4", "h5", ".title"):
            el = anchor.select_one(selector)
            if el:
                title_options.append(clean_title(el.get_text(" ", strip=True)))

        for attr in ("title", "aria-label"):
            if anchor.get(attr):
                title_options.append(clean_title(str(anchor.get(attr))))

        title_options.append(clean_title(anchor.get_text(" ", strip=True)))
        title_options = [
            t for t in title_options
            if t and t not in GENERIC_TEXT and 6 <= len(t) <= 180
        ]
        title = min(title_options, key=len) if title_options else ""
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
    text = re.sub(r"^(?:經濟日報|聯合新聞網|udn房地產)\s*[|｜\-—]\s*", "", text)
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
        ("name", "article:published_time"),
        ("name", "date"),
        ("name", "pubdate"),
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
        for value in (time_el.get("datetime"), time_el.get_text(" ", strip=True)):
            dt = parse_datetime(str(value or ""))
            if dt:
                return dt

    # UDN properties commonly expose datePublished in JSON-LD.
    match = re.search(
        r'"datePublished"\s*:\s*"(20\d{2}-\d{1,2}-\d{1,2}[T ]\d{1,2}:\d{2}(?::\d{2})?[^\"]*)"',
        html,
    )
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
                summary = clean_summary(meta["content"], title)
                if len(summary) >= 25:
                    return summary, published

        paragraphs = []
        for selector in (
            "article p",
            ".article-body p",
            ".article-content p",
            "#story_body_content p",
            ".story_body_content p",
            ".article-content__paragraph p",
        ):
            for p in soup.select(selector):
                text = p.get_text(" ", strip=True)
                if len(text) >= 25 and "歡迎用「轉貼」" not in text:
                    paragraphs.append(text)
                if len("".join(paragraphs)) >= 180:
                    break
            if paragraphs:
                break
        return clean_summary("".join(paragraphs[:2]), title), published
    except Exception as exc:
        print(f"[article] {url}: {exc}")
        return "", None


def fetch_article_summary(url: str, title: str) -> str:
    summary, _ = fetch_article_details(url, title)
    return summary


def load_previous() -> dict[str, dict]:
    if not OUTPUT.exists():
        return {}
    try:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except Exception:
        return {}

    previous = {}
    for items in payload.get("categories", {}).values():
        for item in items:
            if item.get("canonical_url"):
                previous[item["canonical_url"]] = item
            # Also index by numeric story id so the same UDN story shared by
            # money.udn.com and udn.com can reuse its summary.
            if item.get("id"):
                previous[f"id:{item['id']}"] = item
    return previous


def story_id(canonical: str) -> str:
    return canonical.rsplit("/", 1)[-1]


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
            except Exception as exc:
                print(f"[source-error] {key} / {feed['name']}: {exc}")
                continue

            for candidate in candidates:
                if not candidate.get("title"):
                    continue

                canonical = candidate["url"]
                published = candidate.get("published_at")
                preloaded_summary = ""

                # The udn house homepage lists current articles without a
                # visible timestamp. Resolve those dates from the article page
                # before deciding whether the story belongs to today.
                if not published and feed.get("resolve_missing_dates"):
                    preloaded_summary, published = fetch_article_details(
                        canonical, candidate["title"]
                    )
                    time.sleep(0.18)

                if not published or published.astimezone(TZ).date() != today:
                    continue

                item_id = story_id(canonical)
                old = previous.get(canonical) or previous.get(f"id:{item_id}") or {}
                summary = preloaded_summary or old.get("summary", "")
                if looks_mojibake(summary):
                    summary = ""
                if not summary:
                    summary = fetch_article_summary(canonical, candidate["title"])
                    time.sleep(0.18)

                today_items.append(
                    {
                        "id": item_id,
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

        # Numeric story id is shared across UDN properties, so this also
        # removes duplicates when the same story is surfaced by two feeds.
        deduped: dict[str, dict] = {}
        for item in today_items:
            existing = deduped.get(item["id"])
            if not existing:
                deduped[item["id"]] = item
                continue
            # Keep the richer version when one source has a summary/title.
            current_score = len(item.get("summary", "")) + len(item.get("title", ""))
            old_score = len(existing.get("summary", "")) + len(existing.get("title", ""))
            if current_score > old_score:
                deduped[item["id"]] = item

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
