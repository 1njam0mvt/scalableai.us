"""
Personalization / Profile settings for SCALABLE

Backs the frontend's Personalization and Profile menu items. Settings are
per-account-key (a logged-in user's username, or a stable per-browser id
for anonymous/local use) and are actually injected into the system prompt
on every request — this isn't just stored and ignored.

Now Postgres-backed (formerly database/settings/<key>.json files, which
lived on Render's ephemeral free-tier disk and were wiped on restarts).
"""

import logging
import threading
from dataclasses import dataclass, asdict
from typing import Dict, Optional

from app.services.db import SessionLocal, SettingsRecord

logger = logging.getLogger("SCALABLE")

ALLOWED_LANGUAGES = {
    "English", "Spanish", "Mandarin Chinese", "Hindi", "French",
    "Standard Arabic", "Bengali", "Portuguese", "Russian", "Urdu",
    "Indonesian", "German", "Japanese", "Swahili", "Marathi",
    "Telugu", "Turkish", "Tamil", "Vietnamese", "Korean",
    "Italian", "Persian (Farsi)", "Gujarati", "Punjabi", "Polish",
    "Ukrainian", "Malayalam", "Kannada", "Thai", "Dutch",
    "Burmese", "Filipino (Tagalog)", "Romanian", "Uzbek", "Greek",
    "Czech", "Hungarian", "Swedish", "Amharic", "Zulu",
    "Nepali", "Sinhala", "Khmer", "Hebrew", "Finnish",
    "Danish", "Norwegian", "Bulgarian", "Serbian", "Croatian",
    "Slovak", "Lithuanian", "Latvian", "Estonian", "Slovenian",
    "Malay", "Georgian", "Armenian", "Azerbaijani", "Kazakh",
    "Mongolian", "Afrikaans", "Icelandic", "Somali", "Hausa",
}


@dataclass
class UserSettings:
    display_name: str = ""
    preferred_title: str = ""       # how Scalable should address them, e.g. "Sir"
    language: str = "English"
    bio: str = ""                   # free-text personalization notes, injected into system prompt
    theme: str = "dark"             # mirrors the frontend's own local toggle, kept in sync
    photo_url: str = ""             # Cloudinary URL of their uploaded avatar
    improve_model_for_everyone: bool = True
    marketing_measurement: bool = True
    personalized_marketing: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class SettingsService:

    def __init__(self, storage_dir=None):
        # storage_dir kept as an accepted (now unused) constructor arg so
        # the call site in main.py (SettingsService(storage_dir=SETTINGS_DIR))
        # doesn't need to change. Settings now live in Postgres, not on disk.
        self._lock = threading.Lock()
        self._cache: Dict[str, UserSettings] = {}

    @staticmethod
    def _safe_key(key: str) -> str:
        safe_key = "".join(c for c in (key or "") if c.isalnum() or c in ("-", "_"))[:64] or "default"
        return safe_key

    def get(self, key: str) -> UserSettings:
        safe_key = self._safe_key(key)
        with self._lock:
            if safe_key in self._cache:
                return self._cache[safe_key]

        db = SessionLocal()
        try:
            row = db.get(SettingsRecord, safe_key)
            settings = UserSettings(**row.to_dict()) if row else UserSettings()
        except Exception as e:
            logger.warning("[SETTINGS] Could not load settings for %s: %s", key, e)
            settings = UserSettings()
        finally:
            db.close()

        with self._lock:
            self._cache[safe_key] = settings
        return settings

    def update(self, key: str, **fields) -> UserSettings:
        safe_key = self._safe_key(key)
        settings = self.get(safe_key)

        with self._lock:
            if "language" in fields and fields["language"] not in ALLOWED_LANGUAGES:
                fields.pop("language")

            for k, v in fields.items():
                if v is None:
                    continue
                if k == "bio":
                    v = str(v)[:2000]
                if hasattr(settings, k):
                    setattr(settings, k, v)

            self._cache[safe_key] = settings

        db = SessionLocal()
        try:
            row = db.get(SettingsRecord, safe_key)
            if row is None:
                row = SettingsRecord(key=safe_key)
                db.add(row)
            for k, v in settings.to_dict().items():
                setattr(row, k, v)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("[SETTINGS] Failed to persist settings for %s: %s", key, e)
        finally:
            db.close()

        return settings

    def migrate(self, from_key: str, to_key: str) -> Optional[UserSettings]:
        """Copies a guest's settings onto their real account the moment they
        log in or sign up, then removes the guest-keyed row — the guest
        identity is throwaway once it's been folded into a real account, so
        nothing is left behind under the old key. Returns None (no-op) if
        the guest never actually had a settings row, which is the common
        case for a guest who never touched Settings."""
        safe_from = self._safe_key(from_key)

        db = SessionLocal()
        try:
            guest_row = db.get(SettingsRecord, safe_from)
            if guest_row is None:
                return None
            guest_dict = guest_row.to_dict()
        finally:
            db.close()

        # get()/update() each take self._lock internally (it isn't
        # reentrant), so this stays outside any lock of its own and lets
        # those calls do their own locking — calling one while already
        # holding the lock here would deadlock.
        account_settings = self.update(to_key, **guest_dict)

        db = SessionLocal()
        try:
            guest_row = db.get(SettingsRecord, safe_from)
            if guest_row is not None:
                db.delete(guest_row)
                db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("[SETTINGS] Could not remove guest settings row for %s: %s", from_key, e)
        finally:
            db.close()

        with self._lock:
            self._cache.pop(safe_from, None)

        return account_settings

    def build_prompt_addendum(self, key: str) -> str:
        """What actually gets injected into the system prompt for this account."""
        settings = self.get(key)
        parts = []

        if settings.preferred_title:
            parts.append(f"Address the user as: {settings.preferred_title}.")

        if settings.display_name:
            parts.append(f"The user's name is {settings.display_name}.")

        if settings.language and settings.language != "English":
            parts.append(f"Respond in {settings.language} unless the user writes in a different language.")

        if settings.bio:
            parts.append(f"Personal context about the user: {settings.bio}")

        return " ".join(parts)
