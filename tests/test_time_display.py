import unittest
from datetime import datetime, timezone

import monitor as m
import time_display as td

AT = "2026-10-19T16:00:00Z"
NOW = datetime(2026, 10, 19, 17, 0, tzinfo=timezone.utc)


class ConversionTests(unittest.TestCase):
    def result(self, text, at=AT):
        return td.describe_times(text, at)

    def test_every_displayed_timestamp_has_explicit_beijing_offset(self):
        self.assertEqual(td.format_beijing(AT), "2026-10-20 00:00:00 北京时间（UTC+8）")

    def test_today_uses_us_date_instead_of_beijing_date(self):
        value = self.result("Codex reset today at 6pm PT", "2026-10-19T00:00:00Z")
        self.assertIn("2026-10-19 09:00:00 北京时间（UTC+8）", value)
        self.assertNotIn("2026-10-20 09:00:00", value)

    def test_pdt_and_pst_preserve_explicit_offsets(self):
        self.assertIn("2026-10-20 09:00:00", self.result("Codex reset today at 6pm PDT"))
        self.assertIn("2026-10-20 10:00:00", self.result("Codex reset today at 6pm PST"))

    def test_pt_automatically_selects_summer_and_winter_offsets(self):
        self.assertIn("2026-07-11 09:00:00", self.result("Codex reset today at 6pm PT", "2026-07-10T16:00:00Z"))
        self.assertIn("2026-01-11 10:00:00", self.result("Codex reset today at 6pm PT", "2026-01-10T16:00:00Z"))

    def test_et_automatically_selects_summer_and_winter_offsets(self):
        self.assertIn("2026-07-11 06:00:00", self.result("Codex reset today at 6pm ET", "2026-07-10T16:00:00Z"))
        self.assertIn("2026-01-11 07:00:00", self.result("Codex reset today at 6pm ET", "2026-01-10T16:00:00Z"))

    def test_spring_dst_gap_is_not_fabricated(self):
        value = self.result("Codex reset on 2026-03-08 at 2:30am PT", "2026-03-08T12:00:00Z")
        self.assertIn("跳时缺口", value)
        self.assertIn("无法唯一确定", value)

    def test_fall_dst_fold_lists_both_possibilities(self):
        value = self.result("Codex reset on 2026-11-01 at 1:30am PT", "2026-11-01T12:00:00Z")
        self.assertIn("2026-11-01 16:30:00 北京时间（UTC+8）", value)
        self.assertIn("2026-11-01 17:30:00 北京时间（UTC+8）", value)
        self.assertIn("不能唯一确定", value)

    def test_explicit_pst_resolves_fold_without_guessing(self):
        value = self.result("Codex reset on 2026-11-01 at 1:30am PST", "2026-11-01T12:00:00Z")
        self.assertIn("2026-11-01 17:30:00", value)
        self.assertNotIn(" 或 ", value)

    def test_unknown_date_never_assumes_today(self):
        self.assertIn("原文未明确日期", self.result("Codex reset at 6pm PT"))

    def test_unknown_zone_never_assumes_america(self):
        self.assertIn("原文未说明时区", self.result("Codex reset today at 6pm"))

    def test_cst_is_ambiguous_without_us_context(self):
        self.assertIn("CST 可能指不同时区", self.result("Codex reset for us today at 6pm CST"))
        self.assertIn("2026-10-20 08:00:00", self.result("US Central: Codex reset today at 6pm CST"))

    def test_eod_never_becomes_invented_2359_deadline(self):
        value = self.result("Codex reset by EOD PST")
        self.assertIn("北京时间（UTC+8）", value)
        self.assertIn("不推算精确时刻", value)
        self.assertNotIn("23:59", value)

    def test_multiple_clocks_keep_their_own_date_anchors(self):
        value = self.result("Today at 6pm PDT; tomorrow at 9am EDT")
        self.assertIn("2026-10-20 09:00:00", value)
        self.assertIn("2026-10-20 21:00:00", value)
        self.assertEqual(len(td.converted_times("Today at 6pm PDT; tomorrow at 9am EDT", AT)), 2)

    def test_date_after_clock_is_supported(self):
        self.assertIn("2026-10-20 09:00:00", self.result("Codex reset at 6pm PT on 2026-10-19"))

    def test_named_date_and_24_hour_clock(self):
        self.assertIn("2026-10-20 09:00:00", self.result("Codex reset on October 19, 2026 at 18:00 PT"))

    def test_year_missing_is_not_invented(self):
        self.assertIn("未给年份", self.result("Codex reset on October 19 at 6pm PT"))

    def test_invalid_calendar_date_is_not_silently_corrected(self):
        self.assertIn("原文日期无效", self.result("Codex reset on 2026-02-30 at 6pm PST"))

    def test_long_zone_name_and_dotted_ampm(self):
        self.assertIn("2026-10-20 09:00:00", self.result("Today at 6 p.m. Pacific Time"))

    def test_relative_window_has_full_dates_on_both_ends(self):
        value = self.result("Codex reset within the next 2 hours")
        self.assertIn("2026-10-20 00:00:00 北京时间（UTC+8）", value)
        self.assertIn("2026-10-20 02:00:00 北京时间（UTC+8）", value)

    def test_relative_point_is_not_rendered_as_interval(self):
        value = self.result("Codex reset in 2 hours")
        self.assertIn("2026-10-20 02:00:00", value)
        self.assertNotIn(" 至 ", value)

    def test_relative_tomorrow_uses_original_zone_date(self):
        self.assertIn("2026-10-21 09:00:00", self.result("Codex reset tomorrow at 6pm PT"))


