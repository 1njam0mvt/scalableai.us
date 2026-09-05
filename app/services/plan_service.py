"""
Plan/tier tracking for SCALABLE

What this is: a real, working free/pro tier system — daily message limits are
actually enforced, "Upgrade" actually changes the account's tier server-side,
and every plan-checking function here is live and used by main.py.

What this is NOT (yet): a payment processor integration. There is no Stripe
(or similar) account connected, because that requires real API keys from a
real Stripe account that doesn't exist yet. The `upgrade()` method below is
where that would plug in — right now it performs the upgrade directly
(useful for local/personal use, or for manually comping accounts), but it's
structured so that swapping in a real checkout flow means adding a payment
verification step before calling `_set_plan`, not rebuilding this file.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("SCALABLE")

PLAN_LIMITS = {
    "free": {
        "daily_messages": 40,
        "daily_images": 5,
        "label": "Free",
    },
    "pro": {
        "daily_messages": 1000,
        "daily_images": 200,
        "label": "Pro",
    },
}

DEFAULT_PLAN = "free"


@dataclass
class UsageRecord:
    date_key: str = ""
    messages_used: int = 0
    images_used: int = 0


@dataclass
class PlanEntry:
    plan: str = DEFAULT_PLAN
    usage: UsageRecord = field(default_factory=UsageRecord)


class PlanLimitExceeded(Exception):
    def __init__(self, message: str, plan: str, limit_type: str):
        super().__init__(message)
        self.plan = plan
        self.limit_type = limit_type


class PlanService:

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._entries: Dict[str, PlanEntry] = {}
        self._load()

    # ---- persistence ----

    def _load(self):
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for key, val in raw.items():
                usage = UsageRecord(**val.get("usage", {}))
                self._entries[key] = PlanEntry(plan=val.get("plan", DEFAULT_PLAN), usage=usage)
            logger.info("[PLAN] Loaded %d plan record(s)", len(self._entries))
        except Exception as e:
            logger.warning("[PLAN] Could not load plan data: %s", e)

    def _save(self):
        try:
            serializable = {
                key: {"plan": e.plan, "usage": e.usage.__dict__}
                for key, e in self._entries.items()
            }
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2)
        except Exception as e:
            logger.error("[PLAN] Failed to save plan data: %s", e)

    # ---- internals ----

    @staticmethod
    def _today_key() -> str:
        return time.strftime("%Y-%m-%d")

    def _get_entry(self, key: str) -> PlanEntry:
        entry = self._entries.get(key)
        if not entry:
            entry = PlanEntry()
            self._entries[key] = entry

        today = self._today_key()
        if entry.usage.date_key != today:
            entry.usage = UsageRecord(date_key=today)
        return entry

    # ---- public API ----

    def get_status(self, key: str) -> dict:
        with self._lock:
            entry = self._get_entry(key)
            limits = PLAN_LIMITS[entry.plan]
            return {
                "plan": entry.plan,
                "label": limits["label"],
                "messages_used": entry.usage.messages_used,
                "messages_limit": limits["daily_messages"],
                "images_used": entry.usage.images_used,
                "images_limit": limits["daily_images"],
            }

    def check_and_increment_message(self, key: str):
        """Raises PlanLimitExceeded if the daily message cap is hit, else increments it."""
        with self._lock:
            entry = self._get_entry(key)
            limits = PLAN_LIMITS[entry.plan]

            if entry.usage.messages_used >= limits["daily_messages"]:
                raise PlanLimitExceeded(
                    f"You've hit today's {limits['label']} plan limit of "
                    f"{limits['daily_messages']} messages. Upgrade for more, or try again tomorrow.",
                    plan=entry.plan,
                    limit_type="messages",
                )

            entry.usage.messages_used += 1
            self._save()

    def check_and_increment_image(self, key: str):
        with self._lock:
            entry = self._get_entry(key)
            limits = PLAN_LIMITS[entry.plan]

            if entry.usage.images_used >= limits["daily_images"]:
                raise PlanLimitExceeded(
                    f"You've hit today's {limits['label']} plan limit of "
                    f"{limits['daily_images']} generated images. Upgrade for more, or try again tomorrow.",
                    plan=entry.plan,
                    limit_type="images",
                )

            entry.usage.images_used += 1
            self._save()

    def upgrade(self, key: str, payment_verified: bool = True) -> dict:
        """
        payment_verified exists so a real payment step can be inserted later:
        e.g. `payment_verified = stripe_service.confirm_checkout(session_id)`
        before this ever flips someone to 'pro'. Right now it defaults to
        True since there's no payment processor wired in yet.
        """
        if not payment_verified:
            raise PlanLimitExceeded("Payment could not be verified.", plan="free", limit_type="payment")

        with self._lock:
            entry = self._get_entry(key)
            entry.plan = "pro"
            self._save()
            logger.info("[PLAN] %s upgraded to pro", key)
            return self.get_status(key)

    def downgrade(self, key: str) -> dict:
        with self._lock:
            entry = self._get_entry(key)
            entry.plan = "free"
            self._save()
            logger.info("[PLAN] %s downgraded to free", key)
            return self.get_status(key)

        