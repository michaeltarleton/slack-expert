#!/usr/bin/env python3
"""Self-check for slack_refresh. Run: python test_slack_refresh.py"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import slack_refresh as sr
import slack_secret

_WINDOWS = sys.platform == "win32"
if _WINDOWS:
    import dpapi_win  # Windows-only (ctypes DPAPI); sealed-secret test is skipped elsewhere


def _seed(home: Path, *, refresh="xoxe-old", secret="sek", sealed=False):
    d = home / ".claude" / "companies" / "amira" / "data" / "tokens" / "slack"
    d.mkdir(parents=True, exist_ok=True)
    tok = d / "slack.json"
    tok.write_text(json.dumps({
        "ok": True, "user_token": "xoxp-old", "user_refresh_token": refresh,
        "client_id": "cid", "scopes": "chat:write", "expires_at": "2000-01-01T00:00:00+00:00",
    }), encoding="utf-8")
    if sealed:
        blob = base64.b64encode(dpapi_win.protect(secret)).decode("ascii")
        creds = {"client_id": "cid", "client_secret_dpapi": blob}
    else:
        creds = {"client_id": "cid", "client_secret": secret}
    (d / "slack-app-creds.json").write_text(json.dumps(creds), encoding="utf-8")
    return tok


def _run(argv):
    with mock.patch.object(sys, "argv", ["slack_refresh.py", *argv]):
        return sr.main()


def test_refresh_rotates_token():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        os.environ["USERPROFILE"] = str(home)
        os.environ["HOME"] = str(home)
        tok = _seed(home)
        resp = {"ok": True, "access_token": "xoxp-NEW", "refresh_token": "xoxe-NEW",
                "expires_in": 43200}
        with mock.patch.object(sr, "_refresh_one", return_value=resp) as m:
            rc = _run(["--skill", "slack"])
        assert rc == 0, rc
        assert m.call_args.args[0] == "xoxe-old"          # used the OLD refresh token
        data = json.loads(tok.read_text(encoding="utf-8"))
        assert data["user_token"] == "xoxp-NEW"           # access token rotated
        assert data["user_refresh_token"] == "xoxe-NEW"   # refresh token rotated
        assert data["expires_at"] != "2000-01-01T00:00:00+00:00"  # expiry advanced
        env = (tok.with_suffix(".env.sh")).read_text(encoding="utf-8")
        assert "xoxp-NEW" in env
        print("ok: refresh_rotates_token")


def test_sealed_secret_is_decrypted():
    if not _WINDOWS:
        print("skip: sealed_secret_is_decrypted (DPAPI is Windows-only)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        os.environ["USERPROFILE"] = str(home)
        os.environ["HOME"] = str(home)
        _seed(home, secret="TOPSECRET", sealed=True)
        resp = {"ok": True, "access_token": "xoxp-NEW", "refresh_token": "xoxe-NEW",
                "expires_in": 43200}
        with mock.patch.object(sr, "_refresh_one", return_value=resp) as m:
            rc = _run(["--skill", "slack"])
        assert rc == 0, rc
        # third positional arg to _refresh_one is the client_secret it will send
        assert m.call_args.args[2] == "TOPSECRET", "DPAPI-sealed secret must be decrypted"
        print("ok: sealed_secret_is_decrypted")


def test_dead_token_triggers_reauth():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        os.environ["USERPROFILE"] = str(home)
        os.environ["HOME"] = str(home)
        _seed(home)
        with mock.patch.object(sr, "_refresh_one",
                               return_value={"ok": False, "error": "invalid_grant"}), \
             mock.patch.object(sr, "_reauth", return_value=0) as reauth:
            rc = _run(["--skill", "slack"])
        assert rc == 0, rc
        assert reauth.called, "browser re-auth fallback should fire on invalid_grant"
        print("ok: dead_token_triggers_reauth")


def test_partial_failure_persists_earlier_rotation():
    """user token rotates OK, then bot token refresh fails -> the already-rotated
    (single-use) user token MUST be on disk, or the install can't refresh again."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        os.environ["USERPROFILE"] = str(home)
        os.environ["HOME"] = str(home)
        d = home / ".claude" / "companies" / "amira" / "data" / "tokens" / "slack"
        d.mkdir(parents=True, exist_ok=True)
        tok = d / "slack.json"
        tok.write_text(json.dumps({
            "ok": True, "user_token": "xoxp-old", "user_refresh_token": "xoxe-u-old",
            "bot_token": "xoxb-old", "bot_refresh_token": "xoxe-b-old",
            "client_id": "cid", "scopes": "chat:write",
        }), encoding="utf-8")
        (d / "slack-app-creds.json").write_text(
            json.dumps({"client_id": "cid", "client_secret": "sek"}), encoding="utf-8")
        ok = {"ok": True, "access_token": "xoxp-NEW", "refresh_token": "xoxe-u-NEW", "expires_in": 43200}
        bad = {"ok": False, "error": "some_transient_error"}
        with mock.patch.object(sr, "_refresh_one", side_effect=[ok, bad]):
            rc = _run(["--skill", "slack"])
        assert rc == 1, rc  # overall failure (bot leg failed)
        data = json.loads(tok.read_text(encoding="utf-8"))
        assert data["user_token"] == "xoxp-NEW", data["user_token"]          # persisted
        assert data["user_refresh_token"] == "xoxe-u-NEW", data["user_refresh_token"]
        print("ok: partial_failure_persists_earlier_rotation")


