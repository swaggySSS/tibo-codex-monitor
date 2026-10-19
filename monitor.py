#!/usr/bin/env python3
"""Tibo public-post monitor. Python standard library only; no paid APIs."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
BEIJING = timezone(timedelta(hours=8))
FEED_URL = "https://codex-reset.com/api/feed"
PUSH_URL = "https://www.pushplus.plus/send"
DEFAULTS = {
    "feed_url": FEED_URL,
    "max_feed_age_minutes": 45,
    "lookback_hours": 72,
    "include_teasers": True,
    "include_ambiguous_confirmations": True,
    "failure_alert_after": 3,
    "max_posts_per_message": 10,
    "state_branch": "monitor-state",
}


class MonitorError(Exception):
    """Safe-to-display error: never include credentials or raw HTTP responses."""


class HttpError(MonitorError):
    def __init__(self, status, host):
        self.status = status
        super().__init__("%s 返回 HTTP %s" % (host, status))


def utcnow():
    return datetime.now(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str):
        raise MonitorError("数据源缺少有效的发布时间")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MonitorError("数据源时间格式发生变化") from None
    if result.tzinfo is None:
        raise MonitorError("数据源时间缺少时区")
    return result.astimezone(UTC)


def beijing(value):
    return parse_time(value).astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S 北京时间")


def normalize_text(text):
    text = html.unescape(text).replace("’", "'").replace("‘", "'").lower()
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"[^\w\s]", " ", text).strip()


def digest(text):
    return hashlib.sha256(re.sub(r"\s+", " ", text).encode("utf-8")).hexdigest()[:24]


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        original = urllib.parse.urlparse(req.full_url)
        target = urllib.parse.urlparse(newurl)
        if target.scheme != "https" or target.netloc != original.netloc:
            raise MonitorError("接口发生跨域或非 HTTPS 跳转，请人工检查配置")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request_json(url, method="GET", body=None, headers=None):
    host = urllib.parse.urlparse(url).netloc
    if urllib.parse.urlparse(url).scheme != "https":
        raise MonitorError("接口必须使用 HTTPS")
    request_headers = {"User-Agent": "TiboCodexMonitor/1.0", "Accept": "application/json"}
    request_headers.update(headers or {})
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    attempts = 3 if method == "GET" else 1
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, data=payload, method=method, headers=request_headers)
            with urllib.request.build_opener(SafeRedirect()).open(request, timeout=25) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise MonitorError("%s 响应超过大小限制" % host)
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                time.sleep(2 ** attempt)
                continue
            raise HttpError(exc.code, host) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
                continue
            raise MonitorError("%s 连接失败或超时；未输出请求内容" % host) from None
        except (ValueError, UnicodeError):
            raise MonitorError("%s 未返回有效 JSON" % host) from None


@dataclass
class Post:
    id: str
    text: str
    at: str
    url: str
    parents: list


def parse_feed(data, now, config):
    profile = data.get("profile") if isinstance(data, dict) else None
    handle = profile.get("handle") if isinstance(profile, dict) else None
    if not isinstance(handle, str) or handle.lower() != "thsottiaux":
        raise MonitorError("数据源账号身份不符合 @thsottiaux")
    if data.get("source_scope") != "timeline" or data.get("stale") is not False:
        raise MonitorError("数据源报告过期或不再提供 timeline")
    fetched = parse_time(data.get("fetched_at"))
    if not -300 <= (now - fetched).total_seconds() <= config["max_feed_age_minutes"] * 60:
        raise MonitorError("数据源更新时间过旧或异常")
    if not isinstance(data.get("tweets"), list) or not isinstance(data.get("radar_context", []), list):
        raise MonitorError("数据源帖子结构发生变化")
    posts = {}
    # radar_context can contain short confirmations absent from the signal list.
    # Never ingest events, observations, forecasts, or the provider's classifications.
    for item in data.get("radar_context", []) + data["tweets"]:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id", ""))
        if not re.fullmatch(r"\d+", pid) or item.get("url") != "https://x.com/thsottiaux/status/" + pid:
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 30000:
            continue
        if item.get("is_retweet") or re.match(r"^RT\s+@", text):
            continue
        at = parse_time(item.get("at"))
        if at > now + timedelta(minutes=5):
            raise MonitorError("数据源帖子发布时间在未来")
        parents = []
        for name in ("in_reply_to_tweet_id", "quoted_tweet_id", "quoted_status_id"):
            value = str(item.get(name) or "")
            if re.fullmatch(r"\d+", value):
                parents.append(value)
        for ref in item.get("referenced_tweets", []) or []:
            if isinstance(ref, dict) and ref.get("type") in ("replied_to", "quoted"):
                value = str(ref.get("id", ""))
                if re.fullmatch(r"\d+", value):
                    parents.append(value)
        posts[pid] = Post(pid, html.unescape(text.strip()), iso(at), item["url"], sorted(set(parents)))
    # A healthy empty payload is suspicious: do not silently reset a baseline.
    if not posts:
        raise MonitorError("数据源没有可验证的 Tibo 帖子")
    return sorted(posts.values(), key=lambda post: (post.at, int(post.id)))


RESET = re.compile(r"\breset(?:s|ting)?\b|\b(?:refill|replenish|restore)(?:ed|ing)?\b.{0,35}\b(?:quota|usage|limits?|allowance)\b", re.I)
IRRELEVANT = re.compile(r"\bgit\s+reset\b|\bfactory\s+reset\b|reset\s+(?:(?:my|your|the|an?)\s+)?(?:password|settings?|app|computer|repo|branch)\b", re.I)
COMPLETE = re.compile(r"\b(?:i've|i have|we've|we have|have)\s+(?:just\s+)?reset\b|\b(?:usage|limits?|quota)[\w\s]{0,30}\b(?:have been|has been|were|are|is)\s+reset\b|\b(?:it's done|it is done|all propagated|confirmed landed|done and dusted|reset (?:is )?(?:done|complete|completed))\b", re.I)
SHORT_COMPLETE = re.compile(r"^(?:done(?: and dusted)?|it'?s done|all (?:done|propagated)|(?:confirmed )?landed|completed)(?:\s+(?:across|for|to)\s+all\s+(?:accounts|users))?[.!\s]*$", re.I)
FUTURE = re.compile(r"\b(?:will|going to|soon|next|later|tomorrow|today|by eod|within|in \d+|landing|should|hope|planning|feeling)\b", re.I)
CORRECTION = re.compile(r"\b(?:delay(?:ed)?|postpone(?:d)?|cancel(?:led|ed)?|correction|not yet|not done|haven't|hasn't|not resetting|won't reset|will not reset|not reset|no reset)\b", re.I)
RELATIVE = re.compile(r"\b(?:(?:within|in|over)\s+(?:the\s+)?(?:next\s+)?(?:about\s+)?|next\s+)(?:(\d+|an?|one|two|three|half)\s*)?(minutes?|mins?|hours?|hrs?)\b", re.I)
TIMING = re.compile(RELATIVE.pattern + r"|\b(?:eod|tomorrow|tonight|today)\b|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*(?:pst|pdt|pt|utc|gmt)\b", re.I)


def reset_topic(text):
    if not RESET.search(text):
        return False
    quota = re.search(r"\b(?:codex|chatgpt|usage|quota|allowance|banked)\b", text, re.I)
    if IRRELEVANT.search(text) and not re.search(r"\b(?:usage|quota|allowance|banked)\b", text, re.I):
        return False
    if not quota and re.search(r"\b(?:claude|gemini|grok|password|api)\b", text, re.I):
        return False
    return True


def timing_description(post):
    text = post.text.replace("’", "'")
    match = RELATIVE.search(text)
    if match:
        amount, unit = match.group(1) or "one", match.group(2)
        numbers = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "half": 0.5}
        amount = numbers.get(amount.lower(), float(amount) if amount.isdigit() else 1)
        seconds = amount * (3600 if unit.lower().startswith(("hour", "hr")) else 60)
        end = parse_time(post.at) + timedelta(seconds=seconds)
        return "按发帖时间换算：%s 至 %s（原文：%s；仍为预计）" % (beijing(post.at), beijing(iso(end)), match.group(0))
    exact = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*(PST|PDT|UTC|GMT)\b", text, re.I)
    if exact:
        hour, minute = int(exact.group(1)), int(exact.group(2) or 0)
        if 1 <= hour <= 12 and 0 <= minute <= 59:
            offset = {"PST": -8, "PDT": -7, "UTC": 0, "GMT": 0}[exact.group(4).upper()]
            zone = timezone(timedelta(hours=offset))
            local = parse_time(post.at).astimezone(zone)
            hour = hour % 12 + (12 if exact.group(3).lower() == "pm" else 0)
            target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if re.search(r"\btomorrow\b", text, re.I):
                target += timedelta(days=1)
            elif not re.search(r"\btoday\b", text, re.I):
                return "原文 %s；未明确日期，未擅自换算日期" % exact.group(0)
            return "%s（按原文 %s 换算，仍为预计）" % (beijing(iso(target)), exact.group(0))
    if TIMING.search(text):
        return "原文含时间窗口；EOD、today、PT 等若缺少明确边界，仅保留原文，不推算精确时刻。"
    return "原文未提供可确定的执行时间。"


def classify(post, context, config):
    text = post.text.replace("’", "'").replace("‘", "'")
    ancestors = []
    parents = list(post.parents)
    visited = set()
    while parents and len(visited) < 12:
        pid = parents.pop(0)
        if pid in visited:
            continue
        visited.add(pid)
        parent = context.get(pid)
        if parent:
            ancestors.append(parent)
            parents.extend(parent.parents)
    direct_topic = reset_topic(text)
    related = direct_topic or any(reset_topic(parent.text) for parent in ancestors)
    stripped = re.sub(r"https?://\S+|@\w+", "", text).strip()
    if not related:
        if SHORT_COMPLETE.fullmatch(stripped) and not post.parents and config["include_ambiguous_confirmations"]:
            recent = any(reset_topic(p.text) and timedelta(0) <= parse_time(post.at) - parse_time(p.at) <= timedelta(hours=24) for p in context.values() if p.id != post.id)
            if recent:
                return {"stages": ["uncertain"], "summary": "Tibo 发布简短完成用语，附近有重置预告，但缺少直接上下文关联，暂不能确认是额度重置。", "timing": "原文未明确；请核对原帖上下文。"}
        return None
    if not direct_topic and not (SHORT_COMPLETE.fullmatch(stripped) or TIMING.search(text) or CORRECTION.search(text)):
        return None
    stages = []
    if CORRECTION.search(text):
        stages.append("update")
    # Evaluate clauses separately: one post may confirm one reset and announce another.
    clauses = re.split(r"[\n.!?;]+|\bbut\b|\band another\b", text, flags=re.I)
    completed = any(COMPLETE.search(clause) and not re.search(r"\b(?:will|would|should|might|could|may|hope|not|haven't|hasn't|won't)\b", clause, re.I) for clause in clauses)
    if SHORT_COMPLETE.fullmatch(stripped) and ancestors and not CORRECTION.search(text):
        completed = True
    if completed:
        stages.append("confirmed")
    if TIMING.search(text) and (not completed or FUTURE.search(text)):
        stages.append("timing")
    if re.search(r"\bbanked\b", text, re.I):
        stages.append("banked")
    if not stages:
        stages.append("announcement" if FUTURE.search(text) or re.search(r"\bday\s+\d+", text, re.I) else "teaser")
    elif completed and any(FUTURE.search(clause) and RESET.search(clause) for clause in clauses):
        stages.append("announcement")
    if stages == ["teaser"] and not config["include_teasers"]:
        return None
    labels = {"update": "重置相关的延期、取消或更正信息，以原文为准。", "confirmed": "公开收录的 Tibo 原文包含重置完成表述。", "timing": "Tibo 提供了预计执行时间，时间过去并不自动代表已完成。", "banked": "原文涉及可储存的重置额度，领取或使用方式以原文为准。", "announcement": "Tibo 发布额度重置信号或预告，尚未确认执行。", "teaser": "Tibo 提及额度重置，目前仅作为相关讨论或意向。"}
    return {"stages": stages, "summary": " ".join(labels[stage] for stage in stages), "timing": timing_description(post)}


class FileStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise MonitorError("本地状态文件损坏或不可读；未重建基线") from None

    def save(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.path)


class GitHubStore:
    def __init__(self, repository, token, branch, commit_sha, api=request_json):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not re.fullmatch(r"[\w.-]+", branch):
            raise MonitorError("GitHub 仓库或状态分支配置无效")
        self.root = "https://api.github.com/repos/" + repository
        self.headers = {"Authorization": "Bearer " + token, "X-GitHub-Api-Version": "2022-11-28"}
        self.branch, self.commit_sha, self.api, self.sha = branch, commit_sha, api, None
        self.path = self.root + "/contents/state/monitor.json"

    def call(self, url, method="GET", body=None):
        return self.api(url, method=method, body=body, headers=self.headers)

    def load(self):
        try:
            blob = self.call(self.path + "?ref=" + self.branch)
        except HttpError as exc:
            if exc.status == 404:
                return None
            raise
        try:
            value = json.loads(base64.b64decode(blob["content"]).decode("utf-8"))
            self.sha = blob["sha"]
            return value
        except (KeyError, ValueError, UnicodeError):
            raise MonitorError("GitHub 状态文件损坏；未重建基线") from None

    def ensure_branch(self):
        endpoint = self.root + "/git/ref/heads/" + self.branch
        try:
            self.call(endpoint)
            return
        except HttpError as exc:
            if exc.status != 404:
                raise
        if not re.fullmatch(r"[0-9a-fA-F]{40}", self.commit_sha):
            raise MonitorError("缺少有效 GITHUB_SHA，不能创建状态分支")
        try:
            self.call(self.root + "/git/refs", "POST", {"ref": "refs/heads/" + self.branch, "sha": self.commit_sha})
        except HttpError as exc:
            if exc.status != 422:
                raise
            self.call(endpoint)

    def save(self, state):
        self.ensure_branch()
        body = {"message": "Update monitor checkpoint [skip ci]", "branch": self.branch,
                "content": base64.b64encode((json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")).decode("ascii")}
        if self.sha:
            body["sha"] = self.sha
        result = self.call(self.path, "PUT", body)
        try:
            self.sha = result["content"]["sha"]
        except (KeyError, TypeError):
            raise MonitorError("GitHub 状态写入结果无法确认；停止发送") from None


class PushPlus:
    def __init__(self, token, api=request_json):
        if not token or not token.strip() or any(char.isspace() for char in token):
            raise MonitorError("请配置仓库 Secret：PUSHPLUS_TOKEN，注意不要带空格或换行")
        self.token, self.api = token.strip(), api

    def send(self, title, content):
        result = self.api(PUSH_URL, method="POST", body={"token": self.token, "title": title,
            "content": content, "template": "html", "channel": "wechat"})
        if not isinstance(result, dict) or result.get("code") != 200:
            code = result.get("code", "unknown") if isinstance(result, dict) else "unknown"
            if not isinstance(code, (int, float)):
                code = "unknown"
            raise MonitorError("push+ 未受理，错误码 %s（903 检查 Token，905 检查实名；失败消息保留待重试）" % code)
        data = result.get("data")
        receipt = data if isinstance(data, str) else data.get("shortCode") if isinstance(data, dict) else None
        if not isinstance(receipt, str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,128}", receipt):
            raise MonitorError("push+ 未返回可识别的流水号；未标记已受理")
        return receipt


def new_state(now):
    return {"version": 1, "started_at": iso(now), "initialized": False, "posts": {},
            "accepted": {}, "outbox": {}, "health": {"failures": 0, "alerted": False}}


def validate_state(state):
    if not isinstance(state, dict) or state.get("version") != 1:
        raise MonitorError("状态版本无效；未重建基线")
    parse_time(state.get("started_at"))
    if not all(isinstance(state.get(key), dict) for key in ("posts", "accepted", "outbox", "health")):
        raise MonitorError("状态结构无效；未重建基线")


def scope_description(text):
    if re.search(r"\ball\s+paid\b", text, re.I):
        return "原文提到所有付费用户"
    if re.search(r"\ball\s+(?:codex\s+)?users\b|\beveryone(?:'s)?\b", text, re.I):
        return "原文提到所有用户；具体产品范围请看原文"
    plans = re.findall(r"\b(?:Plus|Pro|Business|Enterprise|Team|Edu)\b", text, re.I)
    return "原文提到：" + " / ".join(sorted(set(plans))) if plans else "原文未明确说明"


def render_message(items):
    labels = {"update": "延期/更正", "confirmed": "重置确认", "timing": "时间更新", "banked": "储存重置", "announcement": "预告", "teaser": "相关意向", "uncertain": "待核实的完成消息"}
    sections = []
    for item in items:
        if item["type"] == "health":
            sections.append("<h3>%s</h3><p>%s</p>" % (html.escape(item["title"]), html.escape(item["text"])))
            continue
        post, signal = item["post"], item["signal"]
        name = " / ".join(labels[stage] for stage in signal["stages"])
        manual = "原文提到可手动使用" if re.search(r"\b(?:apply|redeem|use.{0,15}(?:whenever|schedule)|on demand)\b", post["text"], re.I) else "是否需手动领取：原文未明确说明"
        sections.append("<h3>%s</h3><p>%s</p><p>发布：%s<br>预计时间：%s<br>适用范围：%s<br>%s</p><blockquote>%s</blockquote><p><a href=\"%s\">查看 Tibo 原推文</a></p>" % (
            html.escape(name), html.escape(signal["summary"]), beijing(post["at"]), html.escape(signal["timing"]),
            html.escape(scope_description(post["text"])), html.escape(manual), html.escape(post["text"][:1800]).replace("\n", "<br>"), html.escape(post["url"], quote=True)))
    return "<hr>".join(sections) + '<hr><p>来源：<a href="https://codex-reset.com/">codex-reset.com</a> 公开收录，非 OpenAI/X 官方服务；本程序未独立直连 X 核验。以原文和账户实际额度为准。</p>'


def checkpoint(store, state, saved):
    if state != saved:
        store.save(state)
        return copy.deepcopy(state)
    return saved


def run_check(store, fetch_feed, push, config, now):
    state = store.load()
    existed = state is not None
    if state is None:
        state = new_state(now)
    validate_state(state)
    saved = copy.deepcopy(state) if existed else None
    result = {"source": "partial", "new_signals": 0, "accepted": 0, "baseline_created": False}
    try:
        posts = parse_feed(fetch_feed(), now, config)
    except MonitorError as exc:
        # A recovery notice queued during a failed push must not be sent while down.
        state["outbox"] = {key: item for key, item in state["outbox"].items() if item.get("health_event") != "recovery"}
        health = state["health"]
        health["failures"] = health.get("failures", 0) + 1
        health.setdefault("episode", iso(now))
        health["last_error"] = str(exc)
        if health["failures"] >= config["failure_alert_after"] and not health.get("alerted"):
            key = "health:failure:" + health["episode"]
            state["outbox"][key] = {"type": "health", "health_event": "failure", "at": iso(now),
                "title": "Tibo 监控数据源受阻", "text": "已连续 %s 轮无法获得可信数据：%s。没有把读取失败当成没有新消息；后续继续重试。" % (health["failures"], exc)}
        result["source"] = "unavailable"
        result["warning"] = str(exc)
    else:
        result["source"] = "public_feed_available"
        health = state["health"]
        if health.get("failures"):
            # Cancel unsubmitted failure warnings after a transient outage has recovered.
            state["outbox"] = {key: item for key, item in state["outbox"].items() if item.get("health_event") != "failure"}
            if health.get("alerted"):
                key = "health:recovery:" + health.get("episode", iso(now))
                state["outbox"][key] = {"type": "health", "health_event": "recovery", "at": iso(now), "title": "Tibo 监控数据源恢复", "text": "公开数据源已恢复有效读取。数据覆盖仍受第三方收录范围限制。"}
            else:
                health.pop("episode", None)
            health["failures"] = 0
            health.pop("last_error", None)
        health["last_success_day"] = now.astimezone(UTC).date().isoformat()
        context = {}
        for raw in state["posts"].values():
            try:
                parent = Post(**raw["post"])
                if parse_time(parent.at) >= now - timedelta(hours=config["lookback_hours"]):
                    context[parent.id] = parent
            except (KeyError, TypeError):
                raise MonitorError("缓存帖子结构无效；停止发送") from None
        context.update({post.id: post for post in posts})
        first = not state.get("initialized")
        for post in posts:
            old = state["posts"].get(post.id)
            fingerprint = digest(normalize_text(post.text))
            changed = old is not None and old["fingerprint"] != fingerprint
            # Re-evaluate even unchanged text: a reply's parent can arrive later.
            signal = classify(post, context, config)
            eligible = parse_time(post.at) >= parse_time(state["started_at"]) or changed
            if signal and eligible and parse_time(post.at) >= now - timedelta(hours=config["lookback_hours"]):
                key = post.id + ":" + digest(fingerprint + ":" + ",".join(signal["stages"]))
                if key not in state["accepted"] and key not in state["outbox"]:
                    state["outbox"][key] = {"type": "post", "at": post.at, "post": asdict(post), "signal": signal}
                    result["new_signals"] += 1
            if not old or changed or old["post"].get("parents") != post.parents:
                state["posts"][post.id] = {"fingerprint": fingerprint, "post": asdict(post)}
        state["initialized"] = True
        result["baseline_created"] = first
        oldest = now - timedelta(days=30)
        state["posts"] = {key: value for key, value in state["posts"].items() if parse_time(value["post"]["at"]) >= oldest}
        state["accepted"] = {key: value for key, value in state["accepted"].items() if parse_time(value["at"]) >= oldest}
    # Persist the outbox before HTTP submission. Failed pushes remain queued.
    saved = checkpoint(store, state, saved)
    items = sorted(state["outbox"].items(), key=lambda pair: pair[1]["at"])[:config["max_posts_per_message"]]
    if items:
        content = render_message([item for _, item in items])
        while len(content) > 18000 and len(items) > 1:
            items.pop()
            content = render_message([item for _, item in items])
        title = "Tibo · Codex 额度动态（%s条）" % len(items)
        receipt = push.send(title, content)
        for key, item in items:
            state["accepted"][key] = {"at": iso(now), "receipt": receipt, "status": "accepted_not_delivery_verified"}
            del state["outbox"][key]
            if item.get("health_event") == "failure":
                state["health"]["alerted"] = True
            elif item.get("health_event") == "recovery":
                state["health"]["alerted"] = False
                state["health"].pop("episode", None)
        checkpoint(store, state, saved)
        result["accepted"] = len(items)
    result["queued"] = len(state["outbox"])
    return result


def load_config(path):
    config = dict(DEFAULTS)
    if Path(path).exists():
        try:
            values = json.loads(Path(path).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise MonitorError("config.json 无法读取或不是有效 JSON") from None
        if not isinstance(values, dict) or set(values) - set(DEFAULTS):
            raise MonitorError("config.json 含未知配置项")
        config.update(values)
    for key in ("max_feed_age_minutes", "lookback_hours", "failure_alert_after", "max_posts_per_message"):
        if type(config[key]) is not int or not 1 <= config[key] <= 168:
            raise MonitorError("配置项 %s 超出范围" % key)
    for key in ("include_teasers", "include_ambiguous_confirmations"):
        if not isinstance(config[key], bool):
            raise MonitorError("配置项 %s 必须是布尔值" % key)
    url = urllib.parse.urlparse(config["feed_url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise MonitorError("feed_url 必须是无凭证的 HTTPS 地址")
    return config


def summary(lines):
    text = "\n".join(lines)
    print(text)
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as output:
            output.write(text + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("check", "test", "preview"), default="check")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--local-state", help="本地调试使用；GitHub Actions 不要配置此参数")
    parser.add_argument("--feed-file", help="离线预览或测试 JSON；不可与真实推送 check/test 同用")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.feed_file and args.mode != "preview":
            raise MonitorError("--feed-file 仅允许 preview，防止把测试资料当成真实公告")
        fetch = (lambda: json.loads(Path(args.feed_file).read_text(encoding="utf-8"))) if args.feed_file else (lambda: request_json(config["feed_url"]))
        if args.mode == "preview":
            now = utcnow()
            posts = parse_feed(fetch(), now, config)
            context = {post.id: post for post in posts}
            signals = [(post, classify(post, context, config)) for post in posts if parse_time(post.at) >= now - timedelta(hours=config["lookback_hours"])]
            lines = ["预览模式：不推送、不写入基线。", "第三方数据源可用，覆盖有限。"]
            for post, signal in signals:
                if signal:
                    lines.append("- %s | %s | %s" % (beijing(post.at), "/".join(signal["stages"]), post.url))
            summary(lines)
            return 0
        push = PushPlus(os.getenv("PUSHPLUS_TOKEN", ""))
        if args.mode == "test":
            push.send("Tibo 监控 · 微信推送测试", "<p>这是一条部署测试消息，不是额度重置公告。</p><p>若你在微信看到本消息，说明 GitHub 到 push+ 的推送通道可用。</p>")
            summary(["测试请求已被 push+ 受理。请以手机实际收到为准；这不代表额度发生重置。", "下一步：mode 选择 check，手动运行一次建立监控基线。"])
            return 0
        if args.local_state:
            store = FileStore(args.local_state)
        else:
            token = os.getenv("GITHUB_TOKEN", "")
            if not token:
                raise MonitorError("缺少 GITHUB_TOKEN；请从 GitHub Actions 运行，或显式使用 --local-state")
            store = GitHubStore(os.getenv("GITHUB_REPOSITORY", ""), token, config["state_branch"], os.getenv("GITHUB_SHA", ""))
        result = run_check(store, fetch, push, config, utcnow())
        lines = ["检查时间：" + beijing(iso(utcnow())), "数据覆盖：第三方公开收录，未独立读取完整 X 时间线。"]
        if result.get("warning"):
            lines.append("数据源异常：" + result["warning"])
        if result["baseline_created"]:
            lines.append("已建立初始基线。此前历史消息不补发。")
        lines.extend(["新增相关记录：%s；本轮 push+ 已受理：%s；待重试：%s。" % (result["new_signals"], result["accepted"], result["queued"]), "受理不等于微信最终送达；没有新动态时不发送例行微信通知。"])
        summary(lines)
        return 0
    except MonitorError as exc:
        summary(["运行未完成：" + str(exc), "未清空去重状态。请查看 README 的排查表。"])
        return 1


if __name__ == "__main__":
    sys.exit(main())
