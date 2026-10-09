"""Fail-closed Claude credit allowance. No secrets, prompts or payment operations.

This is a local conservative allowance, NOT an Anthropic balance API. Live use
requires the owner to verify the prepaid organization has no purchased credits,
no invoicing, no auto-reload, and an isolated allocation that other users cannot
consume. Do not enable this module until those facts and the credit expiry are
confirmed. Reservations are never refunded, including on ambiguous failures.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING

# Standard direct API USD per million tokens, checked 2026-10-09:
# https://platform.claude.com/docs/en/about-claude/pricing
# Haiku uses its higher context price conservatively at all input lengths.
MODEL_RATES = {
    "claude-sonnet-5-5": (2, 10),
    "claude-sonnet-4-6": (3, 15),
    "claude-haiku-5-5": (Decimal("0.50"), Decimal("2.50")),
    "claude-haiku-4-5-20251001": (1, 5),
}
OUTPUT_HARD_CAP = 4096
ATTESTATION_MAX_AGE = 86400            # default; CLAUDE_ATTESTATION_MAX_HOURS may set 1..168 hours


def attestation_max_age() -> float:
    """How long an owner's account check stays valid. Default 24 h; the owner may choose up to 7 days."""
    raw = os.getenv("CLAUDE_ATTESTATION_MAX_HOURS", "").strip()
    if not raw:
        return ATTESTATION_MAX_AGE
    try:
        hours = float(raw)
    except ValueError:
        raise CreditBlocked("CLAUDE_ATTESTATION_MAX_HOURS must be a number of hours from 1 to 168.") from None
    if not (math.isfinite(hours) and 1 <= hours <= 168):
        raise CreditBlocked("CLAUDE_ATTESTATION_MAX_HOURS must be a number of hours from 1 to 168.")
    return hours * 3600


class CreditBlocked(Exception):
    """Safe reason suitable for an owner-facing configuration status."""


