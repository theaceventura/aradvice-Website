from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import escape
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
    image_url: str
    read_time: str


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
) -> str:
    out = html
    # Replace the opening <html> tag to carry site-level attributes (e.g., class)
    if local_html:
        out = re.sub(r"<html\b.*?>", local_html, out, count=1, flags=re.IGNORECASE)
    # Use a dedicated blog shell so mirrored articles stay visually consistent.
    out = re.sub(
        r"<body\b.*?>",
        '<body class="blog-shell bg-navy-deep text-slate-100 min-h-screen flex flex-col">',
        out,
        count=1,
        flags=re.IGNORECASE,
    )
    if local_head:
        out = re.sub(r"<head\b.*?</head>", local_head, out, count=1, flags=re.DOTALL | re.IGNORECASE)
    if local_header:
        out = re.sub(r"<header\b.*?</header>", local_header, out, count=1, flags=re.DOTALL | re.IGNORECASE)
    # Ensure content starts below fixed header.
    out = re.sub(r'<main class="flex-1">', '<main class="flex-1 pt-36 md:pt-40">', out, count=1, flags=re.IGNORECASE)
    # Keep mirrored article readable while preserving site shell aesthetics.
    out = re.sub(
        r'<article class="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">',
        '<article class="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12 bg-white rounded-[2rem] shadow-[0_24px_70px_rgba(15,23,42,0.08)] border border-slate-200">',
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
    local_head, local_header, local_html, _local_body = read_local_head_and_header()
    path.write_text(
        replace_host_head_and_header(rewritten, local_head, local_header, local_html),
        encoding="utf-8",
    )


def item_datetime(pub_date: str) -> datetime:
    if not pub_date:
        return datetime.now(timezone.utc)
    try:
        return parsedate_to_datetime(pub_date)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def extract_hero_image(html: str) -> str:
    for pattern in (
        r'<meta\s+property="og:image"\s+content="([^"]+)"',
        r'<img[^>]+src="([^"]+)"',
    ):
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def extract_read_time(html: str) -> str:
    match = re.search(r"(\d+\s*min\s*read)", html, flags=re.IGNORECASE)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def is_new_article(pub_date: str, days: int = 7) -> bool:
    published = item_datetime(pub_date)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - published.astimezone(timezone.utc)
    return age.days <= days


def render_more_articles_section(items: list[FeedItem]) -> str:
    cards: list[str] = []
    for item in items:
        published = item_datetime(item.pub_date).strftime("%b %d, %Y")
        new_badge = (
            '<span class="ml-2 inline-flex items-center rounded-full border border-cyan-400/50 bg-cyan-400/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-cyan-300">New</span>'
            if is_new_article(item.pub_date)
            else ""
        )
        image_html = ""
        if item.image_url:
            image_html = (
                '<div class="aspect-[16/9] overflow-hidden bg-slate-900">'
                f'<img src="{escape(item.image_url)}" alt="{escape(item.title)}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" loading="lazy">'
                "</div>"
            )

        meta = published
        if item.read_time:
            meta += f" &middot; {escape(item.read_time)}"

        cards.append(
            f'<a href="/post/{escape(item.slug)}/" class="group block rounded-2xl border border-slate-700/70 bg-slate-900/70 overflow-hidden hover:border-cyan-400/60 hover:shadow-[0_18px_60px_rgba(6,182,212,0.2)] transition-all no-underline" style="text-decoration: none; cursor: pointer;">'
            + image_html
            + '<div class="p-5">'
            + f'<h3 class="text-lg font-semibold text-slate-100 leading-snug mb-2">{escape(item.title)}{new_badge}</h3>'
            + f'<div class="text-sm text-slate-400">{meta}</div>'
            + "</div>"
            + "</a>"
        )

    return (
        '<section class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 border-t border-slate-700/70">'
        '<h2 class="text-3xl font-bold text-slate-100 mb-8">More Articles</h2>'
        '<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">'
        + "".join(cards)
        + "</div>"
        "</section>"
    )


def inject_more_articles(html: str, items: list[FeedItem]) -> str:
    section_html = render_more_articles_section(items)
    replaced = re.sub(
        r'<section class="max-w-5xl\b[^>]*>\s*<h2\b[^>]*>More Articles</h2>.*?</section>',
        section_html,
        html,
        count=1,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if replaced != html:
        return replaced
    return html.replace("</main>", section_html + "\n    </main>", 1)


def render_blog_landing_article(items: list[FeedItem]) -> str:
    return (
        '<article class="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12 bg-slate-900/70 rounded-[2rem] shadow-[0_24px_70px_rgba(2,6,23,0.45)] border border-slate-700/70">'
        '<h1 class="text-4xl sm:text-5xl font-bold text-white leading-tight mb-4">Blog</h1>'
        '<p class="text-lg text-slate-300 mb-8">Select an article to read the full post.</p>'
        + render_recent_articles(items)
        + "</article>"
    )


def inject_blog_landing_view(html: str, items: list[FeedItem]) -> str:
    landing_article = render_blog_landing_article(items)
    return re.sub(
        r"<article\b.*?</article>",
        landing_article,
        html,
        count=1,
        flags=re.DOTALL | re.IGNORECASE,
    )


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


def render_recent_articles(items: list[FeedItem]) -> str:
    rows: list[str] = []
    for item in items:
        published = item_datetime(item.pub_date).strftime("%d %b %Y")
        rows.append(
            "<li class=\"py-3 border-b border-slate-700/60 last:border-0\">"
            f"<a class=\"text-cyan-300 hover:text-cyan-200 no-underline\" href=\"/post/{escape(item.slug)}/\">"
            f"{escape(item.title)}</a>"
            f"<div class=\"mt-1 text-xs text-slate-400\">{escape(published)}</div>"
            "</li>"
        )

    return (
        '<section class="recent-articles mb-10 rounded-2xl border border-slate-700/60 bg-slate-900/65 p-6">'
        '<h2 class="text-sm font-semibold uppercase tracking-wide text-slate-300 mb-4">Recent Articles</h2>'
        '<ul class="m-0 list-none p-0">'
        + "".join(rows)
        + "</ul>"
        "</section>"
    )


def inject_recent_articles(html: str, items: list[FeedItem]) -> str:
    if not items:
        return html

    block = render_recent_articles(items)
    injected = re.sub(
        r'(<div class="article-content\b[^>]*>)',
        block + r"\1",
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    if injected != html:
        return injected
    return html.replace("</article>", block + "</article>", 1)


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
        generated_items.append(
            FeedItem(
                title=raw_item["title"],
                link=raw_item["link"],
                slug=slug,
                pub_date=raw_item["pub_date"],
                html=article_html,
                image_url=extract_hero_image(article_html),
                read_time=extract_read_time(article_html),
            )
        )

    generated_items.sort(key=lambda item: item_datetime(item.pub_date), reverse=True)

    for item in generated_items:
        page_path = article_page_path(item.slug)
        page_html = inject_more_articles(item.html, generated_items)
        write_page(page_path, page_html)

    latest_item = generated_items[0]
    latest_with_listing = inject_more_articles(latest_item.html, generated_items)
    latest_with_listing = inject_blog_landing_view(latest_with_listing, generated_items)
    write_page(ROOT / "blog.html", latest_with_listing)
    (ROOT / "sitemap.xml").write_text(build_sitemap(generated_items), encoding="utf-8")

    print(f"Synced {len(generated_items)} article(s). Latest: {latest_item.slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())