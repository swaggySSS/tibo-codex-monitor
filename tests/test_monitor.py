import base64
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

import monitor as m

NOW = datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc)
CONFIG = dict(m.DEFAULTS)


def post(pid="100", text="Codex limit reset in the next 2 hours.", minutes=-5, parents=None):
    return m.Post(pid, text, m.iso(NOW + timedelta(minutes=minutes)), "https://x.com/thsottiaux/status/" + pid, parents or [])


def feed(posts, now=NOW):
    return {"profile": {"handle": "thsottiaux"}, "source_scope": "timeline", "stale": False,
            "fetched_at": m.iso(now), "tweets": [{"id": p.id, "text": p.text, "at": p.at, "url": p.url,
            "in_reply_to_tweet_id": p.parents[0] if p.parents else None} for p in posts], "radar_context": []}


class MemoryStore:
    def __init__(self, value=None):
        self.value, self.writes, self.fail = value, 0, False

    def load(self):
        return copy.deepcopy(self.value)

    def save(self, state):
        if self.fail:
            raise m.MonitorError("模拟状态写入失败")
        self.value = copy.deepcopy(state)
        self.writes += 1


class FakePush:
    def __init__(self):
        self.calls, self.fail = [], False

    def send(self, title, content):
        self.calls.append((title, content))
        if self.fail:
            raise m.MonitorError("模拟 push+ 未受理")
        return "receipt1234"


class FeedTests(unittest.TestCase):
    def test_combines_signal_and_context_without_provider_predictions(self):
        data = feed([post()])
        p = post("101", "Done")
        data["radar_context"] = [{"id": p.id, "text": p.text, "at": p.at, "url": p.url}]
        data["events"] = [{"summary": "Provider predicts a reset"}]
        self.assertEqual({p.id for p in m.parse_feed(data, NOW, CONFIG)}, {"100", "101"})

    def test_rejects_wrong_profile(self):
        data = feed([post()]); data["profile"]["handle"] = "someone_else"
        with self.assertRaises(m.MonitorError): m.parse_feed(data, NOW, CONFIG)

    def test_malformed_profile_is_treated_as_source_failure(self):
        for profile in (None, [], {"handle": None}):
            data = feed([post()]); data["profile"] = profile
            with self.assertRaises(m.MonitorError): m.parse_feed(data, NOW, CONFIG)

    def test_rejects_foreign_author_even_if_profile_matches(self):
        data = feed([post()]); data["tweets"][0]["url"] = "https://x.com/other/status/100"
        with self.assertRaises(m.MonitorError): m.parse_feed(data, NOW, CONFIG)

    def test_rejects_url_id_mismatch(self):
        data = feed([post()]); data["tweets"][0]["url"] = "https://x.com/thsottiaux/status/999"
        with self.assertRaises(m.MonitorError): m.parse_feed(data, NOW, CONFIG)

    def test_rejects_stale_and_future_fetch(self):
        for delta in (-60, 20):
            with self.subTest(delta=delta):
                with self.assertRaises(m.MonitorError):
                    m.parse_feed(feed([post()], NOW + timedelta(minutes=delta)), NOW, CONFIG)
        data = feed([post()]); data["stale"] = True
        with self.assertRaises(m.MonitorError): m.parse_feed(data, NOW, CONFIG)

    def test_rejects_future_post(self):
        with self.assertRaises(m.MonitorError): m.parse_feed(feed([post(minutes=20)]), NOW, CONFIG)

    def test_retweets_are_not_new_announcements(self):
        data = feed([post(), post("101", "RT @other: reset")])
        self.assertEqual(len(m.parse_feed(data, NOW, CONFIG)), 1)


