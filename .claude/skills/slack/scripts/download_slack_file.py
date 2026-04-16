#!/usr/bin/env python3
"""
Download a file from Slack via the Web API.

Usage:
    python download_slack_file.py --file-id F07XXXXXX --output /tmp/out
    python download_slack_file.py --url "https://files.slack.com/..." --output /tmp/out

Exit codes:
    0  Success
    1  Auth failure (token missing/invalid/insufficient scope)
    2  File not found (404 or invalid file_id)
    3  Network/download error
    4  File exceeds 50 MB cap
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MAX_BYTES = 50 * 1024 * 1024  # 50 MB
FILES_INFO_URL = "https://slack.com/api/files.info"
CHUNK_SIZE = 65536


def _token() -> str:
    """Resolve token in priority order:
    1. SLACK_BOT_TOKEN env var
    2. SLACK_USER_TOKEN env var (set by slack_oauth.py via slack-env.sh)
    3. SLACK_TOKEN env var (generic fallback)
    4. ~/.claude/companies/*/data/tokens/slack/x-slack.json (new per-skill token)
    5. ~/.claude/companies/*/data/slack/token.json (legacy fallback)
    """
    for var in ("SLACK_BOT_TOKEN", "SLACK_USER_TOKEN", "SLACK_TOKEN"):
        tok = os.environ.get(var)
        if tok:
            return tok

    import glob as _glob

    # Per-skill token (new convention)
    new_pattern = str(Path.home() / ".claude" / "companies" / "*" / "data" / "tokens" / "slack" / "x-slack.json")
    for token_file in _glob.glob(new_pattern):
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            tok = data.get("user_token") or data.get("bot_token")
            if tok:
                return tok
        except Exception:
            continue

    # Legacy fallback
    pattern = str(Path.home() / ".claude" / "companies" / "*" / "data" / "slack" / "token.json")
    for token_file in _glob.glob(pattern):
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            tok = data.get("user_token") or data.get("bot_token")
            if tok:
                return tok
        except Exception:
            continue

    return ""


def _fail(code: int, message: str) -> None:
    print(json.dumps({"ok": False, "error": message}), flush=True)
    sys.exit(code)


def _files_info(file_id: str, token: str) -> dict:
    """Call files.info and return the file object."""
    url = f"{FILES_INFO_URL}?file={file_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            _fail(1, f"Slack API auth error {e.code}: check token scopes (files:read required)")
        _fail(3, f"Slack API HTTP error {e.code}")
    except Exception as e:
        _fail(3, f"Network error calling files.info: {e}")

    if not data.get("ok"):
        err = data.get("error", "unknown")
        if err in ("invalid_auth", "not_authed", "token_revoked", "missing_scope"):
            _fail(1, f"Slack auth error: {err}")
        if err in ("file_not_found", "file_deleted"):
            _fail(2, f"File {file_id} not found or deleted: {err}")
        _fail(3, f"files.info error: {err}")

    return data["file"]


def _download(url: str, token: str, output_path: str, file_id: str,
              filename: str, mimetype: str) -> dict:
    """Stream download URL to output_path atomically. Returns result dict."""
    tmp_path = output_path + ".tmp"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            # Check Content-Length guard
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_BYTES:
                _fail(4, f"File exceeds 50 MB cap ({content_length} bytes)")

            total = 0
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                        _fail(4, f"File exceeds 50 MB cap (stopped at {total} bytes)")
                    f.write(chunk)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            _fail(1, f"Download auth error {e.code}: token may lack files:read scope")
        if e.code == 404:
            _fail(2, f"File not found at download URL (404)")
        _fail(3, f"HTTP error downloading file: {e.code}")
    except urllib.error.URLError as e:
        _fail(3, f"Network error downloading file: {e.reason}")
    except Exception as e:
        _fail(3, f"Unexpected error downloading file: {e}")

    os.rename(tmp_path, output_path)

    return {
        "ok": True,
        "output_path": output_path,
        "mimetype": mimetype,
        "filename": filename,
        "size_bytes": total,
        "file_id": file_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Download a Slack file via Web API")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file-id", help="Slack file ID (F-prefixed)")
    group.add_argument("--url", help="Direct private download URL")
    parser.add_argument("--output", required=True, help="Output file path (no extension — added automatically)")
    parser.add_argument("--token", help="Slack bot token (overrides env vars)")
    args = parser.parse_args()

    # Resolve token
    token = args.token or _token()
    if not token:
        _fail(1, "Slack bot token not found. Set SLACK_BOT_TOKEN or pass --token.")

    if args.file_id:
        # Resolve metadata first
        file_obj = _files_info(args.file_id, token)
        file_id = args.file_id
        filename = file_obj.get("name", file_id)
        mimetype = file_obj.get("mimetype", "application/octet-stream")
        url = file_obj.get("url_private_download") or file_obj.get("url_private")
        if not url:
            _fail(2, f"No download URL in files.info response for {file_id}")
    else:
        # URL provided directly
        url = args.url
        file_id = "unknown"
        filename = url.split("/")[-1].split("?")[0] or "file"
        mimetype = "application/octet-stream"

    # Derive extension from filename for output path
    ext = Path(filename).suffix
    output_path = args.output if args.output.endswith(ext) else args.output + ext

    result = _download(url, token, output_path, file_id, filename, mimetype)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
