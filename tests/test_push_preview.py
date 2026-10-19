import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import monitor as m


NOW = datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc)


class TestPushPreview(unittest.TestCase):
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
