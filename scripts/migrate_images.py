import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sync_blog import ROOT, HEADERS, load_post_registry

import requests

def migrate_images() -> None:
    registry = load_post_registry()
    slug_to_id = {slug: f"{pid:03d}" for slug, pid in registry.items()}
    migrated = 0

    for post_index in sorted((ROOT / "post").glob("*/index.html")):
        slug = post_index.parent.name
        html = post_index.read_text(encoding="utf-8")

        img_match = re.search(
            r'<img[^>]*src=["\']'
            r'(https://getautoseo\.com/storage/hero_images/[^"\']+)'
            r'["\'][^>]*>',
            html, flags=re.IGNORECASE
        )
        if not img_match:
            continue

        img_url = img_match.group(1)
        post_id = slug_to_id.get(slug, "000")
        local_filename = f"{post_id}-hero.jpg"
        local_path = ROOT / "post" / slug / local_filename
        relative_path = f"/post/{slug}/{local_filename}"

        if not local_path.exists():
            try:
                resp = requests.get(img_url, headers=HEADERS,
                                    timeout=30)
                resp.raise_for_status()
                local_path.write_bytes(resp.content)
                print(f"  Downloaded: {slug}/{local_filename}")
            except Exception as e:
                print(f"  FAILED {slug}: {e}", file=sys.stderr)
                continue

        title_match = re.search(
            r"<title>([^<]+)</title>", html, flags=re.IGNORECASE
        )
        post_title = title_match.group(1).strip() if title_match else slug

        old_tag = img_match.group(0)
        new_tag = re.sub(
            r'src=["\'][^"\']+["\']',
            f'src="{relative_path}"',
            old_tag
        )
        if 'alt=' not in new_tag.lower():
            new_tag = new_tag.replace(">",
                f' alt="{post_title}">', 1)
        elif re.search(r'alt=["\']["\']', new_tag):
            new_tag = re.sub(
                r'alt=["\']["\']',
                f'alt="{post_title}"',
                new_tag
            )

        html = html.replace(old_tag, new_tag, 1)
        post_index.write_text(html, encoding="utf-8")
        migrated += 1

    print(f"\nDone. {migrated} image(s) migrated.")

if __name__ == "__main__":
    migrate_images()
