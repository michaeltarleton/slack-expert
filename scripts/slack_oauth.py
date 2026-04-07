#!/usr/bin/env python3
"""
One-time Slack OAuth setup for the x-slack download mode.

Usage:
    python scripts/slack_oauth.py --client-id YOUR_ID --client-secret YOUR_SECRET
    python scripts/slack_oauth.py --client-id YOUR_ID --client-secret YOUR_SECRET --company acme

After running:
    - Token saved to ~/.claude/companies/{company}/data/slack/token.json
    - Sourceable env file written to ~/.claude/companies/{company}/data/slack/slack-env.sh
    - Add to your shell profile: source ~/.claude/companies/amira/data/slack/slack-env.sh

The token works for:
    - python scripts/download_slack_file.py (auto-reads token.json)
    - SLACK_BOT_TOKEN env var (if you source the env file)
"""
import argparse
import http.server
import json
import os
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
SCOPES = ""                        # bot scopes (none — we use user scopes)
USER_SCOPES = (
    "channels:read,channels:history,"
    "groups:read,groups:history,"
    "im:read,im:history,"
    "mpim:read,mpim:history,"
    "users:read,search:read,"
    "chat:write,files:read"
)  # user token scopes — covers all x-slack modes (read, send, reply, search, download)
REDIRECT_PORT = 3119               # distinct from port 3118 used by official Slack MCP
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
TOKEN_URL = "https://slack.com/api/oauth.v2.access"

# ---------------------------------------------------------------------------
# OAuth callback HTTP handler
# ---------------------------------------------------------------------------
_auth_result: dict = {}
_server_ready = threading.Event()


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

        # Signal the main thread we're done
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


def _exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    """Exchange authorization code for access token."""
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

    # token.json
    token_file = data_dir / "token.json"
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)
    os.chmod(token_file, 0o600)

    # slack-env.sh (sourceable)
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
        # SLACK_TOKEN is the generic fallback used by download_slack_file.py
        f.write(f'export SLACK_TOKEN="{primary}"\n')
    os.chmod(env_file, 0o600)

    return token_file, env_file


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Authenticate with Slack via OAuth and store token for x-slack download mode"
    )
    parser.add_argument("--client-id", required=True, help="Slack app Client ID")
    parser.add_argument("--client-secret", required=True, help="Slack app Client Secret")
    parser.add_argument("--company", default="amira", help="Company name (default: amira)")
    parser.add_argument("--scopes", default=USER_SCOPES,
                        help=f"User token scopes (default: {USER_SCOPES})")
    args = parser.parse_args()

    if _port_in_use(REDIRECT_PORT):
        print(f"ERROR: Port {REDIRECT_PORT} is already in use. "
              f"Stop any process using it and try again.", file=sys.stderr)
        sys.exit(1)

    # 1. Start local callback server
    server = _start_callback_server()

    # 2. Build authorization URL
    auth_params = urllib.parse.urlencode({
        "client_id": args.client_id,
        "user_scope": args.scopes,
        "redirect_uri": REDIRECT_URI,
    })
    auth_url = f"{AUTHORIZE_URL}?{auth_params}"

    print("=" * 60)
    print("Slack OAuth Setup — x-slack download mode")
    print("=" * 60)
    print()
    print("Opening browser to authorize Slack access...")
    print()
    print(f"If browser does not open, visit this URL manually:")
    print(f"  {auth_url}")
    print()
    print("Waiting for authorization... (Ctrl+C to cancel)")

    webbrowser.open(auth_url)

    # 3. Wait for callback (server shuts itself down after callback)
    server._BaseServer__shutdown_request = False
    server.serve_forever()  # blocks until callback handler calls shutdown()

    if "error" in _auth_result:
        print(f"\nERROR: OAuth failed: {_auth_result['error']}", file=sys.stderr)
        sys.exit(1)

    if "code" not in _auth_result:
        print("\nERROR: No authorization code received.", file=sys.stderr)
        sys.exit(1)

    print("Authorization code received. Exchanging for token...")

    # 4. Exchange code for token
    token_resp = _exchange_code(_auth_result["code"], args.client_id, args.client_secret)

    if not token_resp.get("ok"):
        error = token_resp.get("error", "unknown")
        print(f"\nERROR: Token exchange failed: {error}", file=sys.stderr)
        sys.exit(1)

    # 5. Extract tokens
    user_token = (token_resp.get("authed_user") or {}).get("access_token", "")
    bot_token = token_resp.get("access_token", "")  # bot token (if bot scopes requested)

    token_data = {
        "ok": True,
        "user_token": user_token,
        "bot_token": bot_token,
        "user_id": (token_resp.get("authed_user") or {}).get("id", ""),
        "team_id": (token_resp.get("team") or {}).get("id", ""),
        "team_name": (token_resp.get("team") or {}).get("name", ""),
        "scopes": (token_resp.get("authed_user") or {}).get("scope", args.scopes),
        "obtained_at": datetime.now(timezone.utc).isoformat(),
    }

    # 6. Save token
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
    print("The x-slack download mode will automatically use the stored token.")
    print()
    print("Optional — add to your shell profile (~/.bashrc or ~/.zprofile):")
    print(f'  source "{env_file}"')
    print()
    print("Done.")


if __name__ == "__main__":
    main()
