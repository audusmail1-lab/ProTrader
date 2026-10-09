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
    # Sonnet 5.5 refuses {"type": "disabled"}; its lowest setting is between_tools at effort <= high
    assert body["system"] == aria_ai.SYSTEM_PROMPT and body["thinking"] == {"type": "between_tools"}
    assert body["output_config"] == {"effort": "medium"}
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
    assert status["label"] == "Claude Sonnet 5.5 (Anthropic API, promotional credits)"
    assert "does not use API inputs or outputs to train" in status["privacy"]
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


# ── reasoning configuration and Claude's reasoning blocks ─────────────────────

def test_thinking_settings_follow_each_models_documented_rules(monkeypatch):
    # Sonnet 5.5 rejects "disabled" (400); between_tools is its lowest setting, valid only at effort <= high.
    assert aria_ai.claude_thinking("claude-sonnet-5-5", "low") == {"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}}
    # Haiku 5.5 accepts "disabled" at effort <= high.
    assert aria_ai.claude_thinking("claude-haiku-5-5", "medium") == {"thinking": {"type": "disabled"}, "output_config": {"effort": "medium"}}
    # 4.x models think only when asked: neither field is sent.
    assert aria_ai.claude_thinking("claude-sonnet-4-6", "medium") == {}
    # never xhigh/max (both turn the lowest settings into a 400)
    for bad in ("xhigh", "max", "", None, "extreme"):
        assert aria_ai.claude_thinking("claude-sonnet-5-5", bad)["output_config"] == {"effort": "low"}
    monkeypatch.setenv("ARIA_CLAUDE_THINKING", "adaptive")
    assert aria_ai.claude_thinking("claude-sonnet-5-5", "medium")["thinking"] == {"type": "adaptive"}
    enable(monkeypatch)
    assert aria_ai.route("hello", provider_name="claude")["thinking"] == "low"
    assert aria_ai.route("compare the 4h and 1h", provider_name="claude")["thinking"] == "medium"
    assert aria_ai.route("check my plan", hint="plan", provider_name="claude")["thinking"] == "medium"


def reasoning_stream():
    return [
        {"type": "message_start", "message": {"usage": {"input_tokens": 40}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Checking structure first."}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "c2lnbmF0dXJlLWZha2U="}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_stop", "index": 1},
        {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "toolu_r1", "name": "draw_analysis", "input": {}}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"layers":["structure"]}'}},
        {"type": "content_block_stop", "index": 2},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 12}},
        {"type": "message_stop"},
    ]


def test_reasoning_blocks_round_trip_verbatim_inside_the_tool_turn_only(monkeypatch):
    enable(monkeypatch)
    provider = aria_ai.ClaudeProvider(FAKE_KEY)
    provider._http = FakeHTTP(FakeResponse(events=reasoning_stream()))
    events = run(provider)
    content = events[-1]["content"]
    # kept in order, never streamed to the student as text; the empty text block is dropped
    assert content["parts"][0] == {"claudeThinking": {"type": "thinking", "thinking": "Checking structure first.", "signature": "c2lnbmF0dXJlLWZha2U="}}
    assert "functionCall" in content["parts"][1] and len(content["parts"]) == 2
    assert all("Checking structure" not in e.get("text", "") for e in events if e["type"] == "text")
    # the browser sends it back; the server's validation keeps it unchanged
    old_turn = {"role": "model", "parts": [{"claudeThinking": {"type": "thinking", "thinking": "old", "signature": "b2xk"}}, {"text": "Earlier answer."}]}
    raw = [{"role": "user", "parts": [{"text": "Earlier question"}]}, old_turn,
           {"role": "user", "parts": [{"text": "Draw the structure"}]}, content,
           {"role": "user", "parts": [{"functionResponse": {"name": "draw_analysis", "id": "toolu_r1", "response": {"ok": True}}}]}]
    cleaned = aria_ai.clean_contents(json.loads(json.dumps(raw)))
    assert cleaned[3]["parts"][0] == content["parts"][0]
    body = provider._body("claude-sonnet-5-5", "SYS", cleaned, aria_ai.TOOLS, 100, effort="low")
    assistant = [m for m in body["messages"] if m["role"] == "assistant"]
    # current tool turn: thinking first, then tool_use, verbatim; older turn: reasoning omitted (allowed, saves credit)
    assert assistant[-1]["content"][0] == {"type": "thinking", "thinking": "Checking structure first.", "signature": "c2lnbmF0dXJlLWZha2U="}
    assert assistant[-1]["content"][1]["type"] == "tool_use"
    assert all(b["type"] != "thinking" for b in assistant[0]["content"])
    assert body["messages"][-1]["content"][0] == {"type": "tool_result", "tool_use_id": "toolu_r1", "content": '{"ok": true}'}
    # the same history sent to Gemini (a later fallback) carries no Claude blocks
    gem = aria_ai.GeminiProvider("AIzaFAKE-non-secret-testing-0000000")._body("SYS", cleaned, [], 100, None)
    assert "claudeThinking" not in json.dumps(gem)


