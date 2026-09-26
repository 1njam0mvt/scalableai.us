import hashlib
import hmac
import logging
import re
import secrets
import time
from typing import Optional

import jwt

from config import JWT_SECRET_KEY
from app.services.db import SessionLocal, UserRecord

logger = logging.getLogger("SCALABLE")

PBKDF2_ITERATIONS = 260_000
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
JWT_ALGORITHM = "HS256"
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """Raised for user-facing auth failures (bad credentials, taken username, etc)."""


class AuthService:
    """Postgres-backed username/password auth (formerly file-based JSON —
    see git history for the old database/users/*.json version).

    Not bank-grade (no email verification, no password reset) but
    genuinely real: PBKDF2-hashed passwords with per-user random salts,
    and actual access gating.

    Sessions are stateless JWTs, not a server-side session table. A JWT
    carries everything needed to verify itself (username + expiry, signed
    with JWT_SECRET_KEY) — nothing server-side to lose on a restart. The
    tradeoff, by design: "sign out" only removes the token from the
    browser; the token itself stays valid until it naturally expires.
    Account records (password hashes, email, display name) now live in
    Postgres, which — unlike Render's free-tier local disk — survives
    restarts and redeploys.
    """

    def __init__(self):
        pass  # no per-instance state; every method opens its own session

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

    # ---- row helpers ----

    @staticmethod
    def _normalize_username(username: str) -> str:
        return (username or "").strip().lower()

    def _load_user(self, username: str) -> Optional[dict]:
        username = self._normalize_username(username)
        if not username:
            return None
        db = SessionLocal()
        try:
            row = db.get(UserRecord, username)
            return row.to_dict() if row else None
        finally:
            db.close()

    def _save_user(self, username: str, data: dict) -> None:
        """Upsert — creates the row if new, otherwise overwrites the
        fields present in `data`. Mirrors the old file-based _save_user,
        which always wrote the whole record."""
        username = self._normalize_username(username)
        db = SessionLocal()
        try:
            row = db.get(UserRecord, username)
            if row is None:
                row = UserRecord(username=username)
                db.add(row)
            row.email = data.get("email", row.email or "")
            row.display_name = data.get("display_name", row.display_name or username)
            row.password_hash = data.get("password_hash", row.password_hash)
            row.oauth = data.get("oauth", row.oauth or {})
            row.created_at = data.get("created_at", row.created_at)
            db.commit()
        finally:
            db.close()

    def _email_taken(self, email: str) -> bool:
        return self._find_by_email(email) is not None

    def _find_by_email(self, email: str) -> Optional[dict]:
        email_lower = (email or "").strip().lower()
        if not email_lower:
            return None
        db = SessionLocal()
        try:
            row = db.query(UserRecord).filter(UserRecord.email == email_lower).first()
            return row.to_dict() if row else None
        finally:
            db.close()

    # ---- sessions (stateless JWTs — see class docstring) ----

    def _create_session(self, username: str) -> str:
        now = int(time.time())
        payload = {
            "username": username,
            "iat": now,
            "exp": now + SESSION_TTL_SECONDS,
        }
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    def get_username_for_token(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            # Covers a bad signature (forged/tampered token) and, notably,
            # a token signed under a *previous* JWT_SECRET_KEY. Those
            # tokens fail closed here rather than raising — a stale token
            # should just look logged-out, not error the request.
            return None
        username = payload.get("username")
        if not username:
            return None
        # A JWT alone can't be revoked, but it can still be checked against
        # reality: if the account behind it has since been deleted, its
        # old, not-yet-expired token must not go on "authenticating" as a
        # username with no account. Cheap: a single primary-key lookup.
        db = SessionLocal()
        try:
            if db.get(UserRecord, username) is None:
                return None
        finally:
            db.close()
        return username

    def revoke_session(self, token: Optional[str]) -> None:
        # Deliberately a no-op — see class docstring. The client is
        # responsible for discarding the token; this call exists so
        # /auth/logout has something to call and still returns cleanly.
        pass

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
            "username": self._normalize_username(username),
            "email": email,
            "display_name": (display_name or username).strip()[:60],
            "password_hash": self._hash_password(password),
            "oauth": {},
            "created_at": time.time(),
        }
        self._save_user(username, user_record)
        logger.info("[AUTH] New user signed up: %s", username)
        return self._create_session(self._normalize_username(username))

    def login(self, username_or_email: str, password: str) -> str:
        identifier = (username_or_email or "").strip()
        user_record = self._load_user(identifier)

        if not user_record and "@" in identifier:
            user_record = self._find_by_email(identifier)

        if not user_record or not self._verify_password(password or "", user_record.get("password_hash") or ""):
            raise AuthError("Incorrect username/email or password.")

        username = user_record["username"]
        logger.info("[AUTH] User logged in: %s", username)
        return self._create_session(username)

    def logout(self, token: Optional[str]) -> None:
        # No-op — see revoke_session and the class docstring.
        self.revoke_session(token)

    def get_profile(self, username: str) -> Optional[dict]:
        user_record = self._load_user(username)

        if not user_record:
            return None

        return {
            "username": user_record["username"],
            "email": user_record.get("email", ""),
            "display_name": user_record.get("display_name") or user_record["username"],
            "created_at": user_record.get("created_at"),
        }

    def change_password(self, username: str, current_password: str, new_password: str) -> None:
        user_record = self._load_user(username)

        if not user_record:
            raise AuthError("Account not found.")

        if not self._verify_password(current_password or "", user_record.get("password_hash") or ""):
            raise AuthError("Current password is incorrect.")

        if len(new_password or "") < 8:
            raise AuthError("New password must be at least 8 characters.")

        user_record["password_hash"] = self._hash_password(new_password)
        self._save_user(username, user_record)
        logger.info("[AUTH] Password changed for user: %s", username)

    def delete_account(self, username: str, password: str) -> None:
        user_record = self._load_user(username)

        if not user_record:
            raise AuthError("Account not found.")

        has_password = bool(user_record.get("password_hash"))
        if has_password:
            if not self._verify_password(password or "", user_record.get("password_hash") or ""):
                raise AuthError("Incorrect password.")
        # OAuth-only accounts (no local password) can delete without one —
        # the caller already authenticated via a valid session token.

        # No explicit session revocation needed: get_username_for_token()
        # checks the account still exists before trusting any token's
        # claimed username, so any existing token for this user stops
        # authenticating the instant the row below is deleted.
        username_norm = self._normalize_username(username)
        db = SessionLocal()
        try:
            row = db.get(UserRecord, username_norm)
            if row is not None:
                db.delete(row)
                db.commit()
        except Exception as e:
            db.rollback()
            logger.error("[AUTH] Could not delete user row for %s: %s", username, e)
            raise AuthError("Could not delete account. Please try again.")
        finally:
            db.close()

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

        db = SessionLocal()
        try:
            # 1. Already linked? Match on provider identity, not email.
            #    oauth is a JSON column — filter in Python since JSON
            #    containment operators differ across DB backends
            #    (Postgres vs SQLite, the local-dev fallback).
            all_users = db.query(UserRecord).all()
            for row in all_users:
                linked = row.oauth or {}
                if linked.get(provider) == provider_user_id:
                    logger.info("[AUTH] OAuth login (%s) for existing linked user: %s", provider, row.username)
                    return self._create_session(row.username)
        finally:
            db.close()

        # 2. Not linked yet — does an account with this email already exist?
        #    If so, link this provider to it rather than creating a duplicate.
        existing = self._find_by_email(email) if email else None
        if existing:
            username = existing["username"]
            oauth = existing.get("oauth") or {}
            oauth[provider] = provider_user_id
            existing["oauth"] = oauth
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