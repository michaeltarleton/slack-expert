#!/usr/bin/env python3
"""Self-check for slack_post. Run: python test_slack_post.py"""
import contextlib
import io
import sys
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import slack_post as sp


def test_token_path_mirrors_slack_refresh_with_skill():
    p = sp._token_path("amira", "slack")
    assert str(p).endswith(str(Path("companies") / "amira" / "data" / "tokens" / "slack" / "slack.json")), p
    print("ok: token_path_mirrors_slack_refresh_with_skill")


def test_token_path_mirrors_slack_refresh_legacy_empty_skill():
    """skill == '' must fall back to .../data/slack/token.json, matching
    slack_refresh.py's _token_path -- previously this script always produced
    tokens/slack/.json instead (Copilot review finding)."""
    p = sp._token_path("amira", "")
    assert str(p).endswith(str(Path("companies") / "amira" / "data" / "slack" / "token.json")), p
    print("ok: token_path_mirrors_slack_refresh_legacy_empty_skill")


def test_call_parses_http_error_body():
    err = urllib.error.HTTPError(
        "https://slack.com/api/chat.postMessage", 400, "Bad Request", {},
        io.BytesIO(b'{"ok":false,"error":"channel_not_found"}'),
    )
    with mock.patch.object(sp.urllib.request, "urlopen", side_effect=err):
        resp = sp._call("chat.postMessage", "xoxp-tok", {"channel": "C1", "text": "hi"})
    assert resp.get("error") == "channel_not_found", resp
    print("ok: call_parses_http_error_body")


def test_call_falls_back_when_error_body_not_json():
    err = urllib.error.HTTPError(
        "https://slack.com/api/chat.postMessage", 500, "Internal Server Error", {},
        io.BytesIO(b"not json"),
    )
    with mock.patch.object(sp.urllib.request, "urlopen", side_effect=err):
        resp = sp._call("chat.postMessage", "xoxp-tok", {})
    assert resp == {"ok": False, "error": "http_500"}, resp
    print("ok: call_falls_back_when_error_body_not_json")


AMIRA = "amiralearning.slack.com"


def test_permalink_plain():
    link = sp._permalink(AMIRA, "C0123456", "1776114430.309819")
    assert link == "https://amiralearning.slack.com/archives/C0123456/p1776114430309819", link
    assert "thread_ts" not in link
    print("ok: permalink_plain")


def test_permalink_thread_reply():
    link = sp._permalink(AMIRA, "C0123456", "1776114430.309819", thread_ts="1776114400.100000")
    assert link == (
        "https://amiralearning.slack.com/archives/C0123456/p1776114430309819"
        "?thread_ts=1776114400.100000&cid=C0123456"
    ), link
    print("ok: permalink_thread_reply")


def test_company_flag_accepted_after_subcommand():
    """SKILL.md documents `post --company X ...`. On the top-level parser argparse rejects
    that with exit 2, so the flags live on each subparser."""
    for argv in (["post", "--company", "amira", "--channel", "C1", "--text", "hi"],
                 ["update", "--company", "amira", "--channel", "C1",
                  "--update-ts", "1.2", "--text", "hi"],
                 ["delete", "--company", "amira", "--channel", "C1", "--delete-ts", "1.2"]):
        args = _parse(argv)
        assert args.company == "amira", argv
    print("ok: company_flag_accepted_after_subcommand")


def test_company_flag_value_survives_parsing():
    args = _parse(["post", "--company", "acme", "--skill", "other",
                   "--channel", "C1", "--text", "hi"])
    assert args.company == "acme" and args.skill == "other"
    print("ok: company_flag_value_survives_parsing")


def test_workspace_host_resolves_per_company():
    args = _parse(["post", "--company", "amira", "--channel", "C1", "--text", "hi"])
    assert sp._workspace_host(args) == AMIRA
    print("ok: workspace_host_resolves_per_company")


def test_unknown_company_is_rejected_not_defaulted():
    """A wrong permalink host is worse than an error: the post succeeds and the reported
    link silently points at another workspace."""
    args = _parse(["post", "--company", "acme", "--channel", "C1", "--text", "hi"])
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            sp._workspace_host(args)
    except SystemExit as e:
        assert e.code == 1
        assert "acme" in buf.getvalue()
        print("ok: unknown_company_is_rejected_not_defaulted")
        return
    raise AssertionError("expected SystemExit for unknown company")


