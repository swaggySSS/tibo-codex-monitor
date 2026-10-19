import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import monitor as m


NOW = datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc)


class TestPushPreview(unittest.TestCase):
    def test_diagnostic_labels_real_trigger_and_beijing_time(self):
        body = m.render_diagnostic_message(NOW, "schedule", "12345")
        self.assertIn("schedule（GitHub 自动定时）", body)
        self.assertIn("2026-10-19 12:00:00 北京时间（UTC+8）", body)
        self.assertIn("12345", body)
        self.assertIn("workflow_dispatch（API 或手动触发）", m.render_diagnostic_message(NOW, "workflow_dispatch", "23456"))
        external = m.render_diagnostic_message(NOW, "workflow_dispatch", "34567", "cron-job.org")
        self.assertIn("cron-job.org（调用方声明）", external)
        self.assertIn("2026-10-19 12:00:00 北京时间（UTC+8）", external)
        self.assertIn("34567", external)
        self.assertNotIn("workflow_dispatch（手动触发）", external)

    def test_diagnostic_push_does_not_require_feed_or_state(self):
        with patch("sys.argv", ["monitor.py", "--mode", "diagnostic"]), \
             patch.dict("os.environ", {"GITHUB_EVENT_NAME": "schedule", "GITHUB_RUN_ID": "12345"}), \
             patch.object(m, "load_config", return_value=dict(m.DEFAULTS)), \
             patch.object(m, "PushPlus") as push, \
             patch.object(m, "GitHubStore") as store, \
             patch.object(m, "request_json", side_effect=AssertionError("feed must not be fetched")) as request, \
             patch.object(m, "utcnow", return_value=NOW), \
             patch.object(m, "summary"):
            self.assertEqual(m.main(), 0)
            push.return_value.send.assert_called_once()
            title, body = push.return_value.send.call_args.args
            self.assertIn("5分钟诊断（自动）", title)
            self.assertIn("12345", body)
            store.assert_not_called()
            request.assert_not_called()

    def test_real_renderer_examples_and_actual_generation_time(self):
        body = m.render_test_message(NOW)
        for expected in [
            "全部为虚构示例", "这不是额度重置公告", "重置预告｜待执行",
            "重置时间更新｜仍为预告", "重置确认｜原文称已完成",
            "通知生成时间：2026-10-19 12:00:00 北京时间（UTC+8）",
            "2026-10-20 09:00:00 北京时间（UTC+8）", "6pm PT",
        ]:
            self.assertIn(expected, body)
        self.assertNotIn("/status/", body)

    def test_test_mode_sends_one_message_without_fetching_or_opening_state(self):
        with patch("sys.argv", ["monitor.py", "--mode", "test"]), \
             patch.object(m, "load_config", return_value=dict(m.DEFAULTS)), \
             patch.object(m, "PushPlus") as push, \
             patch.object(m, "GitHubStore") as store, \
             patch.object(m, "request_json") as request, \
             patch.object(m, "utcnow", return_value=NOW), \
             patch.object(m, "summary"):
            self.assertEqual(m.main(), 0)
            push.return_value.send.assert_called_once()
            title, body = push.return_value.send.call_args.args
            self.assertIn("新版模板测试（虚构示例）", title)
            self.assertIn("重置确认｜原文称已完成", body)
            store.assert_not_called()
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
