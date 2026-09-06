import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Optional, Dict, Any

from config import USERS_DIR

logger = logging.getLogger("SCALABLE")

PBKDF2_ITERATIONS = 260_000
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """Raised for user-facing auth failures (bad credentials, taken username, etc)."""


class AuthService:
    """Local, file-based username/password auth.

    Not bank-grade (no email verification, no password reset, single-server
    only) but genuinely real: PBKDF2-hashed passwords with per-user random
    salts, random unguessable session tokens, and actual access gating.
    """

    def __init__(self):
        self._users_dir: Path = USERS_DIR
        self._sessions_file = self._users_dir / "_sessions.json"
        self._sessions: Dict[str, Dict[str, Any]] = self._load_sessions()

    # ---- password hashing ----

    @staticmethod
    def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
        if salt is None:
            salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return f"{salt.hex()}${digest.hex()}"

    @staticmethod
    def _verify_password(password: str, stored: str) -> bool:
        try:
            salt_hex, digest_hex = stored.split("$", 1)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False

    # ---- user file storage ----

    def _user_path(self, username: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", username.lower())
        return self._users_dir / f"{safe}.json"

    def _load_user(self, username: str) -> Optional[dict]:
        path = self._user_path(username)

        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("[AUTH] Could not read user file %s: %s", path, e)
            return None

    def _save_user(self, username: str, data: dict) -> None:
        path = self._user_path(username)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _email_taken(self, email: str) -> bool:
        email_lower = email.strip().lower()

        for path in self._users_dir.glob("*.json"):
            if path.name.startswith("_"):  # skip _sessions.json etc
                continue

            try:
                with open(path, "r", encoding="utf-8") as f:
                    record = json.load(f)
                if (record.get("email") or "").strip().lower() == email_lower:
                    return True
            except Exception:
                continue

        return False

    # ---- sessions ----

    def _load_sessions(self) -> Dict[str, Dict[str, Any]]:
        if not self._sessions_file.exists():
            return {}

        try:
            with open(self._sessions_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            return {tok: s for tok, s in data.items() if s.get("expires_at", 0) > now}
        except Exception as e:
            logger.warning("[AUTH] Could not read sessions file: %s", e)
            return {}

    def _save_sessions(self) -> None:
        try:
            with open(self._sessions_file, "w", encoding="utf-8") as f:
                json.dump(self._sessions, f, indent=2)
        except Exception as e:
            logger.warning("[AUTH] Could not write sessions file: %s", e)

    def _create_session(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {
            "username": username,
            "expires_at": time.time() + SESSION_TTL_SECONDS,
        }
        self._save_sessions()
        return token

    def get_username_for_token(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None

        session = self._sessions.get(token)

        if not session:
            return None

        if session.get("expires_at", 0) <= time.time():
            self._sessions.pop(token, None)
            self._save_sessions()
            return None

        return session.get("username")

    def revoke_session(self, token: Optional[str]) -> None:
        if token and token in self._sessions:
            self._sessions.pop(token, None)
            self._save_sessions()

    # ---- public API ----

    def signup(self, username: str, password: str, email: str, display_name: Optional[str] = None) -> str:
        username = (username or "").strip()
        password = password or ""
        email = (email or "").strip()

        if not USERNAME_RE.match(username):
            raise AuthError("Username must be 3-30 characters: letters, numbers, underscore, or period.")

        if username.startswith("__guest_"):
            raise AuthError("That username is reserved.")

        if not EMAIL_RE.match(email):
            raise AuthError("Please enter a valid email address.")

        if len(password) < 8:
            raise AuthError("Password must be at least 8 characters.")

        if self._load_user(username) is not None:
            raise AuthError("That username is already taken.")

        if self._email_taken(email):
            raise AuthError("An account with that email already exists.")

        user_record = {
            "username": username,
            "email": email,
            "display_name": (display_name or username).strip()[:60],
            "password_hash": self._hash_password(password),
            "created_at": time.time(),
        }
        self._save_user(username, user_record)
        logger.info("[AUTH] New user signed up: %s", username)
        return self._create_session(username)

    def _find_by_email(self, email: str) -> Optional[dict]:
        email_lower = email.strip().lower()

        for path in self._users_dir.glob("*.json"):
            if path.name.startswith("_"):
                continue

            try:
                with open(path, "r", encoding="utf-8") as f:
                    record = json.load(f)
                if (record.get("email") or "").strip().lower() == email_lower:
                    return record
            except Exception:
                continue

        return None

    def login(self, username_or_email: str, password: str) -> str:
        identifier = (username_or_email or "").strip()
        user_record = self._load_user(identifier)

        if not user_record and "@" in identifier:
            user_record = self._find_by_email(identifier)

        if not user_record or not self._verify_password(password or "", user_record.get("password_hash", "")):
            raise AuthError("Incorrect username/email or password.")

        username = user_record["username"]
        logger.info("[AUTH] User logged in: %s", username)
        return self._create_session(username)

    def logout(self, token: Optional[str]) -> None:
        self.revoke_session(token)

    def get_profile(self, username: str) -> Optional[dict]:
        user_record = self._load_user(username)

        if not user_record:
            return None

        return {
            "username": user_record["username"],
            "email": user_record.get("email", ""),
            "display_name": user_record.get("display_name", user_record["username"]),
            "created_at": user_record.get("created_at"),
        }

    def change_password(self, username: str, current_password: str, new_password: str) -> None:
        user_record = self._load_user(username)

        if not user_record:
            raise AuthError("Account not found.")

        if not self._verify_password(current_password or "", user_record.get("password_hash", "")):
            raise AuthError("Current password is incorrect.")

        if len(new_password or "") < 8:
            raise AuthError("New password must be at least 8 characters.")

        user_record["password_hash"] = self._hash_password(new_password)
        self._save_user(username, user_record)
        logger.info("[AUTH] Password changed for user: %s", username)

    def _revoke_all_sessions_for_user(self, username: str) -> None:
        tokens_to_remove = [tok for tok, s in self._sessions.items() if s.get("username") == username]

        for tok in tokens_to_remove:
            self._sessions.pop(tok, None)

        if tokens_to_remove:
            self._save_sessions()

    def delete_account(self, username: str, password: str) -> None:
        user_record = self._load_user(username)

        if not user_record:
            raise AuthError("Account not found.")

        has_password = bool(user_record.get("password_hash"))
        if has_password:
            if not self._verify_password(password or "", user_record.get("password_hash", "")):
                raise AuthError("Incorrect password.")
        # OAuth-only accounts (no local password) can delete without one —
        # the caller already authenticated via a valid session token to
        # reach this endpoint at all.

        self._revoke_all_sessions_for_user(username)
        path = self._user_path(username)

        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            logger.error("[AUTH] Could not delete user file for %s: %s", username, e)
            raise AuthError("Could not delete account. Please try again.")

        logger.info("[AUTH] Account deleted: %s", username)

    # ---- OAuth (Google / Apple / GitHub) ----

    def _generate_username_from(self, base: str) -> str:
        """Turns an OAuth display name/email into a valid, available
        username, appending digits if there's a collision."""
        base = re.sub(r"[^a-zA-Z0-9_.]", "", (base or "").strip().lower())[:24] or "user"
        if len(base) < 3:
            base = (base + "user")[:24]
        candidate = base
        suffix = 0
        while self._load_user(candidate) is not None:
            suffix += 1
            candidate = f"{base}{suffix}"[:30]
        return candidate

    def find_or_create_oauth_user(
        self,
        provider: str,
        provider_user_id: str,
        email: Optional[str],
        display_name: Optional[str],
    ) -> str:
        """Given a verified identity from an OAuth provider, finds the
        matching local account (by provider+provider_user_id first, then
        by email) or creates a new one. Returns a session token.

        provider_user_id is the provider's own stable subject/user id
        (e.g. Google's 'sub' claim, GitHub's numeric id) — never the
        email alone, since emails can change or be reused."""
        provider = provider.strip().lower()

        # 1. Already linked? Match on provider identity, not email.
        for path in self._users_dir.glob("*.json"):
            if path.name.startswith("_"):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    record = json.load(f)
            except Exception:
                continue
            linked = record.get("oauth", {})
            if linked.get(provider) == provider_user_id:
                username = record["username"]
                logger.info("[AUTH] OAuth login (%s) for existing linked user: %s", provider, username)
                return self._create_session(username)

        # 2. Not linked yet — does an account with this email already exist?
        #    If so, link this provider to it rather than creating a duplicate.
        existing = self._find_by_email(email) if email else None
        if existing:
            username = existing["username"]
            existing.setdefault("oauth", {})[provider] = provider_user_id
            self._save_user(username, existing)
            logger.info("[AUTH] Linked %s to existing account: %s", provider, username)
            return self._create_session(username)

        # 3. Brand new user.
        username = self._generate_username_from(display_name or (email.split("@")[0] if email else "") or provider)
        user_record = {
            "username": username,
            "email": (email or "").strip(),
            "display_name": (display_name or username).strip()[:60],
            "password_hash": None,  # OAuth-only account — no local password
            "oauth": {provider: provider_user_id},
            "created_at": time.time(),
        }
        self._save_user(username, user_record)
        logger.info("[AUTH] New user created via %s OAuth: %s", provider, username)
        return self._create_session(username)