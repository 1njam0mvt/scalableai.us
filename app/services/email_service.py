"""
Transactional email — currently just "you've been invited to a shared
chat" — sent via Resend's HTTP API (https://resend.com).

If RESEND_API_KEY isn't set, send_share_invite_email() logs a warning and
returns False rather than raising: inviting someone still works as access
control even with no email configured, the invited person just has to be
handed the link manually instead of receiving it automatically. Nothing
in the calling code should treat a failed/skipped send as an error that
blocks the invite itself.
"""

import logging
from typing import Optional

import httpx

from config import RESEND_API_KEY, RESEND_FROM_EMAIL

logger = logging.getLogger("SCALABLE")

RESEND_ENDPOINT = "https://api.resend.com/emails"
_REQUEST_TIMEOUT = 10


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


async def send_share_invite_email(
    to_email: str,
    share_link: str,
    inviter_name: Optional[str] = None,
    chat_title: Optional[str] = None,
) -> bool:
    """Sends the invite email. Returns True only on a confirmed 2xx from
    Resend; any missing config, network failure, or non-2xx response
    returns False and logs a warning rather than raising, since a failed
    email should never undo or block the invite/share action that
    triggered it."""
    if not RESEND_API_KEY:
        logger.warning(
            "send_share_invite_email skipped for %s — RESEND_API_KEY is not set. "
            "The invite was still recorded; share the link manually.",
            to_email,
        )
        return False

    inviter = _escape(inviter_name or "Someone")
    title = _escape(chat_title or "a conversation")
    safe_link = _escape(share_link)

    subject = f"{inviter} shared a chat with you on ScalableAI"
    html = f"""
    <div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 480px; margin: 0 auto; color: #17171a;">
        <p style="font-size: 15px; line-height: 1.6;">
            <strong>{inviter}</strong> invited you to view <strong>{title}</strong> on ScalableAI.
        </p>
        <p style="margin: 24px 0;">
            <a href="{safe_link}" style="background:#17171a;color:#fff;padding:10px 20px;border-radius:999px;text-decoration:none;font-size:14px;font-weight:600;display:inline-block;">
                View shared chat
            </a>
        </p>
        <p style="font-size: 12.5px; color: #6c6c76; line-height: 1.6;">
            If the button doesn't work, copy this link into your browser:<br>
            <a href="{safe_link}" style="color:#46464f;">{safe_link}</a>
        </p>
    </div>
    """.strip()

    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(
                RESEND_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code >= 200 and resp.status_code < 300:
            return True
        logger.warning(
            "send_share_invite_email: Resend returned %s for %s — %s",
            resp.status_code, to_email, resp.text[:300],
        )
        return False
    except Exception as e:
        logger.warning("send_share_invite_email failed for %s: %s", to_email, e)
        return False