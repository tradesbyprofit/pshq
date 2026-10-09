"""
notifier_telegram.py — sends ICC gold setups to your Telegram.

Set TG_BOT_TOKEN and TG_CHAT_ID through environment variables / GitHub Secrets.
Start your bot in Telegram before testing it. Never put credentials in Git.

  python3 notifier_telegram.py --check   # validate bot + destination, no message
  python3 notifier_telegram.py --test    # connection message, NOT a trade call

Delivery failures raise: a green workflow must not mean a silently lost alert.
"""
from __future__ import annotations
import argparse
import datetime as dt
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from icc_engine import Signal


ACTIVATION_MESSAGE = (
    "✅ ICC GOLD ALERTS — CONNECTION TEST\n\n"
    "The Telegram connection is working. This is NOT a trade call.\n"
    "The bot checks spot gold (XAUUSD), using 4H markup and 1H entries, "
    "on a 15-minute schedule during its London/New York monitoring window.\n"
    "You will only receive a call when a qualifying setup is found. "
    "Trade entries stay manual; the bot will not place orders.\n"
    "Sizing uses your selected 10% risk setting; check the balance shown "
    "in each call against your own account."
)


class TelegramNotifier:
    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or os.getenv("TG_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TG_CHAT_ID")
        if not (self.token and self.chat_id):
            raise RuntimeError("Set TG_BOT_TOKEN and TG_CHAT_ID in GitHub Secrets or the environment.")

    def send(self, sig: Signal):
        if sig.action != "SETUP":
            return  # quiet on NO_TRADE; never manufacture a call for a test
        text = (
            f"🟢 <b>ICC A+ SETUP — {html.escape(sig.symbol)}</b>\n"
            f"Dir: <b>{html.escape(sig.direction.value.upper())}</b>\n"
            f"Entry: <code>{sig.entry}</code>\n"
            f"Stop : <code>{sig.stop}</code>\n"
            f"TP   : <code>{sig.target}</code>  (R:R {sig.rr:.2f})\n"
            f"Time : {sig.when:%Y-%m-%d %H:%M} UTC\n\n"
            f"<i>Alert-only. Verify on your chart, manage risk. Not financial advice.</i>\n"
            f"<i>Checks: {html.escape(sig.reason)}</i>"
        )
        return self._post(text, parse_mode="HTML")

    def send_text(self, text: str):
        # Journal commands contain <fill>/<size>, and lifecycle notes may contain
        # '&'. Treat plain messages as plain text, not invalid Telegram HTML.
        return self._post(text)

    def _request(self, method: str, payload: dict) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(payload).encode()
        try:
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=15) as response:
                result = json.load(response)
        except urllib.error.HTTPError as e:
            # Do not include request URLs: Telegram embeds the secret in them.
            raise RuntimeError(f"Telegram {method} failed (HTTP {e.code}). Check bot/chat access.") from None
        except Exception:
            raise RuntimeError(f"Telegram {method} failed (network or invalid response).") from None
        if not result.get("ok"):
            raise RuntimeError(f"Telegram {method} rejected the request. Check bot/chat access.")
        return result

    def _post(self, text: str, parse_mode: str = None) -> dict:
        payload = {
            "chat_id": self.chat_id, "text": text,
            "disable_web_page_preview": "true",
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return self._request("sendMessage", payload)

    def check(self) -> None:
        """Validate both credentials and chat access without sending a call."""
        self._request("getMe", {})
        self._request("getChat", {"chat_id": self.chat_id})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check the gold-alert Telegram connection.")
    ap.add_argument("--check", action="store_true", help="check bot and destination without sending")
    ap.add_argument("--test", action="store_true", help="send a clearly labelled connection test, not a trade")
    args = ap.parse_args(argv)
    if not (args.check or args.test):
        ap.print_help()
        return 0
    try:
        n = TelegramNotifier()
        if args.check:
            n.check()
            print("Telegram bot and destination verified.")
        if args.test:
            n.send_text(ACTIVATION_MESSAGE)
            print("Telegram accepted the gold-alert connection test (not a trade call).")
    except RuntimeError as e:
        print(f"Telegram check failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
