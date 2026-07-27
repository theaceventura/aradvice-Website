"""One-off backfill: insert the 'Related briefings' block into every existing
local post page. Needed because sync_blog.py only inserts this block for
posts that go through the full write_page() pipeline (freshly fetched from
the live feed) — the 27 posts already on disk never got it. This script
works entirely from local files (post-registry.json, post-categories.json,
post/<slug>/index.html) and touches nothing remote.

Idempotent: skips any post that already has a 'Related briefings' block.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sync_blog as sb

ROOT = sb.ROOT


def extract_title(html: str, slug: str) -> str:
    m = re.search(r'property="og:title"\s+content="([^"]*)"', html)
    if m:
        return sb.unescape(m.group(1))
    m = re.search(r"<title>([^<]*)</title>", html)
    if m:
        return sb.unescape(m.group(1)).split(" | ")[0]
    return slug.replace("-", " ").title()


def main() -> int:
    registry = sb.load_post_registry()
    categories = sb.load_post_categories()

    # Newest-first, matching the ordering visible_items/generated_items use
    # elsewhere in sync_blog.py (higher registry id == more recently published).
    slugs = sorted(registry.keys(), key=lambda s: registry[s], reverse=True)

    items = []
    for slug in slugs:
        page_path = ROOT / "post" / slug / "index.html"
        if not page_path.exists():
            print(f"  skip {slug}: no local file", file=sys.stderr)
            continue
        html = page_path.read_text(encoding="utf-8")
        items.append(sb.FeedItem(
            title=extract_title(html, slug),
            link="", slug=slug, pub_date="", html="",
            image_url="", read_time="",
        ))

    updated = skipped_has_block = skipped_no_cta = 0
    for item in items:
        page_path = ROOT / "post" / item.slug / "index.html"
        html = page_path.read_text(encoding="utf-8")

        if "Related briefings" in html:
            skipped_has_block += 1
            continue

        related_html = sb.render_related_briefings(item, items, categories, registry)
        if not related_html:
            continue

        inserted = sb.insert_related_briefings(html, related_html)
        if inserted == html:
            print(f"  skip {item.slug}: no CTA and no </article> found", file=sys.stderr)
            skipped_no_cta += 1
            continue

        page_path.write_text(inserted, encoding="utf-8")
        updated += 1
        print(f"  updated {item.slug}")

    print(f"\nDone: {updated} updated, {skipped_has_block} already had the block, "
          f"{skipped_no_cta} skipped (no insertion point).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
