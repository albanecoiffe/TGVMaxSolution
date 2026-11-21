from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "refresh_and_alert.py"
SPEC = importlib.util.spec_from_file_location("refresh_and_alert", MODULE_PATH)
refresh_and_alert = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh_and_alert)


WATCH_DIFF = {
    "has_snapshot": True,
    "initialized": False,
    "captured_at": "2026-11-19T07:05:00+00:00",
    "generated_at": "2026-11-19T06:23:00+00:00",
    "current_zero_count": 64706,
    "previous_zero_count": 64700,
    "new_zero_count": 6,
    "removed_zero_count": 0,
    "sample_new_trips": [
        {
            "date": "2026-12-19",
            "train_no": "6641",
            "origin": "PARIS GARE DE LYON",
            "destination": "LYON PART DIEU",
            "departure_time": "06:00",
            "arrival_time": "08:00",
        }
    ],
    "sample_removed_trips": [],
}


def test_summarize_watch_extracts_diff():
    summary = refresh_and_alert.summarize_watch({"zero_watch": WATCH_DIFF}, "http://test")
    assert summary["has_snapshot"] is True
    assert summary["new_zero_count"] == 6
    assert summary["current_zero_count"] == 64706
    assert summary["sample_new_trips"][0]["train_no"] == "6641"
    assert summary["base_url"] == "http://test"


def test_build_issue_body_lists_new_trips():
    summary = refresh_and_alert.summarize_watch({"zero_watch": WATCH_DIFF}, "http://test")
    title, body = refresh_and_alert.build_issue_body(summary)
    assert "6 nouveau(x)" in title
    assert "PARIS GARE DE LYON -> LYON PART DIEU" in body
    assert "train 6641" in body


def test_maybe_create_issue_disabled_without_flag(monkeypatch):
    monkeypatch.delenv("ALERT_ON_NEW_ZERO", raising=False)
    summary = refresh_and_alert.summarize_watch({"zero_watch": WATCH_DIFF}, "http://test")
    assert refresh_and_alert.maybe_create_issue(summary, "owner/repo") is False


def test_maybe_create_issue_no_new_trips(monkeypatch):
    monkeypatch.setenv("ALERT_ON_NEW_ZERO", "true")
    watch = dict(WATCH_DIFF, new_zero_count=0, sample_new_trips=[])
    summary = refresh_and_alert.summarize_watch({"zero_watch": watch}, "http://test")
    assert refresh_and_alert.maybe_create_issue(summary, "owner/repo") is False


def test_maybe_create_issue_calls_gh_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ALERT_ON_NEW_ZERO", "true")
    calls = []

    class Result:
        returncode = 0
        stdout = "https://github.com/owner/repo/issues/42\n"
        stderr = ""

    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(refresh_and_alert.subprocess, "run", fake_run)

    import builtins

    real_open = builtins.open

    def fake_open(path, mode="r", *args, **kwargs):
        if str(path) == "/tmp/zero-issue-body.md":
            return real_open(tmp_path / "body.md", mode, *args, **kwargs)
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    summary = refresh_and_alert.summarize_watch({"zero_watch": WATCH_DIFF}, "http://test")
    assert refresh_and_alert.maybe_create_issue(summary, "owner/repo") is True
    assert calls[0][:4] == ["gh", "issue", "create", "--repo"]
    assert "owner/repo" in calls[0]


def test_main_returns_summary_and_zero_exit(monkeypatch, capsys):
    def fake_post(base_url, path, payload=None, timeout=180.0):
        assert path == "/api/refresh"
        return {"zero_watch": WATCH_DIFF}

    def fake_fetch(base_url, path, timeout=60.0):
        assert path == "/api/watch/latest"
        return WATCH_DIFF

    monkeypatch.setattr(refresh_and_alert, "post_json", fake_post)
    monkeypatch.setattr(refresh_and_alert, "fetch_json", fake_fetch)

    exit_code = refresh_and_alert.main(["--base-url", "http://test", "--no-issue"])
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["new_zero_count"] == 6
    assert output["base_url"] == "http://test"


def test_main_backend_down_returns_1(monkeypatch):
    def fake_post(base_url, path, payload=None, timeout=180.0):
        raise OSError("connection refused")

    monkeypatch.setattr(refresh_and_alert, "post_json", fake_post)
    assert refresh_and_alert.main(["--base-url", "http://down", "--no-issue"]) == 1
