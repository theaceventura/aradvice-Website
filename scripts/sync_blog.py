from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import escape, unescape
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

# Advisor briefs, LinkedIn drafts, and email drafts are internal-only and
# must never live inside a folder GitHub Pages publishes. This defaults to
# a sibling folder outside the git repo entirely; override with
# INTERNAL_DRAFTS_DIR in .env if you want it somewhere else, e.g. a
# separate private repo checked out locally.
import os as _os_early
INTERNAL_DRAFTS_ROOT = Path(_os_early.environ.get(
    "INTERNAL_DRAFTS_DIR",
    str(ROOT.parent / "aradvice-internal-drafts"),
))
FEED_URL = "https://blog.aradvice.com.au/feed.xml"
MANUAL_POSTS = [
    {
        "title": "Linking Cyber Risk to Financial Impact: A Director's Guide to Defensible Board Reporting",
        "link": "https://aradvice.com.au/post/linking-cyber-risk-to-financial-impact-a-directors-guide-to-defensible-board-reporting/",
        "pub_date": "Wed, 10 Jun 2026 00:00:00 +0000",
        "description": "Can you defend a cyber strategy that you cannot quantify in Australian Dollars? As a director, you likely feel the growing disconnect between technical jargon and personal liability.",
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
    html = html.replace("https://blog.aradvice.com.au", MAIN_DOMAIN)
    # Replace externally-hosted author thumbnail with local copy
    html = re.sub(
        r'https://getautoseo\.com/storage/author-thumbnails/[^"\']+',
        "/images/andrew-roberts.jpg",
        html,
    )
    # Fix author-box images that point to hero/og images or missing files
    html = re.sub(
        r'(<div[^>]*class="[^"]*author-box[^"]*"[^>]*>\s*<img\s+)src="(?!/images/andrew-roberts\.jpg)[^"]*"',
        r'\1src="/images/andrew-roberts.jpg"',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return html


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
    # Remove the GetAutoSEO client-side tracking/attribution script. This
    # IIFE generates a per-browser visitor ID, posts pageview and
    # time-on-page beacons to getautoseo.com using a hardcoded API token,
    # and rewrites every internal link's href to append autoseo_vid /
    # autoseo_aid / autoseo_avt / autoseo_src tracking query parameters.
    # Anchored on the literal "TRACKING_TOKEN" variable name, which is
    # unique to this script and stable across articles (unlike
    # ARTICLE_ID/visitorId, which vary per post/visitor). The bounded
    # (?:(?!</script>).)*? construct prevents the match from spanning
    # into unrelated <script> tags elsewhere on the page.
    html = re.sub(
        r'<script\b[^>]*>(?:(?!</script>).)*?TRACKING_TOKEN(?:(?!</script>).)*?</script>',
        '',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # NOTE: the platform-generated Table of Contents is intentionally kept
    # (decision made 27 Jul 2026). It is currently unstyled raw GetAutoSEO
    # markup; a follow-up pass to restyle it to match the site's dark navy
    # / cyan design system is on the list, not yet done.
    return html


def clean_article_content(html: str) -> str:
    """Fix content-level issues introduced by the GetAutoSEO publishing platform."""
    # Convert Markdown-style headings left as plain text inside <p> tags.
    # \s* handles both "## Heading" and "##Heading" (no space after hashes).
    # (?!#) ensures we don't match more # than intended.
    for n, tag in ((3, 'h3'), (2, 'h2'), (1, 'h1')):
        pattern = r'<p>\s*' + '#' * n + r'(?!#)\s*(.+?)\s*</p>'
        html = re.sub(
            pattern,
            lambda m, t=tag: f'<{t}>{m.group(1)}</{t}>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    # Fix CMS bio separator artifact: &quot;,&quot; should be a plain comma
    html = html.replace(' &quot;,&quot; ', ', ')
    html = html.replace(' "," ', ', ')
    # Strip trailing "aradvice.com.au" injected into the bio paragraph
    html = re.sub(r'\s*aradvice\.com\.au\s*(?=</p>)', '', html)
    # Remove duplicate "If this resonates" CTA — keep only the last occurrence.
    # GetAutoSEO renders this CTA in two different shapes depending on the
    # article: sometimes as a single <p><a href="...">...</a></p> wrapping
    # the whole block, sometimes as three bare sibling <p> tags with no
    # anchor at all. Match both.
    cta_pattern = re.compile(
        r'<p[^>]*>\s*<a[^>]*>\s*If this resonates.*?</a>\s*</p>'
        r'|'
        r'<p[^>]*>\s*If this resonates[^<]*</p>\s*<p[^>]*>[^<]*</p>\s*<p[^>]*>[^<]*</p>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    matches = list(cta_pattern.finditer(html))
    if len(matches) > 1:
        for m in reversed(matches[:-1]):
            html = html[:m.start()] + html[m.end():]
    # Strip the redundant trailing bare-URL line GetAutoSEO appends inside the
    # CTA anchor text (the href already carries the destination).
    html = re.sub(
        r'(<a[^>]*href="https://aradvice\.com\.au/contact\.html"[^>]*>'
        r'If this resonates, I would welcome a conversation\.)'
        r'\s*\nDirector Readiness Assessment\s*\naradvice\.com\.au/contact\.html'
        r'(\s*</a>)',
        r'\1 Director Readiness Assessment.\2',
        html,
        flags=re.IGNORECASE,
    )
    # Normalise em/en dashes in the mirrored article body to site house style.
    html = html.replace("\u2014", ", ").replace(" \u2013 ", ", ")
    html = html.replace(", ,", ",").replace(",,", ",").replace(" ,", ",")
    # Retired-product phrasing left in generated bodies -> current product naming.
    html = html.replace("AI Governance Readiness Review", "AI Governance Review")
    html = html.replace("Cyber Governance Readiness Review", "Cyber Governance Review")
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
        'href="director-readiness-assessment.html"': 'href="/director-readiness-assessment.html"',
        "href='director-readiness-assessment.html'": "href='/director-readiness-assessment.html'",
        'href="about.html"': 'href="/about.html"',
        "href='about.html'": "href='/about.html'",
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
    post_id: str = "",
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
    briefing_label = ""
    if post_slug and post_id:
        briefing_label = (
            f'<p style="font-size:11px; color:#94a3b8; letter-spacing:0.1em; '
            f'text-transform:uppercase; margin:0 0 16px 0;">Briefing No. {post_id}</p>'
        )
    out = re.sub(
        r'<article class="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">',
        '<article class="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12 bg-white rounded-[2rem] shadow-[0_24px_70px_rgba(15,23,42,0.08)] border border-slate-200">'
        + briefing_label,
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


def insert_related_briefings(html: str, related_html: str) -> str:
    """Insert related_html directly above the 'If this resonates' CTA. That
    CTA renders in several shapes depending on the article — anchor-wrapped,
    three bare sibling <p> tags, or a single <p> with <br> line breaks — so
    match just the opening tag immediately before the CTA text rather than
    trying to enumerate every closing shape. If there are multiple CTA
    occurrences (a pre-existing dedup gap), insert above the last one, since
    that's the one that actually renders at the end of the article. Falls
    back to appending before </article> if no CTA is found at all."""
    if not related_html:
        return html
    matches = list(re.finditer(
        r'<p[^>]*>(?:\s*<a[^>]*>)?\s*If this resonates',
        html,
        flags=re.IGNORECASE,
    ))
    if matches:
        pos = matches[-1].start()
        return html[:pos] + related_html + html[pos:]
    return html.replace("</article>", related_html + "</article>", 1)


def write_page(path: Path, html: str, feed_item: "FeedItem | None" = None, post_id: str = "000",
                related_html: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rewritten = normalize_internal_links(clean_article_content(strip_platform_widgets(rewrite_domains(html))))
    rewritten = insert_related_briefings(rewritten, related_html)
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
    overrides = load_post_overrides().get(post_slug, {}) if post_slug else {}
    post_title = overrides.get("title") or (feed_item.title if feed_item else "")
    # Generate click-optimised description and per-post keywords via API
    api_desc, post_keywords = ("", "")
    if feed_item and not path.exists():
        api_desc, post_keywords = generate_post_meta(feed_item)

    # Resolve description and keywords — priority:
    #   1. API result (new articles only)
    #   2. Existing local file (preserves previously generated/edited values)
    #   3. Fetched HTML meta (new articles where API failed)
    #   4. Extracted body description
    if overrides.get("meta_description"):
        raw_desc = overrides["meta_description"]
    elif api_desc:
        raw_desc = api_desc
    elif path.exists():
        # Read from the stored page so we never overwrite with inferior CMS content.
        # Fully unescape the captured value — previous runs may have over-encoded it —
        # so escape() in replace_host_head_and_header produces a clean single encoding.
        stored = path.read_text(encoding="utf-8")
        stored_desc_match = (
            re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']{10,})["\']', stored, flags=re.IGNORECASE)
            or re.search(r'<meta[^>]*content=["\']([^"\']{10,})["\'][^>]*name=["\']description["\']', stored, flags=re.IGNORECASE)
        )
        if stored_desc_match:
            raw = stored_desc_match.group(1).strip()
            prev = None
            while prev != raw:
                prev = raw
                raw = unescape(raw)
            raw_desc = raw
        else:
            raw_desc = ""
        if not post_keywords:
            stored_kw_match = re.search(r'<meta[^>]*name=["\']keywords["\'][^>]*content=["\']([^"\']+)["\']', stored, flags=re.IGNORECASE)
            if stored_kw_match:
                post_keywords = stored_kw_match.group(1).strip()
    else:
        fetched_meta_match = (
            re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']{10,})["\']', rewritten, flags=re.IGNORECASE)
            or re.search(r'<meta[^>]*content=["\']([^"\']{10,})["\'][^>]*name=["\']description["\']', rewritten, flags=re.IGNORECASE)
        )
        if fetched_meta_match:
            raw_desc = fetched_meta_match.group(1).strip()
        elif body_desc:
            raw_desc = body_desc
        else:
            raw_desc = ""
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
            f"{MAIN_DOMAIN}/post/{post_slug}/",
            post_id,
        )
    if overrides.get("keywords"):
        post_keywords = overrides["keywords"]
    path.write_text(
        replace_host_head_and_header(
            rewritten, local_head, local_header, local_html,
            post_slug=post_slug,
            post_title=post_title,
            post_description=raw_desc,
            post_url=post_url,
            post_image=post_image,
            post_keywords=post_keywords,
            post_id=post_id,
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


def render_category_filter_bar(
    categories_present: list[str], counts: "dict[str, int] | None" = None
) -> str:
    """Render the topic filter bar shown above the article grid on blog.html.
    categories_present is the ordered list of category keys that have at
    least one post, so we never show an empty filter button.
    counts maps category key -> article count for the badge on each button."""
    if not categories_present:
        return ""
    counts = counts or {}
    total = sum(counts.values())

    def count_badge(n: int, active: bool = False) -> str:
        bg = "bg-cyan-400/20" if active else "bg-slate-700"
        return (
            f'<span class="ml-1.5 inline-block rounded-full {bg} '
            f'px-1.5 py-0.5 text-[9px] font-bold leading-none">{n}</span>'
        )

    buttons = [
        '<button type="button" data-filter="all" '
        'class="category-filter-btn active inline-flex items-center rounded-full '
        'border border-cyan-400/60 bg-cyan-400/10 px-4 py-1.5 text-xs font-semibold '
        f'uppercase tracking-wider text-cyan-300 transition-colors">All{count_badge(total, active=True)}</button>'
    ]
    for cat_key in categories_present:
        label = escape(CATEGORY_LABELS.get(cat_key, cat_key))
        n = counts.get(cat_key, 0)
        badge = count_badge(n) if n else ""
        buttons.append(
            f'<button type="button" data-filter="{escape(cat_key)}" '
            'class="category-filter-btn inline-flex items-center rounded-full '
            'border border-slate-600/70 bg-slate-800/60 px-4 py-1.5 text-xs font-semibold '
            'uppercase tracking-wider text-slate-300 hover:border-cyan-400/60 hover:text-cyan-300 '
            f'transition-colors">{label}{badge}</button>'
        )
    bar_html = (
        '<div class="category-filter-bar flex flex-wrap gap-2 mb-8">'
        + "".join(buttons)
        + "</div>"
    )
    script = """
<script>
(function() {
  var bar = document.querySelector('.category-filter-bar');
  if (!bar) return;
  var buttons = bar.querySelectorAll('.category-filter-btn');
  function setActive(btn) {
    buttons.forEach(function(b) {
      b.classList.remove('active', 'border-cyan-400/60', 'bg-cyan-400/10', 'text-cyan-300');
      b.classList.add('border-slate-600/70', 'bg-slate-800/60', 'text-slate-300');
    });
    btn.classList.add('active', 'border-cyan-400/60', 'bg-cyan-400/10', 'text-cyan-300');
    btn.classList.remove('border-slate-600/70', 'bg-slate-800/60', 'text-slate-300');
  }
  buttons.forEach(function(btn) {
    btn.addEventListener('click', function() {
      var filter = btn.getAttribute('data-filter');
      setActive(btn);
      document.querySelectorAll('[data-category]').forEach(function(card) {
        if (filter === 'all' || card.getAttribute('data-category') === filter) {
          card.style.display = '';
        } else {
          card.style.display = 'none';
        }
      });
    });
  });
})();
</script>
"""
    return bar_html + script


def render_more_articles_section(
    items: list[FeedItem],
    categories: "dict | None" = None,
    show_filter_bar: bool = False,
    heading: str = "More Articles",
) -> str:
    categories = categories or {}
    cards: list[str] = []
    categories_present: list[str] = []
    seen_categories: set = set()
    category_counts: dict[str, int] = {}

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

        cat_key = categories.get(item.slug, _DEFAULT_CATEGORY)
        if cat_key not in seen_categories:
            seen_categories.add(cat_key)
            categories_present.append(cat_key)
        category_counts[cat_key] = category_counts.get(cat_key, 0) + 1
        cat_label = escape(CATEGORY_LABELS.get(cat_key, cat_key))
        cat_badge = (
            f'<span class="inline-block text-[10px] font-bold uppercase tracking-wider '
            f'text-slate-500 mb-2">{cat_label}</span><br/>'
        )

        cards.append(
            f'<a href="/post/{escape(item.slug)}/" data-category="{escape(cat_key)}" '
            'class="group block rounded-2xl border border-slate-700/70 bg-slate-900/70 hover:border-cyan-400/60 hover:shadow-[0_18px_60px_rgba(6,182,212,0.2)] transition-all no-underline" style="text-decoration: none; cursor: pointer;">'
            + image_html
            + '<div class="p-6">'
            + cat_badge
            + f'<h3 class="text-lg font-semibold text-slate-100 leading-snug mb-2">{escape(item.title)}{new_badge}</h3>'
            + f'<div class="text-sm text-slate-400">{meta}</div>'
            + (f'<p class="text-sm text-slate-300 mt-3 leading-relaxed line-clamp-3">{escape(item.excerpt)}</p>' if item.excerpt else "")
            + "</div>"
            + "</a>"
        )

    filter_bar_html = render_category_filter_bar(categories_present, counts=category_counts) if show_filter_bar else ""

    return (
        '<section class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 border-t border-slate-700/70">'
        f'<h2 class="text-2xl font-bold text-slate-100 mb-8">{escape(heading)}</h2>'
        + filter_bar_html
        + '<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">'
        + "".join(cards)
        + "</div>"
        "</section>"
    )



def inject_more_articles(html: str, items: list[FeedItem], categories: "dict | None" = None) -> str:
    section_html = render_more_articles_section(items, categories=categories)
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
    if not items:
        return ""

    latest = items[0]
    published = item_datetime(latest.pub_date).strftime("%d %b %Y")
    post_url = f"/post/{escape(latest.slug)}/"

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
        '<section class="w-full border-b border-slate-700/70 bg-navy-deep">' 
        '<div class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 pb-16">'
        '<p class="text-xs font-bold uppercase tracking-[0.3em] text-primary mb-6">Latest Article</p>'
        f'<h1 class="text-3xl sm:text-4xl font-black text-white leading-tight mb-6 max-w-3xl">'
        f'<a href="{post_url}" class="text-white hover:text-primary transition-colors" style="text-decoration:none;">'
        f'{escape(latest.title)}'
        f'</a></h1>'
        f'<p class="text-sm text-slate-400 mb-6">{meta}</p>'
        f'<p class="text-lg text-slate-300 leading-relaxed max-w-2xl mb-8">{excerpt}</p>'
        f'<a href="{post_url}" class="inline-flex items-center gap-2 bg-primary hover:bg-white text-navy-deep px-8 py-4 text-sm font-bold uppercase tracking-widest transition-all transform hover:-translate-y-0.5 shadow-lg" style="text-decoration:none;">'
        f'Read Article \u2192'
        f'</a>'
        '</div>'
        '</section>'
        '<section class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12 border-t border-slate-700/70">'
        '<div class="max-w-xl mx-auto text-center mb-8">'
        '<p class="text-xs font-bold uppercase tracking-[0.3em] text-primary mb-3">GOVERNANCE BRIEFINGS</p>'
        '<h2 class="text-2xl font-bold text-slate-100 mb-3">Stay informed on cyber and AI governance</h2>'
        '<p class="text-slate-400 text-sm">Short, practical briefings for Australian directors \u2014 delivered when there is something worth reading.</p>'
        '</div>'
        '<div class="max-w-md mx-auto">'
        '<style>'
        '.formkit-form[data-uid="67af2df661"] {'
        'background: transparent !important;'
        'box-shadow: none !important;'
        'max-width: 100% !important;'
        '}'
        '.formkit-form[data-uid="67af2df661"] [data-style="full"] {'
        'display: block !important;'
        'background: transparent !important;'
        '}'
        '.formkit-form[data-uid="67af2df661"] .formkit-column {'
        'background: transparent !important;'
        'padding: 0 !important;'
        'border: none !important;'
        '}'
        '.formkit-form[data-uid="67af2df661"] .formkit-header,'
        '.formkit-form[data-uid="67af2df661"] .formkit-subheader {'
        'display: none !important;'
        '}'
        '.formkit-form[data-uid="67af2df661"] .formkit-alert-success {'
        'background: transparent !important;'
        'border: none !important;'
        'color: #00d4ff !important;'
        'font-size: 16px !important;'
        'font-weight: 600 !important;'
        'text-align: center !important;'
        'padding: 8px 0 !important;'
        '}'
        '.formkit-form[data-uid="67af2df661"] .formkit-powered-by-convertkit-container {'
        'display: none !important;'
        '}'
        '.formkit-form[data-uid="67af2df661"] .formkit-guarantee {'
        'color: #64748b !important;'
        'text-align: center !important;'
        '}'
        '</style>'
        '<script src="https://f.convertkit.com/ckjs/ck.5.js"></script>'
        '<form action="https://app.kit.com/forms/9514147/subscriptions" class="seva-form formkit-form" method="post" data-sv-form="9514147" data-uid="67af2df661" data-format="inline" data-version="5" data-options="{&quot;settings&quot;:{&quot;after_subscribe&quot;:{&quot;action&quot;:&quot;message&quot;,&quot;success_message&quot;:&quot;Success! Check your email to confirm.&quot;}}}">'
        '<ul class="formkit-alert formkit-alert-error" data-element="errors" data-group="alert"></ul>'
        '<div data-element="fields" class="seva-fields formkit-fields">'
        '<div class="formkit-field">'
        '<input class="formkit-input" name="email_address" aria-label="Email Address" placeholder="Your email address" required type="email" style="background:#1e293b; color:#f1f5f9; border:1px solid #475569; border-radius:0; padding:12px 16px; width:100%; font-size:14px;" />'
        '</div>'
        '<button data-element="submit" class="formkit-submit" style="background:#00d4ff; color:#050c1c; border:none; padding:12px 24px; font-weight:700; font-size:12px; letter-spacing:0.1em; text-transform:uppercase; cursor:pointer; width:100%; margin-top:8px;">'
        '<span>Subscribe</span>'
        '</button>'
        '</div>'
        '<p style="color:#64748b; font-size:12px; text-align:center; margin-top:12px;">No spam. Unsubscribe anytime.</p>'
        '</form>'
        '</div>'
        '</section>'
    )

def inject_blog_landing_view(html: str, items: list[FeedItem], categories: "dict | None" = None) -> str:
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
        more_section = render_more_articles_section(
            remaining, categories=categories, show_filter_bar=True, heading="Articles"
        )
        html = re.sub(
            r'<section class="max-w-5xl\b[^>]*>\s*<h2\b[^>]*>(?:More )?Articles</h2>.*?</section>',
            more_section,
            html,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
    return html


def build_items_from_registry() -> list[FeedItem]:
    """Reconstruct a FeedItem for every post in post-registry.json by
    reading its already-published HTML on disk. This is the durable,
    feed-independent source of truth for blog.html and sitemap.xml —
    it never depends on the GetAutoSEO feed being reachable, and it
    correctly includes posts published via publish_original_post()
    that the feed never knew about in the first place."""
    registry = load_post_registry()
    items: list[FeedItem] = []
    for slug in registry:
        post_file = ROOT / "post" / slug / "index.html"
        if not post_file.exists():
            continue
        stored = post_file.read_text(encoding="utf-8")

        title_match = re.search(r"<title>([^<]*)\s*\|", stored)
        title = unescape(title_match.group(1).strip()) if title_match else slug

        desc_match = (
            re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']', stored, flags=re.IGNORECASE)
        )
        excerpt = unescape(desc_match.group(1).strip())[:160] if desc_match else ""

        pub_date_str = ""
        date_match = re.search(r'"datePublished":\s*"([^"]+)"', stored)
        if date_match:
            try:
                dt = datetime.fromisoformat(date_match.group(1).replace("Z", "+00:00"))
                pub_date_str = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
            except ValueError:
                pub_date_str = ""
        if not pub_date_str:
            try:
                mtime = datetime.fromtimestamp(post_file.stat().st_mtime, tz=timezone.utc)
                pub_date_str = mtime.strftime("%a, %d %b %Y %H:%M:%S +0000")
            except OSError:
                pub_date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

        items.append(FeedItem(
            title=title,
            link=f"{MAIN_DOMAIN}/post/{slug}/",
            slug=slug,
            pub_date=pub_date_str,
            html=stored,
            image_url="",
            read_time=extract_read_time(stored),
            excerpt=excerpt,
        ))

    items.sort(key=lambda i: item_datetime(i.pub_date), reverse=True)
    return items


def build_sitemap(items: list[FeedItem]) -> str:
    entries = [
        (f"{MAIN_DOMAIN}/", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/products.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/for-directors.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/founder-advisory.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/ai-governance-review.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/cyber-governance-review.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/director-readiness-assessment.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/about.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/contact.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/resource-hub.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/blog.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/aicd-cyber-principles.html", datetime.now(timezone.utc)),
        (f"{MAIN_DOMAIN}/apra-ai-governance-2026.html", datetime.now(timezone.utc)),
    ]

    # Slugs covered by this run's live GetAutoSEO feed use the feed's own
    # pub_date for lastmod, same as before.
    feed_slugs_seen: set[str] = set()
    for item in items:
        entries.append((f"{MAIN_DOMAIN}/post/{item.slug}/", item_datetime(item.pub_date)))
        feed_slugs_seen.add(item.slug)

    # post-registry.json is the durable source of truth for "this post
    # exists" — independent of whether GetAutoSEO's feed still serves it
    # today. Any registered slug with a real local file on disk gets a
    # sitemap entry even if it has dropped out of the live feed (e.g. the
    # source article was retired/unpublished upstream after we already
    # published our own copy). lastmod falls back to the file's own mtime
    # since no pub_date is available once a slug is no longer in the feed.
    registry = load_post_registry()
    for slug in registry:
        if slug in feed_slugs_seen:
            continue
        post_path = ROOT / "post" / slug / "index.html"
        if not post_path.exists():
            continue
        try:
            mtime = datetime.fromtimestamp(post_path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            mtime = datetime.now(timezone.utc)
        entries.append((f"{MAIN_DOMAIN}/post/{slug}/", mtime))

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


CATEGORY_LABELS: dict[str, str] = {
    "cyber-governance": "Cyber Governance & Oversight",
    "regulation-compliance": "Regulation & Compliance",
    "ai-governance": "AI Governance",
    "board-reporting": "Board Reporting & Disclosure",
    "third-party-risk": "Third-Party & Supply Chain Risk",
    "governance-advisory": "Governance Strategy & Advisory",
}

# Order matters — first match wins. More specific categories are
# checked before the broad cyber-governance fallback.
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("third-party-risk", ["third-party", "third party", "supply chain", "vendor risk"]),
    ("board-reporting", ["investor expectation", "financial impact", "risk reporting", "board reporting", "disclosure"]),
    ("regulation-compliance", ["cyber security act", "apra", "cps-234", "cps 234", "privacy act", "crimes act", "regulatory settlement", "asic v ", " fca "]),
    ("ai-governance", [" ai ", "-ai-", "artificial intelligence", "generative ai", "ai governance", "ai risk", "ai strategy"]),
    ("governance-advisory", ["tech consulting", "digital strategy", "consulting"]),
]

_DEFAULT_CATEGORY = "cyber-governance"


def load_post_categories() -> dict:
    """Load the slug -> category-slug map. Separate file from post-registry.json
    so the existing ID-assignment logic (which expects int values) is untouched."""
    import json
    path = ROOT / "post-categories.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_post_categories(categories: dict) -> None:
    import json
    path = ROOT / "post-categories.json"
    path.write_text(
        json.dumps(categories, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def load_draft(slug: str) -> dict:
    """Load a hand-authored draft package written by the drafting tool."""
    import json
    path = ROOT / "drafts" / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"No draft found at drafts/{slug}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def render_original_post_scaffold(title: str, body_html: str) -> str:
    """Wrap hand-authored article body HTML in the minimal document shape
    write_page()/replace_host_head_and_header() expect: the article wrapper
    class they search for, plus head/body/header/footer tags present so the
    real site shell gets swapped in during processing."""
    escaped_title = escape(title)
    return (
        "<html><head><title>" + escaped_title + "</title></head><body>"
        "<header></header>"
        '<main class="flex-1">'
        '<article class="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">'
        "<h1>" + escaped_title + "</h1>"
        + body_html +
        "</article>"
        "</main>"
        "<footer></footer>"
        "</body></html>"
    )


def publish_original_post(slug: str) -> None:
    """Publish a hand-authored draft from drafts/{slug}.json through the
    same pipeline used for GetAutoSEO posts: ID and category assignment,
    og:image generation, schema, related briefings, LinkedIn draft and
    advisor brief. Does not touch blog.html or sitemap.xml — run a normal
    sync afterward (or call the tail of main()) to refresh those."""
    draft = load_draft(slug)
    title = draft["title"]
    body_html = draft["body_html"]
    meta_description = draft.get("meta_description", "")
    keywords = draft.get("keywords", "")
    category = draft.get("category", _DEFAULT_CATEGORY)
    pub_date_str = draft.get("pub_date") or datetime.now(timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S +0000"
    )

    post_url = f"{MAIN_DOMAIN}/post/{slug}/"
    scaffold_html = render_original_post_scaffold(title, body_html)

    item = FeedItem(
        title=title, link=post_url, slug=slug, pub_date=pub_date_str,
        html=scaffold_html, image_url="", read_time="",
        excerpt=meta_description[:160],
    )

    registry = load_post_registry()
    if slug not in registry:
        valid_ids = [int(v) for v in registry.values() if str(v).isdigit()]
        registry[slug] = max(valid_ids, default=0) + 1
        save_post_registry(registry)
    post_id = f"{registry[slug]:03d}"

    categories = load_post_categories()
    categories[slug] = category
    save_post_categories(categories)

    visible_items = []
    for s, pid in registry.items():
        if s == slug:
            continue
        post_file = ROOT / "post" / s / "index.html"
        if not post_file.exists():
            continue
        stored = post_file.read_text(encoding="utf-8")
        title_match = re.search(r"<title>([^<]*)\s*\|", stored)
        visible_items.append(FeedItem(
            title=title_match.group(1).strip() if title_match else s,
            link=f"{MAIN_DOMAIN}/post/{s}/", slug=s, pub_date="", html="",
            image_url="", read_time="",
        ))

    related_html = render_related_briefings(item, visible_items, categories, registry)
    page_html = inject_more_articles(scaffold_html, visible_items, categories=categories)
    write_page(article_page_path(slug), page_html, feed_item=item,
               post_id=post_id, related_html=related_html)

    write_linkedin_draft(item, post_url, post_id=post_id, force=True)
    write_advisor_brief(item, post_url, post_id=post_id)

    print(f"Published original post: {slug} (Briefing No. {post_id})")
    print("Run a normal sync (no flags) next to refresh blog.html and sitemap.xml.")


def process_pending_drafts() -> None:
    """Automatically publish any draft sitting in drafts/ that hasn't been
    published yet, so dropping an exported file there is the only manual
    step. Already-published drafts are moved into drafts/published/ so
    they are not reprocessed on a later run."""
    drafts_dir = ROOT / "drafts"
    if not drafts_dir.exists():
        return
    published_dir = drafts_dir / "published"
    for draft_path in sorted(drafts_dir.glob("*.json")):
        slug = draft_path.stem
        post_path = article_page_path(slug)
        if post_path.exists():
            # Already published in a previous run — archive and skip.
            published_dir.mkdir(parents=True, exist_ok=True)
            draft_path.rename(published_dir / draft_path.name)
            continue
        try:
            publish_original_post(slug)
            published_dir.mkdir(parents=True, exist_ok=True)
            draft_path.rename(published_dir / draft_path.name)
        except Exception as e:
            print(f"  Failed to auto-publish draft {slug}: {e}", file=sys.stderr)


def load_post_overrides() -> dict:
    """Load manual title/meta/keyword overrides, keyed by slug. Lets a
    single post's SEO title, description, or keywords be corrected
    without touching the GetAutoSEO source (useful while that
    subscription is read-only) or waiting on a full content rewrite."""
    import json
    path = ROOT / "post-overrides.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def fetch_ga4_report(property_id: str, days: int = 30) -> dict:
    """Fetch daily sessions/users trend and top landing pages from GA4
    via the Analytics Data API using a service account."""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Dimension, Metric, OrderBy
    )
    from google.oauth2 import service_account
    import os, json as _json

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not creds_json or not property_id:
        return {}
    creds = service_account.Credentials.from_service_account_info(_json.loads(creds_json))
    client = BetaAnalyticsDataClient(credentials=creds)

    trend_request = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="date")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="engagementRate"),
        ],
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="yesterday")],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
    )
    trend_response = client.run_report(trend_request)
    trend = [
        {
            "date": row.dimension_values[0].value,
            "sessions": int(row.metric_values[0].value),
            "activeUsers": int(row.metric_values[1].value),
            "engagementRate": float(row.metric_values[2].value),
        }
        for row in trend_response.rows
    ]

    pages_request = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="landingPage")],
        metrics=[Metric(name="sessions"), Metric(name="activeUsers"), Metric(name="bounceRate")],
        date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=40,
    )
    pages_response = client.run_report(pages_request)
    top_pages = [
        {
            "page": row.dimension_values[0].value,
            "sessions": int(row.metric_values[0].value),
            "activeUsers": int(row.metric_values[1].value),
            "bounceRate": round(float(row.metric_values[2].value), 3),
        }
        for row in pages_response.rows
    ]

    return {"trend": trend, "top_pages": top_pages}


