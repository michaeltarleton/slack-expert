#!/usr/bin/env python3
"""
Direct Slack Web API sender -- posts/updates/deletes as the user token.

Exists specifically to bypass the Claude app MCP tools (`mcp__slack__*`,
`claude_ai_Slack__*`), which post through the Claude Slack app (A08SF47R6P4)
and stamp every message with a "sent using Claude" watermark, and have been
observed to mangle non-ASCII punctuation (em-dash -> mojibake). Posting
straight to chat.postMessage/chat.update/chat.delete with the user's own
OAuth token produces a plain message with no watermark and correct UTF-8.

Usage:
    python scripts/slack_post.py post   --channel C0123456 --text "hello"
    python scripts/slack_post.py post   --channel C0123456 --text "hi" --thread-ts 1776114430.309819
    python scripts/slack_post.py update --channel C0123456 --update-ts 1776114430.309819 --text "edited"
    python scripts/slack_post.py delete --channel C0123456 --delete-ts 1776114430.309819

    Message text containing shell metacharacters (backticks, $VAR, quotes)
    must go through stdin instead of --text, via a single-quoted heredoc:
        python scripts/slack_post.py post --channel C0123456 --text-stdin <<'EOF'
        message text here, safe for `backticks`, $vars, "quotes"
        EOF

Token resolution:
    ~/.claude/companies/<company>/data/tokens/slack/<skill>.json, key "user_token"
    (mirrors slack_refresh.py's _token_path, including its fallback to
    .../data/slack/token.json when skill is empty). Override the whole path
    with --token-file. Override company/skill with --company/--skill
    (defaults: company=amira, skill=slack).
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

WATERMARK_APP_ID = "A08SF47R6P4"
API_BASE = "https://slack.com/api"
# Permalink host per company. Emitting an amiralearning.slack.com link for a workspace that
# isn't amiralearning reports a correct-looking permalink pointing at the wrong place, so an
# unknown company is an error rather than a silent default. Note this is independent of how
# the token was resolved: --token-file overrides the token path but says nothing about which
# workspace that token belongs to, so it does not (and cannot) imply a host.
# --workspace-host is the override for both cases.
WORKSPACE_HOSTS = {"amira": "amiralearning.slack.com"}


def _token_path(company: str, skill: str) -> Path:
    if skill:
        return Path.home() / ".claude" / "companies" / company / "data" / "tokens" / "slack" / f"{skill}.json"
    return Path.home() / ".claude" / "companies" / company / "data" / "slack" / "token.json"


def _load_user_token(args) -> str:
    # Path() does not expand ~, so a documented-style --token-file ~/.claude/... would
    # silently resolve against the CWD instead of home.
    token_file = (Path(args.token_file).expanduser() if args.token_file
                  else _token_path(args.company, args.skill))
    if not token_file.exists():
        print(f"ERROR: no token file at {token_file}", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(token_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"ERROR: token file {token_file} is unreadable or not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    token = data.get("user_token", "")
    if not token:
        print(f"ERROR: no 'user_token' field in {token_file}", file=sys.stderr)
        sys.exit(1)
    return token


def _call(method: str, token: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/{method}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)  # HTTPError is file-like; body is JSON on Slack API errors
        except Exception:
            return {"ok": False, "error": f"http_{e.code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _workspace_host(args) -> str:
    if getattr(args, "workspace_host", ""):
        return args.workspace_host
    host = WORKSPACE_HOSTS.get(args.company)
    if not host:
        hint = " (--token-file does not imply a host)" if getattr(args, "token_file", "") else ""
        print(f"ERROR: no permalink host known for company '{args.company}'{hint}. "
              f"Known: {', '.join(sorted(WORKSPACE_HOSTS))}. "
              f"Pass --workspace-host <host> to post to another workspace.",
              file=sys.stderr)
        sys.exit(1)
    return host


def _permalink(host: str, channel: str, ts: str, thread_ts: str = "") -> str:
    link = f"https://{host}/archives/{channel}/p{ts.replace('.', '')}"
    if thread_ts:
        link += f"?thread_ts={thread_ts}&cid={channel}"
    return link


def _add_text_args(sub_parser: argparse.ArgumentParser) -> None:
    group = sub_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Message text. Avoid for text with shell "
                        "metacharacters (backticks, $VAR, quotes) -- use --text-stdin instead.")
    group.add_argument("--text-stdin", action="store_true",
                        help="Read message text from stdin (safe for backticks/$VAR/quotes)")


def _resolve_text(args) -> str:
    if args.text_stdin:
        # Read raw bytes and decode as UTF-8 explicitly -- sys.stdin.read() uses
        # the ambient console encoding, which on Windows without UTF-8 mode
        # enabled can mis-decode non-ASCII text (the exact mojibake this
        # script's own user-token approach exists to avoid).
        # rstrip both: a heredoc piped in from a CRLF context leaves a trailing \r that
        # would be posted as a literal carriage return in the Slack message body.
        return sys.stdin.buffer.read().decode("utf-8").rstrip("\r\n")
    return args.text


def _warn_if_watermarked(resp: dict) -> str:
    """Warn, never fail: the write already succeeded, so a non-zero exit here would invite a
    retry that double-posts."""
    app_id = resp.get("message", {}).get("app_id", "")
    if app_id == WATERMARK_APP_ID:
        print(f"WARNING: message carries watermarked app_id {WATERMARK_APP_ID} -- this should "
              "not happen via direct Web API. Investigate token scope/app binding.",
              file=sys.stderr)
    return app_id


def cmd_post(args) -> int:
    host = _workspace_host(args)
    token = _load_user_token(args)
    text = _resolve_text(args)
    payload = {"channel": args.channel, "text": text}
    if args.thread_ts:
        payload["thread_ts"] = args.thread_ts
    resp = _call("chat.postMessage", token, payload)
    if not resp.get("ok"):
        print(f"ERROR: chat.postMessage failed: {resp.get('error')}", file=sys.stderr)
        return 1
    ts = resp.get("ts", "")
    channel = resp.get("channel", args.channel)
    # The postMessage response's own echoed message is authoritative for what
    # was actually posted -- a user-token post cannot be app-attributed, so
    # there is nothing further to verify. A re-fetch via conversations.history
    # was tried previously but doesn't return thread replies, so it silently
    # inspected an unrelated neighboring message and could false-fail here.
    app_id = _warn_if_watermarked(resp)
    print(f"ok ts={ts}")
    print(f"permalink={_permalink(host, channel, ts, args.thread_ts)}")
    if app_id:
        print(f"app_id={app_id}")
    return 0


def cmd_update(args) -> int:
    host = _workspace_host(args)
    token = _load_user_token(args)
    text = _resolve_text(args)
    payload = {"channel": args.channel, "ts": args.update_ts, "text": text}
    resp = _call("chat.update", token, payload)
    if not resp.get("ok"):
        print(f"ERROR: chat.update failed: {resp.get('error')}", file=sys.stderr)
        return 1
    ts = resp.get("ts", args.update_ts)
    channel = resp.get("channel", args.channel)
    thread_ts = resp.get("message", {}).get("thread_ts", "")
    _warn_if_watermarked(resp)
    print(f"ok ts={ts}")
    print(f"permalink={_permalink(host, channel, ts, thread_ts)}")
    return 0


def cmd_delete(args) -> int:
    token = _load_user_token(args)
    payload = {"channel": args.channel, "ts": args.delete_ts}
    resp = _call("chat.delete", token, payload)
    if not resp.get("ok"):
        print(f"ERROR: chat.delete failed: {resp.get('error')}", file=sys.stderr)
        return 1
    print(f"ok deleted ts={args.delete_ts}")
    return 0


def _common_args() -> argparse.ArgumentParser:
    """Shared flags, attached to each SUBparser rather than the top level.

    argparse only accepts a top-level flag *before* the subcommand, so `post --company X`
    -- the natural form, and the one SKILL.md documents -- would exit 2 with
    "unrecognized arguments". Defining them per-subcommand makes the documented invocation
    work. They cannot also live on the top-level parser: the subparser's own default would
    overwrite a value given before the subcommand.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--company", default="amira")
    common.add_argument("--skill", default="slack")
    common.add_argument("--token-file", default="", help="Override the resolved token json path")
    common.add_argument("--workspace-host", default="",
                        help="Override the permalink host (default: per --company)")
    return common


def build_parser() -> argparse.ArgumentParser:
    """The one parser definition. Tests must use this rather than reconstructing an
    equivalent one -- a mirrored copy drifts and passes while the real CLI is broken."""
    parser = argparse.ArgumentParser(description="Post/update/delete Slack messages via direct Web API (user token, no watermark)")
    sub = parser.add_subparsers(dest="command", required=True)
    common = _common_args()

    p_post = sub.add_parser("post", help="Post a new message", parents=[common])
    p_post.add_argument("--channel", required=True)
    _add_text_args(p_post)
    p_post.add_argument("--thread-ts", default="")
    p_post.set_defaults(func=cmd_post)

    p_update = sub.add_parser("update", help="Edit an existing message", parents=[common])
    p_update.add_argument("--channel", required=True)
    p_update.add_argument("--update-ts", required=True)
    _add_text_args(p_update)
    p_update.set_defaults(func=cmd_update)

    p_delete = sub.add_parser("delete", help="Delete an existing message", parents=[common])
    p_delete.add_argument("--channel", required=True)
    p_delete.add_argument("--delete-ts", required=True)
    p_delete.set_defaults(func=cmd_delete)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
