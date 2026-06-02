import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sync_blog import ROOT, HEADERS, load_post_registry

import requests


def migrate_post(post_index: Path, slug: str,
                 slug_to_id: dict) -> int:
    """Find and replace all getautoseo image references in a
    post file. Returns count of replacements made."""
    html = post_index.read_text(encoding="utf-8")

    if 'getautoseo.com' not in html:
        return 0

    post_id = slug_to_id.get(slug, "000")

    # Find all unique getautoseo image URLs in this file
    img_urls = list(dict.fromkeys(re.findall(
        r'https://getautoseo\.com/storage/[^\s"\')\]]+',
        html
    )))

    if not img_urls:
        return 0

    title_match = re.search(
        r"<title>([^<]+)</title>", html, flags=re.IGNORECASE
    )
    post_title = title_match.group(1).replace(
        ' | Andrew Roberts Advisory', '').strip() \
        if title_match else slug

    replaced = 0
    for i, img_url in enumerate(img_urls):
        # Determine local filename
        ext = Path(img_url.split('?')[0]).suffix or '.jpg'
        suffix = '' if i == 0 else f'-{i}'
        local_filename = f"{post_id}-hero{suffix}{ext}"
        local_path = post_index.parent / local_filename
        relative_path = f"/post/{slug}/{local_filename}"

        # Download if not already local
        if not local_path.exists():
            try:
                resp = requests.get(
                    img_url, headers=HEADERS, timeout=30
                )
                resp.raise_for_status()
                local_path.write_bytes(resp.content)
                print(f"  Downloaded: {slug}/{local_filename}")
            except Exception as e:
                print(f"  FAILED {slug} [{img_url}]: {e}",
                      file=sys.stderr)
                continue

        html = html.replace(img_url, relative_path)
        replaced += 1

    if replaced:
        # Ensure alt text on any <img> tags that lack it
        def add_alt(m):
            tag = m.group(0)
            if 'alt=' not in tag.lower():
                return tag.replace('>',
                    f' alt="{post_title}">', 1)
            return tag
        html = re.sub(
            r'<img[^>]*>', add_alt, html,
            flags=re.IGNORECASE
        )
        post_index.write_text(html, encoding="utf-8")

    return replaced


def migrate_images() -> None:
    registry = load_post_registry()
    slug_to_id = {slug: f"{pid:03d}" for slug, pid in registry.items()}
    migrated = 0

    for post_index in sorted(
            (ROOT / "post").glob("*/index.html")):
        slug = post_index.parent.name
        count = migrate_post(post_index, slug, slug_to_id)
        if count:
            migrated += count
            print(f"  {slug}: {count} reference(s) replaced")

    print(f"\nDone. {migrated} reference(s) migrated.")

if __name__ == "__main__":
    migrate_images()