def fetch_gsc_report(site_url: str, days: int = 30) -> dict:
    """Fetch daily clicks/impressions trend and top queries from Search
    Console via the Search Console API using a service account."""
    from googleapiclient.discovery import build
    from google.oauth2 import service_account
    from datetime import timedelta
    import os, json as _json

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not creds_json or not site_url:
        return {}
    creds = service_account.Credentials.from_service_account_info(
        _json.loads(creds_json),
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    service = build("searchconsole", "v1", credentials=creds)

    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=days)

    trend_response = service.searchanalytics().query(
        siteUrl=site_url,
        body={"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": ["date"]},
    ).execute()
    trend = [
        {"date": row["keys"][0], "clicks": row["clicks"], "impressions": row["impressions"],
         "ctr": round(row["ctr"], 4), "position": round(row["position"], 1)}
        for row in trend_response.get("rows", [])
    ]

    queries_response = service.searchanalytics().query(
        siteUrl=site_url,
        body={"startDate": start.isoformat(), "endDate": end.isoformat(),
              "dimensions": ["query"], "rowLimit": 15},
    ).execute()
    top_queries = [
        {"query": row["keys"][0], "clicks": row["clicks"], "impressions": row["impressions"],
         "position": round(row["position"], 1)}
        for row in queries_response.get("rows", [])
    ]

    return {"trend": trend, "top_queries": top_queries}