def test_token_file_does_not_imply_a_workspace_host():
    """An explicit --token-file still can't tell us which workspace the token belongs to, so
    an unknown company must still error -- but the message must say so rather than claim
    --company selected the token file."""
    args = _parse(["post", "--company", "acme", "--token-file", "/tmp/t.json",
                   "--channel", "C1", "--text", "hi"])
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            sp._workspace_host(args)
    except SystemExit:
        msg = buf.getvalue()
        assert "--token-file does not imply a host" in msg, msg
        assert "--workspace-host" in msg
        print("ok: token_file_does_not_imply_a_workspace_host")
        return
    raise AssertionError("expected SystemExit")


def test_workspace_host_override_wins():
    args = _parse(["post", "--company", "acme", "--workspace-host", "acme.slack.com",
                   "--channel", "C1", "--text", "hi"])
    assert sp._workspace_host(args) == "acme.slack.com"
    print("ok: workspace_host_override_wins")


def test_cmd_update_warns_on_watermark_like_post_does():
    args = _parse(["update", "--company", "amira", "--channel", "C1",
                   "--update-ts", "1.2", "--text", "edited"])
    resp = {"ok": True, "ts": "1.2", "channel": "C1",
            "message": {"app_id": sp.WATERMARK_APP_ID}}
    err, out = io.StringIO(), io.StringIO()
    with mock.patch.object(sp, "_load_user_token", return_value="xoxp-x"), \
            mock.patch.object(sp, "_call", return_value=resp), \
            contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        rc = sp.cmd_update(args)
    assert rc == 0, "a successful write must not exit non-zero -- a retry would double-post"
    assert sp.WATERMARK_APP_ID in err.getvalue(), err.getvalue()
    print("ok: cmd_update_warns_on_watermark_like_post_does")


def _fake_stdin(text: str):
    """_resolve_text reads sys.stdin.buffer (raw bytes, explicit UTF-8 decode)
    rather than sys.stdin.read() (ambient-encoding text), so tests must mock
    an object exposing .buffer, not a plain io.StringIO."""
    m = mock.Mock()
    m.buffer = io.BytesIO(text.encode("utf-8"))
    return m


def _parse(argv):
    """Parse with the PRODUCTION parser. This used to reconstruct an equivalent parser,
    which is how `post --company X` shipped broken: the copy accepted it, the real CLI
    exited 2. Never mirror the parser here."""
    return sp.build_parser().parse_args(argv)


def test_text_stdin_preserves_shell_metacharacters():
    tricky = 'has `backticks`, $VARS, "quotes", and -leading-dash-words, plus em-dash: —'
    args = _parse(["post", "--channel", "C1", "--text-stdin"])
    with mock.patch.object(sys, "stdin", _fake_stdin(tricky + "\n")):
        text = sp._resolve_text(args)
    assert text == tricky, text
    print("ok: text_stdin_preserves_shell_metacharacters")


def test_text_stdin_strips_trailing_newlines_like_shell_substitution():
    """Matches bash $(...)/heredoc conventions: trailing newlines (added by the
    heredoc terminator, not authored content) are stripped; interior blank
    lines are preserved."""
    args = _parse(["post", "--channel", "C1", "--text-stdin"])
    with mock.patch.object(sys, "stdin", _fake_stdin("line one\n\nline two\n\n\n")):
        text = sp._resolve_text(args)
    assert text == "line one\n\nline two", repr(text)
    print("ok: text_stdin_strips_trailing_newlines_like_shell_substitution")


def test_text_flag_still_works():
    args = _parse(["post", "--channel", "C1", "--text", "hello world"])
    assert sp._resolve_text(args) == "hello world"
    print("ok: text_flag_still_works")


def test_both_text_flags_errors():
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            _parse(["post", "--channel", "C1", "--text", "a", "--text-stdin"])
            raised = False
        except SystemExit:
            raised = True
    assert raised, "argparse must reject --text and --text-stdin together"
    print("ok: both_text_flags_errors")


