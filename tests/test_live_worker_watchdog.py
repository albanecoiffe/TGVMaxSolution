from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "live_worker" / "check_live_worker.py"
)
SPEC = importlib.util.spec_from_file_location("check_live_worker", MODULE_PATH)
check_live_worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_live_worker)


NOW = datetime(2026, 11, 19, 13, 0, 0, tzinfo=timezone.utc)


def _heartbeat(captured_at: str, **worker_overrides) -> dict:
    worker = {
        "status": "ok",
        "browser_open": True,
        "sncf_tab_ready": True,
        "last_error": None,
    }
    worker.update(worker_overrides)
    return {"has_worker": True, "captured_at": captured_at, "worker": worker}


def test_evaluate_worker_ok():
    ok, reasons = check_live_worker.evaluate_worker(
        _heartbeat("2026-11-19T12:59:30+00:00"), now=NOW, max_age_minutes=5
    )
    assert ok is True
    assert reasons == []


def test_evaluate_worker_stale_heartbeat():
    ok, reasons = check_live_worker.evaluate_worker(
        _heartbeat("2026-11-19T12:50:00+00:00"), now=NOW, max_age_minutes=5
    )
    assert ok is False
    assert any("heartbeat" in reason for reason in reasons)


def test_evaluate_worker_no_heartbeat():
    ok, reasons = check_live_worker.evaluate_worker({"has_worker": False}, now=NOW)
    assert ok is False
    assert reasons == ["aucun heartbeat worker recu"]


def test_evaluate_worker_tab_not_ready_and_error():
    ok, reasons = check_live_worker.evaluate_worker(
        _heartbeat(
            "2026-11-19T12:59:00+00:00",
            sncf_tab_ready=False,
            status="degraded",
            last_error="Replay impossible",
        ),
        now=NOW,
    )
    assert ok is False
    assert any("SNCF Connect" in reason for reason in reasons)
    assert any("degraded" in reason for reason in reasons)
    assert any("Replay impossible" in reason for reason in reasons)


def test_evaluate_worker_browser_closed():
    ok, reasons = check_live_worker.evaluate_worker(
        _heartbeat("2026-11-19T12:59:00+00:00", browser_open=False), now=NOW
    )
    assert ok is False
    assert any("ferme" in reason for reason in reasons)


def test_parse_iso_variants():
    assert check_live_worker.parse_iso("2026-11-19T12:00:00Z") == datetime(
        2026, 11, 19, 12, 0, tzinfo=timezone.utc
    )
    assert check_live_worker.parse_iso("2026-11-19T12:00:00+00:00") is not None
    assert check_live_worker.parse_iso("pas-une-date") is None
    assert check_live_worker.parse_iso(None) is None


def _live_payload() -> dict:
    return {
        "has_live_watch": True,
        "captured_at": "2026-11-19T13:00:00Z",
        "recent_activity": [
            {
                "route": "Paris Montparnasse → Bordeaux Saint-Jean",
                "watch_date": "2026-11-21",
                "type": "zero_day_added",
                "at": "2026-11-19T12:58:00Z",
                "details": {"count": 1, "days": ["2026-11-22"]},
            },
            {
                "route": "Paris Montparnasse → Bordeaux Saint-Jean",
                "watch_date": "2026-11-21",
                "type": "zero_added",
                "at": "2026-11-19T12:59:00Z",
                "details": {"count": 2, "travelIds": ["a", "b"]},
            },
            {
                "route": "Paris Montparnasse → Bordeaux Saint-Jean",
                "watch_date": "2026-11-21",
                "type": "check_ok",
                "at": "2026-11-19T12:59:30Z",
                "details": {"zeroOfferCount": 2},
            },
            {
                "route": "Paris → Lyon",
                "watch_date": "2026-11-23",
                "type": "zero_added",
                "at": "2026-11-19T11:00:00Z",
                "details": {"count": 1},
            },
        ],
    }


def test_extract_recent_zero_alerts_filters_type_and_window():
    alerts = check_live_worker.extract_recent_zero_alerts(_live_payload(), now=NOW, window_minutes=5)
    types = [alert["type"] for alert in alerts]
    assert types == ["zero_added", "zero_day_added"]
    assert all(alert["route"] == "Paris Montparnasse → Bordeaux Saint-Jean" for alert in alerts)
    assert alerts[0]["details"]["travelIds"] == ["a", "b"]


def test_extract_recent_zero_alerts_empty_without_live_watch():
    assert check_live_worker.extract_recent_zero_alerts({"has_live_watch": False}, now=NOW) == []


def test_extract_recent_zero_alerts_custom_window():
    alerts = check_live_worker.extract_recent_zero_alerts(_live_payload(), now=NOW, window_minutes=200)
    assert len(alerts) == 3


def test_main_exit_codes_with_stubbed_fetch(monkeypatch, capsys):
    heartbeat = _heartbeat((NOW - timedelta(minutes=1)).isoformat())
    live = _live_payload()

    def fake_fetch(base_url, path, timeout=15.0):
        assert base_url == "http://test"
        return heartbeat if path == "/api/live-worker/latest" else live

    monkeypatch.setattr(check_live_worker, "fetch_json", fake_fetch)
    monkeypatch.setattr(check_live_worker, "datetime", type(check_live_worker.datetime))

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(check_live_worker, "datetime", FrozenDatetime)

    assert check_live_worker.main(["--base-url", "http://test", "--max-age-minutes", "5"]) == 2

    stale = _heartbeat((NOW - timedelta(minutes=30)).isoformat())

    def fake_fetch_stale(base_url, path, timeout=15.0):
        return stale if path == "/api/live-worker/latest" else {"has_live_watch": False}

    monkeypatch.setattr(check_live_worker, "fetch_json", fake_fetch_stale)
    assert check_live_worker.main(["--base-url", "http://test", "--max-age-minutes", "5"]) == 1

    def fake_fetch_ok(base_url, path, timeout=15.0):
        return heartbeat if path == "/api/live-worker/latest" else {"has_live_watch": False}

    monkeypatch.setattr(check_live_worker, "fetch_json", fake_fetch_ok)
    assert check_live_worker.main(["--base-url", "http://test", "--max-age-minutes", "5"]) == 0