class TemplateTests(unittest.TestCase):
    def item(self, text, stages):
        post = m.Post("100", text, AT, "https://x.com/thsottiaux/status/100", [])
        return {"type": "post", "post": m.asdict(post), "signal": {"stages": stages, "summary": "示例摘要", "timing": "OLD_UNCONVERTED_TIMING"}}

    def test_quote_is_preserved_and_conversion_appended(self):
        item = self.item("Codex reset today at 6pm PDT", ["timing"])
        body = m.render_message([item], now=NOW)
        self.assertIn("Codex reset today at 6pm PDT", body)
        self.assertIn("2026-10-20 09:00:00 北京时间（UTC+8）", body)
        self.assertIn("通知生成时间：2026-10-20 01:00:00 北京时间（UTC+8）", body)
        self.assertNotIn("OLD_UNCONVERTED_TIMING", body)

    def test_completion_post_time_is_not_claimed_as_account_arrival(self):
        body = m.render_message([self.item("We have reset Codex usage limits", ["confirmed"])], now=NOW)
        self.assertIn("原文称已完成", body)
        self.assertIn("不能当成每个账户的实际恢复时刻", body)

    def test_delay_cancel_and_correction_headings(self):
        for text, expected in [("Codex reset delayed", "重置延期"), ("Codex reset cancelled", "重置取消"), ("Correction: Codex reset scope", "重置更正")]:
            with self.subTest(text=text): self.assertIn(expected, m.notification_title([self.item(text, ["update"])]))

    def test_running_reset_is_distinct_from_completed_reset(self):
        post = m.Post("100", "We are resetting Codex usage limits now.", AT, "https://x.com/thsottiaux/status/100", [])
        signal = m.classify(post, {post.id: post}, m.DEFAULTS)
        self.assertIn("progress", signal["stages"])
        self.assertNotIn("confirmed", signal["stages"])

    def test_future_progress_wording_is_not_current_progress(self):
        post = m.Post("100", "We will have a Codex reset in progress tomorrow.", AT, "https://x.com/thsottiaux/status/100", [])
        signal = m.classify(post, {post.id: post}, m.DEFAULTS)
        self.assertNotIn("progress", signal["stages"])

    def test_health_template_has_beijing_generation_time(self):
        body = m.render_message([{"type": "health", "title": "监控数据源受阻", "text": "已连续三轮读取失败"}], now=NOW)
        self.assertIn("2026-10-20 01:00:00 北京时间（UTC+8）", body)


if __name__ == "__main__":
    unittest.main()
