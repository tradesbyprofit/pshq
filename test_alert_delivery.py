"""Offline deployment regressions: no keys, network, or broker orders."""
from __future__ import annotations
import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

import journal
import notifier_telegram as tg
import scanner
from icc_engine import Candle, Direction, Signal


def setup_signal(entry=4000.0, stop=3975.0, target=4050.0):
    return Signal("SETUP", "XAUUSD", Direction.BULL, "test <level> & confirmation",
                  entry=entry, stop=stop, target=target, rr=2.0,
                  when=dt.datetime(2026, 10, 9, 12))


class RecordingNotifier:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    def send_text(self, text):
        if self.fail:
            raise RuntimeError("test delivery failure")
        self.messages.append(text)

    def send(self, signal):
        self.messages.append(signal)


class FakeFeed:
    def candles(self, symbol, timeframe, limit):
        assert symbol == "XAUUSD"
        return [Candle(dt.datetime(2026, 10, 8, 0), 4000, 4001, 3999, 4000)]


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.notifier = tg.TelegramNotifier(token="offline-test-token", chat_id="offline-test-chat")
        self.requests = []

    def response(self, req, timeout):
        self.requests.append(req)
        return io.BytesIO(json.dumps({"ok": True, "result": {}}).encode())

    def test_plain_journal_commands_are_not_parsed_as_html(self):
        with patch.object(tg.urllib.request, "urlopen", side_effect=self.response):
            self.notifier.send_text("fill A0001 --price <fill> --units <size> & note")
        payload = urllib.parse.parse_qs(self.requests[0].data.decode())
        self.assertNotIn("parse_mode", payload)
        self.assertIn("<fill>", payload["text"][0])

    def test_rich_setup_escapes_dynamic_html(self):
        with patch.object(tg.urllib.request, "urlopen", side_effect=self.response):
            self.notifier.send(setup_signal())
        payload = urllib.parse.parse_qs(self.requests[0].data.decode())
        self.assertEqual(payload["parse_mode"], ["HTML"])
        self.assertIn("&lt;level&gt; &amp; confirmation", payload["text"][0])

    def test_no_trade_is_quiet(self):
        with patch.object(tg.urllib.request, "urlopen") as request:
            self.notifier.send(Signal("NO_TRADE", "XAUUSD", Direction.NONE, "wait"))
        request.assert_not_called()

    def test_ok_false_is_a_delivery_failure(self):
        response = io.BytesIO(b'{"ok": false}')
        with patch.object(tg.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(RuntimeError):
                self.notifier.send_text("test")

    def test_http_error_does_not_leak_token_in_url(self):
        url = f"https://api.telegram.org/bot{self.notifier.token}/sendMessage"
        error = urllib.error.HTTPError(url, 403, "Forbidden " + url, {}, None)
        with patch.object(tg.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as result:
                self.notifier.send_text("test")
        self.assertNotIn(self.notifier.token, str(result.exception))
        self.assertIn("HTTP 403", str(result.exception))

    def test_network_error_does_not_leak_token(self):
        error = urllib.error.URLError(self.notifier.token)
        with patch.object(tg.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as result:
                self.notifier.send_text("test")
        self.assertNotIn(self.notifier.token, str(result.exception))

    def test_invalid_response_is_a_failure(self):
        with patch.object(tg.urllib.request, "urlopen", return_value=io.BytesIO(b'not-json')):
            with self.assertRaises(RuntimeError):
                self.notifier.send_text("test")

    def test_check_verifies_bot_and_chat_without_a_message(self):
        with patch.object(tg.urllib.request, "urlopen", side_effect=self.response):
            self.notifier.check()
        self.assertEqual([r.full_url.rsplit("/", 1)[1] for r in self.requests], ["getMe", "getChat"])

    def test_activation_message_is_not_a_fake_trade_or_another_market(self):
        with patch.dict(tg.os.environ, {"TG_BOT_TOKEN": "offline-token", "TG_CHAT_ID": "offline-chat"}):
            with patch.object(tg.TelegramNotifier, "send_text") as send, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(tg.main(["--test"]), 0)
        text = send.call_args.args[0]
        self.assertIn("NOT a trade call", text)
        self.assertIn("XAUUSD", text)
        self.assertNotIn("BTC", text)
        self.assertNotIn("entry 4000", text)

    def test_failed_connection_test_exits_nonzero(self):
        with patch.dict(tg.os.environ, {"TG_BOT_TOKEN": "offline-token", "TG_CHAT_ID": "offline-chat"}):
            with patch.object(tg.TelegramNotifier, "send_text", side_effect=RuntimeError("failed")):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(tg.main(["--test"]), 1)


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "state.json"
        self.journal = root / "journal.jsonl"
        for patcher in [patch.object(scanner, "STATE_FILE", str(self.state)),
                        patch.object(journal, "JOURNAL_FILE", str(self.journal)),
                        patch.object(scanner, "_kalshi_line", return_value="Kalshi: unavailable"),
                        patch.object(scanner.trade_manager, "open_trade")]:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.notifier = RecordingNotifier()

    def scan(self, signal=None, notifier=None):
        with patch.object(scanner, "evaluate", return_value=signal or setup_signal()):
            scanner.scan_once(FakeFeed(), notifier or self.notifier, scanner.Governor())

    def test_same_setup_only_sends_once_across_restarts(self):
        self.scan()
        self.scan()
        self.assertEqual(len(self.notifier.messages), 1)
        self.assertEqual(len(journal.load()), 1)
        self.assertEqual(list(journal.index()), ["A0001"])
        self.assertIn("XAUUSD", scanner.load_state()["sent_alerts"])
        scanner.trade_manager.open_trade.assert_not_called()

    def test_same_levels_on_a_new_candle_are_not_a_new_call(self):
        self.scan()
        signal = setup_signal()
        signal.when += dt.timedelta(hours=1)
        self.scan(signal)
        self.assertEqual(len(self.notifier.messages), 1)

    def test_new_setup_levels_send_a_fresh_call(self):
        self.scan()
        self.scan(setup_signal(entry=4005.0, stop=3980.0, target=4055.0))
        self.assertEqual(len(self.notifier.messages), 2)
        self.assertEqual(list(journal.index()), ["A0001", "A0002"])

    def test_failed_delivery_is_not_deduped_and_retry_keeps_id(self):
        chain = scanner.MultiNotifier([RecordingNotifier(), RecordingNotifier(fail=True)])
        with self.assertRaises(RuntimeError):
            self.scan(notifier=chain)
        self.assertNotIn("XAUUSD", scanner.load_state()["sent_alerts"])
        self.scan()
        self.assertEqual(len(journal.load()), 1)
        self.assertIn("journal id A0001", self.notifier.messages[0])

    def test_feed_error_fails_the_run_instead_of_silent_success(self):
        feed = FakeFeed()
        with patch.object(feed, "candles", side_effect=RuntimeError("gold data unavailable")):
            with self.assertRaisesRegex(RuntimeError, "Live data unavailable for XAUUSD"):
                scanner.scan_once(feed, self.notifier, scanner.Governor())
        self.assertEqual(self.notifier.messages, [])

    def test_session_uses_scan_time_not_old_4h_open_time(self):
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        with patch.object(scanner, "evaluate", return_value=setup_signal()) as evaluate:
            scanner.scan_once(FakeFeed(), self.notifier, scanner.Governor())
        when = evaluate.call_args.kwargs["when"]
        self.assertLess(abs((when - now).total_seconds()), 5)
        self.assertNotEqual(when, FakeFeed().candles("XAUUSD", "4H", 1)[-1].time)


class JournalImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = str(Path(self.tmp.name) / "local.jsonl")
        self.cloud = str(Path(self.tmp.name) / "cloud.jsonl")

    def alert(self, path, signal=None):
        return journal.log_alert(signal or setup_signal(), 10.0, 10000.0, units=40.0,
                                 risk_usd=1000.0, path=path)

    def test_download_import_is_idempotent_and_preserves_fills(self):
        aid = self.alert(self.cloud)
        self.assertEqual(journal.import_alerts(self.cloud, self.local), 1)
        journal.log_fill(aid, 4000, 40, path=self.local)
        journal.log_exit(aid, 4050, reason="tp", path=self.local)
        self.assertEqual(journal.import_alerts(self.cloud, self.local), 0)
        self.assertEqual(journal.closed_trades(path=self.local)[0]["r"], 2.0)

    def test_import_cannot_overwrite_a_different_alert(self):
        self.alert(self.local)
        self.alert(self.cloud, setup_signal(entry=4010.0))
        before = journal.load(self.local)
        with self.assertRaises(ValueError):
            journal.import_alerts(self.cloud, self.local)
        self.assertEqual(journal.load(self.local), before)

    def test_import_does_not_import_cloud_fill_events(self):
        aid = self.alert(self.cloud)
        journal.log_fill(aid, 4000, 40, path=self.cloud)
        journal.import_alerts(self.cloud, self.local)
        self.assertNotIn("fill", journal.index(path=self.local)[aid])

    def test_id_gaps_do_not_reuse_existing_ids(self):
        journal.append({"ev": "alert", "id": "A0009"}, self.local)
        self.assertEqual(journal.next_id(path=self.local), "A0010")


class DeploymentPolicyTests(unittest.TestCase):
    def test_production_only_gold_manual_no_paper_flag(self):
        workflow = Path(__file__).with_name(".github") / "workflows" / "scan.yml"
        text = workflow.read_text()
        self.assertIn("python3 scanner.py --oanda --telegram --market-hours-only", text)
        self.assertNotIn("--paper", text)
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("gold-scan-state", text)
        self.assertNotIn("git push", text)
        self.assertEqual(scanner.WATCH, ["XAUUSD"])
        self.assertEqual(scanner.ALERT_ONLY, {"XAUUSD"})
        self.assertEqual((scanner.HTF, scanner.LTF), ("4H", "1H"))
        self.assertEqual(scanner.RISK_PER_TRADE, 0.10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
