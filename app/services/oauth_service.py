"""
OAuth ("Continue with Google / Apple / GitHub") login.

Standard server-side authorization-code flow for all three providers:

  1. Frontend hits GET /auth/oauth/{provider}/start
  2. We redirect the browser to the provider's consent screen, with a
     random `state` value stored server-side to prevent CSRF
  3. Provider redirects back to GET /auth/oauth/{provider}/callback
     with a `code` (and the `state` we gave it)
  4. We verify `state`, exchange `code` for tokens server-to-server,
     fetch the user's verified identity, then hand off to
     AuthService.find_or_create_oauth_user() to get a session token
  5. We redirect the browser back into the app with that session token

Each provider's client ID/secret come from environment variables — see
.env.example. A provider is simply unavailable (its button can be hidden,
or clicking it returns a clear error) if its env vars aren't set, rather
than crashing the whole app.
"""

import base64
import hashlib
import logging
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger("SCALABLE")

# state tokens expire quickly — this is just CSRF protection for a
# redirect round-trip that normally completes in a few seconds
STATE_TTL_SECONDS = 600


@dataclass
class OAuthIdentity:
    provider: str
    provider_user_id: str
    email: Optional[str]
    display_name: Optional[str]


@dataclass
class ProviderConfig:
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    scope: str
    # Apple uses form_post + a JWT client_secret and returns identity
    # inside the token response itself rather than a separate userinfo
    # call; the other two use a simple userinfo endpoint.
    userinfo_url: Optional[str] = None


class OAuthService:
    def __init__(self, base_url: str, google=None, apple=None, github=None):
        """base_url is the public origin (e.g. https://scalableai.us) used
        to build the callback redirect_uri sent to each provider — this
        MUST exactly match what's registered in that provider's console."""
        self.base_url = base_url.rstrip("/")
        self._pending_state: dict[str, float] = {}  # state -> expiry timestamp
        self.providers: dict[str, ProviderConfig] = {}
        if google:
            self.providers["google"] = google
        if apple:
            self.providers["apple"] = apple
        if github:
            self.providers["github"] = github

    def is_configured(self, provider: str) -> bool:
        return provider in self.providers

    def _redirect_uri(self, provider: str) -> str:
        return f"{self.base_url}/auth/oauth/{provider}/callback"

    def _new_state(self) -> str:
        self._prune_expired_state()
        state = secrets.token_urlsafe(24)
        self._pending_state[state] = time.time() + STATE_TTL_SECONDS
        return state

    def _prune_expired_state(self) -> None:
        now = time.time()
        expired = [s for s, exp in self._pending_state.items() if exp < now]
        for s in expired:
            self._pending_state.pop(s, None)

    def consume_state(self, state: str) -> bool:
        """Returns True exactly once for a given valid, unexpired state —
        prevents replaying the same callback twice."""
        self._prune_expired_state()
        expiry = self._pending_state.pop(state, None)
        return expiry is not None

    def build_authorize_url(self, provider: str) -> str:
        cfg = self.providers.get(provider)
        if not cfg:
            raise ValueError(f"OAuth provider not configured: {provider}")

        state = self._new_state()
        params = {
            "client_id": cfg.client_id,
            "redirect_uri": self._redirect_uri(provider),
            "response_type": "code",
            "scope": cfg.scope,
            "state": state,
        }
        if provider == "apple":
            params["response_mode"] = "form_post"
        return f"{cfg.authorize_url}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, provider: str, code: str) -> OAuthIdentity:
        cfg = self.providers.get(provider)
        if not cfg:
            raise ValueError(f"OAuth provider not configured: {provider}")

        if provider == "google":
            return await self._exchange_google(cfg, code)
        if provider == "github":
            return await self._exchange_github(cfg, code)
        if provider == "apple":
            return await self._exchange_apple(cfg, code)
        raise ValueError(f"Unknown provider: {provider}")

    async def _exchange_google(self, cfg: ProviderConfig, code: str) -> OAuthIdentity:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(cfg.token_url, data={
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "code": code,
                "redirect_uri": self._redirect_uri("google"),
                "grant_type": "authorization_code",
            })
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]

            user_resp = await client.get(cfg.userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
            user_resp.raise_for_status()
            data = user_resp.json()

        return OAuthIdentity(
            provider="google",
            provider_user_id=data["sub"],
            email=data.get("email"),
            display_name=data.get("name"),
        )

    async def _exchange_github(self, cfg: ProviderConfig, code: str) -> OAuthIdentity:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                cfg.token_url,
                data={
                    "client_id": cfg.client_id,
                    "client_secret": cfg.client_secret,
                    "code": code,
                    "redirect_uri": self._redirect_uri("github"),
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            if "error" in token_data:
                raise RuntimeError(f"GitHub token exchange failed: {token_data.get('error_description', token_data['error'])}")
            access_token = token_data["access_token"]

            user_resp = await client.get(cfg.userinfo_url, headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            })
            user_resp.raise_for_status()
            data = user_resp.json()

            email = data.get("email")
            if not email:
                # GitHub only returns a public email if the user set one;
                # otherwise fetch their verified primary email separately.
                emails_resp = await client.get("https://api.github.com/user/emails", headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                })
                if emails_resp.status_code == 200:
                    for e in emails_resp.json():
                        if e.get("primary") and e.get("verified"):
                            email = e.get("email")
                            break

        return OAuthIdentity(
            provider="github",
            provider_user_id=str(data["id"]),
            email=email,
            display_name=data.get("name") or data.get("login"),
        )

    async def _exchange_apple(self, cfg: ProviderConfig, code: str) -> OAuthIdentity:
        # Apple's client_secret is a short-lived JWT you generate, not a
        # static string — see build_apple_client_secret() below. cfg.client_secret
        # here is expected to already be that generated JWT (regenerated
        # periodically; see the deploy notes in DEPLOY.md).
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(cfg.token_url, data={
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "code": code,
                "redirect_uri": self._redirect_uri("apple"),
                "grant_type": "authorization_code",
            })
            token_resp.raise_for_status()
            token_data = token_resp.json()

        # Apple returns identity inside the id_token (a JWT), not a
        # separate userinfo call. We only need the payload's claims, and
        # we already trust this token because it came directly from
        # Apple's token endpoint over TLS (server-to-server) — so this
        # decodes the payload without re-verifying the signature.
        id_token = token_data.get("id_token", "")
        payload = _decode_jwt_payload_unverified(id_token)

        return OAuthIdentity(
            provider="apple",
            provider_user_id=payload.get("sub", ""),
            email=payload.get("email"),
            display_name=None,  # Apple only sends a name on first-ever login, via the form POST body, not here
        )


def _decode_jwt_payload_unverified(token: str) -> dict:
    import json
    try:
        parts = token.split(".")
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception as e:
        logger.warning("[OAUTH] Could not decode Apple id_token: %s", e)
        return {}
    