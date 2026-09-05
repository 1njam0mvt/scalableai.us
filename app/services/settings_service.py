"""
Personalization / Profile settings for SCALABLE

Backs the frontend's Personalization and Profile menu items. Settings are
per-account-key (a logged-in user's user_id, or a stable per-browser id for
anonymous/local use) and are actually injected into the system prompt on
every request — this isn't just stored and ignored.
"""

import json
import logging
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

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

    def to_dict(self) -> dict:
        return asdict(self)


class SettingsService:

    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: Dict[str, UserSettings] = {}

    def _path(self, key: str) -> Path:
        safe_key = "".join(c for c in key if c.isalnum() or c in ("-", "_"))[:64] or "default"
        return self.storage_dir / f"{safe_key}.json"

    def get(self, key: str) -> UserSettings:
        with self._lock:
            if key in self._cache:
                return self._cache[key]

            path = self._path(key)
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    settings = UserSettings(**{k: v for k, v in data.items() if k in UserSettings.__annotations__})
                except Exception as e:
                    logger.warning("[SETTINGS] Could not load settings for %s: %s", key, e)
                    settings = UserSettings()
            else:
                settings = UserSettings()

            self._cache[key] = settings
            return settings

    def update(self, key: str, **fields) -> UserSettings:
        with self._lock:
            settings = self.get(key)

            if "language" in fields and fields["language"] not in ALLOWED_LANGUAGES:
                fields.pop("language")

            for k, v in fields.items():
                if v is None:
                    continue
                if k == "bio":
                    v = str(v)[:2000]
                if hasattr(settings, k):
                    setattr(settings, k, v)

            self._cache[key] = settings

            try:
                with open(self._path(key), "w", encoding="utf-8") as f:
                    json.dump(settings.to_dict(), f, indent=2)
            except Exception as e:
                logger.error("[SETTINGS] Failed to persist settings for %s: %s", key, e)

            return settings

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

    