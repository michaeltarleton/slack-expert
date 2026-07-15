#!/usr/bin/env python3
"""
Non-interactive Slack token refresh (token rotation).

Reads the stored refresh token, exchanges it via `oauth.v2.access`
(grant_type=refresh_token), and atomically rewrites the token + env files.
No browser. Intended to run on a schedule (Windows Task Scheduler, cron).

Requires a custom Slack app with `token_rotation_enabled: true` and the client
secret stored by slack_secret.py (during the one-time interactive setup) --
DPAPI-sealed on Windows, or a plaintext `client_secret` field in the creds file
on other platforms.

Refresh tokens are single-use: each refresh returns a new one, so exactly one
refresher may run against a token. Do not run this concurrently with itself.

If refresh fails (refresh token revoked / scopes changed), falls back to the
interactive slack_oauth.py, which opens the browser for a fresh consent.

Usage:
    python scripts/slack_refresh.py --skill slack
    python scripts/slack_refresh.py --skill slack --company amira
    python scripts/slack_refresh.py --skill slack --check-only   # report, don't refresh
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import slack_secret  # creds store: load_client_creds() decrypts the DPAPI-sealed secret

TOKEN_URL = "https://slack.com/api/oauth.v2.access"


def _token_path(company: str, skill: str) -> Path:
    if skill:
        data_dir = Path.home() / ".claude" / "companies" / company / "data" / "tokens" / "slack"
        return data_dir / f"{skill}.json"
    data_dir = Path.home() / ".claude" / "companies" / company / "data" / "slack"
    return data_dir / "token.json"


def _refresh_one(refresh_token: str, client_id: str, client_secret: str) -> dict:
    """Exchange a single refresh token for a fresh access + refresh token."""
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        # Slack returns its {"ok": false, "error": ...} body even on non-2xx; parse
        # it so codes like invalid_grant reach the reauth fallback in main().
        try:
            return json.load(e)
        except Exception:
            return {"ok": False, "error": f"http_{e.code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _reauth(token_data: dict, client_id: str, company: str, skill: str) -> int:
    """Fallback: launch interactive OAuth (opens browser) for a fresh token.

    The secret is NOT passed on argv -- slack_oauth.py loads it from the DPAPI
    creds store itself.
    """
    script = Path(__file__).with_name("slack_oauth.py")
    cmd = [sys.executable, str(script), "--company", company]
    cid = client_id or token_data.get("client_id", "")
    if cid:
        cmd += ["--client-id", cid]  # omit when unknown so slack_oauth resolves stored/official
    # Always pass --skill (even ""), or slack_oauth's default "slack" would
    # redirect a legacy (empty-skill) re-auth to tokens/slack/slack.json.
    cmd += ["--skill", skill]
    if token_data.get("scopes"):
        cmd += ["--scopes", token_data["scopes"]]
    print("Refresh failed; opening browser for interactive re-auth...", file=sys.stderr)
    return subprocess.call(cmd)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)  # atomic on same filesystem (incl. Windows)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass  # best-effort; Windows may not honor chmod (file ACLs already restrict)


def _write_token_and_env(token_file: Path, token_data: dict, skill: str) -> None:
    _atomic_write(token_file, json.dumps(token_data, indent=2))
    user_token = token_data.get("user_token", "")
    bot_token = token_data.get("bot_token", "")
    primary = user_token or bot_token
    lines = [
        f"# Slack token for {'skill ' + skill if skill else 'x-slack'}",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}",
    ]
    if user_token:
        lines.append(f'export SLACK_USER_TOKEN="{user_token}"')
    if bot_token:
        lines.append(f'export SLACK_BOT_TOKEN="{bot_token}"')
    lines.append(f'export SLACK_TOKEN="{primary}"')
    _atomic_write(token_file.with_suffix(".env.sh"), "\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh a rotating Slack token without a browser")
    parser.add_argument("--company", default="amira")
    parser.add_argument("--skill", default="slack")
    parser.add_argument("--check-only", action="store_true",
                        help="Report token status and exit without refreshing")
    args = parser.parse_args()

    token_file = _token_path(args.company, args.skill)
    if not token_file.exists():
        print(f"ERROR: no token file at {token_file}\n"
              f"  Run the one-time setup first: slack_secret.py then slack_oauth.py "
              f"--skill {args.skill}", file=sys.stderr)
        return 1

    try:
        token_data = json.loads(token_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"ERROR: token file {token_file} is unreadable or not valid JSON: {e}\n"
              f"  Re-run slack_oauth.py --skill {args.skill} to regenerate it.", file=sys.stderr)
        return 1
    expires_at = token_data.get("expires_at", "")

    if args.check_only:
        print(f"token_file: {token_file}")
        print(f"expires_at: {expires_at or '(none -- not a rotating token)'}")
        print(f"has user_refresh_token: {bool(token_data.get('user_refresh_token'))}")
        print(f"has bot_refresh_token:  {bool(token_data.get('bot_refresh_token'))}")
        return 0

    if not (token_data.get("user_refresh_token") or token_data.get("bot_refresh_token")):
        print("ERROR: no refresh token stored. This token was not issued by a "
              "rotation-enabled app. Re-run slack_oauth.py against your custom app.",
              file=sys.stderr)
        return 1

    creds = slack_secret.load_client_creds(args.company, args.skill)
    client_id = creds.get("client_id") or token_data.get("client_id", "")
    if not client_id:
        err = creds.get("client_secret_error")  # a corrupt creds file lacks client_id too
        if err:
            print(f"ERROR: {err}", file=sys.stderr)
        else:
            print("ERROR: no client_id found in the creds store or token file; cannot refresh "
                  "(Slack would reject it as invalid_client_id). Re-run slack_secret.py --skill "
                  f"{args.skill} then slack_oauth.py --skill {args.skill} to set it up.", file=sys.stderr)
        return 1
    client_secret = creds.get("client_secret", "")
    if not client_secret:
        err = creds.get("client_secret_error")
        if err:
            print(f"ERROR: {err}", file=sys.stderr)  # present-but-unreadable: real cause
        else:
            creds_file = slack_secret.creds_path(args.company, args.skill)
            print(f"ERROR: no client secret stored (looked in {creds_file}). "
                  f"Run slack_secret.py --skill {args.skill} to store it.", file=sys.stderr)
        return 1

    refreshed_any = False
    for tok_key, refresh_key in (("user_token", "user_refresh_token"),
                                 ("bot_token", "bot_refresh_token")):
        rt = token_data.get(refresh_key)
        if not rt:
            continue
        resp = _refresh_one(rt, client_id, client_secret)
        if not resp.get("ok"):
            err = resp.get("error", "unknown")
            print(f"ERROR refreshing {tok_key}: {err}", file=sys.stderr)
            # invalid_grant / token_revoked => refresh chain is dead, need consent
            if err in ("invalid_grant", "token_revoked", "invalid_refresh_token"):
                return _reauth(token_data, client_id, args.company, args.skill)
            return 1
        token_data[tok_key] = resp.get("access_token", token_data.get(tok_key, ""))
        token_data[refresh_key] = resp.get("refresh_token", rt)
        exp_in = resp.get("expires_in")
        if exp_in:
            token_data["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=int(exp_in))
            ).isoformat()
        token_data["obtained_at"] = datetime.now(timezone.utc).isoformat()
        # Persist immediately: refresh tokens are single-use, so a just-rotated
        # token must hit disk before we risk a failure refreshing the next one.
        _write_token_and_env(token_file, token_data, args.skill)
        refreshed_any = True

    if not refreshed_any:
        print("ERROR: nothing refreshed.", file=sys.stderr)
        return 1

    # Don't print token material -- this goes to a persisted log every 8h.
    kind = "user" if token_data.get("user_token") else ("bot" if token_data.get("bot_token") else "?")
    print(f"Refreshed OK ({kind} token), expires_at {token_data.get('expires_at')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