class ClassificationTests(unittest.TestCase):
    def signal(self, text, parents=None, extra=None):
        p = post(text=text, parents=parents)
        return m.classify(p, extra or {p.id: p}, CONFIG)

    def test_confirmed_explicit_completed_reset(self):
        signal = self.signal("We have reset Codex usage limits for all paid users.")
        self.assertIn("confirmed", signal["stages"])

    def test_future_and_negation_are_not_completion(self):
        for text in ["We will have reset Codex limits within 2 hours.", "We haven't reset Codex limits yet.", "No reset today."]:
            with self.subTest(text=text):
                self.assertNotIn("confirmed", self.signal(text)["stages"])

    def test_git_and_other_products_are_excluded(self):
        for text in ["How to git reset a Codex repository.", "Reset your password.", "The Claude reset is done.", "Reset API limits."]:
            with self.subTest(text=text): self.assertIsNone(self.signal(text))

    def test_timing_reply_uses_parent(self):
        parent = post("99", "Codex usage reset soon.", -60)
        signal = self.signal("Landing within the next 2 hours", ["99"], {"99": parent})
        self.assertIn("timing", signal["stages"])
        self.assertNotIn("confirmed", signal["stages"])

    def test_done_with_reset_parent_is_confirmation(self):
        parent = post("99", "Codex limit reset soon.", -60)
        self.assertIn("confirmed", self.signal("Done", ["99"], {"99": parent})["stages"])

    def test_done_with_unrelated_parent_is_not_confirmation(self):
        unrelated = post("99", "Message editing feature ships today.", -60)
        reset = post("98", "Codex reset soon.", -120)
        self.assertIsNone(self.signal("Done", ["99"], {"99": unrelated, "98": reset}))

    def test_unlinked_done_is_only_uncertain(self):
        parent = post("99", "Codex reset soon.", -60)
        self.assertEqual(self.signal("Done", extra={"99": parent})["stages"], ["uncertain"])

    def test_unlinked_landed_across_accounts_is_only_uncertain(self):
        parent = post("99", "Codex reset soon.", -60)
        self.assertEqual(self.signal("Confirmed landed across all accounts.", extra={"99": parent})["stages"], ["uncertain"])

    def test_banked_reset_and_manual_usage(self):
        signal = self.signal("A banked reset for Codex is available; apply it on demand.")
        self.assertIn("banked", signal["stages"])

    def test_eod_does_not_invent_precise_deadline(self):
        desc = m.timing_description(post(text="Codex reset by EOD PST."))
        self.assertIn("不推算精确时刻", desc)
        self.assertNotIn("23:59", desc)

    def test_relative_time_converts_to_beijing(self):
        p = post(text="Codex reset within the next 2 hours", minutes=0)
        self.assertIn("2026-10-19 14:00:00 北京时间", m.timing_description(p))

    def test_next_hour_without_number(self):
        self.assertIn("2026-10-19 13:00:00 北京时间", m.timing_description(post(text="Codex reset in the next hour", minutes=0)))

    def test_explicit_pst_with_date_and_without_date(self):
        self.assertIn("2026-10-19 10:00:00 北京时间", m.timing_description(post(text="Codex reset today at 6pm PST", minutes=0)))
        self.assertIn("2026-10-20 10:00:00 北京时间", m.timing_description(post(text="Codex reset tomorrow at 6pm PST", minutes=0)))
        self.assertIn("未明确日期", m.timing_description(post(text="Codex reset at 6pm PST", minutes=0)))

    def test_same_post_can_confirm_and_forecast_another_reset(self):
        stages = self.signal("We have reset Codex limits. Another reset will land tomorrow.")["stages"]
        self.assertIn("confirmed", stages)
        self.assertIn("announcement", stages)

    def test_notification_escapes_html_and_includes_source(self):
        p = post(text="Codex reset <script>alert(1)</script>")
        content = m.render_message([{"type": "post", "post": m.asdict(p), "signal": self.signal(p.text)}])
        self.assertNotIn("<script>", content)
        self.assertIn("未独立直连 X 核验", content)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.store, self.push = MemoryStore(), FakePush()
        self.old = post("99", "Codex reset soon.", -60)

    def run_once(self, posts, now=NOW):
        return m.run_check(self.store, lambda: feed(posts, now), self.push, CONFIG, now)

    def initialize(self):
        self.run_once([self.old])

    def test_first_run_is_baseline_no_history_notifications(self):
        result = self.run_once([self.old])
        self.assertTrue(result["baseline_created"])
        self.assertEqual(self.push.calls, [])

    def test_new_post_sent_once_and_quiet_run_no_extra_commit(self):
        self.initialize()
        p = post("101", "Codex reset within 2 hours", 1)
        now = NOW + timedelta(minutes=15)
        self.run_once([self.old, p], now)
        writes = self.store.writes
        self.run_once([self.old, p], now + timedelta(minutes=15))
        self.assertEqual(len(self.push.calls), 1)
        self.assertEqual(self.store.writes, writes)

    def test_delayed_indexing_does_not_lose_post(self):
        self.initialize()
        self.run_once([self.old], NOW + timedelta(minutes=15))
        self.run_once([self.old, post("101", "Codex reset soon", 2)], NOW + timedelta(minutes=30))
        self.assertEqual(len(self.push.calls), 1)

    def test_edit_of_observed_old_post_can_notify(self):
        self.initialize()
        edited = post("99", "We have reset Codex usage limits.", -60)
        self.run_once([edited], NOW + timedelta(minutes=15))
        self.assertEqual(len(self.push.calls), 1)

    def test_reply_reclassified_when_parent_arrives_later(self):
        self.initialize()
        done = post("102", "Done", 2, ["101"])
        self.run_once([self.old, done], NOW + timedelta(minutes=15))
        self.assertEqual(len(self.push.calls), 0)
        parent = post("101", "Codex reset within 2 hours", 1)
        self.run_once([self.old, parent, done], NOW + timedelta(minutes=30))
        self.assertEqual(len(self.push.calls), 1)
        self.assertIn("重置确认", self.push.calls[0][1])

    def test_push_failure_keeps_queue_until_retry(self):
        self.initialize(); self.push.fail = True
        p = post("101", "Codex reset soon", 1)
        with self.assertRaises(m.MonitorError): self.run_once([self.old, p], NOW + timedelta(minutes=15))
        self.assertEqual(len(self.store.value["outbox"]), 1)
        self.assertEqual(self.store.value["accepted"], {})
        self.push.fail = False
        self.run_once([self.old, p], NOW + timedelta(minutes=30))
        self.assertEqual(self.store.value["outbox"], {})
        self.assertEqual(len(self.store.value["accepted"]), 1)

    def test_state_failure_prevents_notification_submission(self):
        self.initialize(); self.store.fail = True
        with self.assertRaises(m.MonitorError):
            self.run_once([self.old, post("101", minutes=1)], NOW + timedelta(minutes=15))
        self.assertEqual(len(self.push.calls), 0)

    def test_corrupt_state_does_not_silently_reset(self):
        self.store.value = {"version": 9}
        with self.assertRaises(m.MonitorError): self.run_once([self.old])
        self.assertEqual(self.store.writes, 0)

    def test_source_outage_alert_once_then_recovery_once(self):
        self.initialize()
        def unavailable(): raise m.MonitorError("模拟数据源失效")
        for index in range(1, 6):
            m.run_check(self.store, unavailable, self.push, CONFIG, NOW + timedelta(minutes=15 * index))
        self.assertEqual(len(self.push.calls), 1)
        self.assertIn("监控数据源受阻", self.push.calls[0][1])
        self.run_once([self.old], NOW + timedelta(minutes=90))
        self.run_once([self.old], NOW + timedelta(minutes=105))
        self.assertEqual(len(self.push.calls), 2)
        self.assertIn("监控数据源恢复", self.push.calls[1][1])

    def test_transient_failure_is_quiet(self):
        self.initialize()
        def unavailable(): raise m.MonitorError("模拟临时失败")
        m.run_check(self.store, unavailable, self.push, CONFIG, NOW + timedelta(minutes=15))
        self.run_once([self.old], NOW + timedelta(minutes=30))
        self.assertEqual(self.push.calls, [])

    def test_recovery_not_sent_when_source_fails_again(self):
        self.initialize()
        def unavailable(): raise m.MonitorError("模拟数据源失效")
        for index in range(1, 4):
            m.run_check(self.store, unavailable, self.push, CONFIG, NOW + timedelta(minutes=15 * index))
        self.push.fail = True
        with self.assertRaises(m.MonitorError): self.run_once([self.old], NOW + timedelta(minutes=60))
        self.push.fail = False
        calls = len(self.push.calls)
        m.run_check(self.store, unavailable, self.push, CONFIG, NOW + timedelta(minutes=75))
        self.assertEqual(len(self.push.calls), calls)

    def test_elapsed_estimate_never_creates_completion(self):
        self.initialize()
        p = post("101", "Codex reset within 2 hours", 1)
        self.run_once([self.old, p], NOW + timedelta(minutes=15))
        self.run_once([self.old, p], NOW + timedelta(hours=5))
        self.assertEqual(len(self.push.calls), 1)
        self.assertNotIn("重置确认", self.push.calls[0][1])

    def test_large_backlog_is_batched_without_losing_remaining_posts(self):
        self.initialize()
        posts = [post(str(200 + i), "Codex reset soon, update " + str(i), i + 1) for i in range(20)]
        self.run_once([self.old] + posts, NOW + timedelta(minutes=45))
        self.assertEqual(len(self.store.value["outbox"]), 10)
        self.run_once([self.old] + posts, NOW + timedelta(minutes=60))
        self.assertEqual(len(self.store.value["outbox"]), 0)
        self.assertEqual(len(self.store.value["accepted"]), 20)
        self.assertEqual(len(self.push.calls), 2)


