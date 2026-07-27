"""
notifier_telegram.py — Sends ICC A+ setups to your Telegram.

SETUP (free, ~2 minutes):
  1. In Telegram, message @BotFather → /newbot → pick a name → it gives you a
     token like  7123456789:AAH...   Save it.
  2. Message your NEW bot once and send any text (this lets it find your chat).
  3. Get your chat id: message @userinfobot and copy the "Id" number. (Or for a
     group, add the bot to the group and use the group's negative id.)
  4. Export them as env vars:
        export TG_BOT_TOKEN="7123456789:AAH..."
        export TG_CHAT_ID="123456789"
  5. Test:   python3 notifier_telegram.py --test

Then run the scanner with --telegram to get alerted on real setups:
        python3 scanner.py --telegram
"""
from __future__ import annotations
import os, json, urllib.request, urllib.parse, datetime as dt
from icc_engine import Signal


class TelegramNotifier:
    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or os.getenv("TG_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TG_CHAT_ID")
        if not (self.token and self.chat_id):
            raise RuntimeError("Set TG_BOT_TOKEN and TG_CHAT_ID env vars (see file header).")

    def send(self, sig: Signal):
        if sig.action != "SETUP":
            return  # only message on real A+ setups (alert-only, no spam)
        text = (
            f"🟢 <b>ICC A+ SETUP — {sig.symbol}</b>\n"
            f"Dir: <b>{sig.direction.value.upper()}</b>\n"
            f"Entry: <code>{sig.entry}</code>\n"
            f"Stop : <code>{sig.stop}</code>\n"
            f"TP   : <code>{sig.target}</code>  (R:R {sig.rr:.2f})\n"
            f"Time : {sig.when:%Y-%m-%d %H:%M} UTC\n\n"
            f"<i>Alert-only. Verify on your chart, manage risk. Not financial advice.</i>\n"
            f"<i>Checks: {sig.reason}</i>"
        )
        self._post(text)

    def send_text(self, text: str):
        """Send an arbitrary plain message (used for trade lifecycle: partials, closes)."""
        self._post(text)

    def _post(self, text: str):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": self.chat_id, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": "true",
        }).encode()
        try:
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=15) as r:
                ok = json.load(r).get("ok", False)
                if not ok:
                    print("Telegram: sendMessage returned ok=false")
        except Exception as e:
            print(f"Telegram send failed: {e}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="send a test message")
    args = ap.parse_args()
    n = TelegramNotifier()
    if args.test:
        demo = Signal(
            action="SETUP", symbol="BTCUSD", direction=__import__("icc_engine").Direction.BULL,
            reason="test message — ICC pipeline connected",
            entry=64100, stop=63600, target=65200, rr=2.2,
            when=dt.datetime.now().replace(tzinfo=None))
        n.send(demo)
        print("If you received it in Telegram, you're set. If not, check token/chat_id.")
