#!/usr/bin/env python3
"""
One-time Slack OAuth setup for the x-slack skill.

Uses the official Slack MCP app (public client — no client secret needed).
Token is saved to ~/.claude/companies/{company}/data/slack/token.json and
is auto-discovered by scripts/download_slack_file.py.

Usage (default — uses official Slack MCP client ID):
    python scripts/slack_oauth.py
    python scripts/slack_oauth.py --company acme

Usage (custom Slack app — requires your own client ID + secret):
    python scripts/slack_oauth.py --client-id YOUR_ID --client-secret YOUR_SECRET

After running:
    - Token saved to ~/.claude/companies/{company}/data/slack/token.json
    - Sourceable env file at ~/.claude/companies/{company}/data/slack/slack-env.sh
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Official Slack MCP app — public client, PKCE only, no client secret.
# Client ID from ~/.mcp.json (Slack's hosted MCP server at mcp.slack.com/mcp).
OFFICIAL_CLIENT_ID = "1601185624273.8899143856786"

# Port 3118 is registered as redirect URI for the official Slack MCP app.
# Use the same port so Slack accepts our redirect URI.
REDIRECT_PORT = 3118
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"

AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
TOKEN_URL = "https://slack.com/api/oauth.v2.access"

# The official Slack MCP app (public client) only allows files:read as a user scope.
# For broader scopes (channels, messages, search, send), create your own Slack app
# and pass --client-id / --client-secret.
USER_SCOPES = "files:read"

# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------
def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge

# ---------------------------------------------------------------------------
# OAuth callback HTTP handler
# ---------------------------------------------------------------------------
_auth_result: dict = {}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self._respond(404, "Not found")
            return

        params = urllib.parse.parse_qs(parsed.query)

        if "error" in params:
            error = params["error"][0]
            _auth_result["error"] = error
            self._respond(400, f"<h1>OAuth Error</h1><p>{error}</p><p>You can close this tab.</p>")
        elif "code" in params:
            _auth_result["code"] = params["code"][0]
            self._respond(200, (
                "<h1>Authorization successful!</h1>"
                "<p>Token saved. You can close this tab and return to your terminal.</p>"
            ))
        else:
            _auth_result["error"] = "No code or error in callback"
            self._respond(400, "<h1>Unexpected callback</h1><p>No code received.</p>")

        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _respond(self, status: int, body: str):
        content = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass  # suppress access logs


def _start_callback_server() -> http.server.HTTPServer:
    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server


def _exchange_code_pkce(code: str, code_verifier: str, client_id: str) -> dict:
    """Exchange authorization code for token using PKCE (no client secret)."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "redirect_uri": REDIRECT_URI,
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
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _exchange_code_secret(code: str, client_id: str, client_secret: str) -> dict:
    """Exchange authorization code for token using client secret (custom apps)."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
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
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _save_token(token_data: dict, company: str) -> tuple[Path, Path]:
    """Save token.json and slack-env.sh to the company data directory."""
    data_dir = Path.home() / ".claude" / "companies" / company / "data" / "slack"
    data_dir.mkdir(parents=True, exist_ok=True)

    token_file = data_dir / "token.json"
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)
    os.chmod(token_file, 0o600)

    user_token = token_data.get("user_token", "")
    bot_token = token_data.get("bot_token", "")
    primary = user_token or bot_token
    env_file = data_dir / "slack-env.sh"
    with open(env_file, "w", encoding="utf-8") as f:
        f.write("# Slack token — auto-generated by slack_oauth.py\n")
        f.write(f"# Generated: {datetime.now(timezone.utc).isoformat()}\n")
        if user_token:
            f.write(f'export SLACK_USER_TOKEN="{user_token}"\n')
        if bot_token:
            f.write(f'export SLACK_BOT_TOKEN="{bot_token}"\n')
        f.write(f'export SLACK_TOKEN="{primary}"\n')
    os.chmod(env_file, 0o600)

    return token_file, env_file


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Authenticate with Slack via OAuth and store token for x-slack"
    )
    parser.add_argument(
        "--client-id",
        default=OFFICIAL_CLIENT_ID,
        help=f"Slack app Client ID (default: official Slack MCP app {OFFICIAL_CLIENT_ID})",
    )
    parser.add_argument(
        "--client-secret",
        default="",
        help="Slack app Client Secret (only required for custom apps; omit for official Slack MCP)",
    )
    parser.add_argument("--company", default="amira", help="Company name (default: amira)")
    parser.add_argument(
        "--scopes",
        default=USER_SCOPES,
        help=f"User token scopes (default covers all x-slack modes)",
    )
    args = parser.parse_args()

    using_official = args.client_id == OFFICIAL_CLIENT_ID

    if _port_in_use(REDIRECT_PORT):
        print(
            f"ERROR: Port {REDIRECT_PORT} is already in use.\n"
            f"  If Claude Code's Slack MCP is connected, disconnect it first,\n"
            f"  then run this script, then reconnect.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Generate PKCE pair (always — official app requires it; custom apps ignore code_verifier)
    code_verifier, code_challenge = _pkce_pair()

    # Start local callback server
    server = _start_callback_server()

    # Build authorization URL
    auth_params: dict = {
        "client_id": args.client_id,
        "user_scope": args.scopes,
        "redirect_uri": REDIRECT_URI,
    }
    if using_official:
        # Official Slack MCP app uses PKCE
        auth_params["code_challenge"] = code_challenge
        auth_params["code_challenge_method"] = "S256"

    auth_url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(auth_params)}"

    print("=" * 60)
    print("Slack OAuth Setup — x-slack")
    if using_official:
        print("Using official Slack MCP app (PKCE — no client secret needed)")
    else:
        print(f"Using custom app: {args.client_id}")
    print("=" * 60)
    print()
    print("Opening browser to authorize Slack access...")
    print()
    print("If browser does not open, visit this URL manually:")
    print(f"  {auth_url}")
    print()
    print("Waiting for authorization... (Ctrl+C to cancel)")

    webbrowser.open(auth_url)

    # Block until callback handler shuts down the server
    server.serve_forever()

    if "error" in _auth_result:
        print(f"\nERROR: OAuth failed: {_auth_result['error']}", file=sys.stderr)
        sys.exit(1)

    if "code" not in _auth_result:
        print("\nERROR: No authorization code received.", file=sys.stderr)
        sys.exit(1)

    print("Authorization code received. Exchanging for token...")

    # Exchange code for token
    if using_official or not args.client_secret:
        token_resp = _exchange_code_pkce(_auth_result["code"], code_verifier, args.client_id)
    else:
        token_resp = _exchange_code_secret(_auth_result["code"], args.client_id, args.client_secret)

    if not token_resp.get("ok"):
        error = token_resp.get("error", "unknown")
        print(f"\nERROR: Token exchange failed: {error}", file=sys.stderr)
        if error == "invalid_redirect_uri":
            print(
                "  The redirect URI is not registered for this client ID.\n"
                "  If using a custom app, ensure http://localhost:3118/callback\n"
                "  is added to your Slack app's OAuth redirect URIs.",
                file=sys.stderr,
            )
        sys.exit(1)

    # Extract tokens
    user_token = (token_resp.get("authed_user") or {}).get("access_token", "")
    bot_token = token_resp.get("access_token", "")

    token_data = {
        "ok": True,
        "user_token": user_token,
        "bot_token": bot_token,
        "user_id": (token_resp.get("authed_user") or {}).get("id", ""),
        "team_id": (token_resp.get("team") or {}).get("id", ""),
        "team_name": (token_resp.get("team") or {}).get("name", ""),
        "scopes": (token_resp.get("authed_user") or {}).get("scope", args.scopes),
        "obtained_at": datetime.now(timezone.utc).isoformat(),
        "client_id": args.client_id,
    }

    token_file, env_file = _save_token(token_data, args.company)

    print()
    print("=" * 60)
    print("Token saved successfully!")
    print("=" * 60)
    print(f"  Token file:  {token_file}")
    print(f"  Env file:    {env_file}")
    print()
    if user_token:
        masked = user_token[:12] + "..." + user_token[-4:]
        print(f"  User token:  {masked}")
    if bot_token:
        masked = bot_token[:12] + "..." + bot_token[-4:]
        print(f"  Bot token:   {masked}")
    print()
    print("The x-slack skill will automatically use the stored token.")
    print()
    print("Optional — add to your shell profile (~/.bashrc or ~/.zprofile):")
    print(f'  source "{env_file}"')
    print()
    print("Done.")


if __name__ == "__main__":
    main()
