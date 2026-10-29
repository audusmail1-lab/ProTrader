"""Offline ASGI checks for authenticated, in-memory private Oracle image uploads.

Provider credentials, conversations and image bytes are fictional fixtures.
No provider network calls, user images, real credentials or disk uploads occur.
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


CONVERSATION = "conv_FictionalTest123"
PATH = "/api/oracle/conversation/" + CONVERSATION + "/image"
CONFIG = {"ELEVENLABS_API_KEY": "fictional-private-server-key",
          "ORACLE_ELEVENLABS_AGENT_ID": "agent_fictional_oracle"}
SECRET_URL = "wss://api.elevenlabs.io/private?token=fictional-private-token"
PNG = b"\x89PNG\r\n\x1a\n" + b"fictional-image-fixture"
JPEG = b"\xff\xd8\xff" + b"fictional-jpeg-fixture"
WEBP = b"RIFF\x10\x00\x00\x00WEBP" + b"fictional-webp-fixture"


def asgi_upload(*, path=PATH, method="POST", body=PNG, chunks=None, headers=None,
                client="127.0.0.1", host="127.0.0.1:8020", origin="http://127.0.0.1:8020",
                fetch_site="same-origin", content_type="image/png", read_delay=0):
    async def run():
        values = {"host": host, "content-type": content_type}
        if origin is not None:
            values["origin"] = origin
        if fetch_site:
            values["sec-fetch-site"] = fetch_site
        values.update(headers or {})
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                 "query_string": b"", "root_path": "", "headers": [(k.encode(), v.encode()) for k, v in values.items()],
                 "client": (client, 12345), "server": ("127.0.0.1", 8020)}
        parts = list(chunks) if chunks is not None else [body]
        messages, reads = [], 0

        async def receive():
            nonlocal reads
            if reads < len(parts):
                if read_delay:
                    await asyncio.sleep(read_delay)
                value = parts[reads]
                reads += 1
                return {"type": "http.request", "body": value, "more_body": reads < len(parts)}
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)

        await asyncio.wait_for(dashboard.app(scope, receive, send), timeout=3)
        start = next(m for m in messages if m["type"] == "http.response.start")
        content = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return start["status"], {k.decode(): v.decode() for k, v in start["headers"]}, json.loads(content), reads
    return asyncio.run(run())


def provider_response(status=200, body=None):
    return Mock(status_code=status, json=Mock(return_value=body))


class OracleImageUploadTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {**CONFIG, "PROTRADER_LOCAL_PREVIEW": "1"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        dashboard._ORACLE_IMAGE_REQUESTS.clear()
        dashboard._ORACLE_IMAGE_COUNTS.clear()
        self.addCleanup(dashboard._ORACLE_IMAGE_REQUESTS.clear)
        self.addCleanup(dashboard._ORACLE_IMAGE_COUNTS.clear)
        self.get = patch("oracle_api.requests.get", return_value=provider_response(body={
            "agent_id": CONFIG["ORACLE_ELEVENLABS_AGENT_ID"], "conversation_id": CONVERSATION,
            "status": "in-progress", "transcript": [{"message": "PRIVATE_PROVIDER_TRANSCRIPT"}]})).start()
        self.post = patch("oracle_api.requests.post", return_value=provider_response(body={"file_id": "file_receipt123"})).start()
        self.addCleanup(patch.stopall)

    def assert_private_response(self, headers, body):
        self.assertIn("no-store", headers["cache-control"])
        result = json.dumps(body)
        for private in (*CONFIG.values(), SECRET_URL, "PRIVATE_PROVIDER_TRANSCRIPT", "PRIVATE_REQUEST_ID"):
            self.assertNotIn(private, result)

    def test_status_advertises_private_image_route_without_provider_request(self):
        status, headers, body, _ = asgi_upload(method="GET", path="/api/oracle/conversation/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["image_upload_supported"])
        self.assert_private_response(headers, body)
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_valid_images_are_authenticated_only_on_server_and_use_fixed_multipart_contract(self):
        for mime, value, ext in [("image/png", PNG, "png"), ("image/jpeg", JPEG, "jpg"), ("image/webp", WEBP, "webp")]:
            with self.subTest(mime=mime):
                status, headers, body, _ = asgi_upload(content_type=mime, body=value,
                                                     headers={"content-length": str(len(value))})
                self.assertEqual(status, 200)
                self.assertEqual(body, {"file_id": "file_receipt123"})
                self.assert_private_response(headers, body)
                self.get.assert_called_with(
                    "https://api.elevenlabs.io/v1/convai/conversations/" + CONVERSATION,
                    headers={"xi-api-key": CONFIG["ELEVENLABS_API_KEY"]}, timeout=(5, 10), allow_redirects=False)
                self.post.assert_called_with(
                    "https://api.elevenlabs.io/v1/convai/conversations/" + CONVERSATION + "/files",
                    headers={"xi-api-key": CONFIG["ELEVENLABS_API_KEY"]},
                    files={"file": ("chart." + ext, value, mime)}, timeout=(5, 20), allow_redirects=False)

    def test_missing_configuration_stops_before_reading_or_contacting_provider(self):
        for missing in CONFIG:
            with self.subTest(missing=missing), patch.dict(os.environ, {missing: ""}):
                status, headers, body, reads = asgi_upload()
                self.assertEqual(status, 503)
                self.assertEqual(reads, 0)
                self.assert_private_response(headers, body)
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_origin_host_and_local_client_restrictions_apply_before_body_read(self):
        for values in [{"client": "192.0.2.55"}, {"host": "attacker.invalid:8020"},
                       {"origin": None}, {"origin": "null"}, {"origin": "https://attacker.invalid"},
                       {"origin": "http://127.0.0.1:8021"}, {"fetch_site": "cross-site"},
                       {"origin": "http://user@127.0.0.1:8020"}]:
            with self.subTest(values=values):
                status, headers, body, reads = asgi_upload(**values)
                self.assertEqual(status, 403)
                self.assertEqual(reads, 0)
                self.assert_private_response(headers, body)
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_conversation_path_cannot_inject_another_route_or_url(self):
        for value in ["conv_", "wrong123", "conv_ab-c", "conv_" + "a" * 129, "conv_a?token=secret"]:
            with self.subTest(value=value):
                status, _, _, reads = asgi_upload(path="/api/oracle/conversation/" + value + "/image")
                self.assertEqual(status, 400)
                self.assertEqual(reads, 0)
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_media_types_and_compressed_bodies_are_rejected_before_read(self):
        for values in [{"content_type": "text/html"}, {"content_type": "application/pdf"},
                       {"content_type": "image/heic"}, {"headers": {"content-encoding": "gzip"}}]:
            with self.subTest(values=values):
                status, _, _, reads = asgi_upload(**values)
                self.assertEqual(status, 415)
                self.assertEqual(reads, 0)
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_empty_or_mismatched_image_signatures_never_reach_provider(self):
        for mime, value in [("image/png", b""), ("image/png", b"not a png"),
                            ("image/jpeg", PNG), ("image/webp", b"RIFFonly")]:
            with self.subTest(mime=mime, value=value):
                status, headers, body, _ = asgi_upload(content_type=mime, body=value)
                self.assertEqual(status, 400)
                self.assert_private_response(headers, body)
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_content_length_is_bounded_and_a_false_header_cannot_bypass_stream_limit(self):
        limit = dashboard._ORACLE_IMAGE_MAX_BYTES
        for length, expected in [(str(limit + 1), 413), ("-1", 400), ("5bad", 400)]:
            with self.subTest(length=length):
                status, _, _, reads = asgi_upload(headers={"content-length": length})
                self.assertEqual(status, expected)
                self.assertEqual(reads, 0)
        for headers in [{}, {"content-length": "10"}]:
            with self.subTest(headers=headers):
                status, _, _, reads = asgi_upload(chunks=[PNG + bytes(limit - len(PNG)), b"x", b"never-read"], headers=headers)
                self.assertEqual(status, 413)
                self.assertEqual(reads, 2)
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_exact_limit_is_accepted_but_incomplete_body_is_rejected(self):
        limit = dashboard._ORACLE_IMAGE_MAX_BYTES
        status, _, _, _ = asgi_upload(body=PNG + bytes(limit - len(PNG)), headers={"content-length": str(limit)})
        self.assertEqual(status, 200)
        self.get.reset_mock()
        self.post.reset_mock()
        status, _, _, _ = asgi_upload(headers={"content-length": str(len(PNG) + 1)})
        self.assertEqual(status, 400)
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_request_read_timeout_is_bounded_and_never_echoes_exception_content(self):
        with patch("oracle_api._ORACLE_IMAGE_READ_SECONDS", .01):
            status, headers, body, _ = asgi_upload(read_delay=.05)
        self.assertEqual(status, 408)
        self.assert_private_response(headers, body)
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_upload_requires_same_agent_same_conversation_and_active_status(self):
        valid = {"agent_id": CONFIG["ORACLE_ELEVENLABS_AGENT_ID"], "conversation_id": CONVERSATION, "status": "in-progress"}
        for change, expected in [({"agent_id": "another_agent"}, 403), ({"conversation_id": "conv_other"}, 403),
                                 ({"status": "done"}, 409), ({"status": "processing"}, 409), ({"status": "failed"}, 409)]:
            with self.subTest(change=change):
                self.get.return_value = provider_response(body={**valid, **change})
                status, headers, body, _ = asgi_upload()
                self.assertEqual(status, expected)
                self.assert_private_response(headers, body)
        self.post.assert_not_called()

    def test_upstream_failures_and_redirects_are_sanitized_for_both_operations(self):
        for operation in [self.get, self.post]:
            original = operation.return_value
            for code in [301, 401, 403, 429, 500]:
                with self.subTest(operation=operation, code=code):
                    dashboard._ORACLE_IMAGE_REQUESTS.clear()
                    operation.return_value = provider_response(code, {"detail": {
                        "message": SECRET_URL + " " + CONFIG["ELEVENLABS_API_KEY"], "request_id": "PRIVATE_REQUEST_ID"}})
                    status, headers, body, _ = asgi_upload()
                    self.assertEqual(status, 502)
                    self.assert_private_response(headers, body)
                    self.assertFalse(operation.call_args.kwargs["allow_redirects"])
            operation.return_value = original

    def test_permission_error_keeps_only_the_safe_required_scope(self):
        self.post.return_value = provider_response(403, {"detail": {
            "code": "missing_permissions", "required_permission": "convai_write", "message": SECRET_URL}})
        status, headers, body, _ = asgi_upload()
        self.assertEqual(status, 502)
        self.assertIn("ElevenAgents Write", body["detail"])
        self.assert_private_response(headers, body)

    def test_network_and_json_errors_never_leak_exception_text(self):
        for operation in [self.get, self.post]:
            original = operation.return_value
            for error, expected in [(requests.Timeout(SECRET_URL), 504),
                                    (requests.ConnectionError(CONFIG["ELEVENLABS_API_KEY"]), 502)]:
                with self.subTest(operation=operation, error=type(error)):
                    dashboard._ORACLE_IMAGE_REQUESTS.clear()
                    operation.side_effect = error
                    status, headers, body, _ = asgi_upload()
                    self.assertEqual(status, expected)
                    self.assert_private_response(headers, body)
                    operation.side_effect = None
            operation.return_value = Mock(status_code=200, json=Mock(side_effect=ValueError(SECRET_URL)))
            dashboard._ORACLE_IMAGE_REQUESTS.clear()
            status, headers, body, _ = asgi_upload()
            self.assertEqual(status, 502)
            self.assert_private_response(headers, body)
            operation.return_value = original

    def test_invalid_receipts_cannot_echo_urls_or_extra_provider_fields(self):
        for value in [None, "", SECRET_URL, {"secret": "hidden"}, "a" * 161]:
            with self.subTest(value=value):
                self.post.return_value = provider_response(body={"file_id": value, "extra": CONFIG})
                status, headers, body, _ = asgi_upload()
                self.assertEqual(status, 502)
                self.assert_private_response(headers, body)
        self.post.return_value = provider_response(body={"file_id": "bounded_opaque-id123", "extra": CONFIG})
        status, headers, body, _ = asgi_upload()
        self.assertEqual(status, 200)
        self.assertEqual(body, {"file_id": "bounded_opaque-id123"})
        self.assert_private_response(headers, body)

    def test_global_rate_limit_prevents_extra_reads_and_provider_calls(self):
        for _ in range(6):
            self.assertEqual(asgi_upload()[0], 200)
        status, headers, body, reads = asgi_upload()
        self.assertEqual(status, 429)
        self.assertEqual(headers["retry-after"], "60")
        self.assertEqual(reads, 0)
        self.assertEqual(self.get.call_count, 6)
        self.assertEqual(self.post.call_count, 6)
        self.assert_private_response(headers, body)

    def test_per_conversation_limit_survives_rate_window_and_does_not_store_ids_or_images(self):
        for _ in range(10):
            dashboard._ORACLE_IMAGE_REQUESTS.clear()
            self.assertEqual(asgi_upload()[0], 200)
        dashboard._ORACLE_IMAGE_REQUESTS.clear()
        status, headers, body, _ = asgi_upload()
        self.assertEqual(status, 429)
        self.assertEqual(self.post.call_count, 10)
        self.assert_private_response(headers, body)
        self.assertEqual(len(dashboard._ORACLE_IMAGE_COUNTS), 1)
        for key, value in dashboard._ORACLE_IMAGE_COUNTS.items():
            self.assertEqual(len(key), 64)
            self.assertEqual(value[0], 10)
            self.assertIsInstance(value[1], float)
            self.assertNotIn(CONVERSATION, key)

    def test_get_does_not_upload_anything(self):
        self.assertEqual(asgi_upload(method="GET")[0], 405)
        self.get.assert_not_called()
        self.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
