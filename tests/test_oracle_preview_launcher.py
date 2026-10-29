"""Offline startup checks: fictional credentials, no live provider calls."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, call, patch

import requests
import dashboard  # Load native dependencies outside temporary sys.modules patches.

SPEC = importlib.util.spec_from_file_location("oracle_preview_launcher", Path(__file__).resolve().parents[1] / "scripts/start_oracle_preview.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
KEY = "fictional-preflight-secret"
AGENT = "agent_fixture"
SECRET_BODY = {"signed_url": "wss://fictional.invalid/?token=fictional-token", "key": KEY}


class OraclePreviewLauncherTests(unittest.TestCase):
    def setUp(self):
        # Exercise real state isolation without writing into the checkout.
        state_directory = TemporaryDirectory(prefix="oracle-launcher-test-")
        self.addCleanup(state_directory.cleanup)
        self.state_directory = Path(state_directory.name).resolve() / "state"
        configure = launcher.configure_preview_environment
        state_setup = patch.object(
            launcher, "configure_preview_environment",
            side_effect=lambda project, state_dir=None: configure(
                project, state_dir or self.state_directory),
        )
        state_setup.start()
        self.addCleanup(state_setup.stop)
        # Startup tests must never touch the user's real Keychain.
        reader = patch.object(launcher, "_read_saved_key", return_value=None)
        saver = patch.object(launcher, "_save_validated_key", return_value=True)
        platform = patch.object(launcher.sys, "platform", "darwin")
        self.read_saved = reader.start()
        self.save_validated = saver.start()
        platform.start()
        self.addCleanup(reader.stop)
        self.addCleanup(saver.stop)
        self.addCleanup(platform.stop)

    def test_paste_check_rejects_obvious_mistakes_without_key_format_assumptions(self):
        invalid = ("", "fictional••••secret", "fictional●●secret", "fictional…secret",
                   "fictional***secret", "fictional...secret", "https://fictional.invalid/key",
                   "www.fictional.invalid/key", "python3 scripts/start_oracle_preview.py",
                   "/private/tmp/start_oracle_preview.py", "fictional secret", "fictional\tsecret",
                   "fictional\nsecret", "fictional\x00secret", "fictional\x7fsecret", "fictional\u200bsecret")
        for key in invalid:
            with self.subTest(key=key):
                self.assertTrue(launcher._obviously_invalid_key(key))
        for key in ("a", "opaque_value-123", "ABC+/=.-_", "opaque:fictional", "one*star", "a" * 1024):
            with self.subTest(key=key):
                self.assertFalse(launcher._obviously_invalid_key(key))

    def test_hidden_prompt_retries_bad_paste_before_any_network_or_startup(self):
        bad = "fictional••••masked-secret"
        fake_uvicorn = Mock()
        seen = []
        def hidden_input(prompt):
            get.assert_not_called()
            fake_uvicorn.run.assert_not_called()
            seen.append(prompt)
            return bad if len(seen) == 1 else KEY
        with patch.dict(os.environ, {"ORACLE_ELEVENLABS_AGENT_ID": AGENT}, clear=True), \
                patch.object(sys, "argv", ["start_oracle_preview.py"]), \
                patch.object(sys, "path", list(sys.path)), patch.object(launcher.os, "chdir"), \
                patch.dict(sys.modules, {"uvicorn": fake_uvicorn}), \
                patch.object(launcher.sys.stdin, "isatty", return_value=True), \
                redirect_stderr(io.StringIO()) as errors, redirect_stdout(io.StringIO()) as output, \
                patch.object(launcher.sys.stderr, "isatty", return_value=True), \
                patch.object(launcher.getpass, "getpass", side_effect=hidden_input) as prompt, \
                patch.object(launcher.requests, "get", return_value=Mock(status_code=200)) as get:
            launcher.main()
            self.assertEqual(os.environ["ELEVENLABS_API_KEY"], KEY)
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual(get.call_count, 2)
        self.assertTrue(all(item.kwargs["headers"] == {"xi-api-key": KEY} for item in get.call_args_list))
        fake_uvicorn.run.assert_called_once()
        self.assertIn(launcher._KEY_PASTE_ERROR, errors.getvalue())
        for value in (bad, KEY):
            self.assertNotIn(value, errors.getvalue() + output.getvalue())

    def test_bad_environment_key_stops_without_prompt_request_or_secret_echo(self):
        for bad in ("fictional***secret", "https://fictional.invalid/secret", "fictional\nsecret"):
            with self.subTest(bad=bad), \
                    patch.dict(os.environ, {"ELEVENLABS_API_KEY": bad, "ORACLE_ELEVENLABS_AGENT_ID": AGENT}, clear=True), \
                    patch.object(sys, "argv", ["start_oracle_preview.py"]), \
                    patch.object(launcher.getpass, "getpass") as prompt, \
                    patch.object(launcher.requests, "get") as get, \
                    redirect_stderr(io.StringIO()) as errors, redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as exited:
                    launcher.main()
                self.assertEqual(exited.exception.code, 2)
                prompt.assert_not_called()
                get.assert_not_called()
                self.assertIn("configured API key failed the local paste check", errors.getvalue())
                self.assertNotIn(bad, errors.getvalue() + output.getvalue())

    def test_unmasked_input_fallback_is_rejected_without_any_request(self):
        with patch.dict(os.environ, {"ORACLE_ELEVENLABS_AGENT_ID": AGENT}, clear=True), \
                patch.object(sys, "argv", ["start_oracle_preview.py"]), \
                patch.object(launcher.sys.stdin, "isatty", return_value=True), \
                redirect_stderr(io.StringIO()) as errors, \
                patch.object(launcher.sys.stderr, "isatty", return_value=True), \
                patch.object(launcher.getpass, "getpass", side_effect=launcher.getpass.GetPassWarning(KEY)), \
                patch.object(launcher.requests, "get") as get:
            with self.assertRaises(SystemExit):
                launcher.main()
        get.assert_not_called()
        self.assertIn("cannot hide input", errors.getvalue())
        self.assertNotIn(KEY, errors.getvalue())

    def run_checks(self, responses):
        output = io.StringIO()
        with patch.object(launcher.requests, "get", side_effect=responses) as get, redirect_stdout(output):
            launcher._check_provider_access(KEY, AGENT)
        value = output.getvalue()
        for secret in (KEY, AGENT, "fictional-token", "wss://", "https://"):
            self.assertNotIn(secret, value)
        self.assertEqual(get.call_count, 2)
        return get, value

    def test_success_makes_only_two_bounded_gets_without_reading_or_printing_bodies(self):
        responses = [Mock(status_code=200, json=Mock(return_value=SECRET_BODY)) for _ in range(2)]
        get, output = self.run_checks(responses)
        self.assertEqual(output, "Agent read access: succeeded (HTTP 200).\nSigned-URL access: succeeded (HTTP 200).\n")
        self.assertEqual(get.call_args_list, [
            call("https://api.elevenlabs.io/v1/convai/agents/agent_fixture", params=None,
                 headers={"xi-api-key": KEY}, timeout=(5, 10), allow_redirects=False),
            call("https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
                 params={"agent_id": AGENT, "include_conversation_id": "true"},
                 headers={"xi-api-key": KEY}, timeout=(5, 10), allow_redirects=False),
        ])
        for response in responses:
            response.json.assert_not_called()
        self.assertNotIn("private", output.lower())

    def test_rejected_read_does_not_skip_signed_url_check_or_leak_provider_values(self):
        responses = [Mock(status_code=401, json=Mock(return_value={"detail": {
            "code": KEY, "message": "Missing permission convai_write. " + KEY,
            "extra": SECRET_BODY}})), Mock(status_code=200)]
        _, output = self.run_checks(responses)
        self.assertIn("Agent read access: ElevenLabs rejected session authorization (HTTP 401)", output)
        self.assertIn("ElevenAgents Write", output)
        self.assertIn("Signed-URL access: succeeded", output)

    def test_network_failures_are_sanitized_and_never_retried(self):
        _, output = self.run_checks([requests.Timeout(KEY), requests.ConnectionError(str(SECRET_BODY))])
        self.assertIn("Agent read access: ElevenLabs access check timed out", output)
        self.assertIn("Signed-URL access: ElevenLabs access check is temporarily unavailable", output)

    def test_redirect_is_not_followed_and_agent_stays_in_fixed_host_path(self):
        with patch.object(launcher.requests, "get", return_value=Mock(status_code=301, json=Mock(side_effect=ValueError(KEY)))) as get, redirect_stdout(io.StringIO()) as output:
            launcher._check_provider_access(KEY, "agent_/../../?token=fictional-token")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].args[0], "https://api.elevenlabs.io/v1/convai/agents/agent_%2F..%2F..%2F%3Ftoken%3Dfictional-token")
        self.assertTrue(all(item.kwargs["allow_redirects"] is False for item in get.call_args_list))
        self.assertNotIn(KEY, output.getvalue())
        self.assertNotIn("fictional-token", output.getvalue())
        self.assertEqual(output.getvalue().count("unexpected redirect"), 2)

    def test_failed_preflight_does_not_prevent_local_preview_start(self):
        fake_uvicorn = Mock()
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": KEY, "ORACLE_ELEVENLABS_AGENT_ID": AGENT}, clear=True), \
                patch.object(sys, "argv", ["start_oracle_preview.py", "--port", "8020"]), \
                patch.object(sys, "path", list(sys.path)), patch.object(launcher.os, "chdir"), \
                patch.dict(sys.modules, {"uvicorn": fake_uvicorn}), \
                patch.object(launcher.requests, "get", side_effect=[requests.Timeout(KEY), requests.ConnectionError(KEY)]) as get, \
                redirect_stdout(io.StringIO()) as output:
            launcher.main()
        self.assertEqual(get.call_count, 2)
        fake_uvicorn.run.assert_called_once_with("dashboard:app", host="127.0.0.1", port=8020, log_level="warning")
        self.assertNotIn(KEY, output.getvalue())

    def run_startup(self, *, args=(), environment=None, accepted=True, prompt_value=KEY):
        fake_uvicorn = Mock()
        output, errors = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"ORACLE_ELEVENLABS_AGENT_ID": AGENT,
                                                       **(environment or {})}, clear=True))
            stack.enter_context(patch.object(sys, "argv", ["start_oracle_preview.py", *args]))
            stack.enter_context(patch.object(sys, "path", list(sys.path)))
            stack.enter_context(patch.object(launcher.os, "chdir"))
            stack.enter_context(patch.dict(sys.modules, {"uvicorn": fake_uvicorn}))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(errors))
            stack.enter_context(patch.object(launcher.sys.stdin, "isatty", return_value=True))
            stack.enter_context(patch.object(launcher.sys.stderr, "isatty", return_value=True))
            prompt = stack.enter_context(patch.object(launcher.getpass, "getpass", return_value=prompt_value))
            check = stack.enter_context(patch.object(launcher, "_check_provider_access", return_value=accepted))
            launcher.main()
            runtime_key = os.environ["ELEVENLABS_API_KEY"]
            self.assertEqual(Path(os.environ["ACCOUNTS_DB"]).parent, self.state_directory)
            self.assertTrue(self.state_directory.is_dir())
        for secret in (KEY, "older-fictional-secret"):
            self.assertNotIn(secret, output.getvalue() + errors.getvalue())
        fake_uvicorn.run.assert_called_once_with("dashboard:app", host="127.0.0.1", port=8020, log_level="warning")
        return output.getvalue(), prompt, check, runtime_key

    def test_new_prompt_key_is_saved_only_after_successful_provider_checks(self):
        def save_after_check(agent, key):
            launcher._check_provider_access.assert_called_once_with(KEY, AGENT)
            self.assertEqual((agent, key), (AGENT, KEY))
            return True
        self.save_validated.side_effect = save_after_check
        output, prompt, check, runtime_key = self.run_startup()
        check.assert_called_once_with(KEY, AGENT)
        self.save_validated.assert_called_once_with(AGENT, KEY)
        prompt.assert_called_once()
        self.assertEqual(runtime_key, KEY)
        self.assertIn("Future starts reuse it automatically", output)

    def test_saved_key_reused_without_prompt_or_rewrite(self):
        self.read_saved.return_value = KEY
        output, prompt, check, runtime_key = self.run_startup()
        self.read_saved.assert_called_once_with(AGENT)
        prompt.assert_not_called()
        self.save_validated.assert_not_called()
        self.assertEqual(runtime_key, KEY)
        self.assertIn("Using the Oracle key from Mac Keychain", output)

    def test_replacement_bypasses_saved_and_environment_key(self):
        output, prompt, check, runtime_key = self.run_startup(
            args=("--replace-key",), environment={"ELEVENLABS_API_KEY": "older-fictional-secret"})
        self.read_saved.assert_not_called()
        self.save_validated.assert_called_once_with(AGENT, KEY)
        check.assert_called_once_with(KEY, AGENT)
        prompt.assert_called_once()
        self.assertEqual(runtime_key, KEY)

    def test_failed_replacement_preserves_saved_key_and_runs_local_review(self):
        output, prompt, check, runtime_key = self.run_startup(args=("--replace-key",), accepted=False)
        self.read_saved.assert_not_called()
        self.save_validated.assert_not_called()
        self.assertIn("No saved key was changed", output)
        self.assertIn("Local chart review remains available", output)

    def test_rejected_saved_key_is_kept_and_replacement_path_is_explained(self):
        self.read_saved.return_value = KEY
        output, prompt, check, _ = self.run_startup(accepted=False)
        prompt.assert_not_called()
        self.save_validated.assert_not_called()
        self.assertIn("restart with --replace-key", output)

    def test_environment_key_takes_precedence_and_is_not_persisted(self):
        _, prompt, check, runtime_key = self.run_startup(environment={"ELEVENLABS_API_KEY": KEY})
        self.read_saved.assert_not_called()
        self.save_validated.assert_not_called()
        prompt.assert_not_called()
        self.assertEqual(runtime_key, KEY)

    def test_memory_only_bypasses_keychain_entirely(self):
        output, prompt, _, _ = self.run_startup(args=("--memory-only",))
        self.read_saved.assert_not_called()
        self.save_validated.assert_not_called()
        self.assertIn("kept only in this process", prompt.call_args.args[0])
        self.assertIn("not saved by the launcher", output)

    def test_non_mac_uses_hidden_memory_only_prompt(self):
        with patch.object(launcher.sys, "platform", "linux"):
            output, prompt, _, _ = self.run_startup()
        self.read_saved.assert_not_called()
        self.save_validated.assert_not_called()
        self.assertIn("kept only in this process", prompt.call_args.args[0])

    def test_keychain_save_denied_does_not_claim_persistence(self):
        self.save_validated.return_value = False
        output, _, _, _ = self.run_startup()
        self.assertNotIn("Future starts reuse", output)
        self.assertIn("not saved by the launcher", output)

    def test_masked_saved_key_is_never_sent_to_provider(self):
        self.read_saved.return_value = "fictional••••secret"
        with patch.dict(os.environ, {"ORACLE_ELEVENLABS_AGENT_ID": AGENT}, clear=True), \
                patch.object(sys, "argv", ["start_oracle_preview.py"]), \
                patch.object(sys, "path", list(sys.path)), \
                patch.object(launcher.requests, "get") as request, \
                redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit):
                launcher.main()
        request.assert_not_called()
        self.assertIn("--replace-key", errors.getvalue())
        self.assertNotIn("fictional••••secret", errors.getvalue())


class PreviewIsolationTests(unittest.TestCase):
    def test_preview_overrides_ambient_product_paths_before_modules_import(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory, patch.dict(os.environ, {
            'ACCOUNTS_DB': '/var/data/accounts.db', 'SENTINEL_DB': '/var/data/sentinel.db',
            'SENTINEL_RESEARCH_DB': '/var/data/research.db',
            'ARIA_CLAUDE_BUDGET_DB': '/var/data/claude-budget.db',
            'ORACLE_REMOTE_ENABLED': '1', 'SENTINEL_ENABLED': '1',
            'ARIA_AI_ENABLED': '1', 'ARIA_ELEVEN_ENABLED': '1', 'ARIA_CLAUDE_ENABLED': '1',
        }, clear=True):
            root = Path(directory).resolve()
            actual = launcher.configure_preview_environment(root)
            self.assertEqual(actual, root / '.preview-state')
            self.assertTrue(actual.is_dir())
            for key in ('ACCOUNTS_DB', 'SENTINEL_DB', 'SENTINEL_RESEARCH_DB', 'NOTIFY_STATE',
                        'ARIA_AI_DB', 'ARIA_CLAUDE_BUDGET_DB', 'ARIA_ELEVEN_LEDGER_DB'):
                self.assertEqual(Path(os.environ[key]).parent, actual)
            import sentinel_research
            self.assertEqual(Path(sentinel_research.db_path()), actual / 'sentinel_research.db')
            self.assertEqual(os.environ['PROTRADER_LOCAL_PREVIEW'], '1')
            for key in ('SENTINEL_ENABLED', 'ORACLE_REMOTE_ENABLED', 'ARIA_AI_ENABLED',
                        'ARIA_CLAUDE_ENABLED', 'ARIA_ELEVEN_ENABLED'):
                self.assertEqual(os.environ[key], '0')


if __name__ == "__main__":
    unittest.main()
