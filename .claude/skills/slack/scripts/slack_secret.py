#!/usr/bin/env python3
"""
Store the Slack custom-app credentials, with the client secret sealed by DPAPI.

Run this once in YOUR OWN terminal (so the secret is typed into a hidden prompt,
never passed on a command line or through another process):

    python scripts/slack_secret.py --skill slack

With a --skill (the default is "slack") writes:
    ~/.claude/companies/<company>/data/tokens/slack/<skill>-app-creds.json
With an empty --skill "" it uses the legacy path:
    ~/.claude/companies/<company>/data/slack/x-slack-app-creds.json
File contents:
    {"client_id": "...", "client_secret_dpapi": "<base64 DPAPI blob>"}

The secret is decryptable only by your Windows user on this machine (see
dpapi_win.py). slack_oauth.py and slack_refresh.py read it back the same way.
"""
import argparse
import base64
import getpass
import json
import os
import sys
from pathlib import Path


def _dpapi():
    """Lazy import: dpapi_win is Windows-only (ctypes). Only load when actually
    sealing/unsealing, so this module stays importable on macOS/Linux."""
    sys.path.insert(0, str(Path(__file__).parent))
    import dpapi_win
    return dpapi_win


def creds_path(company: str, skill: str) -> Path:
    if skill:
        d = Path.home() / ".claude" / "companies" / company / "data" / "tokens" / "slack"
    else:
        d = Path.home() / ".claude" / "companies" / company / "data" / "slack"
    return d / f"{skill or 'x-slack'}-app-creds.json"


def load_client_creds(company: str, skill: str) -> dict:
    """Return {'client_id', 'client_secret'} from the stored creds file.

    Decrypts the DPAPI-sealed secret; falls back to a plaintext 'client_secret'
    field (older layout). Returns {} only when no creds file exists.

    If the file exists but can't be read/parsed, or the sealed secret can't be
    decrypted, returns 'client_secret_error' (a human-readable string) INSTEAD of
    'client_secret'. This lets callers distinguish "no secret stored" from
    "secret present but unreadable" and surface the real cause -- rather than
    telling the operator to store a secret that is already stored, or silently
    routing OAuth down a flow Slack will reject after the browser step.
    """
    path = creds_path(company, skill)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"client_secret_error": f"creds file {path} is unreadable or not valid JSON: {e}"}
    out = {"client_id": data.get("client_id", "")}
    sealed = data.get("client_secret_dpapi")
    if sealed:
        try:
            out["client_secret"] = _dpapi().unprotect(base64.b64decode(sealed))
        except Exception as e:
            if sys.platform != "win32":
                out["client_secret_error"] = (
                    f"client secret at {path} is DPAPI-sealed (Windows-only) and cannot be "
                    f"read on this platform ({sys.platform}); it was sealed on Windows. "
                    "Provide the secret another way here, or run on the Windows user/machine "
                    "that sealed it.")
            else:
                out["client_secret_error"] = (
                    f"client secret is stored (DPAPI-sealed) at {path} but could not be "
                    f"decrypted: {e}. DPAPI is bound to the Windows user+machine that sealed "
                    "it -- re-run slack_secret.py as that user on this machine.")
    elif data.get("client_secret"):
        out["client_secret"] = data["client_secret"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Store Slack app creds (DPAPI-sealed secret)")
    parser.add_argument("--company", default="amira")
    parser.add_argument("--skill", default="slack")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("ERROR: slack_secret.py seals the client secret with Windows DPAPI and is "
              "Windows-only. On macOS/Linux, store client_secret in plaintext in "
              f"{creds_path(args.company, args.skill)} (0600) instead.", file=sys.stderr)
        return 1

    print("Enter your Slack custom-app credentials (from api.slack.com/apps -> Basic Information).")
    client_id = input("Client ID: ").strip()
    secret = getpass.getpass("Client Secret (hidden): ").strip()
    if not client_id or not secret:
        print("ERROR: both Client ID and Client Secret are required.", file=sys.stderr)
        return 1

    dpapi_win = _dpapi()
    blob = dpapi_win.protect(secret)
    creds = {"client_id": client_id, "client_secret_dpapi": base64.b64encode(blob).decode("ascii")}

    path = creds_path(args.company, args.skill)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass  # best-effort; Windows may not honor chmod (file ACLs already restrict)

    # Verify it decrypts back (fails fast if DPAPI/user mismatch). Explicit check,
    # not assert -- asserts are stripped under `python -O`, which would skip this.
    check = dpapi_win.unprotect(base64.b64decode(creds["client_secret_dpapi"]))
    if check != secret:
        print("ERROR: DPAPI verify failed (decrypted value did not match).", file=sys.stderr)
        return 1
    print(f"Stored (secret sealed by DPAPI): {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
