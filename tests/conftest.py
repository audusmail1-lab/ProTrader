"""pytest collects the unit suites only.

The *_browser.py files are stand-alone Playwright scripts (python3 tests/x_browser.py):
they start servers and patch providers at import time, so collecting them would
run that setup and, in test_aria_claude_voice_browser, replace the Gemini
provider's streaming for every suite imported after it (the Gemini parsing
tests then saw no request). They are run on their own, never through pytest."""
import glob
import os
from collections import OrderedDict
from unittest.mock import patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
collect_ignore = [os.path.basename(p) for p in glob.glob(os.path.join(HERE, "*_browser.py"))] + ["deriv_replay_server.py"]


@pytest.fixture(autouse=True)
def restore_test_environment():
    """A test changing an owner key must not change later tests' permissions."""
    with patch.dict(os.environ):
        yield


@pytest.fixture(autouse=True)
def isolate_legacy_service_fixtures(request, monkeypatch, tmp_path):
    """Legacy script-style suites share imported service modules under pytest.

    Give their stateful scenarios a fresh store and tracker, restoring the
    original objects afterward. This preserves the production behavior while
    preventing an earlier ticket, account owner, or stub from satisfying or
    breaking a later scenario.
    """
    name = request.module.__name__.rsplit(".", 1)[-1]
    if name in {"test_reliability", "test_mt5_tracking", "test_drift"}:
        import sentinel
        import sentinel_live
        import mt5_bridge
        import drift

        monkeypatch.setattr(sentinel, "DB_PATH", str(tmp_path / "sentinel.db"))
        monkeypatch.setattr(sentinel, "_mt5_open", {})
        monkeypatch.setattr(sentinel, "_mt5_state", {"loaded": False, "last": 0.0, "deals": [], "deals_at": 0.0})
        monkeypatch.setattr(sentinel, "_owner_cache", {"v": None, "at": 0.0})
        monkeypatch.setattr(sentinel, "_trend_cache", {})
        monkeypatch.setattr(mt5_bridge, "_channels", OrderedDict())
        monkeypatch.setattr(sentinel_live, "_telegram", sentinel_live._telegram)
        monkeypatch.setattr(drift, "_state", {"last_run": None, "last_error": None, "candles": {}, "ticks": {}, "notes": []})
        sentinel_live.attach(sentinel, mt5_bridge)
        drift.attach(sentinel)
        if name == "test_drift":
            monkeypatch.setenv("SENTINEL_ADMIN_KEY", "o" * 32)

    if name in {"test_notify", "test_notify_watcher"}:
        import notify

        monkeypatch.setattr(notify, "STATE_PATH", str(tmp_path / "notify.json"))
        monkeypatch.setattr(notify, "_state", {"devices": {}, "tg_codes": {}})
        # Those script-style tests assign these callbacks directly. Register
        # their originals before the assignments so they cannot leak.
        monkeypatch.setattr(notify, "_save", notify._save)
        monkeypatch.setattr(notify, "_deliver", notify._deliver)
        monkeypatch.setattr(notify._feed, "want", notify._feed.want)
