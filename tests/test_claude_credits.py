"""Claude adapter and zero-extra-spend gates. Every provider call is mocked."""
import json
import os
import sqlite3
import sys
import time
from multiprocessing import get_context

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import aria_ai
from claude_credits import CreditBlocked, CreditConfig, CreditLedger

FAKE_KEY = "sk-ant-FAKE-only-testing-0000000000000000"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith(("ARIA_", "CLAUDE_", "GEMINI_", "ANTHROPIC_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARIA_AI_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("ARIA_CLAUDE_BUDGET_DB", str(tmp_path / "credits.db"))
    monkeypatch.setenv("ARIA_AI_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    aria_ai._minute.clear()
    aria_ai._leases.clear()
    def forbid_network(*args, **kwargs):
        raise AssertionError("A real provider request is forbidden in this suite")
    monkeypatch.setattr(requests.Session, "post", forbid_network)


def enable(monkeypatch, budget="1"):
    for key in ("ARIA_CLAUDE_ENABLED", "CLAUDE_PREPAID_ONLY_CONFIRMED", "CLAUDE_AUTO_RELOAD_DISABLED_CONFIRMED",
                "CLAUDE_NO_PURCHASED_CREDITS_CONFIRMED", "CLAUDE_ISOLATED_ALLOCATION_CONFIRMED", "CLAUDE_PRICING_CONFIRMED",
                "CLAUDE_PERSISTENT_LEDGER_CONFIRMED"):
        monkeypatch.setenv(key, "1")
    monkeypatch.setenv("CLAUDE_CREDIT_VERIFIED_AT", str(time.time() - 10))
    monkeypatch.setenv("CLAUDE_CREDIT_EXPIRES_AT", str(time.time() + 86400))
    monkeypatch.setenv("CLAUDE_CREDIT_PERIOD", "verified-cycle-2026-10")
    monkeypatch.setenv("ARIA_CLAUDE_CREDIT_BUDGET_USD", budget)
    CreditLedger(aria_ai.claude_config()).provision()


def client():
    app = FastAPI()
    app.include_router(aria_ai.router)
    return TestClient(app)


def ask(c, **extra):
    return c.post("/api/aria/ai/chat", json={"contents": [{"role": "user", "parts": [{"text": "Analyze the chart"}]}], **extra})


class FakeResponse:
    def __init__(self, status=200, events=()):
        self.status_code, self.events, self.closed = status, events, False
    def iter_lines(self, **kwargs):
        for event in self.events:
            if isinstance(event, Exception):
                raise event
            yield ("data: " + json.dumps(event)).encode()
    def close(self):
        self.closed = True


class FakeHTTP:
    def __init__(self, response=None, error=None):
        self.calls, self.response, self.error = [], response or FakeResponse(), error
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def stream_events(tool=False):
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 30}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Measured evidence."}},
        {"type": "content_block_stop", "index": 0},
    ]
    if tool:
        events.extend([
            {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_test", "name": "draw_analysis", "input": {}}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"layers":'}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '["zones"]}'}},
            {"type": "content_block_stop", "index": 1},
        ])
    events.extend([{"type": "message_delta", "delta": {"stop_reason": "tool_use" if tool else "end_turn"}, "usage": {"output_tokens": 20}},
                   {"type": "message_stop"}])
    return events


def run(provider, contents=None, **kw):
    return list(provider.stream_response(model="claude-sonnet-5-5", system=aria_ai.SYSTEM_PROMPT,
                contents=contents or [{"role": "user", "parts": [{"text": "Chart evidence"}]}],
                tools=aria_ai.TOOLS, max_out=100, thinking="medium", timeout=30, **kw))


def test_key_alone_never_enables_or_calls_claude(monkeypatch):
    c = client()
    assert c.get("/api/aria/ai/status").json()["enabled"] is False
    assert ask(c).status_code == 503
    enable(monkeypatch)
    monkeypatch.delenv("CLAUDE_AUTO_RELOAD_DISABLED_CONFIRMED")
    assert ask(c).status_code == 503


@pytest.mark.parametrize("key,value", [
    ("CLAUDE_CREDIT_VERIFIED_AT", "1"), ("CLAUDE_CREDIT_VERIFIED_AT", "nan"),
    ("CLAUDE_CREDIT_EXPIRES_AT", "1"), ("CLAUDE_CREDIT_EXPIRES_AT", "inf"),
    ("ARIA_CLAUDE_CREDIT_BUDGET_USD", "0"), ("ARIA_CLAUDE_CREDIT_BUDGET_USD", "NaN"),
    ("ARIA_CLAUDE_CREDIT_BUDGET_USD", "201"), ("CLAUDE_CREDIT_PERIOD", "new"),
    ("ARIA_CLAUDE_MODEL", "claude-latest"),
])
def test_bad_credit_configuration_fails_closed(monkeypatch, key, value):
    enable(monkeypatch)
    monkeypatch.setenv(key, value)
    assert ask(client()).status_code == 503


def test_future_attestation_and_near_expiry_fail_closed(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setenv("CLAUDE_CREDIT_VERIFIED_AT", str(time.time() + 100))
    assert not aria_ai.ai_state()["enabled"]
    monkeypatch.setenv("CLAUDE_CREDIT_VERIFIED_AT", str(time.time() - 1))
    monkeypatch.setenv("CLAUDE_CREDIT_EXPIRES_AT", str(time.time() + 299))
    assert not aria_ai.ai_state()["enabled"]


def test_claude_wire_format_tools_and_stream_round_trip(monkeypatch):
    enable(monkeypatch)
    provider = aria_ai.ClaudeProvider(FAKE_KEY)
    provider._http = FakeHTTP(FakeResponse(events=stream_events(tool=True)))
    events = run(provider)
    url, call = provider._http.calls[0]
    assert url == "https://api.anthropic.com/v1/messages" and FAKE_KEY not in url
    assert call["headers"]["x-api-key"] == FAKE_KEY
    assert call["headers"]["anthropic-version"] == "2023-06-01"
    assert call["allow_redirects"] is False
    body = call["json"]
    assert body["system"] == aria_ai.SYSTEM_PROMPT and body["thinking"] == {"type": "disabled"}
    assert body["max_tokens"] == 100 and body["stream"] is True
    assert "cache_control" not in body and "metadata" not in body and "fallback_models" not in body
    assert {t["name"] for t in body["tools"]} == aria_ai.TOOL_NAMES
    assert all("input_schema" in t for t in body["tools"])
    assert events[-1]["usage"] == {"input_tokens": 30, "output_tokens": 20}
    call = [e["call"] for e in events if e["type"] == "call"][0]
    assert call == {"id": "toolu_test", "name": "draw_analysis", "args": {"layers": ["zones"]}}
    contents = [{"role": "user", "parts": [{"text": "Draw"}]}, events[-1]["content"],
                {"role": "user", "parts": [{"functionResponse": {"name": "draw_analysis", "response": {"ok": True}}}]}]
    converted = provider._body("claude-sonnet-5-5", "SYS", contents, [], 80)
    assert converted["messages"][-1]["content"][0]["tool_use_id"] == "toolu_test"
    assert converted["messages"][-2]["content"][-1]["id"] == "toolu_test"
    assert FAKE_KEY not in json.dumps(events)
    assert not provider.get_capabilities()["live_voice"]


def test_unmatched_tool_result_is_refused_before_reservation(monkeypatch):
    enable(monkeypatch)
    provider = aria_ai.ClaudeProvider(FAKE_KEY)
    provider._http = FakeHTTP()
    with pytest.raises(aria_ai.ProviderError):
        run(provider, [{"role": "user", "parts": [{"functionResponse": {"name": "draw_analysis", "response": {"ok": True}}}]}])
    assert provider._http.calls == []


def test_timeout_is_reserved_once_never_retried_or_falls_back(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setenv("ARIA_AI_GEMINI_FALLBACK", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKE-non-secret-testing-0000000")
    monkeypatch.setenv("GEMINI_FREE_TIER_CONFIRMED", "1")
    http = FakeHTTP(error=requests.Timeout(FAKE_KEY))
    original = aria_ai.ClaudeProvider.__init__
    def init(self, key):
        original(self, key); self._http = http
    monkeypatch.setattr(aria_ai.ClaudeProvider, "__init__", init)
    response = ask(client())
    assert len(http.calls) == 1 and "timeout" in response.text and FAKE_KEY not in response.text
    config = aria_ai.claude_config()
    assert CreditLedger(config).available() < config.budget


def test_insufficient_reservation_sends_no_request(monkeypatch):
    enable(monkeypatch, "0.000001")
    provider = aria_ai.ClaudeProvider(FAKE_KEY)
    provider._http = FakeHTTP()
    with pytest.raises(aria_ai.ProviderError) as exc:
        run(provider)
    assert exc.value.kind == "credit" and provider._http.calls == []


def test_fallback_is_explicit_free_tier_only_and_not_during_tool_round(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKE-non-secret-testing-0000000")
    monkeypatch.setenv("GEMINI_FREE_TIER_CONFIRMED", "1")
    assert not aria_ai.ai_state()["enabled"]
    monkeypatch.setenv("ARIA_AI_GEMINI_FALLBACK", "1")
    assert aria_ai.ai_state()["provider"] == "gemini"
    assert ask(client(), round=1, model="claude-sonnet-5-5").status_code == 409
    monkeypatch.setenv("GEMINI_FREE_TIER_CONFIRMED", "0")
    assert not aria_ai.ai_state()["enabled"]


def test_status_and_voice_match_claude_without_secrets(monkeypatch):
    enable(monkeypatch)
    c = client()
    status = c.get("/api/aria/ai/status").json()
    assert status["provider"] == "claude" and status["live_voice"] is False
    assert status["label"] == "Claude (promotional credits)"
    assert FAKE_KEY not in json.dumps(status) and "Claude" in status["privacy"]
    assert c.post("/api/aria/ai/voice/session").status_code == 403


def test_persistent_reservations_cannot_expand_cap_or_expiry(monkeypatch):
    enable(monkeypatch)
    config = aria_ai.claude_config()
    CreditLedger(config).reserve(config.budget - 1)
    monkeypatch.setenv("ARIA_CLAUDE_CREDIT_BUDGET_USD", "10")
    monkeypatch.setenv("CLAUDE_CREDIT_EXPIRES_AT", str(config.expires + 86400))
    newer = aria_ai.claude_config()
    assert CreditLedger(newer).available() == 1
    with pytest.raises(CreditBlocked):
        CreditLedger(newer).reserve(2)
    with sqlite3.connect(newer.path) as db:
        row = db.execute("SELECT cap,reserved,expires FROM claude_allowance").fetchone()
    assert row == (config.budget, config.budget - 1, config.expires)


def _reserve_process(config, amount, queue):
    try:
        CreditLedger(config).reserve(amount); queue.put(True)
    except CreditBlocked:
        queue.put(False)


def test_atomic_cross_process_reservations(monkeypatch):
    enable(monkeypatch, "0.01")
    config = aria_ai.claude_config()
    context = get_context("spawn")
    queue = context.Queue()
    processes = [context.Process(target=_reserve_process, args=(config, 6000, queue)) for _ in range(4)]
    for process in processes: process.start()
    results = [queue.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(20); assert process.exitcode == 0
    assert results.count(True) == 1
    assert CreditLedger(config).available() == 4000


def test_cost_reservation_covers_system_history_tools_context_and_output(monkeypatch):
    enable(monkeypatch)
    config = aria_ai.claude_config()
    base = {"model": config.model, "max_tokens": 100, "system": "s", "messages": []}
    large = dict(base, system="α" * 1000, messages=[{"role": "user", "content": "history" * 2000}], tools=aria_ai.TOOLS)
    assert config.reserve_cost(large) > config.reserve_cost(base)
    assert config.reserve_cost(dict(base, max_tokens=4096)) > config.reserve_cost(base)
    with pytest.raises(CreditBlocked): config.reserve_cost(dict(base, max_tokens=4097))
    with pytest.raises(CreditBlocked): config.reserve_cost(dict(base, model="claude-unknown"))


def test_cut_off_stream_and_server_error_do_not_refund_or_retry(monkeypatch):
    enable(monkeypatch)
    provider = aria_ai.ClaudeProvider(FAKE_KEY)
    for response in [FakeResponse(events=stream_events()[:-1]), FakeResponse(status=503)]:
        provider._http = FakeHTTP(response)
        with pytest.raises(aria_ai.ProviderError): run(provider)
        assert len(provider._http.calls) == 1 and response.closed
    config = aria_ai.claude_config()
    assert CreditLedger(config).available() < config.budget


def test_missing_ledger_or_period_never_resets_allowance(monkeypatch):
    enable(monkeypatch)
    config = aria_ai.claude_config()
    CreditLedger(config).reserve(1)
    os.unlink(config.path)
    assert ask(client()).status_code == 503
    assert not os.path.exists(config.path)
    CreditLedger(config).provision()
    monkeypatch.setenv("CLAUDE_CREDIT_PERIOD", "unverified-new-cycle")
    assert ask(client()).status_code == 503


def test_redirect_does_not_forward_key_or_retry(monkeypatch):
    enable(monkeypatch)
    provider = aria_ai.ClaudeProvider(FAKE_KEY)
    provider._http = FakeHTTP(FakeResponse(status=302))
    with pytest.raises(aria_ai.ProviderError): run(provider)
    assert len(provider._http.calls) == 1
    assert provider._http.calls[0][1]["allow_redirects"] is False


def test_tiny_remaining_credit_falls_back_only_before_request(monkeypatch):
    enable(monkeypatch, "0.000001")
    monkeypatch.setenv("ARIA_AI_GEMINI_FALLBACK", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKE-non-secret-testing-0000000")
    monkeypatch.setenv("GEMINI_FREE_TIER_CONFIRMED", "1")
    seen = []
    def only_gemini(name):
        seen.append(name); return aria_ai.MockProvider()
    monkeypatch.setattr(aria_ai, "provider", only_gemini)
    response = ask(client())
    assert seen == ["gemini"] and '"provider":"gemini"' in response.text
    assert CreditLedger(aria_ai.claude_config()).available() == 1


def test_claude_model_change_rejects_tool_round_before_request(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setenv("ARIA_CLAUDE_MODEL", "claude-sonnet-4-6")
    assert ask(client(), round=1, model="claude-sonnet-5-5").status_code == 409


def test_claude_timeout_cannot_exceed_credit_expiry_margin(monkeypatch):
    enable(monkeypatch)
    provider = aria_ai.ClaudeProvider(FAKE_KEY)
    provider._http = FakeHTTP(FakeResponse(events=stream_events()))
    list(provider.stream_response(model="claude-sonnet-5-5", system="sys",
         contents=[{"role": "user", "parts": [{"text": "hi"}]}], tools=[], max_out=100,
         thinking=None, timeout=10000))
    assert provider._http.calls[0][1]["timeout"] == (10, 60.0)


def test_preflight_gemini_fallback_keeps_its_tool_round(monkeypatch):
    enable(monkeypatch, "0.000001")
    monkeypatch.setenv("ARIA_AI_GEMINI_FALLBACK", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKE-non-secret-testing-0000000")
    monkeypatch.setenv("GEMINI_FREE_TIER_CONFIRMED", "1")
    providers = []
    def only_gemini(name):
        providers.append(name); return aria_ai.MockProvider()
    monkeypatch.setattr(aria_ai, "provider", only_gemini)
    aria_ai.MockProvider.script.append({"parts": [{"functionCall": {"name": "draw_analysis", "args": {"layers": ["zones"]}}}]})
    c = client()
    first = ask(c)
    events = [json.loads(line[6:]) for line in first.text.splitlines() if line.startswith("data: ")]
    model = events[0]["model"]
    content = events[-1]["content"]
    contents = [{"role": "user", "parts": [{"text": "Draw zones"}]}, content,
                {"role": "user", "parts": [{"functionResponse": {"name": "draw_analysis", "response": {"ok": True}}}]}]
    second = c.post("/api/aria/ai/chat", json={"contents": contents, "round": 1, "model": model})
    assert second.status_code == 200 and '"provider":"gemini"' in second.text
    assert providers == ["gemini", "gemini"] and "event: done" in second.text
    assert CreditLedger(aria_ai.claude_config()).available() == 1
