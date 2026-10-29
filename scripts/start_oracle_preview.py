"""Start Oracle locally with a hidden prompt and optional macOS Keychain reuse.

The agent config is nonsecret. Secrets never enter command arguments or plain
text files. New prompted keys are saved only after both provider checks pass.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import unicodedata
import warnings
from urllib.parse import quote

import requests


def configure_preview_environment(project: Path, state_dir: Path | None = None) -> Path:
    """Keep preview state and background services separate from the product."""
    directory = (state_dir or project / ".preview-state").resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ.update({
        "PROTRADER_LOCAL_PREVIEW": "1",
        "ORACLE_REMOTE_ENABLED": "0",
        "SENTINEL_ENABLED": "0",
        "ARIA_AI_ENABLED": "0",
        "ARIA_CLAUDE_ENABLED": "0",
        "ARIA_ELEVEN_ENABLED": "0",
        "ACCOUNTS_DB": str(directory / "accounts.db"),
        "SENTINEL_DB": str(directory / "sentinel.db"),
        "SENTINEL_RESEARCH_DB": str(directory / "sentinel_research.db"),
        "NOTIFY_STATE": str(directory / "notify.json"),
        "ARIA_AI_DB": str(directory / "aria-ai.db"),
        "ARIA_CLAUDE_BUDGET_DB": str(directory / "aria-claude-budget.db"),
        "ARIA_ELEVEN_LEDGER_DB": str(directory / "aria-eleven-ledger.db"),
    })
    return directory


_KEY_PASTE_ERROR = ("Paste only the complete newly revealed API key. "
                    "Masked values, commands, URLs, and embedded whitespace cannot be used.")


def _obviously_invalid_key(key: str) -> bool:
    """Reject obvious paste mistakes without assuming a key prefix or length."""
    return (not key or any(char.isspace() or unicodedata.category(char) in ("Cc", "Cf") for char in key)
            or any(marker in key for marker in ("•", "●", "…", "**", "...", "://"))
            or key.lower().startswith("www.") or "start_oracle_preview.py" in key)


def _check_provider_access(key: str, agent: str) -> bool:
    """Make one read request per check; never connect or retain authorization."""
    from oracle_api import _ORACLE_SIGNED_URL_ENDPOINT, _oracle_provider_error

    checks = (
        ("Agent read access", "https://api.elevenlabs.io/v1/convai/agents/" + quote(agent, safe=""), None),
        ("Signed-URL access", _ORACLE_SIGNED_URL_ENDPOINT,
         {"agent_id": agent, "include_conversation_id": "true"}),
    )
    accepted = True
    for label, endpoint, params in checks:
        try:
            response = requests.get(endpoint, params=params, headers={"xi-api-key": key},
                                    timeout=(5, 10), allow_redirects=False)
            # HTTP acceptance establishes endpoint access only, not agent privacy
            # or a usable conversation. Do not print or persist either body.
            result = "succeeded (HTTP 200)." if response.status_code == 200 else _oracle_provider_error(response)
            accepted = accepted and response.status_code == 200
        except requests.Timeout:
            accepted = False
            result = "ElevenLabs access check timed out."
        except (requests.RequestException, ValueError, TypeError):
            accepted = False
            result = "ElevenLabs access check is temporarily unavailable."
        print(f"{label}: {result}")
    return accepted


def _read_saved_key(agent: str) -> str | None:
    from scripts.oracle_keychain import KeychainError, read_key
    try:
        return read_key(agent)
    except KeychainError:
        print("Mac Keychain could not be opened. You can enter the key through the hidden prompt.", file=sys.stderr)
        return None


def _save_validated_key(agent: str, key: str) -> bool:
    from scripts.oracle_keychain import KeychainError, save_key
    try:
        save_key(agent, key)
    except KeychainError:
        print("Mac Keychain could not save the key. It is available only for this running session.", file=sys.stderr)
        return False
    return True


def _prompt_key(parser, will_save: bool) -> str:
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        parser.error("Run this setup in an interactive terminal for a masked API-key prompt. Do not paste a key into chat or a command argument.")
    prompt = ("ElevenLabs API key (hidden; saved in Mac Keychain after validation): " if will_save
              else "ElevenLabs API key (hidden; kept only in this process): ")
    while True:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                key = getpass.getpass(prompt).strip()
        except getpass.GetPassWarning:
            parser.error("This terminal cannot hide input. No key was accepted; use a terminal with secure hidden input.")
        except (EOFError, KeyboardInterrupt):
            parser.exit(1, "\nKey entry cancelled. No saved key was changed.\n")
        if not _obviously_invalid_key(key):
            return key
        print(_KEY_PASTE_ERROR, file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Secure local Oracle preview setup")
    parser.add_argument("--agent-config", type=Path,
                        default=Path("/private/tmp/oracle-elevenlabs-preview-config.json"),
                        help="Nonsecret private-agent configuration JSON")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--state-dir", type=Path, help="Isolated local preview state directory")
    parser.add_argument("--replace-key", action="store_true",
                        help="Prompt for a replacement; update Keychain only after access checks pass")
    parser.add_argument("--memory-only", action="store_true",
                        help="Do not read or save a key in Mac Keychain")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a local port from 1024 to 65535.")
    agent = (os.environ.get("ORACLE_ELEVENLABS_AGENT_ID", "").strip()
             or os.environ.get("ELEVENLABS_AGENT_ID", "").strip())
    if not agent:
        try:
            config = json.loads(args.agent_config.read_text())
            if config.get("requires_authentication") is not True:
                raise ValueError("Private-agent authentication is required.")
            agent = config["agent_id"]
            if not isinstance(agent, str) or not agent.startswith("agent_"):
                raise ValueError("Invalid private-agent reference.")
        except (OSError, ValueError, KeyError, TypeError):
            parser.error("Provide the existing private-agent reference through the server environment or a valid nonsecret --agent-config file.")
    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project))
    configure_preview_environment(project, args.state_dir)
    use_keychain = sys.platform == "darwin" and not args.memory_only
    source = "environment"
    key = "" if args.replace_key else os.environ.get("ELEVENLABS_API_KEY", "")
    if key and _obviously_invalid_key(key.strip()):
        parser.error("The configured API key failed the local paste check. " + _KEY_PASTE_ERROR)
    key = key.strip()
    if not key and use_keychain and not args.replace_key:
        key = _read_saved_key(agent) or ""
        if key:
            if _obviously_invalid_key(key):
                parser.error("The saved key is unusable. Run this launcher with --replace-key to enter the complete secret. The saved key was not changed.")
            source = "keychain"
            print("Using the Oracle key from Mac Keychain.")
    if not key:
        key = _prompt_key(parser, use_keychain)
        source = "prompt"
    os.environ["ELEVENLABS_API_KEY"] = key
    os.environ["ORACLE_ELEVENLABS_AGENT_ID"] = agent
    os.chdir(project)
    import uvicorn
    accepted = _check_provider_access(key, agent)
    saved = source == "keychain"
    if accepted and source == "prompt" and use_keychain:
        saved = _save_validated_key(agent, key)
        if saved:
            print("Oracle key saved in Mac Keychain. Future starts reuse it automatically.")
    if not accepted:
        print("Provider access could not be confirmed. No saved key was changed.")
        print("If the key has expired or was revoked, restart with --replace-key. Local chart review remains available.")
    print(f"Local preview: http://127.0.0.1:{args.port}/?tab=oracle")
    print("Isolated preview: background execution and notification workers are off.")
    print("Open Oracle and choose Connect text first. Voice uses the microphone only when selected.")
    if saved:
        print("The key stays in Mac Keychain when this preview stops. Use --replace-key to replace it.")
    else:
        print("This session's key was not saved by the launcher.")
    print("Press Control-C to stop this preview.")
    uvicorn.run("dashboard:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
