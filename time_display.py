"""Display notification times in Beijing and explain conversions of source text.

Absolute clock times require a date anchor; US generic zones use IANA DST rules.
The original post text is never rewritten. Unknown times stay explicitly unknown.
"""
import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # Older local Python can still run the fixed-offset paths.
    ZoneInfo = None
    ZoneInfoNotFoundError = LookupError

UTC = timezone.utc
BEIJING = timezone(timedelta(hours=8))
LABEL = "北京时间（UTC+8）"
ZONE_PATTERN = r"(?:Pacific(?:\s+(?:Standard|Daylight))?\s+Time|Eastern(?:\s+(?:Standard|Daylight))?\s+Time|Central(?:\s+(?:Standard|Daylight))?\s+Time|Mountain(?:\s+(?:Standard|Daylight))?\s+Time|PST|PDT|PT|EST|EDT|ET|CST|CDT|CT|MST|MDT|MT|UTC|GMT)"
CLOCK = re.compile(r"(?<![\d:])(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)?\s*(?P<zone>" + ZONE_PATTERN + r")\b", re.I)
BARE_CLOCK = re.compile(r"\b\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?", re.I)
RELATIVE = re.compile(r"\b(?:(?:within|in|over)\s+(?:the\s+)?(?:next\s+)?(?:about\s+)?|next\s+)(?:(\d+|an?|one|two|three|half)\s*)?(minutes?|mins?|hours?|hrs?|days?)\b", re.I)
MONTHS = {name: index for index, name in enumerate(("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1)}
MONTH_PATTERN = "|".join(MONTHS)
ANCHOR = re.compile(r"\b(?:today|tomorrow|yesterday)\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:" + MONTH_PATTERN + r")\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b", re.I)
FIXED_ZONES = {"PST": -8, "PDT": -7, "EST": -5, "EDT": -4, "CDT": -5, "MST": -7, "MDT": -6, "UTC": 0, "GMT": 0}
IANA_ZONES = {"PT": "America/Los_Angeles", "ET": "America/New_York", "CT": "America/Chicago", "MT": "America/Denver"}
LONG_ZONES = {"pacific time": "PT", "pacific standard time": "PST", "pacific daylight time": "PDT", "eastern time": "ET", "eastern standard time": "EST", "eastern daylight time": "EDT", "central time": "CT", "central standard time": "CST", "central daylight time": "CDT", "mountain time": "MT", "mountain standard time": "MST", "mountain daylight time": "MDT"}


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def format_beijing(value):
    if isinstance(value, str):
        value = parse(value)
    return value.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S ") + LABEL


def unresolved(reason):
    return LABEL + "：无法唯一确定（" + reason + "）"


def resolve_zone(raw, surrounding):
    normalized = re.sub(r"\s+", " ", raw.lower())
    code = LONG_ZONES.get(normalized, raw.upper())
    if code == "CST":
        central_context = re.search(r"\b(?:central|USA|America)\b", surrounding, re.I) or re.search(r"\bUS\b", surrounding)
        if normalized != "central standard time" and not central_context:
            return None, "CST 可能指不同时区，原文未明确美国中部时区"
        return timezone(timedelta(hours=-6)), "按原文美国中部 CST（UTC-06:00）"
    if code in FIXED_ZONES:
        offset = FIXED_ZONES[code]
        return timezone(timedelta(hours=offset)), "按原文 %s（UTC%+03d:00）" % (code, offset)
    if code in IANA_ZONES:
        if ZoneInfo is None:
            return None, "执行环境不支持 IANA 时区，无法解析 " + code
        try:
            return ZoneInfo(IANA_ZONES[code]), "按原文 %s，依据日期应用美国夏令时规则" % code
        except ZoneInfoNotFoundError:
            return None, "执行环境缺少美国时区数据，无法解析 " + code
    return None, "原文时区无法识别"


def date_anchor(text, clock_match, zone, posted_at):
    # Prefer the last anchor before this clock in its clause. A date immediately
    # following the clock is also valid; don't borrow 'and tomorrow' from a later clock.
    start, end = clock_match.span()
    prefix = text[max(0, start - 180):start]
    prefix = re.split(r"[;\n]|[.!?]\s+(?=[A-Z])", prefix)[-1]
    preceding = list(ANCHOR.finditer(prefix))
    following = re.match(r"\s*(?:on\s+)?(" + ANCHOR.pattern + r")", text[end:end + 65], re.I)
    raw = following.group(1) if following else preceding[-1].group(0) if preceding else None
    if raw is None:
        return None, "原文未明确日期，未擅自推断为今天或明天"
    local_date = posted_at.astimezone(zone).date()
    lower = raw.lower()
    if lower in ("today", "tomorrow", "yesterday"):
        offset = {"today": 0, "tomorrow": 1, "yesterday": -1}[lower]
        return local_date + timedelta(days=offset), "%s 按发帖时原文时区的日期解释" % raw
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return datetime.strptime(raw, "%Y-%m-%d").date(), "采用原文日期 " + raw
        named = re.fullmatch(r"(" + MONTH_PATTERN + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", raw, re.I)
        if named and named.group(3):
            return datetime(int(named.group(3)), MONTHS[named.group(1).lower()], int(named.group(2))).date(), "采用原文日期 " + raw
        return None, "原文日期未给年份，未擅自推断年份"
    except ValueError:
        return None, "原文日期无效，未推断替代日期"


def convert_clock(text, match, posted_at):
    raw = match.group(0)
    zone, zone_note = resolve_zone(match.group("zone"), text[max(0, match.start() - 40):match.end() + 40])
    if zone is None:
        return {"original": raw, "beijing": unresolved(zone_note), "note": "", "kind": "absolute"}
    hour, minute = int(match.group("hour")), int(match.group("minute") or 0)
    ampm = (match.group("ampm") or "").replace(".", "").lower()
    if ampm:
        if not 1 <= hour <= 12:
            return {"original": raw, "beijing": unresolved("原文 12 小时制时刻无效"), "note": "", "kind": "absolute"}
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif match.group("minute") is None and hour <= 12:
        return {"original": raw, "beijing": unresolved("原文未明确上午/下午或 24 小时制"), "note": "", "kind": "absolute"}
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return {"original": raw, "beijing": unresolved("原文时刻无效"), "note": "", "kind": "absolute"}
    day, day_note = date_anchor(text, match, zone, posted_at)
    if day is None:
        return {"original": raw, "beijing": unresolved(day_note), "note": zone_note, "kind": "absolute"}
    naive = datetime(day.year, day.month, day.day, hour, minute)
    # Validate both folds by round-tripping. A spring-forward gap has no valid
    # candidate; a fall-back hour has two. Never silently pick one of the two.
    candidates = {}
    for fold in (0, 1):
        local = naive.replace(tzinfo=zone, fold=fold)
        utc = local.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            candidates[utc] = local.tzname()
    if not candidates:
        rendered = unresolved("该美国本地时刻处于夏令时跳时缺口")
    elif len(candidates) == 2:
        rendered = " 或 ".join(format_beijing(value) for value in sorted(candidates)) + "（美国夏令时回拨，原文不能唯一确定）"
    else:
        rendered = format_beijing(next(iter(candidates)))
    return {"original": raw, "beijing": rendered, "note": "%s；%s" % (zone_note, day_note), "kind": "absolute"}


def converted_times(text, posted_at):
    """Return every recognized source-time conversion without changing the quote."""
    posted = parse(posted_at) if isinstance(posted_at, str) else posted_at.astimezone(UTC)
    results, spans = [], []
    for match in CLOCK.finditer(text):
        results.append((match.start(), convert_clock(text, match, posted)))
        spans.append(match.span())
    for match in RELATIVE.finditer(text):
        number = (match.group(1) or "one").lower()
        numbers = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "half": 0.5}
        amount = numbers.get(number, float(number) if number.isdigit() else 1)
        unit = match.group(2).lower()
        seconds = amount * (86400 if unit.startswith("day") else 3600 if unit.startswith(("hour", "hr")) else 60)
        if not 0 < seconds <= 366 * 86400:
            rendered = unresolved("原文相对时间超出可处理范围")
        else:
            end = posted + timedelta(seconds=seconds)
            rendered = format_beijing(end)
            if not match.group(0).lower().startswith("in "):
                rendered = format_beijing(posted) + " 至 " + rendered
            rendered += "（按推文发布时间换算，仍为预计）"
        results.append((match.start(), {"original": match.group(0), "beijing": rendered, "note": "", "kind": "relative"}))
    for match in re.finditer(r"\bEOD(?:\s+" + ZONE_PATTERN + r")?\b", text, re.I):
        results.append((match.start(), {"original": match.group(0), "beijing": unresolved("EOD 的结束边界未明确，不推算精确时刻"), "note": "保留原文，不把预计时间过去当成重置完成。", "kind": "vague"}))
    for match in BARE_CLOCK.finditer(text):
        if not any(start <= match.start() < end for start, end in spans):
            results.append((match.start(), {"original": match.group(0), "beijing": unresolved("原文未说明时区"), "note": "", "kind": "vague"}))
    if not results and re.search(r"\b(?:today|tomorrow|tonight|yesterday)\b", text, re.I):
        results.append((0, {"original": "原文中的相对日期", "beijing": unresolved("未提供可唯一换算的时区和具体时刻"), "note": "", "kind": "vague"}))
    return [result for _, result in sorted(results, key=lambda pair: pair[0])]


def describe_times(text, posted_at):
    items = converted_times(text, posted_at)
    if not items:
        return LABEL + "：原文未提供可确定的执行时间。"
    return "\n".join("原文 %s → %s%s" % (item["original"], item["beijing"], "；" + item["note"] if item["note"] else "") for item in items)
