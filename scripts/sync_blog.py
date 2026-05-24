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

# Load .env from project root if present
_env_path = ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            import os as _os; _os.environ.setdefault(_k.strip(), _v.strip())
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

def read_local_head_and_header() -> tuple[str, str, str, str, str]:
    """Extract the local site's <html>, <body>, <head>, first <header>, and <footer>.

    Returns a tuple of (head_html, header_html, html_tag, body_tag, footer_html). Missing parts
    return empty strings.
    """
    index_path = ROOT / "index.html"
    if not index_path.exists():
        return "", "", "", "", ""
    content = index_path.read_text(encoding="utf-8")
    head_match = re.search(r"<head\b.*?>(.*?)</head>", content, flags=re.DOTALL | re.IGNORECASE)
    header_match = re.search(r"<header\b.*?</header>", content, flags=re.DOTALL | re.IGNORECASE)
    html_match = re.search(r"(<html\b.*?>)", content, flags=re.IGNORECASE)
    body_match = re.search(r"(<body\b.*?>)", content, flags=re.IGNORECASE)
    footer_match = re.search(r"<footer\b.*?</footer>", content, flags=re.DOTALL | re.IGNORECASE)
    head_html = f"<head>{head_match.group(1)}</head>" if head_match else ""
    header_html = header_match.group(0) if header_match else ""
    html_tag = html_match.group(1) if html_match else ""
    body_tag = body_match.group(1) if body_match else ""
    footer_html = footer_match.group(0) if footer_match else ""
    return head_html, header_html, html_tag, body_tag, footer_html


@dataclass
class FeedItem:
    title: str
    link: str
    slug: str
    pub_date: str
    html: str
    image_url: str
    read_time: str
    excerpt: str = ""


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


