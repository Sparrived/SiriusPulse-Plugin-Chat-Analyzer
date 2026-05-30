"""聊天分析器 — 多维度统计群聊数据。

六大核心分析维度：
  1. ActiveSender    — 消息数量排名
  2. ImageSender     — 图片发送统计
  3. HourlyActivity  — 时段活跃度 + 情感热力图
  4. SentimentTracker — 关键词情感分析
  5. SocialGraph     — 社交关系图谱（提及 + 回复链）
  6. ConversationDynamics — 对话节奏（速度线 + 爆发检测）
  7. VocabRichness   — 词汇丰富度 + 签名词
  8. ContentClassifier — 内容类型分布
  9. DailyDigest     — 每日摘要聚合器
  10. EventChainTracker — 多轮事件链追踪
  11. EchoTracker    — 复读金句检测

消息格式约定（由 main.py 归一化后传入）：
    {
        "user_id": str,
        "content": str,
        "time": int,             # unix 时间戳（秒）
        "speaker_name": str,
        "role": str,             # "human" | "assistant" | "system"
        "multimodal_inputs": list[dict],
    }
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

# ── 中国时区 ──
_CHINA_TZ = timezone(timedelta(hours=8))


def _get_text(msg: dict[str, Any]) -> str:
    """提取消息的纯文本内容。"""
    return str(msg.get("content", ""))


def _get_hour(ts: int) -> int:
    """从 unix 时间戳提取小时（中国时区），失败返回 -1。"""
    try:
        return datetime.fromtimestamp(ts, _CHINA_TZ).hour
    except (OSError, ValueError, OverflowError):
        return -1


# ═══════════════════════════════════════════════════════════════════
# 基类
# ═══════════════════════════════════════════════════════════════════


class Analyzer:
    """单一维度的分析器基类。"""

    name: str = ""
    unit: str = "条"

    def __init__(self) -> None:
        self._counter: Counter[str] = Counter()

    def reset(self) -> None:
        self._counter.clear()

    def process(self, msg: dict[str, Any]) -> None:
        raise NotImplementedError

    def top(self, n: int = 5) -> list[tuple[str, int]]:
        return self._counter.most_common(n)

    @property
    def total(self) -> int:
        return sum(self._counter.values())


# ═══════════════════════════════════════════════════════════════════
# 1. ActiveSender — 消息数量排名
# ═══════════════════════════════════════════════════════════════════


class ActiveSender(Analyzer):
    """发言活跃度 — 统计发言条数。"""

    name = "消息之王"
    unit = "条"

    def process(self, msg: dict[str, Any]) -> None:
        uid = str(msg.get("user_id", ""))
        if uid:
            self._counter[uid] += 1


# ═══════════════════════════════════════════════════════════════════
# 2. ImageSender — 图片发送统计
# ═══════════════════════════════════════════════════════════════════


class ImageSender(Analyzer):
    """图片发送 — 通过 multimodal_inputs 中的图片类型判断。"""

    name = "图片达人"
    unit = "张"

    def process(self, msg: dict[str, Any]) -> None:
        uid = str(msg.get("user_id", ""))
        if not uid:
            return
        count = 0
        for inp in msg.get("multimodal_inputs", []):
            if isinstance(inp, dict) and "image" in inp.get("type", ""):
                count += 1
        if count > 0:
            self._counter[uid] += count


# ═══════════════════════════════════════════════════════════════════
# 3. HourlyActivity — 时段活跃度
# ═══════════════════════════════════════════════════════════════════


class HourlyActivity(Analyzer):
    """时段活跃度 — 统计每个小时的消息数量及最活跃用户。"""

    name = "时段活跃度"
    unit = "条"

    def __init__(self) -> None:
        super().__init__()
        self._start_hour: int = -1
        self._end_hour: int = -1
        self._user_hourly: dict[str, Counter[str]] = {}

    def reset(self) -> None:
        super().reset()
        self._start_hour = -1
        self._end_hour = -1
        self._user_hourly.clear()

    def process(self, msg: dict[str, Any]) -> None:
        ts = msg.get("time", 0)
        uid = str(msg.get("user_id", ""))
        hour = _get_hour(ts)
        if hour < 0:
            return
        if self._start_hour == -1:
            self._start_hour = hour
        self._end_hour = hour
        self._counter[str(hour)] += 1
        if uid:
            if str(hour) not in self._user_hourly:
                self._user_hourly[str(hour)] = Counter()
            self._user_hourly[str(hour)][uid] += 1

    def hourly_data(self, start_hour: int, end_hour: int) -> list[tuple[int, int]]:
        """返回从 start_hour 到 end_hour 的小时数据（支持跨午夜）。"""
        if self._start_hour == -1:
            return []
        result: list[tuple[int, int]] = []
        h = start_hour
        first = True
        while first or h != start_hour:
            first = False
            result.append((h, self._counter.get(str(h), 0)))
            if h == end_hour and len(result) >= 2:
                break
            h = (h + 1) % 24
        return result

    def hourly_top_users(
        self, uid_to_name: dict[str, str]
    ) -> dict[int, tuple[str, str, str]]:
        """返回每个小时最活跃用户。"""
        result: dict[int, tuple[str, str, str]] = {}
        for hour_key, counter in self._user_hourly.items():
            try:
                hour = int(hour_key)
            except ValueError:
                continue
            top_uid, _ = counter.most_common(1)[0] if counter else ("", 0)
            name = uid_to_name.get(top_uid, f"qq_{top_uid}") if top_uid else ""
            result[hour] = (top_uid, name, "")
        return result


# ═══════════════════════════════════════════════════════════════════
# 4. SentimentTracker — 情感分析
# ═══════════════════════════════════════════════════════════════════

# 情感词典：正向词（>=2字匹配）+ 正向词（精确匹配）
_POS_LONG = [
    "开心", "高兴", "快乐", "哈哈", "太棒", "厉害", "优秀", "可爱", "喜欢",
    "不错", "感谢", "谢谢", "赞", "完美", "精彩", "有趣", "好玩", "甜蜜",
    "幸福", "温暖", "感动", "惊喜", "期待", "兴奋", "激动", "帅气", "漂亮",
    "加油", "支持", "恭喜", "祝福", "好运", "顺利", "成功", "厉害", "牛",
]
_POS_SHORT = ["好", "对", "是", "行", "嗯", "爱"]
_NEG_LONG = [
    "难过", "伤心", "生气", "愤怒", "讨厌", "无聊", "烦", "累", "痛",
    "失望", "焦虑", "担心", "害怕", "紧张", "尴尬", "无奈", "抱歉",
    "烦死了", "垃圾", "坑", "倒霉", "崩溃", "头疼", "无语", "算了",
    "呵呵", "服了", "忍不了", "受不了", "够了",
]
_NEG_SHORT = ["不", "没", "差", "坏", "错", "恨", "死"]

# 独立正向 emoji
_POS_EMOJI = [
    "😄", "😊", "😂", "🤣", "😍", "🥰", "😘", "😎", "🤩", "👍",
    "❤️", "🎉", "🎊", "✨", "💪", "👏", "🙌", "💕", "💖", "🔥",
]


class SentimentTracker:
    """关键词情感分析器 — 每条消息打分，聚合为每小时情感指数。"""

    def __init__(self) -> None:
        # 每条消息的情感分数列表
        self._scores: list[tuple[int, float, str]] = []  # (hour, score, uid)
        self._positive_count: int = 0
        self._negative_count: int = 0
        self._total_score: float = 0.0
        self._message_count: int = 0

    def reset(self) -> None:
        self._scores.clear()
        self._positive_count = 0
        self._negative_count = 0
        self._total_score = 0.0
        self._message_count = 0

    def process(self, msg: dict[str, Any]) -> None:
        """分析单条消息的情感，跳过 assistant 角色。"""
        if msg.get("role") == "assistant":
            return
        text = _get_text(msg)
        if not text:
            return
        uid = str(msg.get("user_id", ""))
        ts = msg.get("time", 0)
        hour = _get_hour(ts)
        if hour < 0:
            return

        score = self._score_text(text)
        self._scores.append((hour, score, uid))
        self._message_count += 1
        self._total_score += score

        if score > 0:
            self._positive_count += 1
        elif score < 0:
            self._negative_count += 1

    @staticmethod
    def _score_text(text: str) -> float:
        """对文本进行情感打分，返回 -1.0 ~ +1.0。"""
        pos_hits = 0
        neg_hits = 0

        # 正向长词匹配
        for word in _POS_LONG:
            if word in text:
                pos_hits += 1
        # 正向短词精确匹配
        for word in _POS_SHORT:
            if word in text:
                pos_hits += 1

        # 负向长词匹配
        for word in _NEG_LONG:
            if word in text:
                neg_hits += 1
        # 负向短词精确匹配
        for word in _NEG_SHORT:
            if word in text:
                neg_hits += 1

        # 正向 emoji
        for emoji in _POS_EMOJI:
            if emoji in text:
                pos_hits += 1

        # 负向 emoji
        neg_emoji_count = text.count("😢") + text.count("😭") + text.count("😡")
        neg_hits += neg_emoji_count

        total = pos_hits + neg_hits
        if total == 0:
            return 0.0
        return (pos_hits - neg_hits) / total

    def hourly_sentiment(
        self, hourly_data: list[tuple[int, int]]
    ) -> list[tuple[int, float]]:
        """返回每小时的平均情感分数。"""
        hour_scores: dict[int, list[float]] = {}
        for hour, score, _uid in self._scores:
            hour_scores.setdefault(hour, []).append(score)

        result: list[tuple[int, float]] = []
        for hour, _count in hourly_data:
            scores = hour_scores.get(hour, [])
            avg = sum(scores) / len(scores) if scores else 0.0
            result.append((hour, avg))
        return result

    def overall_stats(self) -> dict[str, Any]:
        """返回整体情感统计。"""
        avg = self._total_score / self._message_count if self._message_count else 0.0
        pos_ratio = (
            self._positive_count / self._message_count * 100
            if self._message_count
            else 0.0
        )
        neg_ratio = (
            self._negative_count / self._message_count * 100
            if self._message_count
            else 0.0
        )
        return {
            "average": avg,
            "positive_count": self._positive_count,
            "negative_count": self._negative_count,
            "positive_ratio": pos_ratio,
            "negative_ratio": neg_ratio,
        }


# ═══════════════════════════════════════════════════════════════════
# 5. SocialGraph — 社交关系图谱
# ═══════════════════════════════════════════════════════════════════


class SocialGraph:
    """社交图谱 — 追踪 @提及 和相邻消息配对。"""

    def __init__(self) -> None:
        # @提及关系：(mentioned_by, mentioned) → count
        self._mentions: Counter[tuple[str, str]] = Counter()
        # 相邻消息关系：(prev_user, next_user) → count
        self._adjacent: Counter[tuple[str, str]] = Counter()
        self._prev_uid: str = ""
        self._prev_ts: int = 0
        # 用户活跃度
        self._user_msgs: Counter[str] = Counter()

    def reset(self) -> None:
        self._mentions.clear()
        self._adjacent.clear()
        self._prev_uid = ""
        self._prev_ts = 0
        self._user_msgs.clear()

    def process(self, msg: dict[str, Any]) -> None:
        """分析单条消息的社交关系。"""
        if msg.get("role") == "assistant":
            return
        uid = str(msg.get("user_id", ""))
        if not uid:
            return
        ts = msg.get("time", 0)
        text = _get_text(msg)

        self._user_msgs[uid] += 1

        # @提及检测：匹配 @数字 或 @名字
        for m in re.finditer(r"@(\d{5,11})", text):
            mentioned = m.group(1)
            if mentioned != uid:
                self._mentions[(uid, mentioned)] += 1

        # 相邻消息配对（5分钟内不同人）
        if self._prev_uid and self._prev_uid != uid and ts - self._prev_ts < 300:
            pair = (self._prev_uid, uid)
            self._adjacent[pair] += 1

        self._prev_uid = uid
        self._prev_ts = ts

    def top_pairs(self, n: int = 8) -> list[dict[str, Any]]:
        """返回互动最多的用户对。"""
        all_pairs: Counter[tuple[str, str]] = Counter()
        for (a, b), cnt in self._adjacent.items():
            key = tuple(sorted([a, b]))
            all_pairs[key] += cnt  # type: ignore[arg-type]
        for (a, b), cnt in self._mentions.items():
            key = tuple(sorted([a, b]))
            all_pairs[key] += cnt  # type: ignore[arg-type]

        result: list[dict[str, Any]] = []
        for (a, b), cnt in all_pairs.most_common(n):
            result.append({"user_a": a, "user_b": b, "count": cnt})
        return result

    def top_mentioned(self, n: int = 5) -> list[tuple[str, int]]:
        """返回被 @提及最多的用户。"""
        mentioned_counter: Counter[str] = Counter()
        for (_by, target), cnt in self._mentions.items():
            mentioned_counter[target] += cnt
        return mentioned_counter.most_common(n)

    def user_degree(self, uid: str) -> int:
        """计算用户的社交度（关联的不同用户数）。"""
        connected: set[str] = set()
        for (a, b) in self._adjacent:
            if a == uid:
                connected.add(b)
            elif b == uid:
                connected.add(a)
        for (a, b) in self._mentions:
            if a == uid:
                connected.add(b)
            elif b == uid:
                connected.add(a)
        return len(connected)

    @property
    def total_edges(self) -> int:
        """总社交连接数。"""
        unique: set[tuple[str, str]] = set()
        for (a, b) in self._adjacent:
            unique.add((a, b))
        for (a, b) in self._mentions:
            unique.add((a, b))
        return len(unique)


# ═══════════════════════════════════════════════════════════════════
# 6. ConversationDynamics — 对话节奏分析
# ═══════════════════════════════════════════════════════════════════


class ConversationDynamics:
    """对话节奏 — 消息速度线、爆发期检测、响应时间统计。"""

    # 速度计算窗口（秒）
    _VELOCITY_WINDOW = 300
    # 爆发检测阈值：窗口内 >= N 条消息
    _BURST_THRESHOLD = 10
    # 响应时间上限（秒）：超过此值不计入响应时间
    _RESPONSE_LIMIT = 300

    def __init__(self) -> None:
        self._timestamps: list[int] = []
        self._burst_periods: list[dict[str, Any]] = []
        self._response_times: list[float] = []
        self._prev_ts: int = 0
        self._prev_uid: str = ""

    def reset(self) -> None:
        self._timestamps.clear()
        self._burst_periods.clear()
        self._response_times.clear()
        self._prev_ts = 0
        self._prev_uid = ""

    def process(self, msg: dict[str, Any]) -> None:
        """记录消息时间戳和响应时间。"""
        if msg.get("role") == "assistant":
            return
        ts = msg.get("time", 0)
        if not ts:
            return
        uid = str(msg.get("user_id", ""))
        self._timestamps.append(ts)

        # 响应时间计算：不同用户的连续消息
        if self._prev_uid and uid != self._prev_uid:
            gap = ts - self._prev_ts
            if 0 < gap < self._RESPONSE_LIMIT:
                self._response_times.append(float(gap))

        self._prev_ts = ts
        self._prev_uid = uid

    def detect_bursts(self) -> list[dict[str, Any]]:
        """检测爆发期（5分钟窗口内 >= 阈值条消息）。"""
        if len(self._timestamps) < self._BURST_THRESHOLD:
            return []

        bursts: list[dict[str, Any]] = []
        i = 0
        while i < len(self._timestamps):
            window_start = self._timestamps[i]
            window_end = window_start + self._VELOCITY_WINDOW
            count = 0
            j = i
            while j < len(self._timestamps) and self._timestamps[j] <= window_end:
                count += 1
                j += 1
            if count >= self._BURST_THRESHOLD:
                try:
                    start_dt = datetime.fromtimestamp(window_start, _CHINA_TZ)
                    end_dt = datetime.fromtimestamp(
                        min(window_end, self._timestamps[j - 1]), _CHINA_TZ
                    )
                    bursts.append({
                        "start": window_start,
                        "end": min(window_end, self._timestamps[j - 1]),
                        "count": count,
                        "time_str": (
                            f"{start_dt.strftime('%H:%M')} - "
                            f"{end_dt.strftime('%H:%M')}"
                        ),
                    })
                except (OSError, ValueError, OverflowError):
                    pass
                i = j
            else:
                i += 1
        self._burst_periods = bursts[:5]
        return self._burst_periods

    def avg_response_time(self) -> float:
        """平均响应时间（秒）。"""
        if not self._response_times:
            return 0.0
        return sum(self._response_times) / len(self._response_times)

    def median_response_time(self) -> float:
        """中位响应时间（秒）。"""
        if not self._response_times:
            return 0.0
        sorted_times = sorted(self._response_times)
        n = len(sorted_times)
        if n % 2 == 0:
            return (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2
        return sorted_times[n // 2]

    def velocity_series(
        self, interval_seconds: int = 300
    ) -> list[tuple[int, int]]:
        """返回时间序列：(timestamp, count) 用于速度线图。"""
        if not self._timestamps:
            return []
        min_ts = min(self._timestamps)
        max_ts = max(self._timestamps)
        series: list[tuple[int, int]] = []
        t = min_ts
        while t <= max_ts:
            window_end = t + interval_seconds
            count = sum(1 for ts in self._timestamps if t <= ts < window_end)
            series.append((t, count))
            t += interval_seconds
        return series

    def peak_velocity(self) -> tuple[int, int]:
        """返回峰值速度 (timestamp, count)。"""
        series = self.velocity_series()
        if not series:
            return (0, 0)
        return max(series, key=lambda x: x[1])


# ═══════════════════════════════════════════════════════════════════
# 7. VocabRichness — 词汇丰富度
# ═══════════════════════════════════════════════════════════════════


class VocabRichness:
    """词汇丰富度 — 独特词比率 + 签名词提取。"""

    def __init__(self) -> None:
        # 全局词频
        self._global_words: Counter[str] = Counter()
        # 用户词频 + 独特词
        self._user_words: dict[str, Counter[str]] = {}
        self._user_unique: dict[str, set[str]] = {}

    def reset(self) -> None:
        self._global_words.clear()
        self._user_words.clear()
        self._user_unique.clear()

    def process(self, msg: dict[str, Any]) -> None:
        """提取消息中的词汇并统计。"""
        if msg.get("role") == "assistant":
            return
        uid = str(msg.get("user_id", ""))
        text = _get_text(msg)
        if not uid or not text:
            return

        tokens = re.findall(r"[\u4e00-\u9fa5]{2,6}|[a-zA-Z]{3,}", text)
        if uid not in self._user_words:
            self._user_words[uid] = Counter()
            self._user_unique[uid] = set()

        for token in tokens:
            self._global_words[token] += 1
            self._user_words[uid][token] += 1
            self._user_unique[uid].add(token)

    def top_rich_users(
        self, min_msgs: int = 10, top_n: int = 5
    ) -> list[dict[str, Any]]:
        """返回词汇最丰富的用户。"""
        result: list[dict[str, Any]] = []
        for uid, word_counter in self._user_words.items():
            total = sum(word_counter.values())
            unique = len(self._user_unique.get(uid, set()))
            if total < min_msgs:
                continue
            ratio = unique / total if total > 0 else 0.0
            # 签名词：用户使用但全局不太常见的词
            signature = []
            for word, cnt in word_counter.most_common(20):
                if cnt >= 2 and self._global_words.get(word, 0) <= cnt + 2:
                    signature.append(word)
                if len(signature) >= 3:
                    break
            result.append({
                "uid": uid,
                "richness": ratio,
                "unique_words": unique,
                "total_words": total,
                "signature": signature,
            })
        result.sort(key=lambda x: x["richness"], reverse=True)
        return result[:top_n]

    def global_word_cloud(self, n: int = 20) -> list[tuple[str, int]]:
        """返回全局高频词（过滤停用词）。"""
        _STOPWORDS = {
            "一个", "这个", "那个", "什么", "怎么", "可以", "没有", "就是",
            "还是", "不是", "已经", "然后", "因为", "所以", "但是", "如果",
            "现在", "知道", "觉得", "时候", "可能", "应该", "这样", "那样",
            "出来", "起来", "一下", "一些", "这些", "那些", "大家", "东西",
        }
        return [
            (w, c)
            for w, c in self._global_words.most_common(n * 3)
            if w not in _STOPWORDS
        ][:n]


# ═══════════════════════════════════════════════════════════════════
# 8. ContentClassifier — 内容类型分类
# ═══════════════════════════════════════════════════════════════════


class ContentClassifier:
    """内容分类 — 将消息分为文本/图片/链接/短消息。"""

    def __init__(self) -> None:
        self._text_count: int = 0
        self._image_count: int = 0
        self._link_count: int = 0
        self._short_count: int = 0
        self._total: int = 0

    def reset(self) -> None:
        self._text_count = 0
        self._image_count = 0
        self._link_count = 0
        self._short_count = 0
        self._total = 0

    def process(self, msg: dict[str, Any]) -> None:
        """分类单条消息。"""
        self._total += 1
        text = _get_text(msg)
        has_image = any(
            isinstance(inp, dict) and "image" in inp.get("type", "")
            for inp in msg.get("multimodal_inputs", [])
        )
        has_link = bool(re.search(r"https?://", text))

        if has_image:
            self._image_count += 1
        elif has_link:
            self._link_count += 1
        elif len(text.strip()) < 8:
            self._short_count += 1
        else:
            self._text_count += 1

    def distribution(self) -> dict[str, int]:
        """返回内容类型分布。"""
        return {
            "text": self._text_count,
            "image": self._image_count,
            "link": self._link_count,
            "short": self._short_count,
            "total": self._total,
        }


# ═══════════════════════════════════════════════════════════════════
# 9. DailyDigest — 每日摘要聚合器
# ═══════════════════════════════════════════════════════════════════


class DailyDigest:
    """每日摘要 — 聚合分析数据，生成文字版摘要。"""

    def __init__(self) -> None:
        self._total_msgs: int = 0
        self._unique_users: set[str] = set()
        self._peak_hour: int = -1
        self._peak_count: int = 0

    def reset(self) -> None:
        self._total_msgs = 0
        self._unique_users.clear()
        self._peak_hour = -1
        self._peak_count = 0

    def process(self, msg: dict[str, Any]) -> None:
        """统计基础指标。"""
        if msg.get("role") == "assistant":
            return
        self._total_msgs += 1
        uid = str(msg.get("user_id", ""))
        if uid:
            self._unique_users.add(uid)

    def set_peak(self, hour: int, count: int) -> None:
        """设置峰值时段。"""
        self._peak_hour = hour
        self._peak_count = count

    def summary_stats(self) -> dict[str, Any]:
        """返回摘要统计。"""
        return {
            "total_messages": self._total_msgs,
            "unique_users": len(self._unique_users),
            "peak_hour": self._peak_hour,
            "peak_count": self._peak_count,
            "avg_per_user": (
                self._total_msgs / len(self._unique_users)
                if self._unique_users
                else 0.0
            ),
        }

    def text_summary(self, uid_to_name: dict[str, str]) -> list[str]:
        """生成文字摘要要点。"""
        lines: list[str] = []
        lines.append(f"共 {self._total_msgs} 条消息")
        lines.append(f"参与人数 {len(self._unique_users)} 人")
        if self._peak_hour >= 0:
            lines.append(f"最活跃时段 {self._peak_hour:02d}:00（{self._peak_count}条）")
        avg = self._total_msgs / len(self._unique_users) if self._unique_users else 0
        lines.append(f"人均发言 {avg:.1f} 条")
        return lines


# ═══════════════════════════════════════════════════════════════════
# 10. EventChainTracker — 多轮事件链追踪
# ═══════════════════════════════════════════════════════════════════


class EventChainTracker:
    """事件链追踪器 — 追踪连续的多轮对话事件。

    事件链定义：消息间隔 < 5分钟视为同一事件链。
    用链内关键词提取话题标签。
    """

    def __init__(self, max_gap_seconds: int = 300) -> None:
        self._max_gap_seconds = max_gap_seconds
        self._chains: list[dict[str, Any]] = []
        self._current_chain: dict[str, Any] | None = None
        self._last_timestamp: int = 0

    def reset(self) -> None:
        self._chains.clear()
        self._current_chain = None
        self._last_timestamp = 0

    def process(self, msg: dict[str, Any]) -> None:
        ts = msg.get("time", 0)
        if not ts:
            return

        text = _get_text(msg).strip()
        uid = str(msg.get("user_id", ""))
        nickname = str(msg.get("speaker_name", f"qq_{uid}"))

        if self._current_chain is not None:
            gap = ts - self._last_timestamp
            if gap > self._max_gap_seconds:
                self._chains.append(self._current_chain)
                self._current_chain = None

        if self._current_chain is None:
            self._current_chain = {
                "start_time": ts,
                "end_time": ts,
                "message_count": 0,
                "participants": set(),
                "participant_uids": set(),
                "topic_preview": "",
                "_keyword_counter": Counter(),
                "raw_messages": [],
                "sample_messages": [],
            }

        self._current_chain["message_count"] += 1
        self._current_chain["end_time"] = ts
        self._current_chain["participants"].add(uid)
        self._current_chain["participant_uids"].add(uid)

        if len(self._current_chain["raw_messages"]) < 30:
            self._current_chain["raw_messages"].append({
                "user_id": uid,
                "nickname": nickname,
                "content": text,
            })

        has_topic = bool(self._current_chain.get("topic_preview"))
        if not has_topic and len(text) >= 6:
            self._current_chain["topic_preview"] = text[:40]

        for m in re.finditer(r"[\u4e00-\u9fa5]{2,4}", text):
            self._current_chain["_keyword_counter"][m.group()] += 1

        if len(self._current_chain["sample_messages"]) < 5 and len(text) >= 4:
            self._current_chain["sample_messages"].append({
                "uid": uid,
                "nickname": nickname,
                "text": text[:60],
            })

        self._last_timestamp = ts

    def finalize(self) -> None:
        """结束并保存最后一个事件链。"""
        if self._current_chain is not None and self._current_chain["message_count"] > 0:
            self._chains.append(self._current_chain)
            self._current_chain = None

    def top_chains(self, n: int = 3) -> list[dict[str, Any]]:
        """返回热度最高的 N 个事件链。"""
        if not self._chains:
            return []

        sorted_chains = sorted(
            self._chains,
            key=lambda c: c["message_count"],
            reverse=True,
        )[:n]

        result = []
        for i, chain in enumerate(sorted_chains):
            start_dt = datetime.fromtimestamp(chain["start_time"], _CHINA_TZ)
            end_dt = datetime.fromtimestamp(chain["end_time"], _CHINA_TZ)
            time_str = f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"

            kw_counter: Counter = chain.get("_keyword_counter", Counter())
            top_keywords = [kw for kw, _ in kw_counter.most_common(5) if len(kw) >= 2]

            if top_keywords:
                topic_label = "、".join(top_keywords[:3])
            else:
                topic_label = chain.get("topic_preview", "") or "群聊讨论"

            if len(topic_label) > 25:
                topic_label = topic_label[:25] + "…"

            result.append({
                "rank": i + 1,
                "message_count": chain["message_count"],
                "participant_count": len(chain["participants"]),
                "participant_uids": list(
                    chain.get("participant_uids", chain["participants"])
                ),
                "time_range": time_str,
                "topic_label": topic_label,
                "topic_keywords": top_keywords[:5],
                "raw_messages": chain.get("raw_messages", []),
                "sample_messages": chain["sample_messages"][:3],
            })

        return result


# ═══════════════════════════════════════════════════════════════════
# 11. EchoTracker — 复读金句检测
# ═══════════════════════════════════════════════════════════════════


class EchoTracker:
    """复读金句 — 筛选短时间内被不同用户重复多次的消息。"""

    def __init__(self, window_seconds: int = 180) -> None:
        self._window = window_seconds
        self._entries: list[tuple[int, str, str]] = []

    def reset(self) -> None:
        self._entries.clear()

    def process(self, msg: dict[str, Any]) -> None:
        ts = msg.get("time", 0)
        uid = str(msg.get("user_id", ""))
        if not ts or not uid:
            return
        text = _get_text(msg).strip()
        if len(text) >= 4:
            self._entries.append((int(ts), uid, text))

    def top_echoes(self, n: int = 5) -> list[dict[str, Any]]:
        """返回 Top-N 复读金句。"""
        if len(self._entries) < 3:
            return []

        half_window = self._window / 2
        seen: set[tuple[str, str]] = set()
        echoes: dict[str, dict[str, Any]] = {}

        for i in range(len(self._entries)):
            ts_i, uid_i, text_i = self._entries[i]
            key = (uid_i, text_i)
            if key in seen:
                continue
            seen.add(key)

            count = 0
            uids: set[str] = set()
            for ts_j, uid_j, text_j in self._entries:
                if text_j == text_i and abs(ts_j - ts_i) <= half_window:
                    count += 1
                    uids.add(uid_j)

            if count >= 3 and len(uids) >= 2 and text_i not in echoes:
                echoes[text_i] = {"text": text_i, "count": count, "uids": list(uids)}

        sorted_echoes = sorted(echoes.values(), key=lambda e: e["count"], reverse=True)
        return sorted_echoes[:n]