def _usd_micro(value: str) -> int:
    try:
        n = Decimal(value)
        if not n.is_finite() or n <= 0 or n > 200:
            raise ValueError
        return int((n * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, ValueError, OverflowError):
        raise CreditBlocked("Set a positive Claude credit allowance of at most $200.") from None


def _timestamp(name: str) -> float:
    """A UTC Unix timestamp, or an ISO 8601 time with an explicit UTC zone (2026-10-17T00:00:00Z)."""
    raw = os.getenv(name, "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(Z|\+00:00)", raw):
            from datetime import datetime
            value = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        else:
            value = float(raw)
        if not 0 < value < 1e11:
            raise ValueError
        return value
    except ValueError:
        raise CreditBlocked(f"Set {name} as a UTC time like 2026-10-17T00:00:00Z (or a Unix timestamp).") from None


@dataclass(frozen=True)
class CreditConfig:
    period: str
    budget: int
    expires: float
    verified: float
    model: str
    path: str

    @classmethod
    def from_environment(cls, default_path: str) -> "CreditConfig":
        if os.getenv("ARIA_CLAUDE_ENABLED", "") != "1":
            raise CreditBlocked("Claude is off until ARIA_CLAUDE_ENABLED=1 is explicitly approved.")
        checks = ("CLAUDE_PREPAID_ONLY_CONFIRMED", "CLAUDE_AUTO_RELOAD_DISABLED_CONFIRMED",
                  "CLAUDE_NO_PURCHASED_CREDITS_CONFIRMED", "CLAUDE_ISOLATED_ALLOCATION_CONFIRMED",
                  "CLAUDE_PRICING_CONFIRMED", "CLAUDE_PERSISTENT_LEDGER_CONFIRMED")
        if any(os.getenv(k, "") != "1" for k in checks):
            raise CreditBlocked("Claude account, isolated promotional allowance and pricing safeguards are not verified.")
        if not os.getenv("ANTHROPIC_API_KEY", "").strip():
            raise CreditBlocked("No Claude API key is configured in the server environment.")
        period = os.getenv("CLAUDE_CREDIT_PERIOD", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", period):
            raise CreditBlocked("Set the stable CLAUDE_CREDIT_PERIOD for this credit allocation.")
        model = os.getenv("ARIA_CLAUDE_MODEL", "claude-sonnet-5-5").strip()
        if model not in MODEL_RATES:
            raise CreditBlocked("The Claude model has no reviewed pricing allowance.")
        path = os.getenv("ARIA_CLAUDE_BUDGET_DB", "").strip()
        if not path or not os.path.isabs(path) or not os.path.isdir(os.path.dirname(path)):
            raise CreditBlocked("Set ARIA_CLAUDE_BUDGET_DB on verified persistent private storage.")
        config = cls(period, _usd_micro(os.getenv("ARIA_CLAUDE_CREDIT_BUDGET_USD", "0")),
                     _timestamp("CLAUDE_CREDIT_EXPIRES_AT"), _timestamp("CLAUDE_CREDIT_VERIFIED_AT"),
                     model, path)
        config.check_time()
        return config

    def check_time(self) -> None:
        now = time.time()
        if self.verified > now + 60 or now - self.verified >= attestation_max_age():
            raise CreditBlocked("Claude credit/account verification is stale; recheck before using credits.")
        # A request may continue charging after a disconnect. Stop well before expiry.
        if now + 300 >= self.expires:
            raise CreditBlocked("Claude promotional credits have expired or are about to expire.")

    def reserve_cost(self, body: dict) -> int:
        if body.get("model") != self.model:
            raise CreditBlocked("The requested Claude model differs from the reviewed model.")
        max_out = body.get("max_tokens")
        if type(max_out) is not int or not 1 <= max_out <= OUTPUT_HARD_CAP:
            raise CreditBlocked("Claude output exceeds the reviewed hard limit.")
        # Plain text/client tools only. Reserve twice every UTF-8 JSON byte plus
        # 2048 tokens for provider-side formatting/tool overhead. This is deliberately
        # a large local safety margin, not an exact token count or billing guarantee.
        size = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        if size > 120000:
            raise CreditBlocked("The Claude request exceeds the reviewed input limit.")
        inp, out = MODEL_RATES[self.model]
        return int((Decimal(size * 2 + 2048) * Decimal(inp) + Decimal(max_out) * Decimal(out))
                   .to_integral_value(rounding=ROUND_CEILING))


def _owned_by_app_user(path: str) -> None:
    """Provisioning from a host shell runs as root, but the server runs as the 'app' user:
    hand the private ledger to it, or the server could not open it until the next restart."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        try:
            import pwd
            entry = pwd.getpwnam("app")
            os.chown(path, entry.pw_uid, entry.pw_gid)
        except (KeyError, ImportError, OSError):
            pass


class CreditLedger:
    """One persistent SQLite ledger shared by every worker for this allocation.

    Reusing a period cannot increase its initial cap or expiry. Renew attestation
    on the same period; a NEW verified monthly allocation needs a NEW period.
    """
    def __init__(self, config: CreditConfig):
        self.config = config

    def _connect(self):
        # Request handlers may never recreate a lost ledger or a credit period.
        # A deployment with missing persistence therefore stops instead of resetting.
        from pathlib import Path
        return sqlite3.connect(Path(self.config.path).as_uri() + "?mode=rw", uri=True,
                               timeout=10, isolation_level=None)

    def provision(self) -> None:
        """Explicit OFFLINE owner operation, once for a freshly verified allocation.

        Never called by the provider or an HTTP endpoint. Existing period rows
        remain unchanged; only a newly verified allocation gets a new period.
        """
        self.config.check_time()
        with closing(sqlite3.connect(self.config.path, timeout=10)) as db:
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS claude_allowance (period TEXT PRIMARY KEY, cap INTEGER NOT NULL, reserved INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL)")
                db.execute("INSERT OR IGNORE INTO claude_allowance(period,cap,expires) VALUES(?,?,?)",
                           (self.config.period, self.config.budget, self.config.expires))
        os.chmod(self.config.path, 0o600)
        _owned_by_app_user(self.config.path)

    def available(self) -> int:
        self.config.check_time()
        with closing(self._connect()) as db:
            row = db.execute("SELECT cap,reserved,expires FROM claude_allowance WHERE period=?", (self.config.period,)).fetchone()
        if not row:
            raise CreditBlocked("This verified Claude allocation has not been provisioned offline.")
        if time.time() + 300 >= min(row[2], self.config.expires):
            raise CreditBlocked("This Claude credit allocation has expired.")
        return max(0, min(row[0], self.config.budget) - row[1])

    def reserve(self, amount: int) -> None:
        self.config.check_time()
        if type(amount) is not int or amount <= 0:
            raise CreditBlocked("Invalid Claude credit reservation.")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT cap,reserved,expires FROM claude_allowance WHERE period=?", (self.config.period,)).fetchone()
            if not row:
                raise CreditBlocked("This Claude credit allocation is not provisioned.")
            cap, expires = min(row[0], self.config.budget), min(row[2], self.config.expires)
            if time.time() + 300 >= expires or row[1] + amount > cap:
                raise CreditBlocked("Claude has reached its reserved promotional-credit allowance.")
            db.execute("UPDATE claude_allowance SET cap=?,reserved=reserved+?,expires=? WHERE period=?",
                       (cap, amount, expires, self.config.period))
            db.execute("COMMIT")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()


def main(argv: list) -> int:
    """python3 claude_credits.py provision   create this allocation's ledger (offline, once)
python3 claude_credits.py check       say whether Claude may run, and what is left (no network)"""
    if argv[1:] not in (["provision"], ["check"]):
        print(main.__doc__)
        return 2
    try:
        config = CreditConfig.from_environment("")
        if argv[1] == "provision":
            CreditLedger(config).provision()
            print("Claude ledger ready:", config.path, "| period", config.period)
        left = CreditLedger(config).available()
        print(f"Claude may run: ${left / 1e6:.2f} of ${config.budget / 1e6:.2f} left in period {config.period};"
              f" check valid until {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(config.verified + attestation_max_age()))};"
              f" credits stop at {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(config.expires - 300))}.")
        return 0
    except (CreditBlocked, sqlite3.Error, OSError) as e:
        print("Claude is blocked:", e)
        return 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv))
