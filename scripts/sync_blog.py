from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests


ROOT = Path(__file__).resolve().parents[1]
MAIN_DOMAIN = "https://aradvice.com.au"
FEED_URL = "https://blog.aradvice.com.au/feed.xml"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
    "Referer": FEED_URL,
}

LOCAL_HEADER_HTML = """
<header class="sticky top-0 z-50 bg-navy-deep/90 backdrop-blur-xl border-b border-white/5">
    <div class="max-w-[1400px] mx-auto px-8 h-24 flex items-center justify-between">
        <div class="flex items-center gap-3">
            <span class="material-symbols-outlined text-primary text-4xl neon-glow">shield_person</span>
            <span class="text-xl font-black tracking-tighter text-white uppercase">Andrew Roberts Advisory</span>
        </div>

        <nav class="hidden xl:flex items-center gap-10">
            <a class="nav-link" href="/index.html">Home</a>
            <a class="nav-link" href="/readiness-review.html">Readiness Review</a>
            <a class="nav-link" href="/resource-hub.html">Resource Hub</a>
            <a class="nav-link" href="/blog.html">Blog</a>
            <a class="nav-link" href="/index.html#services">Services</a>
            <a class="nav-link" href="/index.html#approach">About</a>
        </nav>
    </div>
</header>
""".strip()


@dataclass
class FeedItem:
    title: str
    link: str
    slug: str
    pub_date: str
    html: str


def fetch_text(url: str, accept: str) -> str:
    response = requests.get(
        url,
        headers={**HEADERS, "Accept": accept},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def item_slug(link: str, title: str) -> str:
    path = urlparse(link).path.strip("/")
    if path.startswith("post/"):
        parts = path.split("/", 1)
        if len(parts) == 2 and parts[1]:
            return parts[1].rstrip("/")
    return slugify(title)


def parse_feed(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for item_node in root.findall(".//item"):
        title = (item_node.findtext("title") or "").strip()
        link = (item_node.findtext("link") or "").strip()
        pub_date = (item_node.findtext("pubDate") or "").strip()
        description = (item_node.findtext("description") or "").strip()
        items.append(
            {
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "description": description,
            }
        )
    return items


def rewrite_domains(html: str) -> str:
    return html.replace("https://blog.aradvice.com.au", MAIN_DOMAIN)


def replace_host_header(html: str) -> str:
    return re.sub(r"<header\b.*?</header>", LOCAL_HEADER_HTML, html, count=1, flags=re.DOTALL | re.IGNORECASE)


def article_page_path(slug: str) -> Path:
    return ROOT / "post" / slug / "index.html"


def write_page(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rewritten = rewrite_domains(html)
    path.write_text(replace_host_header(rewritten), encoding="utf-8")


def item_datetime(pub_date: str) -> datetime:
    if not pub_date:
        return datetime.now(timezone.utc)
    try:
        return parsedate_to_datetime(pub_date)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def build_sitemap(items: list[FeedItem]) -> str:
    entries = [
        (f"{MAIN_DOMAIN}/", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/index.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/readiness-review.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/resource-hub.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/blog.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/privacy-policy.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/terms-of-service.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/liability-disclaimer.html", datetime.now(timezone.utc)),
    ]
    for item in items:
        entries.append((f"{MAIN_DOMAIN}/post/{item.slug}/", item_datetime(item.pub_date)))

    seen: set[str] = set()
    url_nodes: list[str] = []
    for loc, dt in entries:
        if loc in seen:
            continue
        seen.add(loc)
        url_nodes.append(
            "  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <lastmod>{dt.date().isoformat()}</lastmod>\n"
            "  </url>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(url_nodes)
        + "\n</urlset>\n"
    )


def main() -> int:
    feed_xml = fetch_text(FEED_URL, "application/rss+xml, application/xml, text/xml")
    feed_items = parse_feed(feed_xml)
    if not feed_items:
        print("No feed items found.", file=sys.stderr)
        return 1

    generated_items: list[FeedItem] = []
    for raw_item in feed_items:
        slug = item_slug(raw_item["link"], raw_item["title"])
        article_html = fetch_text(raw_item["link"], "text/html,application/xhtml+xml")
        page_path = article_page_path(slug)
        write_page(page_path, article_html)
        generated_items.append(
            FeedItem(
                title=raw_item["title"],
                link=raw_item["link"],
                slug=slug,
                pub_date=raw_item["pub_date"],
                html=article_html,
            )
        )

    latest_item = generated_items[0]
    write_page(ROOT / "blog.html", latest_item.html)
    (ROOT / "sitemap.xml").write_text(build_sitemap(generated_items), encoding="utf-8")

    print(f"Synced {len(generated_items)} article(s). Latest: {latest_item.slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())