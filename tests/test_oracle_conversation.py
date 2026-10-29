"""Offline ASGI checks for private, server-authorized conversation preparation.

All provider credentials and signed URLs here are deliberately fictional.
No real agent, conversation, account, market data or paid API is accessed.
"""
import asyncio
import json
import os
import unittest
from unittest.mock import Mock, patch

import requests

import oracle_api
dashboard = oracle_api
from fastapi import FastAPI
app = FastAPI()
app.include_router(dashboard.router)
dashboard.app = app


SIGNED_URL = ("wss://api.elevenlabs.io/v1/convai/conversation?agent_id=agent_test_fixture"
              "&conversation_signature=fictional-one-use-authorization")
CONFIG = {"ELEVENLABS_API_KEY": "fictional-server-key",
          "ORACLE_ELEVENLABS_AGENT_ID": "agent_test_fixture"}


def asgi_request(method, path, *, client="127.0.0.1", host="127.0.0.1:8019",
                 origin="http://127.0.0.1:8019", fetch_site="same-origin"):
    """Exercise the actual FastAPI routes/middleware without an HTTPX install."""
    async def run():
        headers = [(b"host", host.encode())]
        if origin is not None:
            headers.append((b"origin", origin.encode()))
        if fetch_site:
            headers.append((b"sec-fetch-site", fetch_site.encode()))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                 "query_string": b"", "root_path": "", "headers": headers,
                 "client": (client, 12345), "server": ("127.0.0.1", 8019)}
        messages, delivered = [], False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)

        await asyncio.wait_for(dashboard.app(scope, receive, send), timeout=3)
        start = next(m for m in messages if m["type"] == "http.response.start")
        body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return start["status"], dict((k.decode(), v.decode()) for k, v in start["headers"]), json.loads(body)
    return asyncio.run(run())


class OracleConversationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {**CONFIG, "PROTRADER_LOCAL_PREVIEW": "1"}, clear=True)
        self.env.start()
        dashboard._ORACLE_SESSION_REQUESTS.clear()
        self.addCleanup(self.env.stop)
        self.addCleanup(dashboard._ORACLE_SESSION_REQUESTS.clear)

    def provider(self, **kwargs):
        return patch("oracle_api.requests.get", return_value=Mock(
            status_code=kwargs.get("status", 200), json=Mock(return_value=kwargs.get("body", {"signed_url": SIGNED_URL}))))

    def test_status_only_reports_presence_without_keys_agent_references_or_network(self):
        with self.provider() as get:
            status, headers, body = asgi_request("GET", "/api/oracle/conversation/status", origin=None, fetch_site="")
        self.assertEqual(status, 200)
        self.assertTrue(body["configured"])
        self.assertTrue(body["api_key_configured"])
        self.assertTrue(body["agent_configured"])
        self.assertFalse(body["provider_access_verified"])
        self.assertFalse(body["agent_privacy_verified"])
        self.assertIn("no-store", headers["cache-control"])
        self.assertNotIn(CONFIG["ELEVENLABS_API_KEY"], json.dumps(body))
        self.assertNotIn(CONFIG["ORACLE_ELEVENLABS_AGENT_ID"], json.dumps(body))
        get.assert_not_called()

    def test_missing_setup_returns_explicit_503_and_no_provider_request(self):
        for missing in ["ELEVENLABS_API_KEY", "ORACLE_ELEVENLABS_AGENT_ID"]:
            with self.subTest(missing=missing), patch.dict(os.environ, {missing: ""}), self.provider() as get:
                status, headers, body = asgi_request("POST", "/api/oracle/conversation/session")
                self.assertEqual(status, 503)
                self.assertIn("not configured", body["detail"])
                self.assertIn("no-store", headers["cache-control"])
                get.assert_not_called()

    def test_private_signed_url_uses_server_header_and_is_transient_one_use(self):
        with self.provider() as get:
            status, headers, body = asgi_request("POST", "/api/oracle/conversation/session")
        self.assertEqual(status, 200)
        self.assertEqual(body["signed_url"], SIGNED_URL)
        self.assertTrue(body["single_use"])
        self.assertEqual(body["expires_in_seconds"], 900)
        self.assertEqual(body["transport"], "websocket")
        self.assertIn("no-store", headers["cache-control"])
        get.assert_called_once_with(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            params={"agent_id": "agent_test_fixture", "include_conversation_id": "true"},
            headers={"xi-api-key": "fictional-server-key"}, timeout=(5, 10), allow_redirects=False)
        self.assertNotIn("fictional-server-key", json.dumps(body))
        self.assertTrue(all(isinstance(value, float) for value in dashboard._ORACLE_SESSION_REQUESTS))

    def test_specific_agent_environment_reference_takes_precedence_and_generic_is_fallback(self):
        with patch.dict(os.environ, {"ELEVENLABS_AGENT_ID": "agent_other_fixture"}), self.provider() as get:
            asgi_request("POST", "/api/oracle/conversation/session")
            self.assertEqual(get.call_args.kwargs["params"]["agent_id"], "agent_test_fixture")
        with patch.dict(os.environ, {"ORACLE_ELEVENLABS_AGENT_ID": "", "ELEVENLABS_AGENT_ID": "agent_other_fixture"}), self.provider() as get:
            asgi_request("POST", "/api/oracle/conversation/session")
            self.assertEqual(get.call_args.kwargs["params"]["agent_id"], "agent_other_fixture")

    def test_remote_clients_rebinding_hosts_and_cross_origin_requests_are_forbidden(self):
        cases = [
            {"client": "192.0.2.55"}, {"host": "attacker.invalid:8019"},
            {"origin": "https://attacker.invalid"}, {"origin": "null"}, {"origin": None},
            {"origin": "http://127.0.0.1:8020"}, {"fetch_site": "cross-site"},
            {"origin": "http://user@127.0.0.1:8019"}, {"origin": "http://127.0.0.1:8019/path"},
        ]
        for values in cases:
            with self.subTest(values=values), self.provider() as get:
                status, headers, body = asgi_request("POST", "/api/oracle/conversation/session", **values)
                self.assertEqual(status, 403)
                self.assertIn("local preview", body["detail"])
                self.assertIn("no-store", headers["cache-control"])
                get.assert_not_called()

    def test_status_is_also_restricted_to_local_requester_and_local_host(self):
        with self.provider() as get:
            for values in [{"client": "192.0.2.55"}, {"host": "attacker.invalid:8019"}]:
                status, _, _ = asgi_request("GET", "/api/oracle/conversation/status", **values)
                self.assertEqual(status, 403)
            get.assert_not_called()

    def test_localhost_and_ipv6_loopback_are_supported_without_remote_access(self):
        for values in [{"host": "localhost:8019", "origin": "http://localhost:8019"},
                       {"client": "::1", "host": "[::1]:8019", "origin": "http://[::1]:8019"}]:
            with self.subTest(values=values), self.provider():
                status, _, _ = asgi_request("POST", "/api/oracle/conversation/session", **values)
                self.assertEqual(status, 200)

    def test_provider_errors_never_echo_upstream_bodies_credentials_or_urls(self):
        for code in [301, 401, 403, 429, 500]:
            with self.subTest(code=code), self.provider(status=code, body={"detail": SIGNED_URL}) as get:
                status, headers, body = asgi_request("POST", "/api/oracle/conversation/session")
                self.assertEqual(status, 502)
                self.assertNotIn(SIGNED_URL, json.dumps(body))
                self.assertIn("no-store", headers["cache-control"])
        dashboard._ORACLE_SESSION_REQUESTS.clear()
        for error, expected in [(requests.Timeout(SIGNED_URL), 504),
                                (requests.ConnectionError("fictional-server-key"), 502),
                                (ValueError(SIGNED_URL), 502)]:
            with patch("oracle_api.requests.get", side_effect=error):
                status, _, body = asgi_request("POST", "/api/oracle/conversation/session")
                self.assertEqual(status, expected)
                self.assertNotIn(SIGNED_URL, json.dumps(body))
                self.assertNotIn("fictional-server-key", json.dumps(body))

    def test_provider_diagnostics_distinguish_safe_codes_and_legacy_status(self):
        cases = {
            "invalid_api_key": "rejected the server API key as invalid",
            "missing_api_key": "missing server API key",
            "missing_permissions": "missing API-key permissions",
            "insufficient_permissions": "insufficient permissions",
            "quota_exceeded": "exhausted account quota",
            "insufficient_credits": "insufficient account credits",
        }
        for field in ("code", "status"):
            for code, expected in cases.items():
                with self.subTest(field=field, code=code):
                    dashboard._ORACLE_SESSION_REQUESTS.clear()
                    upstream = {"detail": {field: code, "message": SIGNED_URL + " fictional-server-key",
                                            "request_id": "fictional-private-request", "extra": CONFIG}}
                    with self.provider(status=401, body=upstream):
                        status, headers, body = asgi_request("POST", "/api/oracle/conversation/session")
                    self.assertEqual(status, 502)
                    self.assertIn(expected, body["detail"])
                    self.assertIn(code, body["detail"])
                    self.assertIn("no-store", headers["cache-control"])
                    encoded = json.dumps(body)
                    for secret in (SIGNED_URL, "fictional-server-key", "fictional-private-request", "agent_test_fixture"):
                        self.assertNotIn(secret, encoded)

    def test_provider_permission_scope_is_only_an_explicit_allowlisted_label(self):
        cases = [
            ({"required_permission": "convai_read"}, "ElevenAgents Read"),
            ({"param": "convai_write"}, "ElevenAgents Write"),
            ({"message": "The API key is missing the permission convai_write to execute this operation. " + SIGNED_URL}, "ElevenAgents Write"),
            ({"message": "Missing convai_read permission. fictional-server-key"}, "ElevenAgents Read"),
            ({"message": "Missing a permission; see " + SIGNED_URL}, None),
            ({"scope": "convai_write-unknown"}, None),
            ({"message": "permission convai_write_extra"}, None),
            ({"scope": "convai_read", "required_permission": "convai_write"}, None),
            ({"message": "Unrelated URL https://example.invalid/convai_write"}, None),
        ]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                upstream = Mock(status_code=401, json=Mock(return_value={"detail": {"status": "missing_permissions", **fields}}))
                result = oracle_api._oracle_provider_error(upstream)
                if expected:
                    self.assertIn("Provider-identified scope: " + expected, result)
                else:
                    self.assertNotIn("Provider-identified scope", result)
                self.assertNotIn(SIGNED_URL, result)
                self.assertNotIn("fictional-server-key", result)
                self.assertNotIn("https://", result)

    def test_unknown_malformed_errors_have_distinct_http_fallbacks_without_leaks(self):
        expected = {301: "unexpected redirect", 401: "HTTP 401", 402: "HTTP 402",
                    403: "HTTP 403", 429: "rate or concurrency limit", 500: "provider service error",
                    503: "provider service error", 400: "could not prepare"}
        malformed = [None, [], {"detail": SIGNED_URL}, {"detail": {"code": ["invalid_api_key"]}},
                     {"detail": {"code": "unknown-fictional-server-key", "status": "invalid_api_key", "message": SIGNED_URL}}]
        for http_status, fragment in expected.items():
            for provider_body in malformed:
                with self.subTest(http_status=http_status, provider_body=provider_body):
                    upstream = Mock(status_code=http_status, json=Mock(return_value=provider_body))
                    result = oracle_api._oracle_provider_error(upstream)
                    self.assertIn(fragment, result)
                    for secret in (SIGNED_URL, "fictional-server-key", "invalid_api_key"):
                        self.assertNotIn(secret, result)
        upstream = Mock(status_code=401, json=Mock(side_effect=ValueError(SIGNED_URL)))
        self.assertIn("HTTP 401", oracle_api._oracle_provider_error(upstream))
        with patch("oracle_api.requests.get", return_value=upstream):
            status, _, body = asgi_request("POST", "/api/oracle/conversation/session")
        self.assertEqual(status, 502)
        self.assertIn("HTTP 401", body["detail"])
        self.assertNotIn(SIGNED_URL, json.dumps(body))

    def test_additional_published_auth_codes_never_echo_provider_values(self):
        codes = ("invalid_authorization_header", "unauthorized", "sign_in_required", "forbidden",
                 "workspace_access_denied", "feature_not_available", "subscription_required")
        for field in ("code", "status"):
            for code in codes:
                with self.subTest(field=field, code=code):
                    dashboard._ORACLE_SESSION_REQUESTS.clear()
                    upstream = {"detail": {field: code, "type": "authentication_error",
                                            "message": SIGNED_URL, "param": "fictional-server-key"}}
                    with self.provider(status=401, body=upstream):
                        status, headers, body = asgi_request("POST", "/api/oracle/conversation/session")
                    self.assertEqual(status, 502)
                    self.assertIn(code, body["detail"])
                    self.assertNotIn("authentication_error", body["detail"])
                    self.assertIn("no-store", headers["cache-control"])
                    self.assertNotIn(SIGNED_URL, json.dumps(body))
                    self.assertNotIn("fictional-server-key", json.dumps(body))

    def test_safe_error_type_fallback_preserves_code_and_legacy_precedence(self):
        types = ("validation_error", "invalid_request", "authentication_error", "payment_required",
                 "authorization_error", "not_found", "conflict", "rate_limit_error",
                 "internal_error", "service_unavailable")
        for error_type in types:
            with self.subTest(error_type=error_type):
                detail = {"type": error_type, "code": "fictional-secret-code", "status": "invalid_api_key",
                          "message": SIGNED_URL, "request_id": "fictional-private-request"}
                result = oracle_api._oracle_provider_error(Mock(status_code=401, json=Mock(return_value={"detail": detail})))
                self.assertIn("(" + error_type + ")", result)
                self.assertIn("JSON object; detail object; code unrecognized", result)
                for value in ("invalid_api_key", "fictional-secret-code", SIGNED_URL, "fictional-private-request"):
                    self.assertNotIn(value, result)
        for fields, expected in [({"code": "unauthorized", "status": "invalid_api_key"}, "unauthorized"),
                                 ({"status": "unauthorized"}, "unauthorized")]:
            detail = {"type": "authorization_error", **fields}
            result = oracle_api._oracle_provider_error(Mock(status_code=401, json=Mock(return_value={"detail": detail})))
            self.assertIn("(" + expected + ")", result)
            self.assertNotIn("authorization_error", result)

    def test_unknown_provider_shape_is_fixed_metadata_only(self):
        cases = [
            ({}, "JSON object; detail missing; code missing"),
            ({"detail": {}}, "JSON object; detail object; code missing"),
            ({"detail": SIGNED_URL}, "JSON object; detail string; code missing"),
            ({"detail": [SIGNED_URL]}, "JSON object; detail other; code missing"),
            ([SIGNED_URL], "JSON list; detail missing; code missing"),
            ("fictional-server-key", "JSON scalar; detail missing; code missing"),
            (None, "JSON scalar; detail missing; code missing"),
            ({"detail": {"code": "fictional-server-key", "type": "fictional-secret-type"}},
             "JSON object; detail object; code unrecognized"),
            ({"detail": {"code": [SIGNED_URL], "type": {"secret": SIGNED_URL}}},
             "JSON object; detail object; code unrecognized"),
            ({"detail": {"status": "fictional-server-key"}}, "JSON object; detail object; code unrecognized"),
        ]
        for provider_body, expected in cases:
            with self.subTest(expected=expected):
                dashboard._ORACLE_SESSION_REQUESTS.clear()
                with self.provider(status=401, body=provider_body):
                    status, _, body = asgi_request("POST", "/api/oracle/conversation/session")
                self.assertEqual(status, 502)
                self.assertIn("HTTP 401", body["detail"])
                self.assertIn(expected, body["detail"])
                for value in (SIGNED_URL, "fictional-server-key", "fictional-secret-type"):
                    self.assertNotIn(value, json.dumps(body))
        upstream = Mock(status_code=401, json=Mock(side_effect=ValueError(SIGNED_URL)))
        result = oracle_api._oracle_provider_error(upstream)
        self.assertIn("not JSON; detail missing; code missing", result)
        self.assertNotIn(SIGNED_URL, result)

    def test_recognized_authorization_errors_keep_explicit_required_scope_without_leaks(self):
        for http_status in (401, 403):
            for code in ("unauthorized", "sign_in_required", "invalid_api_key"):
                with self.subTest(http_status=http_status, code=code):
                    detail = {"code": code, "required_permission": "convai_write",
                              "message": SIGNED_URL + " fictional-server-key",
                              "param": "https://fictional.invalid/convai_read"}
                    result = oracle_api._oracle_provider_error(Mock(status_code=http_status, json=Mock(return_value={"detail": detail})))
                    self.assertIn("(" + code + ")", result)
                    self.assertIn("Provider-identified scope: ElevenAgents Write.", result)
                    for secret in (SIGNED_URL, "fictional-server-key", "https://", "wss://"):
                        self.assertNotIn(secret, result)
        detail = {"code": "invalid_api_key", "required_permission": SIGNED_URL,
                  "message": "See https://fictional.invalid/convai_write fictional-server-key"}
        result = oracle_api._oracle_provider_error(Mock(status_code=401, json=Mock(return_value={"detail": detail})))
        self.assertIn("(invalid_api_key)", result)
        self.assertNotIn("Provider-identified scope", result)
        for secret in (SIGNED_URL, "fictional-server-key", "https://", "wss://"):
            self.assertNotIn(secret, result)

    def test_unknown_authorization_errors_expose_only_explicit_required_scope(self):
        cases = [
            ({"required_permission": "convai_write"}, "ElevenAgents Write"),
            ({"required_scope": "convai_read", "type": "authentication_error"}, "ElevenAgents Read"),
            ({"message": "The key is missing the permission convai_write. " + SIGNED_URL}, "ElevenAgents Write"),
            ({"message": "This operation requires 'convai_read' permission. fictional-server-key"}, "ElevenAgents Read"),
            ("The required scope: convai_write is missing. " + SIGNED_URL, "ElevenAgents Write"),
            ({"message": "Currently granted convai_read permission. " + SIGNED_URL}, None),
            ({"scope": "convai_write"}, None),
            ({"required_permission": "convai_write-unknown"}, None),
            ({"message": "Missing permission convai_write_extra"}, None),
            ({"message": "Missing permission convai_write-unknown"}, None),
            ({"required_permission": "convai_read", "message": "Missing convai_write permission"}, None),
        ]
        for status in (401, 403):
            for fields, expected in cases:
                with self.subTest(status=status, fields=fields):
                    detail = {"code": "unknown-fictional-server-key", **fields} if isinstance(fields, dict) else fields
                    result = oracle_api._oracle_provider_error(Mock(status_code=status, json=Mock(return_value={"detail": detail})))
                    if expected:
                        self.assertIn("Provider-identified scope: " + expected, result)
                        self.assertNotIn("No specific permission was identified", result)
                    else:
                        self.assertNotIn("Provider-identified scope", result)
                    for secret in (SIGNED_URL, "fictional-server-key", "https://", "wss://"):
                        self.assertNotIn(secret, result)
        result = oracle_api._oracle_provider_error(Mock(status_code=500, json=Mock(return_value={
            "detail": {"code": "unknown", "required_permission": "convai_write"}})))
        self.assertNotIn("Provider-identified scope", result)

    def test_invalid_or_nonofficial_provider_urls_are_rejected(self):
        invalid = [None, "https://api.elevenlabs.io/v1/convai/conversation?conversation_signature=fake",
                   "wss://attacker.invalid/v1/convai/conversation?conversation_signature=fake",
                   "wss://api.elevenlabs.io/wrong?conversation_signature=fake",
                   "wss://api.elevenlabs.io/v1/convai/conversation", "wss://api.elevenlabs.io:invalid/path"]
        for value in invalid:
            with self.subTest(value=value), self.provider(body={"signed_url": value}):
                status, _, body = asgi_request("POST", "/api/oracle/conversation/session")
                self.assertEqual(status, 502)
                self.assertNotIn("signed_url", body)

    def test_rate_limit_bounds_token_issuance_and_get_does_not_issue_tokens(self):
        with self.provider() as get:
            for _ in range(6):
                self.assertEqual(asgi_request("POST", "/api/oracle/conversation/session")[0], 200)
            status, headers, body = asgi_request("POST", "/api/oracle/conversation/session")
            self.assertEqual(status, 429)
            self.assertEqual(headers["retry-after"], "60")
            self.assertEqual(get.call_count, 6)
            status, _, _ = asgi_request("GET", "/api/oracle/conversation/session")
            self.assertEqual(status, 405)
            self.assertEqual(get.call_count, 6)


if __name__ == "__main__":
    unittest.main()
