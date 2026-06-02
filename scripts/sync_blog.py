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
from PIL import Image, ImageDraw, ImageFont


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
MANUAL_POSTS = [
    {
        "title": "Linking Cyber Risk to Financial Impact: A Director's Guide to Defensible Board Reporting",
        "link": "https://aradvice.com.au/post/linking-cyber-risk-to-financial-impact-a-directors-guide-to-defensible-board-reporting/",
        "pub_date": "Wed, 10 Jun 2026 00:00:00 +0000",
        "description": "Can you defend a cyber strategy that you cannot quantify in Australian Dollars? As a director, you likely feel the growing disconnect between technical jargon and personal liability.",
    },
    {
        "title": "Director's Guide to Artificial Intelligence Risks: Defensible Oversight in 2026",
        "link": "https://aradvice.com.au/post/directors-guide-to-artificial-intelligence-risks-defensible-oversight-in-2026/",
        "pub_date": "Mon, 08 Jun 2026 00:00:00 +0000",
        "description": "Our director's guide to artificial intelligence risks helps you meet your duty of care. Learn defensible AI oversight for 2026 regulatory compliance in Australia.",
    },
    {
        "title": "Questions for Boards to Ask About Corporate AI Strategy: A 2026 Director's Checklist",
        "link": "https://aradvice.com.au/post/questions-for-boards-to-ask-about-corporate-ai-strategy-a-2026-directors-checklist/",
        "pub_date": "Thu, 05 Jun 2026 00:00:00 +0000",
        "description": "Facing ASIC scrutiny? Here are the critical questions for boards to ask about corporate AI strategy to mitigate fiduciary risk and meet 2026 director duties.",
    },
]
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
    "Referer": FEED_URL,
}

def read_local_head_and_header() -> tuple[str, str, str, str, str, str]:
    """Extract the local site's <html>, <body>, <head>, first <header>, <footer>, and nav scripts.

    Returns a tuple of (head_html, header_html, html_tag, body_tag, footer_html, nav_scripts).
    Missing parts return empty strings.
    """
    index_path = ROOT / "index.html"
    if not index_path.exists():
        return "", "", "", "", "", ""
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
    footer_pos = content.rfind("</footer>")
    nav_scripts = ""
    if footer_pos != -1:
        after_footer = content[footer_pos + len("</footer>"):]
        found = re.findall(r"<script\b[^>]*>.*?</script>", after_footer, flags=re.DOTALL | re.IGNORECASE)
        nav_scripts = "\n".join(found)
    return head_html, header_html, html_tag, body_tag, footer_html, nav_scripts


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


def parse_blog_index() -> list[dict[str, str]]:
    """Scrape all article links from the paginated blog index."""
    base = "https://blog.aradvice.com.au"
    items: list[dict[str, str]] = []
    page = 1
    seen: set[str] = set()

    while True:
        url = base if page == 1 else f"{base}?page={page}"
        try:
            html = fetch_text(url, "text/html")
        except Exception as e:
            print(f"  Blog index page {page} failed: {e}",
                  file=sys.stderr)
            break

        # Extract article links — hrefs may be relative (/post/...) or absolute
        links = re.findall(
            r'href=["\'](?:' + re.escape(base) + r')?(/post/([^"\']+))["\']',
            html
        )
        new_found = False
        for path, slug in links:
            slug = slug.rstrip("/")
            full_url = base + path.rstrip("/") + "/"
            if full_url in seen:
                continue
            seen.add(full_url)
            new_found = True
            items.append({
                "title": "",   # filled later from article
                "link": full_url,
                "pub_date": "",
                "description": "",
            })

        # Check for next page link
        if f'page={page + 1}' not in html or not new_found:
            break
        page += 1

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


