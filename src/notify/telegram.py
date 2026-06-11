"""Send-only Telegram client (Bot API over HTTPS).

No long-polling, no webhook handling here — inbound commands go through the
Cloudflare Worker (Phase 6). Restricted to TELEGRAM_CHAT_ID.
"""

import logging

import requests

from config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
MAX_LEN = 4096  # Telegram hard limit per message


def send_message(text: str, disable_preview: bool = True) -> bool:
    """Send a message to the owner's chat; split if over the length limit.

    Args:
        text: Message body (plain text; Telegram HTML disabled to avoid
            escaping pitfalls with tickers like <AAPL>).
        disable_preview: Suppress link previews (keeps scan messages compact).

    Returns:
        True if every chunk was accepted; False on any failure (logged, never
        raises — alerts must not crash the pipeline).
    """
    token, chat_id = settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.error("telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — message dropped")
        return False
    ok = True
    chunks = [text[i : i + MAX_LEN] for i in range(0, len(text), MAX_LEN)] or [""]
    for chunk in chunks:
        try:
            resp = requests.post(
                f"{API_BASE}/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": disable_preview,
                },
                timeout=15,
            )
            if not (resp.ok and resp.json().get("ok")):
                logger.error("telegram: send failed: %s", resp.text[:300])
                ok = False
        except requests.RequestException:
            logger.exception("telegram: send raised")
            ok = False
    return ok
