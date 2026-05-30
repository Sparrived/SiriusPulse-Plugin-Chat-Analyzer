"""聊天分析器 — 多维度统计群聊活跃度。

所有分析器通过一次遍历完成全量统计，零外部依赖。
适配引擎归档消息格式（BasicMemoryEntry → 规范化 dict）。

消息格式约定（由 main.py 归一化后传入）：
    {
        "user_id": str,          # 用户 ID
        "content": str,          # 纯文本内容（已去除 CQ 码）
        "time": int,             # unix 时间戳（秒）
        "speaker_name": str,     # 显示昵称
        "role": str,             # "human" | "assistant" | "system"
        "multimodal_inputs": list[dict],  # 多模态附件（图片等）
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


class ActiveSender(Analyzer):
    """发言活跃度 — 统计发言条数。"""

    name = "话痨之王"
    unit = "条"

    def process(self, msg: dict[str, Any]) -> None:
        uid = str(msg.get("user_id", ""))
        if uid:
            self._counter[uid] += 1


class WordCount(Analyzer):
    """单条消息最长字数 — content 字段的字符数。"""

    name = "长文写手"
    unit = "字"

    def process(self, msg: dict[str, Any]) -> None:
        uid = str(msg.get("user_id", ""))
        text = _get_text(msg)
        if uid and text:
            char_count = len(text)
            if char_count > 0:
                self._counter[uid] = max(self._counter.get(uid, 0), char_count)


class ImageSender(Analyzer):
    """图片发送 — 通过 multimodal_inputs 中的图片类型判断。

    引擎归档不再保留 CQ 码的 sub_type 区分，
    因此统一统计所有图片附件，不再区分表情包与普通图片。
    """

    name = "图片分享达人"
    unit = "张"

    def process(self, msg: dict[str, Any]) -> None:
        uid = str(msg.get("user_id", ""))
        if not uid:
            return
        count = 0
        for inp in msg.get("multimodal_inputs", []):
            if isinstance(inp, dict):
                inp_type = inp.get("type", "")
                if "image" in inp_type:
                    count += 1
        if count > 0:
            self._counter[uid] += count


class HourlyActivity(Analyzer):
    """时段活跃度 — 统计每个小时的消息数量及该时段最活跃用户。"""

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
        try:
            hour = datetime.fromtimestamp(ts, _CHINA_TZ).hour
        except (OSError, ValueError, OverflowError):
            return
        if self._start_hour == -1:
            self._start_hour = hour
        self._end_hour = hour
        self._counter[str(hour)] += 1
        if uid:
            hour_key = str(hour)
            if hour_key not in self._user_hourly:
                self._user_hourly[hour_key] = Counter()
            self._user_hourly[hour_key][uid] += 1

    def hourly_data(self, start_hour: int, end_hour: int) -> list[tuple[int, int]]:
        """返回从 start_hour 到 end_hour 的小时数据（按时间正序，支持跨午夜）。"""
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
        """返回每个小时最活跃用户的信息。"""
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


class EchoTracker:
    """复读金句 — 筛选短时间内（3分钟）被不同用户重复3次以上的消息。"""

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
                echoes[text_i] = {
                    "text": text_i,
                    "count": count,
                    "uids": list(uids),
                }

        sorted_echoes = sorted(echoes.values(), key=lambda e: e["count"], reverse=True)
        return sorted_echoes[:n]


class NightOwlIndex(Analyzer):
    """夜猫子指数 — 统计每个用户在深夜时段（0:00-6:00）的发消息占比。"""

    name = "夜猫子指数"
    unit = "%"

    _NIGHT_START = 0
    _NIGHT_END = 6

    def __init__(self) -> None:
        super().__init__()
        self._total_counter: Counter[str] = Counter()

    def reset(self) -> None:
        super().reset()
        self._total_counter.clear()

    def process(self, msg: dict[str, Any]) -> None:
        uid = str(msg.get("user_id", ""))
        if not uid:
            return
        self._total_counter[uid] += 1
        ts = msg.get("time", 0)
        try:
            hour = datetime.fromtimestamp(ts, _CHINA_TZ).hour
        except (OSError, ValueError, OverflowError):
            return
        if self._NIGHT_START <= hour < self._NIGHT_END:
            self._counter[uid] += 1

    def night_owl_ratio(self) -> list[tuple[str, float]]:
        """返回每个用户的深夜发言占比（只返回总发言 >= 5 条的用户）。"""
        ratios: list[tuple[str, float]] = []
        for uid, night_count in self._counter.items():
            total = self._total_counter.get(uid, 0)
            if total >= 5:
                ratios.append((uid, night_count / total * 100))
        ratios.sort(key=lambda x: x[1], reverse=True)
        return ratios


class TopicTracker:
    """话题追踪器 — 从消息中提取关键词，计算话题热度变化。"""

    def __init__(self) -> None:
        self._word_counter: Counter[str] = Counter()
        self._hourly_topics: dict[int, Counter[str]] = {}
        self._message_count: int = 0

    def reset(self) -> None:
        self._word_counter.clear()
        self._hourly_topics.clear()
        self._message_count = 0

    def process(self, msg: dict[str, Any]) -> None:
        text = _get_text(msg)
        self._message_count += 1

        ts = msg.get("time", 0)
        try:
            hour = datetime.fromtimestamp(ts, _CHINA_TZ).hour
        except (OSError, ValueError, OverflowError):
            hour = 0

        for m in re.finditer(r"[\u4e00-\u9fa5]{2,4}", text):
            word = m.group()
            self._word_counter[word] += 1
            self._hourly_topics.setdefault(hour, Counter())[word] += 1

    def top_words(self, n: int = 20) -> list[tuple[str, int]]:
        return self._word_counter.most_common(n)

    def topic_heatmap(self) -> dict[int, list[tuple[str, int]]]:
        """每小时 top-5 关键词。"""
        return {
            h: counter.most_common(5)
            for h, counter in sorted(self._hourly_topics.items())
        }

    @property
    def message_count(self) -> int:
        return self._message_count


class EventChainTracker:
    """事件链追踪器 — 追踪群聊中连续的多轮对话事件。

    事件链定义：消息间隔 < 5分钟视为同一事件链的连续讨论。
    用链内关键词提取话题标签，替代无意义的首条消息片段。
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
        china_tz = timezone(timedelta(hours=8))
        for i, chain in enumerate(sorted_chains):
            start_dt = datetime.fromtimestamp(chain["start_time"], china_tz)
            end_dt = datetime.fromtimestamp(chain["end_time"], china_tz)
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
                "participant_uids": list(chain.get("participant_uids", chain["participants"])),
                "time_range": time_str,
                "topic_label": topic_label,
                "topic_keywords": top_keywords[:5],
                "raw_messages": chain.get("raw_messages", []),
                "sample_messages": chain["sample_messages"][:3],
            })

        return result