def test_altered_or_oversized_reasoning_blocks_are_refused(monkeypatch):
    bad = [{"claudeThinking": {"type": "thinking", "thinking": "x", "signature": "not base64 <script>"}},
           {"claudeThinking": {"type": "thinking", "thinking": "x"}},
           {"claudeThinking": {"type": "other", "data": "abc"}},
           {"claudeThinking": {"type": "thinking", "thinking": "x" * 30000, "signature": "abc"}}]
    for part in bad:
        assert aria_ai._clean_part(part, "model") is None
    # only the model's own turn may carry one
    assert aria_ai._clean_part({"claudeThinking": {"type": "redacted_thinking", "data": "ZGF0YQ=="}}, "user") is None
    assert aria_ai._clean_part({"claudeThinking": {"type": "redacted_thinking", "data": "ZGF0YQ=="}}, "model") == {"claudeThinking": {"type": "redacted_thinking", "data": "ZGF0YQ=="}}
    # an oversized block is dropped from a plain answer, but a tool step that needs it stops instead
    enable(monkeypatch)
    big = reasoning_stream()
    big[3] = {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "A" * 30000}}
    provider = aria_ai.ClaudeProvider(FAKE_KEY)
    provider._http = FakeHTTP(FakeResponse(events=big))
    with pytest.raises(aria_ai.ProviderError):
        run(provider)
    plain = [e for e in big if not (e.get("index") == 2)]
    plain[-2] = {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}}
    provider._http = FakeHTTP(FakeResponse(events=plain))
    assert all("claudeThinking" not in p for p in run(provider)[-1]["content"]["parts"])


def test_labels_and_privacy_notice_name_the_provider_that_answers(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKE-non-secret-testing-0000000")
    monkeypatch.setenv("GEMINI_FREE_TIER_CONFIRMED", "1")
    monkeypatch.setenv("ARIA_AI_GEMINI_FALLBACK", "1")
    c = client()
    st = c.get("/api/aria/ai/status").json()        # Claude not approved: the labelled Gemini fallback answers
    assert st["provider"] == "gemini" and st["fallback"] is True and st["label"] == "Gemini (free-tier fallback)"
    assert "standing in for Claude" in st["privacy"] and "Google may use" in st["privacy"]
    assert "fallback_reason" not in st                # why Claude is off is shown to the owner only
    monkeypatch.setenv("SENTINEL_ADMIN_KEY", "owner-key-for-tests")
    st = c.get("/api/aria/ai/status", headers={"x-sentinel-key": "owner-key-for-tests"}).json()
    assert "ARIA_CLAUDE_ENABLED" in st["fallback_reason"]
    enable(monkeypatch)
    st = c.get("/api/aria/ai/status").json()
    assert st["provider"] == "claude" and st["fallback"] is False and "Gemini's free tier answers instead (labelled)" in st["privacy"]
    assert FAKE_KEY not in json.dumps(st) and "AIzaFAKE" not in json.dumps(st)


def test_an_unanswered_tool_call_in_an_older_turn_never_blocks_later_questions(monkeypatch):
    enable(monkeypatch)
    provider = aria_ai.ClaudeProvider(FAKE_KEY)
    stale = [{"role": "user", "parts": [{"text": "Analyse"}]},
             {"role": "model", "parts": [{"text": "Let me draw."}, {"functionCall": {"name": "draw_analysis", "id": "toolu_cut", "args": {"layers": ["zones"]}}}]},
             {"role": "user", "parts": [{"text": "Next question"}]}]
    body = provider._body("claude-sonnet-5-5", "SYS", aria_ai.clean_contents(stale), [], 100)
    assert [b["type"] for m in body["messages"] for b in m["content"]].count("tool_use") == 0
    assert body["messages"][1] == {"role": "assistant", "content": [{"type": "text", "text": "Let me draw."}]}
    # inside the CURRENT turn an unanswered call is still refused (the app must answer it)
    with pytest.raises(aria_ai.ProviderError):
        provider._body("claude-sonnet-5-5", "SYS", stale[:2] + [{"role": "user", "parts": [{"functionResponse": {"name": "draw_analysis", "id": "other", "response": {}}}]}], [], 100)


def test_times_may_be_written_as_utc_dates_and_the_check_window_is_the_owners_choice(monkeypatch, capsys):
    enable(monkeypatch)
    monkeypatch.setenv("CLAUDE_CREDIT_EXPIRES_AT", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400)))
    assert aria_ai.ai_state()["enabled"]
    for bad in ("2026-10-17", "2026-10-17T00:00:00", "17/10/2026", "2026-10-17T00:00:00+01:00"):
        monkeypatch.setenv("CLAUDE_CREDIT_EXPIRES_AT", bad)            # no zone, or not UTC: refused
        assert not aria_ai.ai_state()["enabled"], bad
    monkeypatch.setenv("CLAUDE_CREDIT_EXPIRES_AT", str(time.time() + 86400))
    monkeypatch.setenv("CLAUDE_CREDIT_VERIFIED_AT", str(time.time() - 30 * 3600))   # 30 h ago
    assert not aria_ai.ai_state()["enabled"]                          # default window: 24 h
    monkeypatch.setenv("CLAUDE_ATTESTATION_MAX_HOURS", "72")
    assert aria_ai.ai_state()["enabled"]
    for bad in ("0", "169", "nan", "week"):
        monkeypatch.setenv("CLAUDE_ATTESTATION_MAX_HOURS", bad)
        assert not aria_ai.ai_state()["enabled"], bad
    monkeypatch.setenv("CLAUDE_ATTESTATION_MAX_HOURS", "72")
    import claude_credits
    assert claude_credits.main(["x", "check"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Claude may run: $1.00 of $1.00") and FAKE_KEY not in out
    monkeypatch.setenv("ARIA_CLAUDE_ENABLED", "0")
    assert claude_credits.main(["x", "check"]) == 1 and "blocked" in capsys.readouterr().out