def strip_platform_widgets(html: str) -> str:
    """Remove third-party CMS widgets injected by the publishing platform."""
    # Remove the full reader feedback overlay div and its script
    html = re.sub(
        r'<div id=["\']readerFeedbackOverlay["\'].*?</div>\s*<script>\s*\(function\(\).*?</script>',
        '',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Remove orphaned feedback widget fragment starting from rfRatingError
    # through the closing </div></div> that ends the widget block
    html = re.sub(
        r'<p id=["\']rfRatingError["\'][^>]*>.*?</div>\s*</div>',
        '',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Belt-and-suspenders: remove any remaining feedback textarea block
    html = re.sub(
        r'<p[^>]*>\s*Any more feedback about it\?.*?</div>\s*</div>',
        '',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return html


def normalize_internal_links(html: str) -> str:
    replacements = {
        'href="index.html"': 'href="/"',
        "href='index.html'": "href='/'",
        'href="blog.html"': 'href="/blog.html"',
        "href='blog.html'": "href='/blog.html'",
        'href="for-directors.html"': 'href="/for-directors.html"',
        "href='for-directors.html'": "href='/for-directors.html'",
        'href="products.html"': 'href="/products.html"',
        "href='products.html'": "href='/products.html'",
        'href="founder-advisory.html"': 'href="/founder-advisory.html"',
        "href='founder-advisory.html'": "href='/founder-advisory.html'",
        'href="ai-governance-review.html"': 'href="/ai-governance-review.html"',
        "href='ai-governance-review.html'": "href='/ai-governance-review.html'",
        'href="cyber-governance-review.html"': 'href="/cyber-governance-review.html"',
        "href='cyber-governance-review.html'": "href='/cyber-governance-review.html'",
        'href="contact.html"': 'href="/contact.html"',
        "href='contact.html'": "href='/contact.html'",
        'href="readiness-review.html"': 'href="/cyber-governance-review.html"',
        "href='readiness-review.html'": "href='/cyber-governance-review.html'",
        'href="resource-hub.html"': 'href="/resource-hub.html"',
        "href='resource-hub.html'": "href='/resource-hub.html'",
        'href="privacy-policy.html"': 'href="/privacy-policy.html"',
        "href='privacy-policy.html'": "href='/privacy-policy.html'",
        'href="terms-of-service.html"': 'href="/terms-of-service.html"',
        "href='terms-of-service.html'": "href='/terms-of-service.html'",
        'href="liability-disclaimer.html"': 'href="/liability-disclaimer.html"',
        "href='liability-disclaimer.html'": "href='/liability-disclaimer.html'",
    }
    out = html
    for old, new in replacements.items():
        out = out.replace(old, new)
    return out


def replace_host_head_and_header(
    html: str,
    local_head: str,
    local_header: str,
    local_html: str,
    local_footer: str = "",
    post_slug: str = "",
    post_title: str = "",
    post_description: str = "",
    post_url: str = "",
    post_image: str = "",
    page_title: str = "",
    page_description: str = "",
    page_url: str = "",
    page_image: str = "",
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
    # Inject page-specific meta tags so generated pages do not inherit homepage canonicals.
    canonical_url = ""
    title = ""
    description = ""
    image = ""
    if post_slug:
        canonical_url = post_url or f"{MAIN_DOMAIN}/post/{post_slug}/"
        title = post_title or "Andrew Roberts Advisory"
        description = post_description or ""
        image = post_image or f"{MAIN_DOMAIN}/og-image.jpg"
    elif page_url:
        canonical_url = page_url
        title = page_title or "Andrew Roberts Advisory"
        description = page_description or ""
        image = page_image or f"{MAIN_DOMAIN}/og-image.jpg"

    if canonical_url:
        escaped_title = escape(title)
        escaped_description = escape(description)
        escaped_url = escape(canonical_url)
        escaped_image = escape(image)
        # Remove existing tags we are replacing
        out = re.sub(r'<link[^>]*rel=["\']canonical["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
        out = re.sub(r'<title>[^<]*</title>', "", out, flags=re.IGNORECASE)
        out = re.sub(r'<meta[^>]*name=["\']description["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
        out = re.sub(r'<meta[^>]*property=["\']og:title["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
        out = re.sub(r'<meta[^>]*property=["\']og:description["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
        out = re.sub(r'<meta[^>]*property=["\']og:url["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
        out = re.sub(r'<meta[^>]*property=["\']og:image["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
        out = re.sub(r'<meta[^>]*property=["\']twitter:title["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
        out = re.sub(r'<meta[^>]*property=["\']twitter:description["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
        out = re.sub(r'<meta[^>]*property=["\']twitter:url["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
        out = re.sub(r'<meta[^>]*property=["\']twitter:image["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
        # Build and inject post-specific tags before </head>
        injected = (
            f'<title>{escaped_title} | Andrew Roberts Advisory</title>\n    '
            f'<meta name="description" content="{escaped_description}" />\n    '
            f'<link rel="canonical" href="{escaped_url}" />\n    '
            f'<meta property="og:title" content="{escaped_title}" />\n    '
            f'<meta property="og:description" content="{escaped_description}" />\n    '
            f'<meta property="og:url" content="{escaped_url}" />\n    '
            f'<meta property="og:image" content="{escaped_image}" />\n    '
            f'<meta property="twitter:title" content="{escaped_title}" />\n    '
            f'<meta property="twitter:description" content="{escaped_description}" />\n    '
            f'<meta property="twitter:url" content="{escaped_url}" />\n    '
            f'<meta property="twitter:image" content="{escaped_image}" />\n    '
        )
        out = re.sub(r"</head>", injected + "</head>", out, count=1, flags=re.IGNORECASE)
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
    if local_footer:
        existing_footer = re.search(r"<footer\b.*?</footer>", out, flags=re.DOTALL | re.IGNORECASE)
        if existing_footer:
            out = re.sub(r"<footer\b.*?</footer>", local_footer, out, count=1, flags=re.DOTALL | re.IGNORECASE)
        else:
            out = out.replace("</body>", local_footer + "\n</body>", 1)
    return normalize_internal_links(out)


def article_page_path(slug: str) -> Path:
    return ROOT / "post" / slug / "index.html"


def write_page(path: Path, html: str, feed_item: "FeedItem | None" = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rewritten = normalize_internal_links(strip_platform_widgets(rewrite_domains(html)))
    local_head, local_header, local_html, _local_body, local_footer = read_local_head_and_header()
    # Extract post slug from path: /post/{slug}/index.html
    post_slug = ""
    try:
        relative = path.relative_to(ROOT)
        if relative.parts[0] == "post" and relative.name == "index.html" and len(relative.parts) >= 3:
            post_slug = relative.parts[1]
    except (ValueError, IndexError):
        pass
    post_title = feed_item.title if feed_item else ""
    # Extract plain-text description from feed item description field (strip HTML tags)
    raw_desc = ""
    if feed_item:
        # Use a short excerpt: strip HTML tags from description, truncate to 160 chars
        raw_desc = re.sub(r"<[^>]+>", "", feed_item.html[:2000])
        raw_desc = re.sub(r"\s+", " ", raw_desc).strip()[:160]
    post_url = f"{MAIN_DOMAIN}/post/{post_slug}/" if post_slug else ""
    post_image = feed_item.image_url if feed_item and feed_item.image_url else ""
    page_title = ""
    page_description = ""
    page_url = ""
    page_image = ""
    if path == ROOT / "blog.html":
        page_title = "Blog"
        page_description = "Board-level insights on cyber governance, AI governance, technology oversight, and defensible decision-making for Australian directors."
        page_url = f"{MAIN_DOMAIN}/blog.html"
        page_image = f"{MAIN_DOMAIN}/og-image.jpg"
    path.write_text(
        replace_host_head_and_header(
            rewritten, local_head, local_header, local_html,
            post_slug=post_slug,
            post_title=post_title,
            post_description=raw_desc,
            post_url=post_url,
            post_image=post_image,
            page_title=page_title,
            page_description=page_description,
            page_url=page_url,
            page_image=page_image,
            local_footer=local_footer,
        ),
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

        meta = published
        if item.read_time:
            meta += f" &middot; {escape(item.read_time)}"

        cards.append(
            f'<a href="/post/{escape(item.slug)}/" class="group block rounded-2xl border border-slate-700/70 bg-slate-900/70 hover:border-cyan-400/60 hover:shadow-[0_18px_60px_rgba(6,182,212,0.2)] transition-all no-underline" style="text-decoration: none; cursor: pointer;">'
            + image_html
            + '<div class="p-6">'
            + f'<h3 class="text-lg font-semibold text-slate-100 leading-snug mb-2">{escape(item.title)}{new_badge}</h3>'
            + f'<div class="text-sm text-slate-400">{meta}</div>'
            + (f'<p class="text-sm text-slate-300 mt-3 leading-relaxed line-clamp-3">{escape(item.excerpt)}</p>' if item.excerpt else "")
            + "</div>"
            + "</a>"
        )

    return (
        '<section class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 border-t border-slate-700/70">'
        '<h2 class="text-3xl font-bold text-slate-100 mb-8">Articles</h2>'
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
        '<p class="text-lg text-slate-300">Select an article below to read the full post.</p>'
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
        (f"{MAIN_DOMAIN}/products.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/for-directors.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/founder-advisory.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/ai-governance-review.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/cyber-governance-review.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/contact.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/resource-hub.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/blog.html", datetime.now(timezone.utc)),
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


def generate_linkedin_post(item: FeedItem, post_url: str) -> str:
    """Generate a draft LinkedIn post for a feed item using the Anthropic API."""
    import urllib.request
    import json

    # Vary tone based on article index (cycle through 3 styles)
    slug_hash = sum(ord(c) for c in item.slug) % 3
    tone_instructions = [
        "Write in a direct, authoritative tone as Andrew Roberts, an advisor speaking plainly to Australian board directors. State a clear position. No fluff.",
        "Open with a thought-provoking question or challenge directed at board directors. Make them feel the personal stakes. Then deliver a clear point.",
        "Anchor the post to a specific regulatory pressure or real-world incident relevant to Australian directors. Make it feel timely and urgent.",
    ][slug_hash]

    # Extract a clean plain-text excerpt from the article
    plain_text = re.sub(r"<[^>]+>", "", item.html[:3000])
    plain_text = re.sub(r"\s+", " ", plain_text).strip()[:1500]

    prompt = f"""You are writing a LinkedIn post on behalf of Andrew Roberts, founder of Andrew Roberts Advisory (aradvice.com.au), an independent board-level advisor on cyber governance and AI governance for Australian directors.

Article title: {item.title}
Article URL: {post_url}
Article excerpt: {plain_text}

Instructions:
- {tone_instructions}
- Write 6 to 10 lines. Medium length. No padding.
- Write in first person as Andrew Roberts.
- The audience is Australian non-executive directors and board members.
- Reference Australian regulatory context where relevant (ASIC, AICD, Corporations Act, Cyber Security Act 2024).
- End with the article URL on its own line.
- Do not use hashtags.
- Do not use bullet points or emojis.
- Do not use the phrase "I am pleased to share" or any similar announcement language.
- Output only the post text. No preamble, no explanation."""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["content"][0]["text"].strip()
    except Exception as e:
        return f"[LinkedIn post generation failed: {e}]"


def write_linkedin_draft(item: FeedItem, post_url: str) -> None:
    """Write a LinkedIn draft post to /linkedin/{slug}.txt if it doesn't already exist."""
    linkedin_dir = ROOT / "linkedin"
    linkedin_dir.mkdir(exist_ok=True)
    draft_path = linkedin_dir / f"{item.slug}.txt"
    if draft_path.exists():
        return  # Don't overwrite existing drafts
    print(f"  Generating LinkedIn draft for: {item.slug}")
    post_text = generate_linkedin_post(item, post_url)
    draft_path.write_text(post_text, encoding="utf-8")


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
        raw_excerpt = re.sub(r"<[^>]+>", "", raw_item.get("description", ""))
        raw_excerpt = re.sub(r"\s+", " ", raw_excerpt).strip()[:160]
        generated_items.append(
            FeedItem(
                title=raw_item["title"],
                link=raw_item["link"],
                slug=slug,
                pub_date=raw_item["pub_date"],
                html=article_html,
                image_url=extract_hero_image(article_html),
                read_time=extract_read_time(article_html),
                excerpt=raw_excerpt,
            )
        )

    generated_items.sort(key=lambda item: item_datetime(item.pub_date), reverse=True)

    for i, item in enumerate(generated_items):
        page_path = article_page_path(item.slug)
        page_html = inject_more_articles(item.html, generated_items)
        write_page(page_path, page_html, feed_item=item)
        if i < 5:
            post_url = f"{MAIN_DOMAIN}/post/{item.slug}/"
            write_linkedin_draft(item, post_url)

    latest_item = generated_items[0]
    latest_with_listing = inject_more_articles(latest_item.html, generated_items)
    latest_with_listing = inject_blog_landing_view(latest_with_listing, generated_items)
    write_page(ROOT / "blog.html", latest_with_listing)
    (ROOT / "sitemap.xml").write_text(build_sitemap(generated_items), encoding="utf-8")

    print(f"Synced {len(generated_items)} article(s). Latest: {latest_item.slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())