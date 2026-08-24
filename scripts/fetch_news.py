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

SOURCES = {
    "instant": {
        "label": "即時",
        "url": "https://money.udn.com/rank/newest/1001/0/1?from=edn_navibar",
    },
    "finance": {
        "label": "金融",
        "url": "https://money.udn.com/money/cate/12017?from=edn_navibar",
    },
    "housing": {
        "label": "房市",
        "url": "https://money.udn.com/money/cate/5593?from=edn_navibar",
    },
}

STORY_PATH_RE = re.compile(r"^/money/story/\d+/\d+/?$")
DATE_RE = re.compile(
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?"
)
GENERIC_TEXT = {
    "上一篇", "下一篇", "看更多", "即時", "金融", "房市", "經濟日報",
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
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def canonical_story_url(href: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.netloc not in {"money.udn.com", "udn.com", "www.udn.com"}:
        return None
    if not STORY_PATH_RE.match(parsed.path):
        return None
    return f"https://money.udn.com{parsed.path.rstrip('/')}"


def share_url(canonical: str) -> str:
    return canonical + "?from=ednappsharing"


def clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = DATE_RE.sub("", text).strip(" ｜|—-")
    return text


def parse_datetime(text: str) -> datetime | None:
    match = DATE_RE.search(text or "")
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
    for _ in range(5):
        if node is None:
            break

        if hasattr(node, "find"):
            time_el = node.find("time")
            if time_el:
                dt = parse_datetime(time_el.get_text(" ", strip=True))
                if dt:
                    return dt

            for attr in ("datetime", "data-time", "data-date"):
                value = node.attrs.get(attr) if hasattr(node, "attrs") else None
                if value:
                    dt = parse_datetime(str(value).replace("T", " "))
                    if dt:
                        return dt

        text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
        if len(text) <= 500:
            dt = parse_datetime(text)
            if dt:
                return dt
        node = getattr(node, "parent", None)

    parent = getattr(anchor, "parent", None)
    if parent is not None:
        text = parent.get_text(" ", strip=True)
        if len(text) <= 500:
            dt = parse_datetime(text)
            if dt:
                return dt
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
    text = re.sub(r"^經濟日報\s*[|｜\-—]\s*", "", text)
    if title and text.startswith(title):
        text = text[len(title):].lstrip(" ｜|—-：:")
    if len(text) > 150:
        cut = max(text.rfind("。", 0, 150), text.rfind("；", 0, 150))
        if cut >= 65:
            text = text[: cut + 1]
        else:
            text = text[:147].rstrip("，、；： ") + "…"
    return text


def fetch_article_summary(url: str, title: str) -> str:
    try:
        html = fetch(url)
        soup = BeautifulSoup(html, "html.parser")

        for attrs in (
            {"property": "og:description"},
            {"name": "description"},
            {"name": "twitter:description"},
        ):
            meta = soup.find("meta", attrs=attrs)
            if meta and meta.get("content"):
                summary = clean_summary(meta["content"], title)
                if len(summary) >= 25:
                    return summary

        paragraphs = []
        for selector in (
            "article p",
            ".article-body p",
            ".article-content p",
            "#story_body_content p",
        ):
            for p in soup.select(selector):
                text = p.get_text(" ", strip=True)
                if len(text) >= 25 and "歡迎用「轉貼」" not in text:
                    paragraphs.append(text)
                if len("".join(paragraphs)) >= 180:
                    break
            if paragraphs:
                break
        return clean_summary("".join(paragraphs[:2]), title)
    except Exception as exc:
        print(f"[summary] {url}: {exc}")
        return ""


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
    return previous


def main() -> None:
    now = datetime.now(TZ)
    today = now.date()
    previous = load_previous()
    categories: dict[str, list[dict]] = {}

    for key, source in SOURCES.items():
        print(f"[source] {source['label']} {source['url']}")
        try:
            html = fetch(source["url"])
            candidates = extract_candidates(html, source["url"])
        except Exception as exc:
            print(f"[source-error] {key}: {exc}")
            categories[key] = []
            continue

        today_items = []
        for candidate in candidates:
            published = candidate.get("published_at")
            if not published or published.astimezone(TZ).date() != today:
                continue
            if not candidate.get("title"):
                continue

            canonical = candidate["url"]
            old = previous.get(canonical, {})
            summary = old.get("summary", "")
            if not summary:
                summary = fetch_article_summary(canonical, candidate["title"])
                time.sleep(0.18)

            today_items.append(
                {
                    "id": canonical.rsplit("/", 1)[-1],
                    "title": candidate["title"],
                    "published_at": published.isoformat(),
                    "time": published.strftime("%H:%M"),
                    "url": share_url(canonical),
                    "canonical_url": canonical,
                    "summary": summary,
                }
            )

        deduped = {item["id"]: item for item in today_items}
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