def test_refresh_one_parses_http_error_body():
    """Slack OAuth errors can arrive as a non-2xx with a JSON body; _refresh_one
    must surface {error} so the invalid_grant reauth branch can fire."""
    import io
    import urllib.error
    err = urllib.error.HTTPError(
        "https://slack.com/api/oauth.v2.access", 400, "Bad Request", {},
        io.BytesIO(b'{"ok":false,"error":"invalid_grant"}'))
    with mock.patch.object(sr.urllib.request, "urlopen", side_effect=err):
        resp = sr._refresh_one("rt", "cid", "sek")
    assert resp.get("error") == "invalid_grant", resp
    print("ok: refresh_one_parses_http_error_body")


def test_undecryptable_secret_reports_cause():
    """A stored-but-undecryptable secret must surface the real cause, not the
    misleading 'no secret -- go store it' (the round-2 review-gate finding)."""
    if not _WINDOWS:
        print("skip: undecryptable_secret_reports_cause (DPAPI is Windows-only)")
        return
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        os.environ["USERPROFILE"] = str(home)
        os.environ["HOME"] = str(home)
        d = home / ".claude" / "companies" / "amira" / "data" / "tokens" / "slack"
        d.mkdir(parents=True, exist_ok=True)
        (d / "slack.json").write_text(json.dumps({
            "ok": True, "user_token": "xoxp-old", "user_refresh_token": "xoxe-old", "client_id": "cid",
        }), encoding="utf-8")
        (d / "slack-app-creds.json").write_text(json.dumps({
            "client_id": "cid",
            "client_secret_dpapi": base64.b64encode(b"not-a-real-dpapi-blob").decode("ascii"),
        }), encoding="utf-8")
        creds = slack_secret.load_client_creds("amira", "slack")
        assert "client_secret" not in creds, creds
        assert creds.get("client_secret_error"), creds
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = _run(["--skill", "slack"])
        assert rc == 1, rc
        assert "could not be decrypted" in buf.getvalue(), buf.getvalue()
        print("ok: undecryptable_secret_reports_cause")