def extract_and_strip_meta_description(html: str) -> tuple[str, str]:
    """Strip the 'Meta Description' heading + paragraph block injected by GetAutoSEO."""
    match = re.search(
        r'<h3[^>]*>\s*Meta\s+Description\s*</h3>\s*<p[^>]*>(.*?)</p>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return html, ""
    desc_text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
    return html[:match.start()] + html[match.end():], desc_text


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
    local_nav_scripts: str = "",
    post_slug: str = "",
    post_title: str = "",
    post_description: str = "",
    post_url: str = "",
    post_image: str = "",
    post_keywords: str = "",
    article_schema: str = "",
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
        escaped_description = escape(description).replace("&#x27;", "'")
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
        out = re.sub(r'<meta[^>]*name=["\']keywords["\'][^>]*/?>', "", out, flags=re.IGNORECASE)
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
            f'<meta name="keywords" content="{escape(post_keywords)}" />\n    '
        )
        out = re.sub(r"</head>", injected + "</head>", out, count=1, flags=re.IGNORECASE)
        if article_schema:
            out = re.sub(
                r"</head>",
                article_schema + "\n</head>",
                out, count=1, flags=re.IGNORECASE
            )
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
    # Strip hero image figure from article pages
    if post_slug:
        # Remove any <figure> containing an <img> near article top
        out = re.sub(
            r'<figure[^>]*>.*?<img[^>]*>.*?</figure>',
            '',
            out,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Also remove bare hero <img> tags with hero_image in src
        out = re.sub(
            r'<img[^>]*(?:hero_image|hero-image)[^>]*>',
            '',
            out,
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
    if local_nav_scripts:
        out = re.sub(r"</body>", local_nav_scripts + "\n</body>", out, count=1, flags=re.IGNORECASE)
    return normalize_internal_links(out)


def article_page_path(slug: str) -> Path:
    return ROOT / "post" / slug / "index.html"


def write_page(path: Path, html: str, feed_item: "FeedItem | None" = None, post_id: str = "000") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rewritten = normalize_internal_links(strip_platform_widgets(rewrite_domains(html)))
    rewritten, body_desc = extract_and_strip_meta_description(rewritten)
    local_head, local_header, local_html, _local_body, local_footer, local_nav_scripts = read_local_head_and_header()
    # Extract post slug from path: /post/{slug}/index.html
    post_slug = ""
    try:
        relative = path.relative_to(ROOT)
        if relative.parts[0] == "post" and relative.name == "index.html" and len(relative.parts) >= 3:
            post_slug = relative.parts[1]
    except (ValueError, IndexError):
        pass
    post_title = feed_item.title if feed_item else ""
    # Generate click-optimised description and per-post keywords via API
    api_desc, post_keywords = ("", "")
    if feed_item:
        api_desc, post_keywords = generate_post_meta(feed_item)

    # Fallback chain if API call failed
    if not api_desc:
        existing_meta_match = (
            re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']{10,})["\']', rewritten, flags=re.IGNORECASE)
            or re.search(r'<meta[^>]*content=["\']([^"\']{10,})["\'][^>]*name=["\']description["\']', rewritten, flags=re.IGNORECASE)
        )
        if existing_meta_match:
            raw_desc = existing_meta_match.group(1).strip()
        elif body_desc:
            raw_desc = body_desc
        else:
            raw_desc = ""
    else:
        raw_desc = api_desc
    post_url = f"{MAIN_DOMAIN}/post/{post_slug}/" if post_slug else ""
    post_image = ""
    if feed_item and post_slug:
        try:
            generated_image = generate_og_image(feed_item, post_slug, post_id=post_id)
            post_image = f"{MAIN_DOMAIN}{generated_image}"
        except Exception as e:
            print(f"  og:image generation failed for {post_slug}: {e}", file=sys.stderr)
            post_image = feed_item.image_url if feed_item.image_url else ""
    page_title = ""
    page_description = ""
    page_url = ""
    page_image = ""
    if path == ROOT / "blog.html":
        page_title = "Board Cyber & AI Governance Insights"
        page_description = (
            "Practical insights for Australian directors on cyber "
            "governance, AI oversight, and defensible decision-making "
            "under Australian regulatory expectations."
        )
        page_url = f"{MAIN_DOMAIN}/blog.html"
        page_image = f"{MAIN_DOMAIN}/og-image.jpg"
    article_schema = ""
    if post_slug and feed_item:
        article_schema = generate_article_schema(
            feed_item,
            f"{MAIN_DOMAIN}/post/{post_slug}/"
        )
    path.write_text(
        replace_host_head_and_header(
            rewritten, local_head, local_header, local_html,
            post_slug=post_slug,
            post_title=post_title,
            post_description=raw_desc,
            post_url=post_url,
            post_image=post_image,
            post_keywords=post_keywords,
            article_schema=article_schema,
            page_title=page_title,
            page_description=page_description,
            page_url=page_url,
            page_image=page_image,
            local_footer=local_footer,
            local_nav_scripts=local_nav_scripts,
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
        '<h2 class="text-2xl font-bold text-slate-100 mb-8">More Articles</h2>'
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
    """Render the blog landing page hero featuring the latest article."""
    if not items:
        return ""

    latest = items[0]
    published = item_datetime(latest.pub_date).strftime("%d %b %Y")
    post_url = f"/post/{escape(latest.slug)}/"

    # Extract plain text excerpt from article-content div only
    content_match = re.search(
        r'<div[^>]*class=["\'][^"\']*article-content[^"\']*["\'][^>]*>(.*?)</div>\s*</article>',
        latest.html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if content_match:
        excerpt_html = content_match.group(1)
    else:
        h1_match = re.search(r"</h1>.*?(<p\b.*?</p>)", latest.html, flags=re.DOTALL | re.IGNORECASE)
        excerpt_html = h1_match.group(1) if h1_match else latest.html[:2000]
    raw = re.sub(r"<[^>]+>", "", excerpt_html[:2000])
    raw = re.sub(r"\s+", " ", raw).strip()
    excerpt = raw[:220].rsplit(" ", 1)[0] + "..."

    meta = published
    if latest.read_time:
        meta += f" &middot; {escape(latest.read_time)}"

    return (
        # Full-width dark hero
        '<section class="w-full border-b border-slate-700/70 bg-navy-deep">'
        '<div class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 pb-16">'

        # Eyebrow label
        '<p class="text-xs font-bold uppercase tracking-[0.3em] text-primary mb-6">Latest Article</p>'

        # Title
        f'<h1 class="text-3xl sm:text-4xl font-black text-white leading-tight mb-6 max-w-3xl">'
        f'<a href="{post_url}" class="text-white hover:text-primary transition-colors" style="text-decoration:none;">'
        f'{escape(latest.title)}'
        f'</a></h1>'

        # Meta
        f'<p class="text-sm text-slate-400 mb-6">{meta}</p>'

        # Excerpt
        f'<p class="text-lg text-slate-300 leading-relaxed max-w-2xl mb-8">{excerpt}</p>'

        # CTA
        f'<a href="{post_url}" class="inline-flex items-center gap-2 bg-primary hover:bg-white text-navy-deep px-8 py-4 text-sm font-bold uppercase tracking-widest transition-all transform hover:-translate-y-0.5 shadow-lg" style="text-decoration:none;">'
        f'Read Article →'
        f'</a>'

        '</div>'
        '</section>'

        '<section class="w-full bg-navy-rich border-b border-slate-700/70">'
        '<div class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-14">'
        '<p class="text-xs font-bold uppercase tracking-[0.3em] text-primary mb-4">Governance Briefings</p>'
        '<h2 class="text-2xl sm:text-3xl font-black text-white leading-tight mb-3 max-w-xl">Stay informed on cyber and AI governance</h2>'
        '<p class="text-slate-300 mb-8 max-w-lg">Short, practical briefings for Australian directors — delivered when there\'s something worth reading.</p>'
        '<form action="https://app.kit.com/forms/67af2df661/subscriptions" method="POST" class="flex flex-col sm:flex-row gap-3 max-w-lg">'
        '<input type="email" name="email_address" placeholder="Your email address" required'
        ' class="flex-1 px-4 py-3 bg-white/5 border border-slate-600 text-slate-100 placeholder-slate-400 focus:outline-none focus:border-primary text-sm" />'
        '<button type="submit"'
        ' class="bg-primary hover:bg-white text-navy-deep px-8 py-3 text-sm font-bold uppercase tracking-widest transition-all whitespace-nowrap">'
        'Subscribe'
        '</button>'
        '</form>'
        '<p class="text-xs text-slate-500 mt-3">No spam. Unsubscribe anytime.</p>'
        '</div>'
        '</section>'
    )


def inject_blog_landing_view(html: str, items: list[FeedItem]) -> str:
    landing_article = render_blog_landing_article(items)
    # Replace the article hero
    html = re.sub(
        r"<article\b.*?</article>",
        landing_article,
        html,
        count=1,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Replace the articles section with all items except the latest
    remaining = items[1:] if len(items) > 1 else []
    if remaining:
        more_section = render_more_articles_section(remaining)
        html = re.sub(
            r'<section class="max-w-5xl\b[^>]*>\s*<h2\b[^>]*>Articles</h2>.*?</section>',
            more_section,
            html,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
    return html


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


def load_post_registry() -> dict:
    """Load or create the post ID registry mapping slug to sequential ID."""
    registry_path = ROOT / "post-registry.json"
    if registry_path.exists():
        import json
        return json.loads(registry_path.read_text(encoding="utf-8"))
    return {}


def save_post_registry(registry: dict) -> None:
    """Save the post ID registry."""
    import json
    registry_path = ROOT / "post-registry.json"
    registry_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def assign_post_ids(items: list[FeedItem]) -> dict:
    """Assign sequential IDs to posts by publish date. IDs never change once assigned."""
    registry = load_post_registry()

    # Sort by publish date oldest first for ID assignment
    sorted_items = sorted(items, key=lambda i: item_datetime(i.pub_date))

    # Find highest existing ID
    next_id = max((int(v) for v in registry.values()), default=0) + 1

    # Assign IDs to any new slugs not yet in registry
    changed = False
    for item in sorted_items:
        if item.slug not in registry:
            registry[item.slug] = next_id
            next_id += 1
            changed = True

    if changed:
        save_post_registry(registry)

    return registry


def generate_post_mapping(items: list[FeedItem], registry: dict) -> None:
    """Generate a markdown mapping document of all posts with their IDs and assets."""
    sorted_items = sorted(items, key=lambda i: item_datetime(i.pub_date))

    lines = [
        "# Post Registry and Asset Map\n",
        f"Generated: {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}\n",
        f"Total posts: {len(sorted_items)}\n",
        "\n---\n",
    ]

    for item in sorted_items:
        post_id = registry.get(item.slug, "???")
        id_str = f"{post_id:03d}"
        published = item_datetime(item.pub_date).strftime("%d %b %Y")
        post_url = f"{MAIN_DOMAIN}/post/{item.slug}/"

        lines.append(f"\n## [{id_str}] {item.title}")
        lines.append(f"- **ID:** {id_str}")
        lines.append(f"- **Published:** {published}")
        lines.append(f"- **Slug:** `{item.slug}`")
        lines.append(f"- **URL:** {post_url}")
        lines.append(f"- **Article:** `post/{item.slug}/index.html`")
        lines.append(f"- **og:image:** `post/{item.slug}/{id_str}-og-image.png`")
        lines.append(f"- **LinkedIn draft:** `post/{item.slug}/{id_str}-linkedin.txt`")
        lines.append(f"- **LinkedIn log:** see `post/{item.slug}/posting-log.md`")
        lines.append(f"- **Advisor brief:** `post/{item.slug}/{id_str}-advisor-brief.md`")
        lines.append("")

    mapping_path = ROOT / "post-map.md"
    mapping_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Post map written: post-map.md ({len(sorted_items)} entries)")


def generate_og_image(item: FeedItem, post_slug: str, post_id: str = "000") -> str:
    """Generate a branded PNG og:image for a blog post. Returns the relative image path."""
    import textwrap

    output_dir = ROOT / "post" / post_slug
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{post_id}-og-image.png"

    if output_path.exists():
        return f"/post/{post_slug}/{post_id}-og-image.png"

    W, H = 1200, 630
    NAVY  = (5, 12, 28)
    CYAN  = (0, 212, 255)
    WHITE = (255, 255, 255)
    MUTED = (71, 85, 105)
    DARK  = (3, 8, 16)
    SLATE = (100, 116, 139)

    img = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(img)

    # Top cyan accent bar
    draw.rectangle([(0, 0), (W, 8)], fill=CYAN)

    # Favicon icon top-left
    favicon_path = ROOT / "favicon.ico"
    if favicon_path.exists():
        try:
            favicon = Image.open(favicon_path).convert("RGBA")
            icon = favicon.resize((80, 80), Image.LANCZOS)
            img.paste(icon, (80, 52), icon)
        except Exception:
            pass

    def load_font(size: int) -> ImageFont.FreeTypeFont:
        font_candidates = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for path in font_candidates:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                continue
        return ImageFont.load_default()

    # Brand name beside icon
    draw.text((178, 62), "ANDREW ROBERTS ADVISORY",
              font=load_font(16), fill=CYAN)
    draw.rectangle([(178, 86), (540, 87)], fill=(0, 212, 255, 60))

    # Article title — max 3 lines
    wrapped = textwrap.wrap(item.title, width=34)[:3]
    ty = 175
    for line in wrapped:
        draw.text((80, ty), line, font=load_font(64), fill=WHITE)
        ty += 78

    # Post date — parsed from RFC 2822 pub_date string
    if item.pub_date:
        try:
            date_str = item_datetime(item.pub_date).strftime("%-d %B %Y")
        except Exception:
            date_str = ""
        if date_str:
            draw.text((80, ty + 16), date_str, font=load_font(20), fill=SLATE)

    # Footer bar
    draw.rectangle([(0, H - 56), (W, H)], fill=DARK)
    draw.rectangle([(0, H - 57), (W, H - 56)], fill=(0, 212, 255, 50))
    draw.text((80, H - 36), "aradvice.com.au", font=load_font(14), fill=CYAN)
    draw.text((W - 370, H - 36), "Independent Board Advisory",
              font=load_font(14), fill=MUTED)

    img.save(output_path, "PNG", optimize=True)
    return f"/post/{post_slug}/{post_id}-og-image.png"


def generate_linkedin_post(item: FeedItem, post_url: str) -> str:
    """Generate a draft LinkedIn post for a feed item using the Anthropic API."""
    import urllib.request
    import json

    # Vary tone based on article index (cycle through 3 styles)
    slug_hash = sum(ord(c) for c in item.slug) % 3
    tone_instructions = [
        "Open with a specific scenario — a real question a director asked, a board meeting moment, a specific metric or number that reveals a governance problem. Make it feel like something that happened last week. Then draw out the implication for the reader.",
        "Open with a direct challenge or provocation aimed at the reader personally. Use 'you' and 'your board'. Make them feel the gap between where they are and where they need to be. Do not soften it.",
        "Open with a specific board paper moment, a regulator question, or an incident scenario. Walk through what it reveals about governance. End with the stakes if nothing changes.",
    ][slug_hash]

    # Extract a clean plain-text excerpt from the article
    plain_text = re.sub(r"<[^>]+>", "", item.html[:3000])
    plain_text = re.sub(r"\s+", " ", plain_text).strip()[:1500]

    prompt = f"""You are writing a LinkedIn post on behalf of Andrew Roberts, founder of Andrew Roberts Advisory (aradvice.com.au), an independent board-level advisor on cyber governance and AI governance for Australian directors.

Article title: {item.title}
Article URL: {post_url}
Article excerpt: {plain_text}

POST TYPE FOR THIS ARTICLE (use this to determine structure):
{tone_instructions}

WHAT MAKES A GREAT POST:
- It opens with something specific — a precise scenario, a sharp question, an unexpected detail — not a broad industry observation
- Each paragraph advances the argument. Nothing restates what came before.
- The closing line is the sharpest line in the post. It should be a provocation, a reframe, or a clear statement of stakes that lands independently of everything above it. It must be memorable.
- The best posts make a director stop and think "that's exactly my situation" or "I hadn't thought of it that way"

VOICE:
- First person as Andrew Roberts — a practitioner, not a commentator
- Authoritative without being academic. Direct without being blunt.
- Specific and concrete. Vague generalisations undermine credibility with this audience.
- Never frame content as a product: never use "I've developed", "I've written", "I've created", "I've seen boards struggle", "In my experience"
- Never use "asked me last week", "a client told me", or similar anecdote framing — state scenarios directly without attributing them to named interactions

REGULATORY REFERENCES:
- Only reference real, specific regulatory events, inquiries, or enforcement actions if they appear verbatim in the article excerpt. Do not invent or imply regulatory events.
- ASIC, AICD, Corporations Act, Cyber Security Act 2024 may be referenced accurately and specifically.

BANNED PHRASES — never use these:
- "The regulatory environment is tightening"
- "The gap between X and Y"
- "Cannot meaningfully interrogate" (maximum once per post, prefer alternatives)
- "Governing blind"
- "Translation layer"
- "I am pleased to share", "Let's dive in", "Game changer", "Wake-up call"
- "This matters now because", "This is why"
- "Most Australian boards" or "Most Australian directors" as an opening — find a more specific entry point
- Opening a paragraph with "Most Australian boards" more than once per post

FORMAT:
- 6 to 10 lines. No padding. No wasted sentences.
- No hashtags, bullet points, or emojis.
- End with the article URL on its own line, nothing after it.
- Output only the post text. No preamble, no explanation, no title."""

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


def generate_email_draft(item: FeedItem, post_url: str) -> tuple[str, str]:
    """Generate a plain-text email subject and body for a new article using the Anthropic API.
    Returns (subject, body)."""
    import urllib.request, json, os

    plain_text = re.sub(r"<[^>]+>", "", item.html[:3000])
    plain_text = re.sub(r"\s+", " ", plain_text).strip()[:1500]

    prompt = f"""You are writing a brief email to Australian company directors who have subscribed to receive governance briefings from Andrew Roberts Advisory (aradvice.com.au).

Article title: {item.title}
Article URL: {post_url}
Article excerpt: {plain_text}

Write a plain-text email with two parts:

SUBJECT: A direct, specific subject line under 60 characters. Lead with the governance issue, not "New article" or "New briefing". Example format: "Cyber Security Act 2024: Your board obligations" or "APRA CPS 234: What directors must do".

BODY: 4-6 sentences maximum.
- Sentence 1: State the specific governance problem or risk this article addresses. Be concrete — name the regulation, the liability, or the board gap.
- Sentences 2-3: What the article covers and why it matters right now for Australian directors personally.
- Sentence 4: One clear call to action with the article URL.
- Sign off: "Andrew Roberts\\nAndrew Roberts Advisory"
- Footer: "You're receiving this because you subscribed at aradvice.com.au."

Rules:
- No HTML, no markdown, plain text only
- No "I hope this finds you well" or similar openers
- No exclamation marks
- Do not mention "newsletter" or "blog post"
- Address the reader as a director with personal accountability
- Under 150 words total for the body

Return a JSON object with exactly two keys:
"subject": the subject line
"body": the full email body

Return only the JSON. No preamble, no markdown fences."""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

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
            raw = data["content"][0]["text"].strip()
            parsed = json.loads(raw)
            return parsed.get("subject", ""), parsed.get("body", "")
    except Exception as e:
        print(f"  generate_email_draft failed for {item.slug}: {e}",
              file=sys.stderr)
        return "", ""


def send_kit_broadcast(subject: str, body: str) -> bool:
    """Send a broadcast email via the Kit (ConvertKit) API.
    Returns True on success."""
    import urllib.request, json, os

    api_key = os.environ.get("KIT_API_KEY", "")
    if not api_key:
        print("  KIT_API_KEY not set — skipping broadcast",
              file=sys.stderr)
        return False

    # Convert plain text body to minimal HTML for Kit
    html_body = "<br>".join(body.split("\n"))

    payload = json.dumps({
        "broadcast": {
            "subject": subject,
            "content": html_body,
            "description": subject,
            "public": False,
            "published_at": None,
            "send_at": None,
            "email_layout_template": "plain",
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.kit.com/v4/broadcasts",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Kit-Api-Key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            broadcast_id = data.get("broadcast", {}).get("id", "")
            send_req = urllib.request.Request(
                f"https://api.kit.com/v4/broadcasts/{broadcast_id}/send",
                data=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "X-Kit-Api-Key": api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(send_req, timeout=30):
                pass
            print(f"  Email broadcast sent: {subject}")
            return True
    except Exception as e:
        print(f"  Kit broadcast failed: {e}", file=sys.stderr)
        return False


def load_email_log() -> set:
    """Return set of slugs already emailed."""
    log_path = ROOT / "log" / "email-log.md"
    if not log_path.exists():
        return set()
    slugs = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- slug:"):
            slugs.add(line.replace("- slug:", "").strip())
    return slugs


def update_email_log(item: FeedItem, subject: str,
                     sent: bool, dry_run: bool = False) -> None:
    """Append an entry to the email log."""
    log_path = ROOT / "log" / "email-log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    existing = log_path.read_text(
        encoding="utf-8") if log_path.exists() else ""
    if not existing:
        existing = "# Email Broadcast Log\n\n"
    status = "dry-run" if dry_run else ("sent" if sent else "failed")
    published = item_datetime(item.pub_date).strftime("%d %b %Y")
    entry = (
        f"\n## {item.title}\n"
        f"- slug: {item.slug}\n"
        f"- subject: {subject}\n"
        f"- article_date: {published}\n"
        f"- logged: "
        f"{datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}\n"
        f"- status: {status}\n"
    )
    log_path.write_text(existing + entry, encoding="utf-8")


def write_email_draft(item: FeedItem, post_url: str,
                      post_id: str = "000",
                      dry_run: bool = False) -> None:
    """Generate email draft, save to disk, and send via Kit unless already sent or dry_run."""
    emailed = load_email_log()
    if item.slug in emailed:
        return

    article_dir = ROOT / "post" / item.slug
    article_dir.mkdir(parents=True, exist_ok=True)
    draft_path = article_dir / f"{post_id}-email.txt"

    subject, body = generate_email_draft(item, post_url)
    if not subject or not body:
        return

    # Always save the draft to disk
    draft_path.write_text(
        f"SUBJECT: {subject}\n\n{body}",
        encoding="utf-8"
    )
    print(f"  Email draft saved: {draft_path.name}")

    if dry_run:
        print(f"  [DRY RUN] Would send: {subject}")
        update_email_log(item, subject, sent=False, dry_run=True)
        return

    sent = send_kit_broadcast(subject, body)
    update_email_log(item, subject, sent=sent, dry_run=False)


def update_linkedin_log(item: FeedItem, draft_path: Path, post_id: str = "000") -> None:
    """Maintain a log of LinkedIn drafts generated, for tracking posting status."""
    log_path = ROOT / "log" / "posting-log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    if item.slug in existing:
        return
    published = item_datetime(item.pub_date).strftime("%d %b %Y")
    entry = (
        f"\n## {item.title}\n"
        f"- **ID:** {post_id}\n"
        f"- **Slug:** {item.slug}\n"
        f"- **Article date:** {published}\n"
        f"- **Draft generated:** {datetime.now(timezone.utc).strftime('%d %b %Y')}\n"
        f"- **Draft file:** post/{item.slug}/{post_id}-linkedin.txt\n"
        f"- **Status:** [ ] Draft [ ] Edited [ ] Posted\n"
        f"- **Posted date:**\n"
        f"- **Notes:**\n"
    )
    if not existing:
        header = "# LinkedIn Posting Log\n\nTrack draft status and posting history.\n"
        log_path.write_text(header + entry, encoding="utf-8")
    else:
        log_path.write_text(existing + entry, encoding="utf-8")


def write_linkedin_draft(item: FeedItem, post_url: str, post_id: str = "000") -> None:
    """Write a LinkedIn draft post to /post/{slug}/{post_id}-linkedin.txt if it doesn't already exist."""
    article_dir = ROOT / "post" / item.slug
    article_dir.mkdir(parents=True, exist_ok=True)
    draft_path = article_dir / f"{post_id}-linkedin.txt"
    if draft_path.exists():
        return
    print(f"  Generating LinkedIn draft for: {item.slug}")
    post_text = generate_linkedin_post(item, post_url)
    draft_path.write_text(post_text, encoding="utf-8")
    update_linkedin_log(item, draft_path, post_id=post_id)


def generate_advisor_brief(item: FeedItem, post_url: str) -> str:
    """Generate an internal advisor briefing doc for a feed item using the Anthropic API."""
    import urllib.request
    import json

    plain_text = re.sub(r"<[^>]+>", "", item.html[:6000])
    plain_text = re.sub(r"\s+", " ", plain_text).strip()[:4000]

    prompt = f"""You are preparing an internal advisor briefing for Andrew Roberts, founder of Andrew Roberts Advisory (aradvice.com.au), an independent board-level advisor on cyber governance and AI governance for Australian directors.

A client director has just read the following article and may ring Andy to discuss it. Andy needs a concise internal reference he can scan before or during the call.

Article title: {item.title}
Article URL: {post_url}
Article content: {plain_text}

Write the briefing in plain markdown. Use the following structure exactly:

## What the article argues
Two or three sentences. The core thesis — what Andy is claiming and why it matters for Australian directors right now.

## Key regulatory and legal context
Bullet points. Only include regulators, legislation, enforcement actions, or standards that are explicitly mentioned or clearly implied in the article. Do not invent regulatory context. Include ASIC, APRA, the Corporations Act, or the Cyber Security Act 2024 only where the article supports it.

## Questions a client is likely to ask
Four to six bullet points. Specific questions a director or board chair would realistically ask after reading this article. Phrase them as the client would ask them, not as abstract topics.

## How to respond — key messages
For each likely question area, one or two sentences on the position Andy should take. Concrete and actionable. No vague generalities.

## Advisory angles — services to position
Bullet points. What specific services or engagements does this article create an opening for? Be direct about the commercial opportunity without being sales-y.

## Watch-outs
Two or three bullet points. Things Andy should be careful not to overstate, areas of genuine uncertainty in the law or regulation, or nuances the article glosses over that a sophisticated client might push back on.

Output only the briefing. No preamble, no explanation."""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1500,
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
        return f"[Advisor brief generation failed: {e}]"


def generate_post_meta(item: FeedItem) -> tuple[str, str]:
    """Generate a click-optimised meta description and post-specific keywords
    for a blog post using the Anthropic API.
    Returns (description, keywords_csv) — both as plain strings."""
    import urllib.request, json, os

    plain_text = re.sub(r"<[^>]+>", "", item.html[:3000])
    plain_text = re.sub(r"\s+", " ", plain_text).strip()[:1500]

    prompt = f"""You are writing SEO metadata for a blog post on aradvice.com.au,
an independent board-level advisory practice for Australian directors on cyber
and AI governance.

Post title: {item.title}
Post excerpt: {plain_text}

Return a JSON object with exactly two keys:
- "description": A meta description of 130–155 characters. Lead with the
  director's specific problem or risk (not a description of the article).
  Include a reason to click. End with a concrete outcome or action.
  Do not start with "Directors," or "Learn". Never mention the site name.
- "keywords": A comma-separated list of 6–8 specific keywords for this post
  only. Use terms a director would actually search for. Include relevant
  regulation names (e.g. APRA CPS 234, Cyber Security Act 2024, ASIC s180)
  where topically relevant. Do not include generic site-wide terms like
  "board advisory" or "Australian boards" — those are already on the homepage.

Return only the JSON object. No preamble, no markdown fences."""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

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
            raw = data["content"][0]["text"].strip()
            parsed = json.loads(raw)
            return parsed.get("description", ""), parsed.get("keywords", "")
    except Exception as e:
        print(f"  generate_post_meta failed for {item.slug}: {e}", file=sys.stderr)
        return "", ""


def generate_article_schema(item: FeedItem, post_url: str) -> str:
    """Generate JSON-LD Article schema for a blog post."""
    published = item_datetime(item.pub_date).isoformat()
    escaped_title = escape(item.title)
    return (
        '<script type="application/ld+json">\n'
        '{\n'
        '  "@context": "https://schema.org",\n'
        '  "@type": "Article",\n'
        f'  "headline": "{escaped_title}",\n'
        f'  "url": "{post_url}",\n'
        f'  "datePublished": "{published}",\n'
        '  "author": {\n'
        '    "@type": "Person",\n'
        '    "name": "Andrew Roberts",\n'
        '    "url": "https://aradvice.com.au/about.html"\n'
        '  },\n'
        '  "publisher": {\n'
        '    "@type": "Organization",\n'
        '    "name": "Andrew Roberts Advisory",\n'
        '    "url": "https://aradvice.com.au",\n'
        '    "logo": "https://aradvice.com.au/favicon.ico"\n'
        '  }\n'
        '}\n'
        '</script>'
    )


def write_advisor_brief(item: FeedItem, post_url: str, post_id: str = "000") -> None:
    """Write an internal advisor briefing doc to /post/{slug}/{post_id}-advisor-brief.md if it doesn't already exist."""
    article_dir = ROOT / "post" / item.slug
    article_dir.mkdir(parents=True, exist_ok=True)
    brief_path = article_dir / f"{post_id}-advisor-brief.md"
    if brief_path.exists():
        return
    print(f"  Generating advisor brief for: {item.slug}")
    brief_text = generate_advisor_brief(item, post_url)
    published = item_datetime(item.pub_date).strftime("%d %b %Y")
    header = (
        f"# Advisor Brief — {item.title}\n\n"
        f"**Article:** {post_url}  \n"
        f"**Published:** {published}  \n"
        f"**Generated:** {datetime.now(timezone.utc).strftime('%d %b %Y')}  \n\n"
        "---\n\n"
    )
    brief_path.write_text(header + brief_text, encoding="utf-8")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate email drafts without sending"
    )
    args = parser.parse_args()
    dry_run = args.dry_run

    # Primary: scrape blog index pages to get all articles
    feed_items = parse_blog_index()

    # Fallback: supplement with RSS feed items (for pub_date
    # and description which index pages don't provide)
    try:
        feed_xml = fetch_text(
            FEED_URL,
            "application/rss+xml, application/xml, text/xml"
        )
        rss_items = parse_feed(feed_xml)
        # Build lookup of RSS data by slug for merging
        rss_by_slug: dict[str, dict] = {}
        for rss in rss_items:
            s = item_slug(rss["link"], rss["title"])
            rss_by_slug[s] = rss
    except Exception as e:
        print(f"  RSS feed fetch failed, continuing without: {e}",
              file=sys.stderr)
        rss_by_slug = {}

    if not feed_items:
        print("No articles found on blog index.", file=sys.stderr)
        return 1

    # Merge RSS metadata into index-scraped items
    for item in feed_items:
        slug = item_slug(item["link"], item["title"])
        if slug in rss_by_slug:
            rss = rss_by_slug[slug]
            item["pub_date"] = rss.get("pub_date", "")
            item["description"] = rss.get("description", "")
            if not item["title"]:
                item["title"] = rss.get("title", "")

    print(f"  Found {len(feed_items)} articles on blog index "
          f"({len(rss_by_slug)} in RSS feed)")

    # Merge manually-managed posts not in the getautoseo feed
    feed_slugs = {item_slug(i["link"], i["title"])
                  for i in feed_items}
    for manual in MANUAL_POSTS:
        s = item_slug(manual["link"], manual["title"])
        if s not in feed_slugs:
            feed_items.append(manual)

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

    # Assign persistent sequential IDs by publish date
    registry = assign_post_ids(generated_items)

    manual_slugs = {item_slug(m["link"], m["title"]) for m in MANUAL_POSTS}

    for i, item in enumerate(generated_items):
        page_path = article_page_path(item.slug)
        post_url = f"{MAIN_DOMAIN}/post/{item.slug}/"
        post_id = f"{registry.get(item.slug, 0):03d}"

        # Skip HTML regeneration for manually-managed posts
        if item.slug in manual_slugs:
            write_linkedin_draft(item, post_url, post_id=post_id)
            write_advisor_brief(item, post_url, post_id=post_id)
            write_email_draft(item, post_url, post_id=post_id, dry_run=dry_run)
            continue

        page_html = inject_more_articles(item.html, generated_items)
        write_page(page_path, page_html, feed_item=item, post_id=post_id)
        write_linkedin_draft(item, post_url, post_id=post_id)
        write_advisor_brief(item, post_url, post_id=post_id)
        write_email_draft(item, post_url, post_id=post_id, dry_run=dry_run)

    latest_item = generated_items[0]
    remaining_items = generated_items[1:] if len(generated_items) > 1 else []
    latest_with_listing = inject_more_articles(latest_item.html, remaining_items)
    latest_with_listing = inject_blog_landing_view(latest_with_listing, generated_items)
    write_page(ROOT / "blog.html", latest_with_listing)
    (ROOT / "sitemap.xml").write_text(build_sitemap(generated_items), encoding="utf-8")

    generate_post_mapping(generated_items, registry)
    print(f"Synced {len(generated_items)} article(s). Latest: {latest_item.slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())