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

def read_local_head_and_header() -> tuple[str, str, str, str]:
    """Extract the local site's <html>, <body>, <head>, and first <header>.

    Returns a tuple of (head_html, header_html, html_tag, body_tag). Missing parts
    return empty strings.
    """
    index_path = ROOT / "index.html"
    if not index_path.exists():
        return "", "", "", ""
    content = index_path.read_text(encoding="utf-8")
    head_match = re.search(r"<head\b.*?>(.*?)</head>", content, flags=re.DOTALL | re.IGNORECASE)
    header_match = re.search(r"<header\b.*?</header>", content, flags=re.DOTALL | re.IGNORECASE)
    html_match = re.search(r"(<html\b.*?>)", content, flags=re.IGNORECASE)
    body_match = re.search(r"(<body\b.*?>)", content, flags=re.IGNORECASE)
    head_html = f"<head>{head_match.group(1)}</head>" if head_match else ""
    header_html = header_match.group(0) if header_match else ""
    html_tag = html_match.group(1) if html_match else ""
    body_tag = body_match.group(1) if body_match else ""
    return head_html, header_html, html_tag, body_tag


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


def replace_host_head_and_header(
    html: str,
    local_head: str,
    local_header: str,
    local_html: str,
    local_body: str,
) -> str:
    out = html
    # Replace the opening <html> tag to carry site-level attributes (e.g., class)
    if local_html:
        out = re.sub(r"<html\b.*?>", local_html, out, count=1, flags=re.IGNORECASE)
    # Replace the opening <body> tag to carry site-level base styling.
    if local_body:
        out = re.sub(r"<body\b.*?>", local_body, out, count=1, flags=re.IGNORECASE)
    if local_head:
        out = re.sub(r"<head\b.*?</head>", local_head, out, count=1, flags=re.DOTALL | re.IGNORECASE)
    if local_header:
        out = re.sub(r"<header\b.*?</header>", local_header, out, count=1, flags=re.DOTALL | re.IGNORECASE)
    # Ensure content starts below fixed header.
    out = re.sub(r'<main class="flex-1">', '<main class="flex-1 pt-28">', out, count=1, flags=re.IGNORECASE)
    # Keep mirrored article readable while preserving site shell aesthetics.
    out = re.sub(
        r'<article class="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">',
        '<article class="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10 bg-white rounded-2xl shadow-xl border border-slate-200">',
        out,
        count=1,
        flags=re.IGNORECASE,
    )
    # Ensure Google Fonts and Material Symbols are present; inject if missing.
    if 'fonts.googleapis' not in out:
        font_links = (
            '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet" />'
            '<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet" />'
        )
        out = re.sub(r"</head>", font_links + "</head>", out, count=1, flags=re.IGNORECASE)
    # Add inline fallback CSS so typography looks correct if fonts are blocked.
    if 'font-family: Inter' not in out and 'fonts.googleapis' not in out:
        fallback_css = (
            '<style>\n'
            '  :root{--accent-color:#2563eb} body, .article-content{font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:#111827;}\n'
            '  .material-symbols-outlined{font-variation-settings: "FILL" 0, "wght" 400;}\n'
            '</style>'
        )
        out = re.sub(r"</head>", fallback_css + "</head>", out, count=1, flags=re.IGNORECASE)
    return out


def article_page_path(slug: str) -> Path:
    return ROOT / "post" / slug / "index.html"


def write_page(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rewritten = rewrite_domains(html)
    local_head, local_header, local_html, local_body = read_local_head_and_header()
    path.write_text(
        replace_host_head_and_header(rewritten, local_head, local_header, local_html, local_body),
        encoding="utf-8",
    )


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