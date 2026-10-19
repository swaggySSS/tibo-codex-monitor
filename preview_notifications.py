"""Generate synthetic examples with the same renderer used by real push messages.

No network, no secrets, no state writes, and no actual push messages.
"""
import html
from datetime import datetime, timezone
from pathlib import Path

import monitor as m

AT = "2026-10-19T16:00:00Z"
GENERATED = datetime(2026, 10, 19, 17, 0, tzinfo=timezone.utc)


def samples():
    texts = [
        ("重置意向", "I am considering another Codex usage reset."),
        ("预告重置", "We will reset Codex usage limits for all paid users."),
        ("明确重置时间", "Codex usage reset today at 6pm PT."),
        ("正在执行", "We are now resetting Codex usage limits."),
        ("确认完成", "We have reset Codex usage limits for all paid users."),
        ("延期", "The Codex usage reset is delayed until tomorrow at 9am ET."),
        ("取消", "The Codex usage reset is cancelled."),
        ("更正适用范围", "Correction: the Codex reset applies only to Pro users."),
        ("储存重置额度", "A banked reset is available for all paid Codex users. You can apply it on demand."),
        ("疑似确认，待核实", "Done"),
        ("时间无法精确换算", "Codex reset by EOD PST."),
    ]
    prior = m.Post("900000", "Codex usage reset soon.", "2026-10-19T15:00:00Z", "https://x.com/thsottiaux", [])
    result = []
    for index, (name, text) in enumerate(texts):
        post = m.Post(str(900001 + index), text, AT, "https://x.com/thsottiaux", [])
        signal = m.classify(post, {post.id: post, prior.id: prior}, m.DEFAULTS)
        if signal is None:
            raise ValueError("Synthetic example did not classify: " + name)
        result.append((name, {"type": "post", "post": m.asdict(post), "signal": signal}))
    result.extend([
        ("监控异常", {"type": "health", "title": "Tibo 监控数据源受阻", "text": "已连续 3 轮无法获得可信公开数据，后续继续重试。这不代表没有新消息。"}),
        ("监控恢复", {"type": "health", "title": "Tibo 监控数据源恢复", "text": "公开数据源已恢复有效读取，后续继续监控。数据覆盖仍受第三方收录范围限制。"}),
    ])
    return result


def build_html():
    sections = []
    for index, (name, item) in enumerate(samples(), 1):
        title = m.notification_title([item])
        sections.append('<section id="sample-%s"><p class="badge">虚构示例 %s · %s</p><h2>%s</h2><article>%s</article></section>' % (
            index, index, html.escape(name), html.escape(title), m.render_message([item], now=GENERATED)))
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tibo 微信通知模板 · 虚构示例</title><style>body{font:16px/1.75 system-ui,sans-serif;color:#17232a;background:#f3f5f5;max-width:820px;margin:40px auto;padding:0 20px}h1{font-size:28px}h2{font-size:20px}h3{font-size:18px}h4{font-size:15px;margin-bottom:8px}section{margin:32px 0}.badge{color:#5b6370;font-size:13px}article{background:white;border:1px solid #d8dfe2;border-radius:14px;padding:24px}blockquote{margin:12px 0;padding:12px 16px;background:#f6f8f8;border-left:3px solid #9baeb4}hr{border:0;border-top:1px solid #e0e6e8;margin:20px 0}small{color:#60727a}a{color:#087f5b}code{background:#edf2f3;padding:2px 5px;border-radius:3px}.notice{background:#fff3d1;border:1px solid #e9cf7c;padding:18px;border-radius:10px}</style><h1>Tibo 微信通知模板</h1><div class="notice"><strong>以下全部是虚构测试示例，不是真实重置公告。</strong><br>正文由实际发送函数生成；微信/公众号卡片的最终排版由 push+ 和微信决定。示例链接仅指向账号主页。示例中展示的时间均明确标注北京时间（UTC+8），英文引文保留原时区并另附换算结果。</div>' + ''.join(sections) + '</html>'


if __name__ == "__main__":
    path = Path(__file__).resolve().with_name("notification_samples.html")
    path.write_text(build_html(), encoding="utf-8")
    print("Generated synthetic examples without sending notifications: " + str(path))