class AdapterTests(unittest.TestCase):
    def test_push_accepted_requires_business_success_and_receipt(self):
        for data in [{"code": 905}, {"code": 200}, {"code": 200, "data": ""}]:
            with self.subTest(data=data):
                with self.assertRaises(m.MonitorError): m.PushPlus("private-token", lambda *a, **kw: data).send("test", "test")
        self.assertEqual(m.PushPlus("private-token", lambda *a, **kw: {"code": 200, "data": "receipt1234"}).send("a", "b"), "receipt1234")

    def test_push_error_never_echoes_token_or_server_body(self):
        client = m.PushPlus("private-token", lambda *a, **kw: {"code": 903, "msg": "private-token"})
        with self.assertRaises(m.MonitorError) as exc: client.send("test", "test")
        self.assertNotIn("private-token", str(exc.exception))

    def test_github_denied_is_not_missing_state(self):
        def denied(*a, **kw): raise m.HttpError(403, "api.github.com")
        store = m.GitHubStore("owner/repo", "secret", "monitor-state", "a" * 40, denied)
        with self.assertRaises(m.HttpError): store.load()

    def test_github_uses_returned_sha_for_checkpoint(self):
        requests = []
        state = m.new_state(NOW)
        def api(url, method="GET", body=None, headers=None):
            requests.append((url, method, body))
            if "/contents/" in url and method == "GET":
                return {"sha": "old-sha", "content": base64.b64encode(json.dumps(state).encode()).decode()}
            if method == "PUT": return {"content": {"sha": "new-sha"}}
            return {"ref": "refs/heads/monitor-state"}
        store = m.GitHubStore("owner/repo", "secret", "monitor-state", "a" * 40, api)
        self.assertEqual(store.load(), state)
        store.save(state)
        put = next(body for _, method, body in requests if method == "PUT")
        self.assertEqual(put["sha"], "old-sha")
        self.assertEqual(store.sha, "new-sha")


if __name__ == "__main__":
    unittest.main()