def _anthropic_text(data: dict) -> str:
    """Extract the text content block from an Anthropic API response.
    This account has extended thinking on by default, so content[0] is
    often a 'thinking' block rather than the actual 'text' block —
    scan for the text block instead of assuming its position."""
    for block in data.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    raise KeyError("text")


def generate_report_commentary(ga4_data: dict, gsc_data: dict) -> dict:
    """Ask the Anthropic API to analyse the day's GA4/Search Console data
    and return short, grounded commentary plus new article topic ideas.
    Returns {} on any failure so the report still renders without it."""
    import urllib.request, json as _json, os

    payload_data = {
        "ga4_trend_last_30_days": ga4_data.get("trend", []),
        "top_site_pages_last_7_days": ga4_data.get("top_pages", [])[:15],
        "gsc_trend_last_30_days": gsc_data.get("trend", []),
        "top_search_queries_last_30_days": gsc_data.get("top_queries", []),
    }

    prompt = f"""You are analysing website performance data for aradvice.com.au,
an independent board-level advisory practice for Australian directors on cyber
and AI governance.

Here is the raw data (JSON):
{_json.dumps(payload_data)}

Write three short sections based ONLY on what this data actually shows. Do
not invent numbers, trends, or explanations not supported by the data given.

1. "working": 2 to 4 short bullet points on what is genuinely performing
   well (rising trends, strong CTR/position combinations, standout pages).
   Cite the specific numbers from the data.
2. "not_working": 2 to 4 short bullet points on what looks weak (declining
   trends, high impressions with low clicks, pages with no search
   visibility). Cite the specific numbers.
3. "topic_suggestions": 2 to 4 new article topic ideas for Australian
   directors on cyber and AI governance, based on search queries in the
   data that show real demand but are not well served by an existing
   strong page. If the data does not clearly suggest anything, say so
   honestly in a single entry rather than inventing a plausible topic.

Rules:
- Every claim must be traceable to a specific number in the data provided.
- Never use em dashes or en dashes. Use commas or full stops instead.
- Keep each bullet to one sentence.
- Return ONLY a JSON object with keys "working", "not_working", and
  "topic_suggestions", each an array of strings. No markdown fences, no
  preamble, nothing before or after the object."""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=_json.dumps({
            "model": "claude-sonnet-5",
            "max_tokens": 2500,
            "messages": [{"role": "user", "content": prompt}]
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
            raw = _anthropic_text(data).strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return _json.loads(raw)
    except Exception as e:
        print(f"  Report commentary generation failed: {e}", file=sys.stderr)
        return {}


def fetch_briefing_performance(property_id: str) -> list[dict]:
    """Fetch per-briefing GA4 performance for the last 7 days and a longer
    'to date' window (365 days, a practical proxy for since-inception given
    the site's age and GA4's typical data retention), merged by page path.
    Restricted to /post/ pages via a dimension filter so this returns every
    briefing, not just the top few by session volume."""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Dimension, Metric, OrderBy,
        FilterExpression, Filter
    )
    from google.oauth2 import service_account
    import os, json as _json

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not creds_json or not property_id:
        return []
    creds = service_account.Credentials.from_service_account_info(_json.loads(creds_json))
    client = BetaAnalyticsDataClient(credentials=creds)

    post_filter = FilterExpression(
        filter=Filter(
            field_name="landingPage",
            string_filter=Filter.StringFilter(
                value="/post/", match_type=Filter.StringFilter.MatchType.CONTAINS
            ),
        )
    )

    def run(date_range):
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name="landingPage")],
            metrics=[Metric(name="sessions"), Metric(name="activeUsers"), Metric(name="bounceRate")],
            date_ranges=[date_range],
            dimension_filter=post_filter,
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=100,
        )
        response = client.run_report(request)
        return {
            row.dimension_values[0].value: {
                "sessions": int(row.metric_values[0].value),
                "activeUsers": int(row.metric_values[1].value),
                "bounceRate": round(float(row.metric_values[2].value), 3),
            }
            for row in response.rows
        }

    week = run(DateRange(start_date="7daysAgo", end_date="yesterday"))
    to_date = run(DateRange(start_date="365daysAgo", end_date="yesterday"))

    all_pages = set(week.keys()) | set(to_date.keys())
    merged = []
    for page in all_pages:
        w = week.get(page, {"sessions": 0, "activeUsers": 0, "bounceRate": 0})
        t = to_date.get(page, {"sessions": 0, "activeUsers": 0})
        merged.append({
            "page": page,
            "week_sessions": w["sessions"],
            "week_users": w["activeUsers"],
            "week_bounce": w["bounceRate"],
            "to_date_sessions": t.get("sessions", 0),
            "to_date_users": t.get("activeUsers", 0),
        })
    merged.sort(key=lambda r: r["to_date_sessions"], reverse=True)
    return merged