def test_corrupt_creds_signals_error_without_id():
    """Corrupt creds file -> client_secret_error and NO client_id, so slack_oauth's
    guard fires instead of silently defaulting to the official app (round-3 High)."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        os.environ["USERPROFILE"] = str(home)
        os.environ["HOME"] = str(home)
        d = home / ".claude" / "companies" / "amira" / "data" / "tokens" / "slack"
        d.mkdir(parents=True, exist_ok=True)
        (d / "slack-app-creds.json").write_text("{ this is not valid json", encoding="utf-8")
        creds = slack_secret.load_client_creds("amira", "slack")
        assert "client_id" not in creds, creds
        assert creds.get("client_secret_error"), creds
        print("ok: corrupt_creds_signals_error_without_id")


def test_missing_client_id_errors():
    """No client_id in creds store or token file -> clear error, not an opaque
    invalid_client_id from Slack (round-3 finding #2)."""
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        os.environ["USERPROFILE"] = str(home)
        os.environ["HOME"] = str(home)
        d = home / ".claude" / "companies" / "amira" / "data" / "tokens" / "slack"
        d.mkdir(parents=True, exist_ok=True)
        (d / "slack.json").write_text(json.dumps({
            "ok": True, "user_token": "xoxp-old", "user_refresh_token": "xoxe-old",
        }), encoding="utf-8")  # no client_id, no creds file
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = _run(["--skill", "slack"])
        assert rc == 1, rc
        assert "no client_id" in buf.getvalue(), buf.getvalue()
        print("ok: missing_client_id_errors")


def test_resolve_client_logic():
    """slack_oauth._resolve_client: explicit --client-id escapes the creds-error
    abort; a corrupt/undecryptable store aborts only on the fallback path."""
    import slack_oauth as so
    OFF = so.OFFICIAL_CLIENT_ID
    # no creds -> official, no error
    assert so._resolve_client(None, "", {}) == (OFF, "", None)
    # normal custom store -> uses stored id + secret
    assert so._resolve_client(None, "", {"client_id": "C", "client_secret": "S"}) == ("C", "S", None)
    # corrupt store (error, no id), default resolution -> abort; id defaults to official
    cid, sec, err = so._resolve_client(None, "", {"client_secret_error": "corrupt"})
    assert cid == OFF and err == "corrupt"
    # decrypt-fail store (error + custom id), default -> abort
    cid, sec, err = so._resolve_client(None, "", {"client_id": "C", "client_secret_error": "boom"})
    assert cid == "C" and err == "boom"
    # explicit CUSTOM id, no secret, broken store -> STILL abort (custom app needs a
    # secret; must not fall into PKCE-with-custom-app). The dangerous case.
    cid, sec, err = so._resolve_client("CUSTOM", "", {"client_secret_error": "x"})
    assert cid == "CUSTOM" and err == "x"
    # explicit OFFICIAL id, no secret, broken store -> allow (official PKCE needs no secret)
    cid, sec, err = so._resolve_client(OFF, "", {"client_secret_error": "x"})
    assert cid == OFF and err is None
    # explicit --client-secret provided -> no abort even with a store error
    cid, sec, err = so._resolve_client(None, "MYSECRET", {"client_secret_error": "x"})
    assert sec == "MYSECRET" and err is None
    print("ok: resolve_client_logic")


def test_missing_refresh_token_errors():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        os.environ["USERPROFILE"] = str(home)
        os.environ["HOME"] = str(home)
        _seed(home, refresh="")  # no refresh token stored
        rc = _run(["--skill", "slack"])
        assert rc == 1, "should error when no refresh token present"
        print("ok: missing_refresh_token_errors")


if __name__ == "__main__":
    test_refresh_rotates_token()
    test_sealed_secret_is_decrypted()
    test_dead_token_triggers_reauth()
    test_partial_failure_persists_earlier_rotation()
    test_refresh_one_parses_http_error_body()
    test_undecryptable_secret_reports_cause()
    test_corrupt_creds_signals_error_without_id()
    test_missing_client_id_errors()
    test_resolve_client_logic()
    test_missing_refresh_token_errors()
    print("ALL PASS")