def test_neither_text_flag_errors():
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            _parse(["post", "--channel", "C1"])
            raised = False
        except SystemExit:
            raised = True
    assert raised, "argparse must require exactly one of --text/--text-stdin"
    print("ok: neither_text_flag_errors")


def test_update_also_requires_exactly_one_text_flag():
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            _parse(["update", "--channel", "C1", "--update-ts", "1.1"])
            raised = False
        except SystemExit:
            raised = True
    assert raised, "update subcommand must also require --text/--text-stdin"
    print("ok: update_also_requires_exactly_one_text_flag")


def test_leading_dash_text_via_stdin_is_unaffected_by_argparse():
    """The LOW finding: argparse rejects a bare leading-dash token passed to
    --text (e.g. --text "-oops"). --text-stdin sidesteps this entirely since
    the value never goes through argv parsing."""
    args = _parse(["post", "--channel", "C1", "--text-stdin"])
    with mock.patch.object(sys, "stdin", _fake_stdin("-oops\n")):
        text = sp._resolve_text(args)
    assert text == "-oops", text
    print("ok: leading_dash_text_via_stdin_is_unaffected_by_argparse")


def test_cmd_post_watermark_match_warns_but_returns_zero():
    """The core HIGH fix: a watermarked app_id on the message actually posted
    (echoed in the chat.postMessage response, not a re-fetch) must WARN on
    stderr and still return 0 -- never fail a send that already succeeded,
    since a retrying caller would double-post."""
    def fake_call(method, token, payload):
        assert method == "chat.postMessage"
        return {"ok": True, "ts": "1776114430.309819", "channel": "C1",
                "message": {"app_id": sp.WATERMARK_APP_ID}}

    args = _parse(["post", "--channel", "C1", "--text", "hi"])
    stdout, stderr = io.StringIO(), io.StringIO()
    with mock.patch.object(sp, "_load_user_token", return_value="xoxp-fake"), \
         mock.patch.object(sp, "_call", side_effect=fake_call), \
         contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        rc = sp.cmd_post(args)
    assert rc == 0, rc
    assert "WARNING" in stderr.getvalue(), stderr.getvalue()
    assert "ok ts=1776114430.309819" in stdout.getvalue(), stdout.getvalue()
    print("ok: cmd_post_watermark_match_warns_but_returns_zero")


def test_cmd_post_clean_message_no_warning():
    def fake_call(method, token, payload):
        return {"ok": True, "ts": "1776114430.309819", "channel": "C1",
                "message": {"app_id": ""}}

    args = _parse(["post", "--channel", "C1", "--text", "hi"])
    stderr = io.StringIO()
    with mock.patch.object(sp, "_load_user_token", return_value="xoxp-fake"), \
         mock.patch.object(sp, "_call", side_effect=fake_call), \
         contextlib.redirect_stderr(stderr):
        rc = sp.cmd_post(args)
    assert rc == 0, rc
    assert stderr.getvalue() == "", stderr.getvalue()
    print("ok: cmd_post_clean_message_no_warning")


if __name__ == "__main__":
    # Discover, never hand-list. A hand-maintained call list silently skips any test added
    # without also editing the list, and still prints ALL PASS.
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print("FAIL " + name + ": " + str(e))
        except KeyboardInterrupt:
            # The BaseException handler below exists to catch SystemExit; it must NOT
            # swallow Ctrl+C, which would log one ERROR per test and grind on.
            raise
        except SystemExit as e:
            # SystemExit is a BaseException, so a bare `except Exception` lets it unwind the
            # runner: remaining tests never execute and no summary prints. The module under
            # test calls sys.exit() in _load_user_token and _workspace_host, so this is
            # reachable, and it would look like a pass to anything reading stdout.
            failed += 1
            print("ERROR " + name + ": unexpected SystemExit(" + str(e.code) + ")")
        except BaseException as e:  # noqa: BLE001
            failed += 1
            print("ERROR " + name + ": " + repr(e))
    print(("ALL PASS (%d)" % len(tests)) if not failed
          else ("%d of %d FAILED" % (failed, len(tests))))
    sys.exit(1 if failed else 0)
