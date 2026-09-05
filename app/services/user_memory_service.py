"""
Per-user memory notes for SCALABLE.

Separate from Personalization (nickname/response-length/custom-instructions,
which are structured settings) and separate from a specific chat's own
history. This is a small, freeform, plain-text scratchpad per user —
"things Scalable has picked up about this person" — that persists across
every conversation they have, and that the user can see, edit, or clear
themselves at any time.

Storage: one .txt file per user at database/user_memory/<username>.txt.
Usernames are already validated at signup (auth_service), so we reuse that
same safe-filename assumption here rather than re-deriving our own slug.
"""

import logging
import re
import threading
from pathlib import Path
from typing import Optional

from config import USER_MEMORY_DIR, USER_MEMORY_MAX_BYTES

logger = logging.getLogger("SCALABLE")

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


class UserMemoryService:
    """Reads/writes/appends a single plain-text memory file per user."""

    def __init__(self) -> None:
        self._dir: Path = USER_MEMORY_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def _lock_for(self, username: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(username)
            if lock is None:
                lock = threading.Lock()
                self._locks[username] = lock
            return lock

    def _path_for(self, username: str) -> Optional[Path]:
        """Returns the file path for a username, or None if the username
        doesn't look like a safe filename (defense in depth — usernames
        should already be validated at signup, but never trust it twice)."""
        if not username or not _USERNAME_RE.match(username):
            logger.warning("[USER_MEMORY] Rejected unsafe username for memory path: %r", username)
            return None
        return self._dir / f"{username}.txt"

    def read(self, username: str) -> str:
        """Returns the user's current memory notes, or '' if none exist yet."""
        path = self._path_for(username)
        if not path or not path.exists():
            return ""
        try:
            with self._lock_for(username):
                return path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("[USER_MEMORY] Could not read memory for %s: %s", username, e)
            return ""

    def write(self, username: str, content: str) -> bool:
        """Overwrites the user's memory notes entirely (used by the
        Settings UI when the user edits/clears their own memory)."""
        path = self._path_for(username)
        if not path:
            return False
        content = content[:USER_MEMORY_MAX_BYTES]
        try:
            with self._lock_for(username):
                path.write_text(content, encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("[USER_MEMORY] Could not write memory for %s: %s", username, e)
            return False

    def append_fact(self, username: str, fact: str) -> bool:
        """Adds one durable fact as a new line, called by the chat pipeline
        when the model decides something is worth remembering. Silently
        no-ops (rather than erroring the chat) if the file is already at
        its size cap — memory is best-effort, not load-bearing."""
        fact = (fact or "").strip()
        if not fact:
            return False
        path = self._path_for(username)
        if not path:
            return False
        try:
            with self._lock_for(username):
                existing = path.read_text(encoding="utf-8") if path.exists() else ""
                if fact in existing:
                    return True  # already recorded, avoid duplicate lines
                new_content = (existing.rstrip("\n") + "\n" + fact).lstrip("\n")
                if len(new_content.encode("utf-8")) > USER_MEMORY_MAX_BYTES:
                    logger.info("[USER_MEMORY] Memory file for %s at cap, dropping new fact", username)
                    return False
                path.write_text(new_content, encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("[USER_MEMORY] Could not append memory for %s: %s", username, e)
            return False

    def clear(self, username: str) -> bool:
        path = self._path_for(username)
        if not path:
            return False
        try:
            with self._lock_for(username):
                if path.exists():
                    path.unlink()
            return True
        except OSError as e:
            logger.warning("[USER_MEMORY] Could not clear memory for %s: %s", username, e)
            return False


user_memory_service = UserMemoryService()