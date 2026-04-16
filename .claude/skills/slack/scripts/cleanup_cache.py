#!/usr/bin/env python3
"""
Delete expired entries from the Slack file download cache.

Usage:
    python cleanup_cache.py --cache-dir ~/.claude/companies/amira/data/slack/downloads/

Output (JSON to stdout):
    { "ok": true, "deleted_count": 3, "remaining_count": 7 }
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up expired Slack file cache entries")
    parser.add_argument("--cache-dir", required=True, help="Cache directory path")
    args = parser.parse_args()

    cache_dir = Path(os.path.expanduser(args.cache_dir))

    if not cache_dir.exists():
        print(json.dumps({"ok": True, "deleted_count": 0, "remaining_count": 0}))
        return

    now = datetime.now(timezone.utc)
    deleted = 0
    remaining = 0
    errors: list[str] = []

    for meta_path in cache_dir.glob("*.meta.json"):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            expires_at_str = meta.get("expires_at", "")
            if not expires_at_str:
                continue

            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))

            if expires_at < now:
                # Delete both .md and .meta.json
                file_id = meta.get("file_id", meta_path.stem.replace(".meta", ""))
                md_path = cache_dir / f"{file_id}.md"

                for path in (meta_path, md_path):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError as e:
                        errors.append(f"Failed to delete {path}: {e}")

                deleted += 1
            else:
                remaining += 1

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            errors.append(f"Skipped malformed meta {meta_path.name}: {e}")

    result: dict = {"ok": True, "deleted_count": deleted, "remaining_count": remaining}
    if errors:
        result["warnings"] = errors

    print(json.dumps(result))


if __name__ == "__main__":
    main()