def generate_briefing_commentary(briefings: list[dict]) -> dict:
    """Ask the Anthropic API for a short, grounded one-line note per
    briefing, based only on that briefing's own week-vs-to-date numbers.
    Returns a dict mapping page path to a one-sentence note, or {} on
    failure so the table still renders without commentary."""
    import urllib.request, json as _json, os

    if not briefings:
        return {}

    prompt = f"""Here is per-briefing performance data for aradvice.com.au (JSON):
{_json.dumps(briefings)}

For each briefing (identified by its "page" path), write ONE short sentence
of commentary based only on the numbers given for that specific briefing,
comparing its week_sessions/week_users against its to_date_sessions/
to_date_users and week_bounce. Note whether it looks like a strong, weak,
new, or declining performer relative to its own history. Do not compare
across different briefings and do not invent context not present in the
numbers given.

Return ONLY a JSON object mapping each "page" value to its one-sentence
commentary string. No markdown fences, no preamble, nothing else."""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=_json.dumps({
            "model": "claude-sonnet-5",
            "max_tokens": 3000,
            "messages": [{"role": "user", "content": prompt}]
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
            raw = _anthropic_text(data)
            raw = raw.replace("```json", "").replace("```", "").strip()
            return _json.loads(raw)
    except Exception as e:
        print(f"  Briefing commentary generation failed: {e}", file=sys.stderr)
        return {}


def render_briefing_table(briefings: list[dict], commentary: dict) -> str:
    """Render the per-briefing week-vs-to-date performance table."""
    if not briefings:
        return "<p style='color:#94a3b8;'>No briefing data available.</p>"
    rows = ""
    for b in briefings:
        note = commentary.get(b["page"], "")
        rows += (
            "<tr>"
            f"<td>{escape(b['page'])}</td>"
            f"<td>{b['week_sessions']}</td>"
            f"<td>{b['week_users']}</td>"
            f"<td>{b['to_date_sessions']}</td>"
            f"<td>{b['to_date_users']}</td>"
            f"<td>{escape(note)}</td>"
            "</tr>"
        )
    return (
        '<table class="report-table"><thead><tr>'
        '<th>Briefing</th><th>Sessions (7d)</th><th>Users (7d)</th>'
        '<th>Sessions (to date)</th><th>Users (to date)</th><th>Commentary</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
    )


def render_daily_report_html(ga4_data: dict, gsc_data: dict, commentary: dict, briefing_performance: list[dict] = None, briefing_commentary: dict = None) -> str:
    """Render the hidden daily report as a standalone static HTML page."""
    import json as _json
    generated_at = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    def render_bullets(items):
        if not items:
            return "<p style='color:#94a3b8;'>No commentary available.</p>"
        return "<ul style='margin:0; padding-left:20px; color:#cbd5e1;'>" + "".join(
            f"<li style='margin-bottom:6px;'>{escape(str(i))}</li>" for i in items
        ) + "</ul>"

    working_html = render_bullets(commentary.get("working", []))
    not_working_html = render_bullets(commentary.get("not_working", []))
    topics_html = render_bullets(commentary.get("topic_suggestions", []))
    ga4_trend_json = _json.dumps(ga4_data.get("trend", []))
    gsc_trend_json = _json.dumps(gsc_data.get("trend", []))

    def render_table(rows, columns):
        if not rows:
            return "<p style='color:#94a3b8;'>No data available.</p>"
        head = "".join(f"<th>{c}</th>" for c in columns)
        body = "".join(
            "<tr>" + "".join(f"<td>{escape(str(r.get(c, '')))}</td>" for c in columns) + "</tr>"
            for r in rows
        )
        return f'<table class="report-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'

    all_pages = ga4_data.get("top_pages", [])
    top_briefings = [p for p in all_pages if p.get("page", "").startswith("/post/")][:10]
    top_site_pages = [p for p in all_pages if not p.get("page", "").startswith("/post/")][:10]

    top_site_pages_table = render_table(top_site_pages, ["page", "sessions", "activeUsers", "bounceRate"])
    top_briefings_table = render_table(top_briefings, ["page", "sessions", "activeUsers", "bounceRate"])
    top_queries_table = render_table(gsc_data.get("top_queries", []), ["query", "clicks", "impressions", "position"])

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8" />
<meta name="robots" content="noindex, nofollow" />
<title>Daily Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  body {{ background:#050c1c; color:#e2e8f0; font-family:-apple-system,sans-serif; padding:32px; }}
  h1 {{ font-size:20px; }}
  h2 {{ font-size:15px; margin-top:32px; color:#00d4ff; }}
  .meta {{ color:#64748b; font-size:12px; margin-bottom:24px; }}
  .report-table {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }}
  .report-table th {{ text-align:left; color:#94a3b8; border-bottom:1px solid #24304f; padding:6px 10px; }}
  .report-table td {{ padding:6px 10px; border-bottom:1px solid #172136; }}
  canvas {{ max-width:100%; background:#0b1730; border-radius:12px; padding:16px; }}
</style>
</head><body>
<h1>Daily Site Report</h1>
<p class="meta">Generated {generated_at}. Not linked anywhere on the site.</p>
<h2>What's working</h2>
{working_html}
<h2>What's not working</h2>
{not_working_html}
<h2>Suggested new topics</h2>
{topics_html}
<h2>Sessions &amp; users, last 30 days (GA4)</h2>
<canvas id="ga4Chart" height="90"></canvas>
<h2>Clicks &amp; impressions, last 30 days (Search Console)</h2>
<canvas id="gscChart" height="90"></canvas>
<h2>Most popular pages, last 7 days</h2>
{top_site_pages_table}
<h2>Most popular briefings, last 7 days</h2>
{top_briefings_table}
<h2>Briefing performance, this week vs to date</h2>
{render_briefing_table(briefing_performance or [], briefing_commentary or {})}
<h2>Top search queries, last 30 days</h2>
{top_queries_table}
<script>
const ga4Trend = {ga4_trend_json};
const gscTrend = {gsc_trend_json};
new Chart(document.getElementById('ga4Chart'), {{
  type: 'line',
  data: {{ labels: ga4Trend.map(d => d.date), datasets: [
    {{ label: 'Sessions', data: ga4Trend.map(d => d.sessions), borderColor: '#00d4ff', tension: 0.3 }},
    {{ label: 'Active users', data: ga4Trend.map(d => d.activeUsers), borderColor: '#22c55e', tension: 0.3 }}
  ]}},
  options: {{ plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }},
    scales: {{ x: {{ ticks: {{ color: '#94a3b8' }} }}, y: {{ ticks: {{ color: '#94a3b8' }} }} }} }}
}});
new Chart(document.getElementById('gscChart'), {{
  type: 'line',
  data: {{ labels: gscTrend.map(d => d.date), datasets: [
    {{ label: 'Clicks', data: gscTrend.map(d => d.clicks), borderColor: '#facc15', tension: 0.3 }},
    {{ label: 'Impressions', data: gscTrend.map(d => d.impressions), borderColor: '#a78bfa', tension: 0.3, yAxisID: 'y1' }}
  ]}},
  options: {{ plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }},
    scales: {{ x: {{ ticks: {{ color: '#94a3b8' }} }}, y: {{ ticks: {{ color: '#94a3b8' }} }},
      y1: {{ position: 'right', ticks: {{ color: '#94a3b8' }}, grid: {{ drawOnChartArea: false }} }} }} }}
}});
</script>
</body></html>"""


def generate_daily_report() -> None:
    """Generate the hidden daily analytics report. Fails silently with a
    stderr note if Google credentials are not configured, so a normal
    sync never breaks because of this."""
    import os
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        print("  GOOGLE_SERVICE_ACCOUNT_JSON not set — skipping daily report", file=sys.stderr)
        return
    try:
        ga4_data = fetch_ga4_report(property_id=os.environ.get("GA4_PROPERTY_ID", ""))
        gsc_data = fetch_gsc_report(site_url=os.environ.get("GSC_SITE_URL", "sc-domain:aradvice.com.au"))
        commentary = generate_report_commentary(ga4_data, gsc_data)
        briefing_performance = fetch_briefing_performance(property_id=os.environ.get("GA4_PROPERTY_ID", ""))
        briefing_commentary = generate_briefing_commentary(briefing_performance)
        html = render_daily_report_html(ga4_data, gsc_data, commentary, briefing_performance, briefing_commentary)
        report_dir = ROOT / "internal-8f2k1q"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "daily-report.html").write_text(html, encoding="utf-8")
        print("  Daily report generated: internal-8f2k1q/daily-report.html")
        print("  --- Daily Report Highlights ---")
        for bullet in commentary.get("working", []):
            print(f"    [working] {bullet}")
        for bullet in commentary.get("not_working", []):
            print(f"    [not working] {bullet}")
        for bullet in commentary.get("topic_suggestions", []):
            print(f"    [topic idea] {bullet}")
        print(f"  Full report: {MAIN_DOMAIN}/internal-8f2k1q/daily-report.html")
    except Exception as e:
        print(f"  Daily report generation failed: {e}", file=sys.stderr)


def guess_category(title: str, slug: str) -> str:
    """Best-effort keyword match against title/slug. Falls back to the
    cyber-governance default if nothing matches. Always returns a valid
    category key from CATEGORY_LABELS."""
    haystack = f" {title.lower()} {slug.lower().replace('-', ' ')} "
    for category, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in haystack:
                return category
    return _DEFAULT_CATEGORY


def select_related_posts(
    current_slug: str,
    current_category: str,
    items: list[FeedItem],
    categories: dict,
    limit: int = 3,
) -> list[FeedItem]:
    """Pick up to `limit` posts sharing the current post's category. Falls
    back to filling remaining slots with other recent posts if there are
    fewer than `limit` category matches. `items` should already be sorted
    newest-first (as generated_items and visible_items are in main())."""
    others = [i for i in items if i.slug != current_slug]
    same_category = [
        i for i in others
        if categories.get(i.slug, _DEFAULT_CATEGORY) == current_category
    ]
    picked = same_category[:limit]
    if len(picked) < limit:
        picked_slugs = {i.slug for i in picked}
        fallback = [i for i in others if i.slug not in picked_slugs]
        picked.extend(fallback[: limit - len(picked)])
    return picked


def render_related_briefings(
    current_item: FeedItem,
    items: list[FeedItem],
    categories: dict,
    registry: dict,
) -> str:
    """Render a 'Related briefings' card grid for insertion just above the
    CTA block on an individual post page. Returns '' if no related posts
    are available (e.g. this is the only post)."""
    current_category = categories.get(current_item.slug, _DEFAULT_CATEGORY)
    related = select_related_posts(current_item.slug, current_category, items, categories)
    if not related:
        return ""
    cards = []
    for rel in related:
        cat_key = categories.get(rel.slug, _DEFAULT_CATEGORY)
        cat_label = escape(CATEGORY_LABELS.get(cat_key, cat_key))
        post_id = registry.get(rel.slug, 0)
        cards.append(
            f'<a href="/post/{escape(rel.slug)}/" style="text-decoration:none; display:block; '
            'background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:16px 20px;">'
            f'<span style="font-size:12px; color:#0f6e56; background:#e1f5ee; '
            f'padding:2px 8px; border-radius:6px;">{cat_label}</span>'
            f'<p style="font-size:14px; font-weight:600; color:#0f172a; '
            f'margin:10px 0 6px; line-height:1.4;">{escape(rel.title)}</p>'
            f'<p style="font-size:12px; color:#94a3b8; margin:0;">Briefing No. {post_id:03d}</p>'
            '</a>'
        )
    return (
        '<div style="border-top:1px solid #e2e8f0; padding-top:24px; margin:32px 0;">'
        '<h3 style="font-size:18px; font-weight:600; margin:0 0 16px 0;">Related briefings</h3>'
        '<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px;">'
        + "".join(cards)
        + "</div></div>"
    )


def assign_post_categories(items: list[FeedItem]) -> dict:
    """Ensure every item has a category in post-categories.json, guessing for
    any new slugs. Never overwrites an existing (possibly manually corrected)
    category. Returns the full slug -> category map."""
    categories = load_post_categories()
    changed = False
    for item in items:
        if item.slug not in categories:
            categories[item.slug] = guess_category(item.title, item.slug)
            changed = True
    if changed:
        save_post_categories(categories)
    return categories


def assign_post_ids(items: list[FeedItem]) -> dict:
    """Assign sequential IDs to posts by publish date. IDs never change once assigned."""
    registry = load_post_registry()

    # Sort by publish date oldest first for ID assignment
    sorted_items = sorted(items, key=lambda i: item_datetime(i.pub_date))

    # Find highest existing ID — skip non-integer values from manual edits
    valid_ids = []
    for v in registry.values():
        try:
            valid_ids.append(int(v))
        except (TypeError, ValueError):
            print(f"  Warning: non-integer value in post registry: {v!r} — skipping", file=sys.stderr)
    next_id = max(valid_ids, default=0) + 1

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
        lines.append(f"- **LinkedIn draft:** `[internal]/{item.slug}/{id_str}-linkedin.txt`")
        lines.append(f"- **LinkedIn log:** see `log/posting-log.md`")
        lines.append(f"- **Advisor brief:** `[internal]/{item.slug}/{id_str}-advisor-brief.md`")
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

    # Briefing number — top-right, level with brand name
    _br_text = f"BRIEFING NO. {post_id}"
    _br_font = load_font(20)
    _br_bbox = draw.textbbox((0, 0), _br_text, font=_br_font)
    _br_w = _br_bbox[2] - _br_bbox[0]
    draw.text((W - 80 - _br_w, 62), _br_text, font=_br_font, fill=CYAN)

    # Article title — max 3 lines
    wrapped = textwrap.wrap(item.title, width=34)[:3]
    ty = 175
    for line in wrapped:
        draw.text((80, ty), line, font=load_font(64), fill=WHITE)
        ty += 78

    # Post date — parsed from RFC 2822 pub_date string
    if item.pub_date:
        try:
            dt = item_datetime(item.pub_date)
            date_str = f"{dt.day} {dt.strftime('%B %Y')}"
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


def extract_article_text(html: str, limit: int) -> str:
    """Extract readable article body text from fetched HTML for AI prompts.
    Prefers the article-content div, falls back to <article>, then <body>."""
    source = html
    for pattern in (
        r'<div[^>]*class=["\'][^"\']*article-content[^"\']*["\'][^>]*>(.*?)</article>',
        r"<article\b[^>]*>(.*?)</article>",
        r"<body\b[^>]*>(.*?)</body>",
    ):
        m = re.search(pattern, html, flags=re.DOTALL | re.IGNORECASE)
        if m:
            source = m.group(1)
            break
    source = re.sub(r"<script\b.*?</script>", "", source, flags=re.DOTALL | re.IGNORECASE)
    source = re.sub(r"<style\b.*?</style>", "", source, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", source)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def sanitise_ai_text(text: str) -> str:
    """Remove em/en dashes and tidy spacing in AI-generated copy."""
    text = text.replace("—", ", ").replace(" – ", ", ")
    text = text.replace(", ,", ",").replace(",,", ",").replace(" ,", ",")
    return re.sub(r" {2,}", " ", text)


def utm_url(post_url: str, source: str, slug: str) -> str:
    """Append UTM campaign parameters to a post URL. Campaign is the post
    slug (already lowercase) so each post is tracked individually. Source is
    the channel ('kit' or 'linkedin'); medium is derived from it."""
    medium = "email" if source == "kit" else "social"
    sep = "&" if "?" in post_url else "?"
    return (
        f"{post_url}{sep}utm_source={source}"
        f"&utm_medium={medium}"
        f"&utm_campaign={slug}"
    )


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

    plain_text = extract_article_text(item.html, 1500)

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
- Never present an invented scenario as a real event. Banned framings include "Last month", "Recently", "This week", or any phrasing implying the event actually occurred. Invented dialogue must be framed as illustrative ("Picture the question...", "Consider a chair who is asked...") never as a reported exchange.

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

HARD RULES:
- The opening must express the same core argument as the article title, in different words. A reader who clicks through must find exactly what the opening promised.
- Never use em dashes or en dashes anywhere. Restructure the sentence or use a comma or full stop instead.
- No exclamation marks.
- Never state a commencement date, deadline, or penalty figure for any legislation.
- Do not describe any legislation or obligation as upcoming, pending, approaching, or "moving toward" enforcement. The Cyber Security Act 2024 and its obligations are current law; refer to them in the present tense as in force, never as future or impending.

FORMAT:
- 6 to 10 lines. No padding. No wasted sentences.
- No hashtags, bullet points, or emojis.
- End with the article URL on its own line, nothing after it.
- Output only the post text. No preamble, no explanation, no title."""

    payload = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 2500,
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
            return sanitise_ai_text(_anthropic_text(data).strip())
    except Exception as e:
        return f"[LinkedIn post generation failed: {e}]"


def generate_email_draft(item: FeedItem, post_url: str) -> tuple[str, str]:
    """Generate a plain-text email subject and body for a new article using the Anthropic API.
    Returns (subject, body)."""
    import urllib.request, json, os

    plain_text = extract_article_text(item.html, 1500)

    prompt = f"""You are writing a brief email to Australian company directors who have subscribed to receive governance briefings from Andrew Roberts Advisory (aradvice.com.au).

Article title: {item.title}
Article URL: {post_url}
Article excerpt: {plain_text}

Write a plain-text email with two parts:

SUBJECT: A direct, specific subject line under 60 characters. Lead with the governance issue, not "New article" or "New briefing". Example format: "Cyber Security Act 2024: Your board obligations" or "APRA CPS 234: What directors must do".

BODY: 3-4 sentences maximum. No salutation — open cold with the first substantive sentence.

- Sentence 1: Describe a specific situation — a boardroom moment, a procurement decision, a model deployed without sign-off, a board paper that couldn't answer the regulator's question. Frame it as explicitly illustrative or composite, never as a real event that occurred. Use present-tense hypothetical framing such as "Picture a board that..." or "Imagine a director who...". Do not use "recently", "last month", "this week", or past-tense narration that implies the scene actually happened. Concrete and particular, but unmistakably illustrative. Do NOT open with generalisations about "most boards" or "directors must" or "your board faces". Do not state a problem abstractly — place the reader in a scene.
- Sentences 2-3: Name the concrete consequence if this is wrong. Regulatory, legal, or reputational — be specific about what actually happens to the director. Not "shifts the conversation", not "transforms risk into responsibility", not "manageable oversight protocols". What is the actual exposure? Name the realistic enforcer: for an s.180 duty-of-care breach that is ASIC bringing civil penalty proceedings against the director personally; a liquidator may also pursue the claim on the company's behalf if the entity later fails. Do not say a shareholder can pursue a director "personally" under s.180, that requires court leave for a derivative action brought in the company's name. State the exposure directly. Only reference specific regulatory actions or enforcement if they appear verbatim in the article excerpt — otherwise name the legal mechanism (e.g. s.180 Corporations Act duty of care) and the personal consequence.
- Final line: The article URL on its own line, nothing else before or after it — no "Read more at", no "Full article:", just the bare URL.
- Sign off: "Andrew"

Rules:
- The subject line must express the same core argument as the article title, in different words. A reader who clicks through must find exactly what the subject promised.
- No salutation of any kind — no "Hi", no "Dear", no "Hello"
- No "I hope this finds you well" or similar openers
- No exclamation marks
- Never use em dashes or en dashes anywhere. Restructure the sentence or use a comma or full stop instead.
- Never state a commencement date, deadline, or penalty figure for any legislation.
- Do not describe any legislation or obligation as upcoming, pending, approaching, or "moving toward" enforcement. The Cyber Security Act 2024 and its obligations are current law; refer to them in the present tense as in force, never as future or impending.
- The opening scenario must be causally coherent. Read it back as a literal sequence of events and confirm it makes sense.
- Banned phrases — never use these: "most boards lack", "your board faces", "directors must", "shifts the conversation", "transforms X into Y", "manageable oversight protocols", "structured board responsibility", "defensible processes for overseeing", "the regulatory environment", "growing exposure", "practical frameworks", "courts are increasingly", "regulators are increasingly", "ASIC is increasingly", "increasingly scrutinising", "increasingly important"
- Do not mention "newsletter", "blog post", or "article" — write as if delivering a direct observation, not promoting content
- Under 110 words total for the body
- Tone: the same register as a brief note from a trusted advisor who has just seen something relevant — not a marketing email, not a warning, not a sales pitch
- CRITICAL: Do not reference specific regulatory requirements, deadlines, or enforcement actions unless they appear verbatim in the article excerpt provided. If unsure, omit the regulatory reference entirely and focus on the director's personal legal exposure instead.

Return a JSON object with exactly two keys:
"subject": the subject line
"body": the full email body

Return only the JSON. No preamble, no markdown fences."""

    payload = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 2000,
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
            raw = _anthropic_text(data).strip()
            parsed = json.loads(raw)
            return (sanitise_ai_text(parsed.get("subject", "")),
                    sanitise_ai_text(parsed.get("body", "")))
    except Exception as e:
        print(f"  generate_email_draft failed for {item.slug}: {e}",
              file=sys.stderr)
        return "", ""


def send_kit_broadcast(subject: str, body: str, briefing_no: int = 0,
                       test_email: str = "") -> bool:
    """Send a broadcast email via the Kit (ConvertKit) API v4.
    Returns True on success."""
    import urllib.request, json, os
    from datetime import datetime, timezone

    api_key = os.environ.get("KIT_API_KEY", "")
    if not api_key:
        print("  KIT_API_KEY not set — skipping broadcast",
              file=sys.stderr)
        return False

    # Guard: never send more than one subscriber broadcast per calendar day.
    # Skipped entirely for test sends — they never touch the real subscriber
    # list and must not block or consume the day's live send.
    if not test_email:
        guard_path = ROOT / "log" / "last-broadcast-date.txt"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if guard_path.exists() and guard_path.read_text(encoding="utf-8").strip() == today:
            print(f"  Broadcast guard: already sent today — BLOCKED: {subject}",
                  file=sys.stderr)
            return False
        guard_path.parent.mkdir(parents=True, exist_ok=True)
        guard_path.write_text(today, encoding="utf-8")

    # Convert plain text body to HTML for Kit.
    # - Strips the redundant subscribe disclaimer line (now covered by the
    #   styled template footer).
    # - Renders the article URL as a styled button-style link instead of
    #   plain text.
    lines = [p.strip() for p in body.split("\n") if p.strip()]

    disclaimer = "You're receiving this because you subscribed at aradvice.com.au."
    lines = [l for l in lines if l != disclaimer]

    url_pattern = re.compile(r'^https?://\S+$')
    html_parts = []
    for line in lines:
        if url_pattern.match(line):
            html_parts.append(
                '<p style="margin:20px 0 24px 0;">'
                f'<a href="{line}" style="display:inline-block; '
                'font-family:Arial, Helvetica, sans-serif; font-size:14px; '
                'font-weight:bold; color:#0a1628; text-decoration:none; '
                'border-bottom:2px solid #00d4e8; padding-bottom:2px;">'
                'Read the full briefing &rarr;</a></p>'
            )
        else:
            html_parts.append(f"<p>{line}</p>")
    html_body = "".join(html_parts)

    # Prepend the briefing number as a styled label, matching the Kit
    # email template's header typography (deterministic, not AI-generated)
    if briefing_no:
        briefing_label = (
            '<p style="font-size:11px; color:#888888; letter-spacing:0.06em; '
            'text-transform:uppercase; margin:0 0 8px 0;">'
            f'Briefing No. {briefing_no}</p>'
        )
        html_body = briefing_label + html_body

    # Kit v4: flat payload, send_at set to now triggers immediate send
    send_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if test_email:
        subject = f"[TEST] {subject}"
        subscriber_filter = [{"email_address": test_email}]
    else:
        subscriber_filter = [{"all": True}]
    payload = json.dumps({
        "subject": subject,
        "content": html_body,
        "description": subject,
        "public": False,
        "send_at": send_at,
        "preview_text": "",
        "subscriber_filter": subscriber_filter,
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
            broadcast_id = data.get("broadcast", {}).get("id") or data.get("id", "")
            print(f"  Email broadcast sent: {subject} (id={broadcast_id})")
            return True
    except Exception as e:
        print(f"  Kit broadcast failed: {e}", file=sys.stderr)
        return False


def load_email_log() -> set:
    """Return set of slugs already emailed.
    Entries with status 'failed' are excluded so blocked or failed
    sends retry on a later run."""
    log_path = ROOT / "log" / "email-log.md"
    if not log_path.exists():
        return set()
    slugs = set()
    current = ""
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- slug:"):
            current = line.replace("- slug:", "").strip()
        elif line.startswith("- status:"):
            status = line.replace("- status:", "").strip()
            if current and status != "failed":
                slugs.add(current)
            current = ""
    return slugs


def update_email_log(item: FeedItem, subject: str,
                     status: str) -> None:
    """Append an entry to the email log."""
    log_path = ROOT / "log" / "email-log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    existing = log_path.read_text(
        encoding="utf-8") if log_path.exists() else ""
    if not existing:
        existing = "# Email Broadcast Log\n\n"
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
                      dry_run: bool = False,
                      force: bool = False,
                      test_email: str = "") -> None:
    """Generate email draft, save to disk, and send via Kit unless already sent or dry_run."""
    emailed = load_email_log()
    if item.slug in emailed and not force:
        print(f"  Email: {item.slug} — already sent, skipped")
        return

    article_dir = INTERNAL_DRAFTS_ROOT / item.slug
    article_dir.mkdir(parents=True, exist_ok=True)
    draft_path = article_dir / f"{post_id}-email.txt"

    tagged_url = utm_url(post_url, "kit", item.slug)
    subject, body = generate_email_draft(item, tagged_url)
    if not subject or not body:
        return

    try:
        brief_no = int(post_id)
    except (TypeError, ValueError):
        brief_no = 0

    # Always save the draft to disk
    draft_path.write_text(
        f"SUBJECT: {subject}\n\n{body}",
        encoding="utf-8"
    )
    print(f"  Email draft saved: {draft_path.name}")

    if dry_run:
        print(f"  [DRY RUN] Would send: {subject}")
        update_email_log(item, subject, status="dry-run")
        return

    # Test sends never touch the email log — they must be repeatable and
    # must not mark the article as "already emailed" for the real send.
    if not test_email:
        # Log before sending — prevents duplicate sends if log write fails after
        update_email_log(item, subject, status="sending")

    # Split body into one sentence per line so send_kit_broadcast
    # wraps each sentence in its own <p> tag.
    def split_sentences(text: str) -> str:
        lines = text.splitlines()
        result = []
        for line in lines:
            line = line.strip()
            if not line:
                result.append("")
                continue
            sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', line)
            result.extend(s.strip() for s in sentences if s.strip())
        return "\n".join(result)

    broadcast_body = split_sentences(body)
    sent = send_kit_broadcast(subject, broadcast_body, briefing_no=brief_no,
                              test_email=test_email)

    # Patch status in log now we know the outcome. Skipped for test sends,
    # since they never wrote a "sending" entry above.
    if not test_email:
        log_path = ROOT / "log" / "email-log.md"
        log_text = log_path.read_text(encoding="utf-8")
        final_status = "sent" if sent else "failed"
        log_text = re.sub(
            rf'(- slug: {re.escape(item.slug)}\n(?:.*\n)*?- status:) sending',
            rf'\1 {final_status}',
            log_text,
        )
        log_path.write_text(log_text, encoding="utf-8")


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


def write_linkedin_draft(item: FeedItem, post_url: str, post_id: str = "000",
                         force: bool = False) -> None:
    """Write a LinkedIn draft to INTERNAL_DRAFTS_ROOT/{slug}/{post_id}-linkedin.txt
    if it doesn't already exist. Never write this to the public post/ folder —
    GitHub Pages publishes everything there. force=True regenerates and
    overwrites the existing draft file."""
    article_dir = INTERNAL_DRAFTS_ROOT / item.slug
    article_dir.mkdir(parents=True, exist_ok=True)
    draft_path = article_dir / f"{post_id}-linkedin.txt"
    if draft_path.exists() and not force:
        print(f"  LinkedIn: {item.slug} — draft exists, skipped")
        return
    print(f"  Generating LinkedIn draft for: {item.slug}")
    tagged_url = utm_url(post_url, "linkedin", item.slug)
    post_text = generate_linkedin_post(item, tagged_url)
    if post_text.startswith("[LinkedIn post generation failed"):
        print(f"  LinkedIn draft generation failed for {item.slug} — skipping write.", file=sys.stderr)
        return
    draft_path.write_text(post_text, encoding="utf-8")
    if force:
        print(f"\n  [TEST] Regenerated LinkedIn draft for {item.slug}")
        print(post_text)
        print()
    update_linkedin_log(item, draft_path, post_id=post_id)


def generate_advisor_brief(item: FeedItem, post_url: str, override_html: str | None = None) -> str:
    """Generate an internal advisor briefing doc for a feed item using the Anthropic API."""
    import urllib.request
    import json

    plain_text = extract_article_text(override_html if override_html else item.html, 4000)

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

Hard rules: never use em dashes or en dashes. Never state a commencement date, deadline, or penalty figure for any legislation unless it appears verbatim in the article content.

Output only the briefing. No preamble, no explanation."""

    payload = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 3500,
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
            return sanitise_ai_text(_anthropic_text(data).strip())
    except Exception as e:
        return f"[Advisor brief generation failed: {e}]"


def generate_post_meta(item: FeedItem) -> tuple[str, str]:
    """Generate a click-optimised meta description and post-specific keywords
    for a blog post using the Anthropic API.
    Returns (description, keywords_csv) — both as plain strings."""
    import urllib.request, json, os

    plain_text = extract_article_text(item.html, 1500)

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
  Never use em dashes or en dashes. Never state a commencement date or deadline.
- "keywords": A comma-separated list of 6–8 specific keywords for this post
  only. Use terms a director would actually search for. Include relevant
  regulation names (e.g. APRA CPS 234, Cyber Security Act 2024, ASIC s180)
  where topically relevant. Do not include generic site-wide terms like
  "board advisory" or "Australian boards" — those are already on the homepage.

Return only the JSON object. No preamble, no markdown fences."""

    payload = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 1800,
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
            raw = _anthropic_text(data).strip()
            parsed = json.loads(raw)
            return sanitise_ai_text(parsed.get("description", "")), parsed.get("keywords", "")
    except Exception as e:
        print(f"  generate_post_meta failed for {item.slug}: {e}", file=sys.stderr)
        return "", ""


def generate_article_schema(item: FeedItem, post_url: str, post_id: str = "000") -> str:
    """Generate JSON-LD Article schema for a blog post."""
    published = item_datetime(item.pub_date).isoformat()
    escaped_title = escape(item.title)
    return (
        '<script type="application/ld+json">\n'
        '{\n'
        '  "@context": "https://schema.org",\n'
        '  "@type": "Article",\n'
        f'  "headline": "{escaped_title}",\n'
        f'  "identifier": "Briefing No. {post_id}",\n'
        f'  "url": "{post_url}",\n'
        f'  "datePublished": "{published}",\n'
        f'  "mainEntityOfPage": "{post_url}",\n'
        '  "inLanguage": "en-AU",\n'
        '  "author": {\n'
        '    "@type": "Person",\n'
        '    "name": "Andrew Roberts",\n'
        '    "url": "https://aradvice.com.au/about.html",\n'
        '    "jobTitle": "Independent Board Advisor, Cyber & AI Governance",\n'
        '    "sameAs": ["https://www.linkedin.com/in/andrewjakeroberts/"]\n'
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


def write_advisor_brief(item: FeedItem, post_url: str, post_id: str = "000", force: bool = False) -> None:
    """Write an internal advisor briefing doc to /post/{slug}/{post_id}-advisor-brief.md if it doesn't already exist."""
    article_dir = INTERNAL_DRAFTS_ROOT / item.slug
    article_dir.mkdir(parents=True, exist_ok=True)
    brief_path = article_dir / f"{post_id}-advisor-brief.md"
    if brief_path.exists() and not force:
        print(f"  Brief: {item.slug} — exists, skipped")
        return
    print(f"  Generating advisor brief for: {item.slug}")

    # Prefer the already-published local file over item.html, which is
    # populated by fetching the post's own live URL — fragile if the page
    # hadn't finished deploying, was serving a stale cache, or the fetch
    # hit a transient error. The local file, once it exists, is the
    # authoritative, guaranteed-complete copy.
    override_html = None
    local_path = article_page_path(item.slug)
    if local_path.exists():
        override_html = local_path.read_text(encoding="utf-8")

    source_for_check = override_html if override_html else item.html
    if len(extract_article_text(source_for_check, 4000)) < 200:
        print(f"  Advisor brief: {item.slug} — article content too thin or unavailable, skipping rather than writing a low-quality brief", file=sys.stderr)
        return

    brief_text = generate_advisor_brief(item, post_url, override_html=override_html)
    if brief_text.startswith("[Advisor brief generation failed"):
        print(f"  Advisor brief generation failed for {item.slug} — skipping write.", file=sys.stderr)
        return
    published = item_datetime(item.pub_date).strftime("%d %b %Y")
    header = (
        f"# Advisor Brief — {item.title}\n\n"
        f"**Article:** {post_url}  \n"
        f"**Published:** {published}  \n"
        f"**Generated:** {datetime.now(timezone.utc).strftime('%d %b %Y')}  \n\n"
        "---\n\n"
    )
    brief_path.write_text(header + brief_text, encoding="utf-8")


class _Tee:
    """Duplicate a stream into a buffer so run output can be emailed."""
    def __init__(self, stream, buffer):
        self.stream = stream
        self.buffer = buffer
    def write(self, data):
        self.stream.write(data)
        self.buffer.write(data)
        return len(data)
    def flush(self):
        self.stream.flush()


def render_run_report_email_html(body: str) -> str:
    """Turn the plain-text captured console output into readable HTML:
    the '--- Daily Report Highlights ---' block (if present) is rendered
    as proper headed, colour-coded bullet lists; everything else (the
    routine sync log) stays as a smaller monospace block underneath."""
    marker = "--- Daily Report Highlights ---"
    if marker in body:
        before, rest = body.split(marker, 1)
        # The highlights block runs until the next line that doesn't start
        # with one of the bullet prefixes or leading whitespace continuing
        # a wrapped bullet — in practice, until "Full report:" or end of text.
        if "Full report:" in rest:
            highlights_block, after = rest.split("Full report:", 1)
            after = "Full report:" + after
        else:
            highlights_block, after = rest, ""
    else:
        before, highlights_block, after = body, "", ""

    def section(items, color, label):
        if not items:
            return ""
        lis = "".join(f'<li style="margin-bottom:8px;">{escape(i.strip())}</li>' for i in items)
        return (
            f'<p style="color:{color}; font-weight:700; text-transform:uppercase; '
            f'font-size:12px; letter-spacing:0.05em; margin:20px 0 8px 0;">{label}</p>'
            f'<ul style="margin:0; padding-left:20px; color:#1e293b;">{lis}</ul>'
        )

    working, not_working, topics = [], [], []
    for line in highlights_block.splitlines():
        line = line.strip()
        if line.startswith("[working]"):
            working.append(line[len("[working]"):])
        elif line.startswith("[not working]"):
            not_working.append(line[len("[not working]"):])
        elif line.startswith("[topic idea]"):
            topics.append(line[len("[topic idea]"):])

    highlights_html = (
        section(working, "#16a34a", "What's working")
        + section(not_working, "#dc2626", "What's not working")
        + section(topics, "#2563eb", "Suggested new topics")
    )

    log_text = escape(before + after)
    log_html = (
        '<p style="color:#64748b; font-weight:700; text-transform:uppercase; '
        'font-size:11px; letter-spacing:0.05em; margin:28px 0 8px 0;">Sync log</p>'
        f'<pre style="font-family:monospace; font-size:11px; color:#475569; '
        f'white-space:pre-wrap; line-height:1.5;">{log_text}</pre>'
    )

    return highlights_html + log_html


def send_run_report(body: str, status: str) -> None:
    """Email the run transcript to the operator via Kit's API, targeting
    only the subscriber tagged RUN_REPORT_TAG_ID (see .env), never the
    full subscriber list. Kit's Broadcasts API has no way to target a
    single email address directly — subscriber_filter only supports
    segment/tag ids, and silently defaults to ALL subscribers if given
    an unrecognised filter shape. That defaulting previously caused a
    run report to go out to the entire real subscriber list. To guard
    against that happening again: (1) refuse to send at all unless the
    tag id is explicitly configured, (2) create the broadcast as an
    unsent draft first, (3) read the filter Kit actually stored back
    and confirm it matches exactly what was requested before triggering
    the send, aborting (leaving an unsent draft) on any mismatch. Never
    raises."""
    import urllib.request
    import json as _json
    import os

    api_key = os.environ.get("KIT_API_KEY", "")
    tag_id_raw = os.environ.get("RUN_REPORT_TAG_ID", "")
    if not api_key or not tag_id_raw:
        print("  KIT_API_KEY/RUN_REPORT_TAG_ID not set — skipping run report",
              file=sys.stderr)
        return
    try:
        tag_id = int(tag_id_raw)
    except ValueError:
        sys.__stderr__.write(f"  RUN_REPORT_TAG_ID is not a valid integer: {tag_id_raw!r} — skipping run report\n")
        return

    def _kit_request(path: str, body: dict | None, method: str) -> dict:
        req = urllib.request.Request(
            f"https://api.kit.com/v4{path}",
            data=_json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"Content-Type": "application/json", "X-Kit-Api-Key": api_key},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    ts = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    subject = f"sync_blog {status} — {ts}"
    html_body = render_run_report_email_html(body)
    base_payload = {
        "subject": subject,
        "content": html_body,
        "description": subject,
        "public": False,
        "preview_text": "",
        "subscriber_filter": [{"all": [{"type": "tag", "ids": [tag_id]}]}],
    }

    try:
        # Step 1: create as an unsent draft (no send_at).
        created = _kit_request("/broadcasts", {**base_payload, "send_at": None}, "POST")
        broadcast_id = created.get("broadcast", {}).get("id")

        # Step 2: read back what Kit actually stored for subscriber_filter.
        fetched = _kit_request(f"/broadcasts/{broadcast_id}", None, "GET")
        stored_filter = fetched.get("broadcast", {}).get("subscriber_filter")
        stored_tag_ids = set()
        for group in (stored_filter or []):
            for clause in (group.get("all") or []):
                if clause.get("type") == "tag":
                    stored_tag_ids.update(clause.get("ids", []))
        if stored_tag_ids != {tag_id}:
            sys.__stderr__.write(
                f"  Run report ABORTED: Kit stored an unexpected subscriber_filter "
                f"({stored_filter!r}) instead of tag id {tag_id} — leaving broadcast "
                f"{broadcast_id} as an unsent draft rather than risk sending to the "
                f"wrong audience. Check the Kit dashboard.\n"
            )
            return

        # Step 3: filter confirmed correct — trigger the actual send.
        send_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _kit_request(f"/broadcasts/{broadcast_id}", {**base_payload, "send_at": send_at}, "PUT")
        sys.__stdout__.write(f"  Run report sent via Kit (id={broadcast_id}, tag_id={tag_id})\n")
    except Exception as e:
        sys.__stderr__.write(f"  Run report send via Kit failed: {e}\n")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate email drafts without sending"
    )
    parser.add_argument(
        "--test", metavar="SLUG", default="", dest="test_slug",
        help="Force-regenerate the email and LinkedIn drafts for SLUG (never sends, email log untouched, overwrites the LinkedIn draft file)"
    )
    parser.add_argument(
        "--publish-draft", metavar="SLUG", default="", dest="publish_slug",
        help="Publish a hand-authored draft from drafts/SLUG.json through the "
             "full pipeline (ID, category, images, related briefings, LinkedIn "
             "draft, advisor brief), then exit. Follow with a normal sync run "
             "to refresh blog.html and sitemap.xml."
    )
    parser.add_argument(
        "--send-test-to", metavar="EMAIL", default="", dest="test_email",
        help="Send a real test broadcast for --test SLUG to this email address only. "
             "Subject is prefixed [TEST]. Bypasses the daily-send guard and the "
             "email log entirely — safe to run repeatedly without affecting the "
             "real subscriber list or blocking the next live send. Requires --test."
    )
    args = parser.parse_args()
    dry_run = args.dry_run
    test_slug = args.test_slug
    test_email = args.test_email
    if test_email and not test_slug:
        parser.error("--send-test-to requires --test SLUG")
    if test_slug and not test_email:
        dry_run = True

    if args.publish_slug:
        publish_original_post(args.publish_slug)
        return 0

    process_pending_drafts()
    generate_daily_report()

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

    primary_index_ok = bool(feed_items)
    if not primary_index_ok:
        print("No GetAutoSEO feed items found (expected now that GetAutoSEO is "
              "retired). Continuing with locally published posts only.", file=sys.stderr)

    # Merge RSS metadata into index-scraped items
    for item in feed_items:
        slug = item_slug(item["link"], item["title"])
        if slug in rss_by_slug:
            rss = rss_by_slug[slug]
            item["pub_date"] = rss.get("pub_date", "")
            item["description"] = rss.get("description", "")
            if not item["title"]:
                item["title"] = rss.get("title", "")

    if primary_index_ok:
        print(f"  Found {len(feed_items)} articles on blog index "
              f"({len(rss_by_slug)} in RSS feed)")

    # Merge manually-managed posts not in the getautoseo feed.
    # Also register their slugs so the main loop treats them as manual
    # even if the blog index has picked them up independently.
    feed_slugs = {item_slug(i["link"], i["title"])
                  for i in feed_items}
    manual_slug_set = {item_slug(m["link"], m["title"]) for m in MANUAL_POSTS}
    for manual in MANUAL_POSTS:
        s = item_slug(manual["link"], manual["title"])
        if s not in feed_slugs:
            feed_items.append(manual)

    # Also pick up any RSS articles not yet appearing on the blog index page
    # (e.g. newly published posts that the index hasn't refreshed to show yet).
    for rss_slug, rss in rss_by_slug.items():
        if rss_slug not in feed_slugs:
            feed_items.append({
                "link": rss["link"],
                "title": rss["title"],
                "pub_date": rss.get("pub_date", ""),
                "description": rss.get("description", ""),
            })
            print(f"  RSS-only article queued: {rss_slug}")

    generated_items: list[FeedItem] = []
    for raw_item in feed_items:
        slug = item_slug(raw_item["link"], raw_item["title"])
        try:
            article_html = fetch_text(raw_item["link"], "text/html,application/xhtml+xml")
        except Exception as e:
            print(f"  Skipping {raw_item['link']}: fetch failed: {e}", file=sys.stderr)
            continue
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
    # Assign topic categories (auto-guessed for new posts, preserved for existing)
    categories = assign_post_categories(generated_items)

    # Detect posts GetAutoSEO has silently dropped from its own feed since a
    # previous run. These are registered slugs that no longer appear in
    # today's feed at all. The local post/ file and sitemap entry (via the
    # registry fallback in build_sitemap) survive regardless — this check
    # exists purely so Andy is told immediately instead of finding out by
    # accident later.
    if primary_index_ok:
        current_feed_slugs = {item.slug for item in generated_items}
        dropped_slugs = sorted(set(registry.keys()) - current_feed_slugs)
        if dropped_slugs:
            print(
                f"  WARNING: {len(dropped_slugs)} post(s) registered but missing "
                f"from today's GetAutoSEO feed (source may have unpublished them):",
                file=sys.stderr,
            )
            for slug in dropped_slugs:
                print(f"    - {slug} (registry id {registry[slug]})", file=sys.stderr)

    # Only render published articles (exclude future-dated posts from blog/sitemap)
    now = datetime.now(timezone.utc)
    visible_items = [i for i in generated_items if item_datetime(i.pub_date) <= now]

    manual_slugs = manual_slug_set

    for i, item in enumerate(generated_items):
        page_path = article_page_path(item.slug)
        post_url = f"{MAIN_DOMAIN}/post/{item.slug}/"
        post_id = f"{registry.get(item.slug, 0):03d}"

        # Skip full HTML regeneration for manually-managed posts,
        # but still run content cleaning and link normalisation on the existing file.
        # If the local file is missing, fall through to full write_page() processing.
        if item.slug in manual_slugs:
            if page_path.exists():
                fixed = page_path.read_text(encoding="utf-8")
                fixed = normalize_internal_links(
                    clean_article_content(
                        strip_platform_widgets(
                            rewrite_domains(fixed)
                        )
                    )
                )
                page_path.write_text(fixed, encoding="utf-8")
                write_linkedin_draft(item, post_url, post_id=post_id,
                                     force=(item.slug == test_slug))
                write_advisor_brief(item, post_url, post_id=post_id, force=(item.slug == test_slug))
                if item_datetime(item.pub_date) <= now:
                    write_email_draft(item, post_url, post_id=post_id, dry_run=dry_run,
                                      force=(item.slug == test_slug),
                                      test_email=(test_email if item.slug == test_slug else ""))
                continue
            # File deleted — rebuild via full pipeline using fetched HTML

        other_items = [i for i in visible_items if i.slug != item.slug]
        page_html = inject_more_articles(item.html, other_items, categories=categories)
        related_html = render_related_briefings(item, visible_items, categories, registry)
        write_page(page_path, page_html, feed_item=item, post_id=post_id, related_html=related_html)
        write_linkedin_draft(item, post_url, post_id=post_id,
                             force=(item.slug == test_slug))
        write_advisor_brief(item, post_url, post_id=post_id, force=(item.slug == test_slug))
        write_email_draft(item, post_url, post_id=post_id, dry_run=dry_run,
                          force=(item.slug == test_slug),
                          test_email=(test_email if item.slug == test_slug else ""))

    # Patch any existing post pages not in the current sync (e.g. fell off blog index):
    # apply content cleaning and remove stale future-article cards.
    future_slugs = {i.slug for i in generated_items if i not in visible_items}
    synced_slugs = {i.slug for i in generated_items}
    for post_dir in ROOT.glob("post/*/index.html"):
        slug = post_dir.parent.name
        if slug in synced_slugs:
            continue  # already handled above
        html = post_dir.read_text(encoding="utf-8")
        patched = normalize_internal_links(
            clean_article_content(strip_platform_widgets(rewrite_domains(html)))
        )
        for fs in future_slugs:
            patched = re.sub(
                rf'<a\s+href="[^"]*{re.escape(fs)}[^"]*"[^>]*>.*?</a>',
                '',
                patched,
                flags=re.DOTALL,
            )
        if patched != html:
            post_dir.write_text(patched, encoding="utf-8")

    # blog.html and sitemap.xml are built from every locally published post
    # (post-registry.json + files on disk), not from the GetAutoSEO feed.
    # This is durable regardless of that feed's availability, and correctly
    # reflects posts published via publish_original_post() as "latest" when
    # appropriate, which the feed-derived list never did.
    registry_items = build_items_from_registry()
    if not registry_items:
        print("No published articles found on disk — skipping blog and sitemap generation.", file=sys.stderr)
        commit_message = "Sync maintenance: link cleanup (no published articles)"
    else:
        latest_item = registry_items[0]
        remaining_items = registry_items[1:] if len(registry_items) > 1 else []
        latest_with_listing = inject_more_articles(latest_item.html, remaining_items, categories=categories)
        latest_with_listing = inject_blog_landing_view(latest_with_listing, registry_items, categories=categories)
        write_page(ROOT / "blog.html", latest_with_listing)
        (ROOT / "sitemap.xml").write_text(build_sitemap(registry_items), encoding="utf-8")
        generate_post_mapping(registry_items, registry)
        print(f"Synced {len(registry_items)} total published article(s) "
              f"({len(generated_items)} contributed by the feed this run). "
              f"Latest: {latest_item.slug}")
        commit_message = f"Sync blog content, update {latest_item.slug}"

    _git_commit_and_push(commit_message)
    return 0


def _git_commit_and_push(commit_message: str) -> None:
    """Stage all sync output, commit if there are changes, and push."""
    import subprocess

    def run(cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)

    # Stash working-tree changes so pull --rebase can proceed cleanly,
    # then restore them on top of the updated remote state.
    stash = run(["git", "stash", "--include-untracked", "-m", "sync pre-pull stash"])
    stashed = stash.returncode == 0 and "No local changes to save" not in stash.stdout

    pull = run(["git", "pull", "--rebase"])
    if pull.returncode != 0:
        if stashed:
            run(["git", "stash", "pop"])
        print(f"  git pull failed — skipping commit/push:\n{pull.stderr}", file=sys.stderr)
        return

    if stashed:
        pop = run(["git", "stash", "pop"])
        if pop.returncode != 0:
            print(f"  git stash pop failed — skipping commit/push:\n{pop.stderr}", file=sys.stderr)
            return

    run(["git", "add", "-A"])

    status = run(["git", "status", "--porcelain"])
    if not status.stdout.strip():
        print("  git: nothing to commit")
        return

    commit = run(["git", "commit", "-m", commit_message])
    if commit.returncode != 0:
        print(f"  git commit failed:\n{commit.stderr}", file=sys.stderr)
        return
    print(f"  git commit: {commit_message}")

    push = run(["git", "push"])
    if push.returncode != 0:
        print(f"  git push failed:\n{push.stderr}", file=sys.stderr)
    else:
        print("  git push: OK")


if __name__ == "__main__":
    import io
    import traceback
    _buf = io.StringIO()
    sys.stdout = _Tee(sys.__stdout__, _buf)
    sys.stderr = _Tee(sys.__stderr__, _buf)
    _status = "OK"
    _code = 0
    try:
        _code = main()
        if _code:
            _status = f"EXIT {_code}"
    except Exception:
        traceback.print_exc()
        _status = "FAILED"
        _code = 1
    finally:
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        if "--test" not in sys.argv:
            send_run_report(_buf.getvalue() or "(no output)", _status)
    raise SystemExit(_code)