"""群聊分析 Plugin — 统计活跃度并生成 HTML 图片报告。

触发方式：
    /ca analyze [持续时间分钟数] — 手动分析
    定时自动分析 — 通过 _plugin_schedule 配置每日定时

消息来源：从引擎归档（archive/*.jsonl）读取历史消息，
不再通过 adapter.get_group_msg_history 拉取。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sirius_pulse.plugins import PluginBase, PluginResponse, command
from sirius_pulse.plugins.config import get_config_manager

from .analyzers import (
    ActiveSender,
    ImageSender,
    EventChainTracker,
    HourlyActivity,
    NightOwlIndex,
    TopicTracker,
    WordCount,
    EchoTracker,
)
from .render import html_to_png, render_report_html

logger = logging.getLogger(__name__)

# ── 中国时区 ──
_CHINA_TZ = timezone(timedelta(hours=8))

# ── 归档读取上限：防止超大文件 OOM ──
_MAX_ARCHIVE_LINES = 5000


class ChatAnalyzerPlugin(PluginBase):
    """群聊分析插件。

    从引擎归档读取群聊历史，统计多维度活跃度数据，
    用 HTML 渲染成图片报告发送到群聊，并用 LLM 生成人格化总结。
    """

    _plugin_name = "chat_analyzer"
    _plugin_display_name = "群聊分析"
    _plugin_description = (
        "统计群聊活跃度（话痨榜、长文、图片、表情包、时段分布），"
        "生成 HTML 图片报告，并由 AI 总结当日话题。"
    )
    _plugin_version = "3.0.0"
    _plugin_author = "sirius-chat"
    _plugin_dependencies = ["playwright"]
    _plugin_nl_examples = [
        "分析一下群聊数据",
        "看看今天谁最活跃",
        "群聊报告",
    ]
    _plugin_nl_slots = {
        "duration": {"type": "int", "description": "分析时长（分钟），默认 1440（24 小时）"},
    }
    _plugin_prompt_inject = (
        "群聊分析：群友们可以让我分析群聊活跃度数据，包括话痨榜、"
        "长文统计、图片和表情包使用统计等，我可以生成带图表的分析报告"
    )

    # 定时自动分析：默认每晚 22:00，分析最近 1440 分钟
    _plugin_schedule = [
        {"time": "22:00", "duration": 1440},
    ]

    def on_load(self) -> None:
        logger.info("群聊分析插件已加载")
        self._schedule_cancel_event: asyncio.Event | None = None
        self._schedule_task: asyncio.Task | None = None
        self._schedule_list: list[dict[str, Any]] = []
        self._config_listener: Any = None

        try:
            self._config_listener = get_config_manager().add_listener(
                self._on_config_changed
            )
        except Exception as exc:
            logger.warning("注册配置监听器失败: %s", exc)

        self._schedule_task = asyncio.create_task(self._run_schedule_loop())

    def on_unload(self) -> None:
        logger.info("群聊分析插件已卸载")
        self._cancel_schedule()
        if self._config_listener:
            self._config_listener.stop()

    def _cancel_schedule(self) -> None:
        if self._schedule_task:
            self._schedule_task.cancel()
            self._schedule_task = None
        if self._schedule_cancel_event:
            self._schedule_cancel_event.set()
            self._schedule_cancel_event = None

    def _on_config_changed(self, plugin_name: str, config: dict[str, Any]) -> None:
        """配置变更回调：热重载定时配置。"""
        if plugin_name != self._plugin_name:
            return

        settings = config.get("settings", {})
        new_schedule = settings.get("schedule", [])
        if new_schedule and isinstance(new_schedule, list):
            logger.info(
                "群聊分析定时配置已更新: %s",
                ", ".join(s.get("time", "?") for s in new_schedule),
            )
            self._schedule_list = new_schedule
            if hasattr(self, '_schedule_triggered'):
                self._schedule_triggered.clear()

    def _get_schedule_list(self) -> list[dict[str, Any]]:
        """获取定时配置列表（优先从配置管理器读取，回退到默认值）。"""
        if self._schedule_list:
            return self._schedule_list

        try:
            config = get_config_manager().get_settings(self._plugin_name)
            schedule = config.get("schedule", [])
            if schedule and isinstance(schedule, list):
                self._schedule_list = schedule
                return schedule
        except Exception:
            pass

        return self._plugin_schedule

    async def _run_schedule_loop(self) -> None:
        """后台定时循环：每 30 秒检查一次，到配置时间后触发自动分析。"""
        self._schedule_cancel_event = asyncio.Event()
        _last_date_key: str = ""
        self._schedule_triggered: set[str] = set()

        while not self._schedule_cancel_event.is_set():
            schedule_list = self._get_schedule_list()

            now = datetime.now(_CHINA_TZ)
            today_key = now.strftime("%Y%m%d")

            if today_key != _last_date_key:
                self._schedule_triggered.clear()
                _last_date_key = today_key

            for entry in schedule_list:
                time_str = entry.get("time", "22:00")
                duration = int(entry.get("duration", 1440))
                trigger_key = f"{today_key}:{time_str}:{duration}"

                try:
                    target_h, target_m = map(int, time_str.split(":"))
                except (ValueError, AttributeError):
                    continue

                target_dt = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
                diff_seconds = (now - target_dt).total_seconds()

                if 0 <= diff_seconds < 60 and trigger_key not in self._schedule_triggered:
                    self._schedule_triggered.add(trigger_key)
                    logger.info(
                        "群聊分析定时触发: time=%s, duration=%d", time_str, duration,
                    )
                    try:
                        await self._run_scheduled_analysis(duration)
                    except Exception as exc:
                        logger.warning("定时分析执行失败: %s", exc)

            try:
                await asyncio.wait_for(
                    self._schedule_cancel_event.wait(),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break

    async def _run_scheduled_analysis(self, duration: int) -> None:
        """定时触发的分析：遍历引擎已知的所有群，依次分析并发送报告。"""
        engine = self._get_engine()
        if engine is None:
            logger.warning("定时分析跳过：engine 未就绪")
            return

        group_ids: list[str] = []
        try:
            group_ids = list(engine.basic_memory.list_groups())
        except Exception:
            pass

        if not group_ids:
            group_ids = self._scan_archive_groups(engine)

        if not group_ids:
            logger.info("定时分析跳过：未找到活跃群")
            return

        adapter = self.ctx.adapter

        for gid in group_ids:
            try:
                messages = await self._fetch_history(gid, duration)
                if not messages:
                    logger.info("定时分析 [%s] 无消息，跳过", gid)
                    continue

                end_time = datetime.now(_CHINA_TZ)
                start_time = end_time - timedelta(minutes=duration)

                logger.info(
                    "定时分析 [%s] 获取到 %d 条消息，duration=%d",
                    gid, len(messages), duration,
                )

                report = await self._analyze(messages, gid, start_time, end_time)
                await self._render_and_send(report, adapter, gid)
            except Exception as exc:
                logger.warning("定时分析 [%s] 失败: %s", gid, exc)

        logger.info("定时分析完成，共处理 %d 个群", len(group_ids))

    @command(
        "ca",
        prefix="/",
        patterns=["ca analyse", "ca analyze", "ca", "群聊分析", "聊天分析"],
        pattern_type="prefix",
        render_mode="llm",
        description="分析群聊数据并生成报告",
        examples=["/ca analyze", "/ca analyze 360"],
        system_prompt_suffix="请用活泼的语气告知用户分析报告已生成，并简要提一下亮点。",
        max_tokens=200,
        timeout=120.0,
    )
    async def cmd_analyze(self, duration: int = 1440) -> PluginResponse:
        """分析群聊数据并生成图片报告。

        Args:
            duration: 分析时长（分钟），默认 1440（24 小时）
        """
        group_id = self.ctx.message.group_id
        if not group_id:
            return PluginResponse.fail("只能在群聊中使用此指令")

        duration = max(10, min(duration, 10080))

        messages = await self._fetch_history(group_id, duration)
        if not messages:
            return PluginResponse.fail(f"未能获取到聊天记录（已尝试拉取最近 {duration} 分钟）")

        earliest_ts = min((m.get("time", 0) for m in messages if m.get("time")), default=0)
        earliest_time = (
            datetime.fromtimestamp(earliest_ts, _CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
            if earliest_ts else "未知"
        )
        logger.info(
            "群聊分析 [%s] 获取到 %d 条消息，最早记录时间: %s（分析窗口: %d 分钟）",
            group_id, len(messages), earliest_time, duration,
        )

        end_time = datetime.now(_CHINA_TZ)
        start_time = end_time - timedelta(minutes=duration)
        report = await self._analyze(messages, group_id, start_time, end_time)

        adapter = self.ctx.adapter
        try:
            await self._render_and_send(report, adapter, group_id)
        except RuntimeError:
            text_report = self._text_report(report)
            return PluginResponse.ok(text=text_report, data=report, mood_hint="活泼、惊喜")

        return PluginResponse.ok(
            text=(
                f"📊 群聊分析报告已生成（{report['time_range']}），"
                "来看看大家的精彩表现吧~"
            ),
            data=report,
            mood_hint="活泼、惊喜",
        )

    # ── 引擎工具 ──

    def _get_engine(self) -> Any:
        """获取底层引擎实例。"""
        try:
            return self.ctx.engine.get_engine() if self.ctx.engine else None
        except Exception:
            return None

    @staticmethod
    def _scan_archive_groups(engine: Any) -> list[str]:
        """扫描归档目录，返回所有有归档数据的群 ID 列表。"""
        work_path = getattr(engine, "work_path", None)
        if not work_path:
            return []
        archive_dir = Path(work_path) / "archive"
        if not archive_dir.is_dir():
            return []
        return [
            p.stem for p in archive_dir.glob("*.jsonl")
            if p.stat().st_size > 0
        ]

    # ── 历史消息获取（从引擎归档读取）──

    async def _fetch_history(
        self, group_id: str, duration: int,
    ) -> list[dict[str, Any]]:
        """从引擎归档中获取指定时间范围内的群聊历史消息。

        优先读取 archive/{group_id}.jsonl 归档文件（全量历史），
        回退到 basic_memory 内存窗口（最多 30 条）。
        """
        engine = self._get_engine()
        if engine is None:
            return []

        work_path = getattr(engine, "work_path", None)
        if work_path:
            archive_path = Path(work_path) / "archive" / f"{group_id}.jsonl"
            if archive_path.exists():
                entries = self._read_archive_file(archive_path)
                return self._filter_by_duration(entries, duration)

        return self._read_memory_window(engine, group_id, duration)

    def _read_archive_file(self, archive_path: Path) -> list[dict[str, Any]]:
        """从 JSONL 归档文件读取并规范化消息。"""
        messages: list[dict[str, Any]] = []
        try:
            lines = archive_path.read_text(encoding="utf-8").splitlines()
            for line in lines[-_MAX_ARCHIVE_LINES:]:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                normalized = self._normalize_entry(entry)
                if normalized:
                    messages.append(normalized)
        except Exception as exc:
            logger.warning("读取归档文件失败 [%s]: %s", archive_path.name, exc)

        return messages

    def _read_memory_window(
        self, engine: Any, group_id: str, duration: int,
    ) -> list[dict[str, Any]]:
        """从 basic_memory 内存窗口获取消息（回退方案）。"""
        try:
            entries = engine.basic_memory.get_all(group_id)
            messages = []
            for e in entries:
                normalized = self._normalize_memory_entry(e)
                if normalized:
                    messages.append(normalized)
            return self._filter_by_duration(messages, duration)
        except Exception as exc:
            logger.warning("读取内存窗口失败 [%s]: %s", group_id, exc)
            return []

    @staticmethod
    def _resolve_user_id(entry: dict[str, Any]) -> str:
        """从归档条目中提取平台用户 ID（QQ 号）。

        优先使用 channel_user_id（平台原始 ID），回退到 user_id。
        engine 的 user_id 可能是内部 UUID，不是 QQ 号。
        """
        return entry.get("channel_user_id", "") or entry.get("user_id", "")

    @staticmethod
    def _resolve_user_id_from_obj(entry: Any) -> str:
        """从 BasicMemoryEntry 对象中提取平台用户 ID。"""
        return getattr(entry, "channel_user_id", "") or getattr(entry, "user_id", "")

    @staticmethod
    def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
        """将 JSONL 归档条目规范化为分析器可用的消息格式。"""
        ts = ChatAnalyzerPlugin._parse_iso_timestamp(entry.get("timestamp", ""))
        if not ts:
            return None

        return {
            "user_id": ChatAnalyzerPlugin._resolve_user_id(entry),
            "content": entry.get("content", ""),
            "time": ts,
            "speaker_name": entry.get("speaker_name", ""),
            "role": entry.get("role", ""),
            "multimodal_inputs": entry.get("multimodal_inputs", []),
        }

    @staticmethod
    def _normalize_memory_entry(entry: Any) -> dict[str, Any] | None:
        """将 BasicMemoryEntry 对象规范化为分析器可用的消息格式。"""
        ts_str = getattr(entry, "timestamp", "")
        ts = ChatAnalyzerPlugin._parse_iso_timestamp(ts_str)
        if not ts:
            return None

        return {
            "user_id": ChatAnalyzerPlugin._resolve_user_id_from_obj(entry),
            "content": getattr(entry, "content", ""),
            "time": ts,
            "speaker_name": getattr(entry, "speaker_name", ""),
            "role": getattr(entry, "role", ""),
            "multimodal_inputs": getattr(entry, "multimodal_inputs", []),
        }

    @staticmethod
    def _parse_iso_timestamp(ts_str: str) -> int:
        """解析 ISO 8601 时间戳为 unix 秒。支持带/不带时区。"""
        if not ts_str:
            return 0
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_CHINA_TZ)
            return int(dt.timestamp())
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _filter_by_duration(
        messages: list[dict[str, Any]], duration: int,
    ) -> list[dict[str, Any]]:
        """按时间范围过滤消息并排序。"""
        cutoff = int(datetime.now(_CHINA_TZ).timestamp()) - duration * 60
        filtered = [m for m in messages if m.get("time", 0) >= cutoff]
        filtered.sort(key=lambda m: m.get("time", 0))
        return filtered

    # ── 昵称解析 ──

    def _build_uid_to_name(self, messages: list[dict[str, Any]]) -> dict[str, str]:
        """从消息列表中构建 uid → 昵称 映射。"""
        mapping: dict[str, str] = {}
        for msg in messages:
            uid = str(msg.get("user_id", ""))
            name = msg.get("speaker_name", "")
            if uid and name and uid not in mapping:
                mapping[uid] = name
        return mapping

    async def _resolve_nickname(
        self, group_id: str, user_id: str, adapter: Any,
    ) -> str:
        """回退：通过 adapter 获取用户昵称。"""
        try:
            info = await adapter.get_group_member_info(group_id, user_id)
            return info.get("card") or info.get("nickname", "")
        except Exception:
            return ""

    # ── 分析引擎 ──

    async def _analyze(
        self,
        messages: list[dict[str, Any]],
        group_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        """执行多维度分析。"""
        user_analyzers = [
            ActiveSender(),
            WordCount(),
            ImageSender(),
        ]
        night_owl = NightOwlIndex()
        hourly_analyzer = HourlyActivity()
        topic_tracker = TopicTracker()
        event_tracker = EventChainTracker()
        echo_tracker = EchoTracker()

        all_analyzers = [*user_analyzers, hourly_analyzer, night_owl]
        for msg in messages:
            for a in all_analyzers:
                a.process(msg)
            topic_tracker.process(msg)
            event_tracker.process(msg)
            echo_tracker.process(msg)

        event_tracker.finalize()

        uid_to_name = self._build_uid_to_name(messages)

        all_uids: set[str] = set()
        for a in user_analyzers:
            for uid, _ in a.top(10):
                all_uids.add(uid)

        top_events = event_tracker.top_chains(3)
        for event in top_events:
            for uid in event.get("participant_uids", []):
                all_uids.add(str(uid))

        adapter = self.ctx.adapter
        self_uid = str(getattr(adapter, "self_id", "") or "")
        if self_uid:
            all_uids.discard(self_uid)

        missing_uids = all_uids - set(uid_to_name.keys())
        for uid in missing_uids:
            name = await self._resolve_nickname(group_id, uid, adapter)
            uid_to_name[uid] = name or f"qq_{uid}"

        rankings: dict[str, list[tuple[str, str, int]]] = {}
        for a in user_analyzers:
            entries = [(uid, uid_to_name.get(uid, f"qq_{uid}"), count) for uid, count in a.top(5)]
            rankings[a.name] = entries

        hourly = hourly_analyzer.hourly_data(start_time.hour, end_time.hour)
        hourly_top_users = hourly_analyzer.hourly_top_users(uid_to_name)

        for event in top_events:
            for msg in event.get("sample_messages", []):
                uid = msg.get("uid", "")
                msg["nickname"] = uid_to_name.get(uid, msg.get("nickname", f"qq_{uid}"))
            for msg in event.get("raw_messages", []):
                uid = msg.get("user_id", "")
                msg["nickname"] = uid_to_name.get(uid, msg.get("nickname", f"qq_{uid}"))

        await self._analyze_event_chains(top_events, uid_to_name, group_id)

        commentary = await self._generate_commentary(
            topic_tracker, rankings, messages, start_time, end_time,
            night_owl, uid_to_name, top_events, group_id,
        )

        top_echoes = echo_tracker.top_echoes(5)

        return {
            "group_id": group_id,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "time_range": (
                f"{start_time.strftime('%m/%d %H:%M')} — "
                f"{end_time.strftime('%m/%d %H:%M')}"
            ),
            "message_count": len(messages),
            "rankings": {
                name: [{"uid": e[0], "name": e[1], "count": e[2]} for e in entries]
                for name, entries in rankings.items()
            },
            "hourly": [{"hour": h, "count": c} for h, c in hourly],
            "hourly_top_users": {
                str(h): {"uid": uid, "name": name}
                for h, (uid, name, _) in hourly_top_users.items()
            },
            "self_uid": self_uid,
            "uid_to_name": uid_to_name,
            "top_events": top_events,
            "top_echoes": top_echoes,
            "topic_words": [{"word": w, "count": c} for w, c in topic_tracker.top_words(15)],
            "commentary": commentary,
        }

    # ── HTML 渲染 → 发送图片 ──

    async def _render_and_send(
        self, report: dict[str, Any], adapter: Any, group_id: str,
    ) -> str:
        start_time = datetime.fromisoformat(report["start_time"])
        end_time = datetime.fromisoformat(report["end_time"])

        rankings = {
            name: [(e["uid"], e["name"], e["count"]) for e in entries]
            for name, entries in report["rankings"].items()
        }
        hourly = [(h["hour"], h["count"]) for h in report["hourly"]]
        hourly_top = report.get("hourly_top_users", {})
        top_echoes = report.get("top_echoes", [])
        uid_to_name = report.get("uid_to_name", {})
        commentary = report.get("commentary", "")

        group_name = group_id
        try:
            info = await adapter.get_group_info(group_id)
            group_name = info.get("group_name", group_id)
        except Exception:
            pass

        html = render_report_html(
            group_name=group_name,
            group_id=group_id,
            start_time=start_time,
            end_time=end_time,
            rankings=rankings,
            hourly_data=hourly,
            hourly_top_users=hourly_top,
            top_echoes=top_echoes,
            uid_to_name=uid_to_name,
            commentary=commentary,
            plugin_version=self._plugin_version,
            self_uid=report.get("self_uid", ""),
            top_events=report.get("top_events", []),
        )

        png_bytes = await html_to_png(html)
        img_base64 = base64.b64encode(png_bytes).decode()

        from sirius_pulse.adapters.models import ImageSegment, MessageGroup

        await adapter.send_group_message(
            group_id,
            MessageGroup([ImageSegment(file_path=f"base64://{img_base64}")]),
        )
        return img_base64

    # ── 文本报告回退 ──

    def _text_report(self, report: dict[str, Any]) -> str:
        lines: list[str] = [
            f"📊 群聊分析报告 ({report['time_range']})",
            f"总消息数：{report['message_count']} 条",
            "",
        ]
        for name, entries in report["rankings"].items():
            if not entries:
                continue
            lines.append(f"🏆 {name}：")
            for e in entries[:3]:
                lines.append(f"  {e['name']}: {e['count']} 条")
            lines.append("")
        if report.get("commentary"):
            lines.append(f"📝 群聊总结：{report['commentary']}")
        return "\n".join(lines)

    # ── LLM 事件链分析 ──

    async def _analyze_event_chains(
        self,
        top_events: list[dict[str, Any]],
        uid_to_name: dict[str, str],
        group_id: str,
    ) -> None:
        """用分析小模型对每个事件链做语义分析。"""
        if not top_events:
            return

        async def _analyze_one(event: dict[str, Any]) -> None:
            try:
                result = await self._analyze_single_event_chain(event, uid_to_name, group_id)
                if result:
                    event["llm_title"] = result.get("title", "")
                    event["llm_tags"] = result.get("tags", [])
                    event["llm_flow"] = result.get("flow", "")
            except Exception as exc:
                logger.warning("事件链 #%d LLM 分析失败: %s", event.get("rank", 0), exc)

        await asyncio.gather(*[_analyze_one(e) for e in top_events])

    async def _analyze_single_event_chain(
        self,
        event: dict[str, Any],
        uid_to_name: dict[str, str],
        group_id: str,
    ) -> dict[str, Any] | None:
        """对单个事件链调用分析小模型。"""
        participant_uids = event.get("participant_uids", [])
        participant_lines = []
        for uid in participant_uids:
            name = uid_to_name.get(str(uid), f"qq_{uid}")
            participant_lines.append(f"  {uid} | {name}")
        participant_text = "\n".join(participant_lines)

        raw_msgs = event.get("raw_messages", [])
        if raw_msgs:
            dialogue_lines = []
            for msg in raw_msgs:
                uid = str(msg.get("user_id", ""))
                name = uid_to_name.get(uid, msg.get("nickname", f"qq_{uid}"))
                text = msg.get("content", "")
                if text:
                    dialogue_lines.append(f"[{name}({uid})]: {text}")
            dialogue_text = "\n".join(dialogue_lines)
        else:
            dialogue_lines = []
            for msg in event.get("sample_messages", []):
                uid = msg.get("uid", "")
                name = uid_to_name.get(uid, msg.get("nickname", f"qq_{uid}"))
                text = msg.get("text", "")
                dialogue_lines.append(f"[{name}({uid})]: {text}")
            dialogue_text = "\n".join(dialogue_lines)

        if not dialogue_text.strip():
            return None

        names_hint = "、".join(
            f"{uid}({uid_to_name.get(str(uid), f'qq_{uid}')})"
            for uid in participant_uids[:10]
        )

        prompt = f"""\
分析以下群聊事件链的对话内容，给出一个标题、若干标签、和一段简短的事件流程描述。
【可用的参与者】{names_hint}

【事件链对话（按时间顺序）】{dialogue_text}

【安全约束】- 输出内容必须完全安全、积极、无害，不得使用任何政治敏感、色情、暴力、违法或不当内容
- 使用中性、正面的语言进行概括
- 标签只使用日常生活类词汇（如：游戏、美食、学习、工作、旅行、运动、娱乐、影视、音乐、技术等）
【输出要求】严格输出 JSON，不要包含任何 XML 标签：{{
  "title": "一句话事件标题（20字以内，安全正面）",
  "tags": ["标签1", "标签2", "标签3"],
  "flow": "一段50-80字的事件流程描述，自然叙述发生了什么。提到群友时必须用尖括号包住QQ号标记，例如：<12388389247> 分享了一个有趣的话题，后来 <123456789> 也加入了讨论"
}}

只输出 JSON，不要其他内容。JSON 字符串内不要使用双引号（用单引号描述），不要使用任何 XML 标签。"""

        try:
            raw = await self.ctx.engine.generate_text_analysis(prompt, group_id=group_id)
            if not raw:
                return None

            cleaned = raw.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0]
            result = self._parse_event_json(cleaned)
            if result:
                flow = result.get("flow", "")
                if flow:
                    result["flow"] = self._expand_mentions(flow, uid_to_name)
                return result
            logger.warning("事件链 LLM 分析 JSON 解析失败，raw 前200字: %s", raw[:200])
            return None
        except Exception as exc:
            err_str = str(exc)
            if "data_inspection" in err_str or "inappropriate" in err_str:
                logger.info("事件链 LLM 被内容审核拦截，降级为元数据摘要")
                return await self._analyze_event_chain_fallback(event, uid_to_name, group_id)
            logger.warning("事件链 LLM 分析失败: %s", exc)
            return None

    async def _analyze_event_chain_fallback(
        self,
        event: dict[str, Any],
        uid_to_name: dict[str, str],
        group_id: str,
    ) -> dict[str, Any] | None:
        """内容审核拦截后的降级方案。"""
        keywords = event.get("topic_keywords", [])
        topic_label = event.get("topic_label", "") or "群聊讨论"
        msg_count = event["message_count"]
        participant_count = event["participant_count"]

        participant_uids = event.get("participant_uids", [])
        names_hint = "、".join(
            f"{uid}({uid_to_name.get(str(uid), f'qq_{uid}')})"
            for uid in participant_uids[:10]
        )

        keywords_str = "、".join(keywords[:5]) if keywords else topic_label
        time_range = event["time_range"]

        prompt = f"""\
请根据以下群聊事件链的元数据，生成一个标题和简短描述。
【基本信息】时间：{time_range}
消息数：{msg_count}条 参与人数：{participant_count}人 高频词：{keywords_str}

【可用的参与者】{names_hint}

【输出要求】严格输出 JSON，不要包含任何 XML 标签：{{
  "title": "一句话事件标题（20字以内，安全正面）",
  "tags": ["标签1", "标签2"],
  "flow": "一段不高于200字的事件概述。提到群友时必须且只能用尖括号包住QQ号标记，例如：<12388389247>，不得在标记中添加除QQ号以外的任何内容"
}}
只输出 JSON，不要其他内容。JSON 字符串内不要使用双引号，不要使用任何 XML 标签。"""

        try:
            raw = await self.ctx.engine.generate_text_analysis(prompt, group_id=group_id)
            if raw:
                cleaned = raw.strip()
                if "```json" in cleaned:
                    cleaned = cleaned.split("```json")[1].split("```")[0]
                elif "```" in cleaned:
                    cleaned = cleaned.split("```")[1].split("```")[0]
                result = self._parse_event_json(cleaned)
                if result:
                    flow = result.get("flow", "")
                    if flow:
                        result["flow"] = self._expand_mentions(flow, uid_to_name)
                    return result
        except Exception as exc:
            logger.warning("事件链降级分析也失败: %s", exc)
        return None

    @staticmethod
    def _parse_event_json(raw: str) -> dict[str, Any] | None:
        """尝试多种方式解析 LLM 输出的 JSON。"""
        try:
            return json.loads(raw)
        except Exception:
            pass

        try:
            fixed = re.sub(r",\s*([}\]])", r"\1", raw)
            return json.loads(fixed)
        except Exception:
            pass

        try:
            result: dict[str, Any] = {}

            title_m = re.search(r'"title"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', raw)
            if title_m:
                result["title"] = title_m.group(1)

            tags_m = re.search(r'"tags"\s*:\s*\[(.*?)\]', raw, re.DOTALL)
            if tags_m:
                tag_strs = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', tags_m.group(1))
                result["tags"] = [t.strip() for t in tag_strs if t.strip()]

            flow_m = re.search(r'"flow"\s*:\s*"(.+)"(?:\s*\})', raw, re.DOTALL)
            if not flow_m:
                flow_m = re.search(r'"flow"\s*:\s*"(.+?)"(?:\s*[,}])', raw, re.DOTALL)
            if flow_m:
                flow = flow_m.group(1).replace('\\"', '"').replace('\\n', '\n')
                result["flow"] = flow

            if result.get("title") or result.get("flow"):
                result.setdefault("title", "群聊讨论")
                result.setdefault("tags", [])
                result.setdefault("flow", "")
                return result
        except Exception:
            pass

        return None

    @staticmethod
    def _expand_mentions(text: str, uid_to_name: dict[str, str]) -> str:
        """将 LLM 输出的 <QQ号> 尖括号标记替换为 <user> 标签。"""
        if not text:
            return text

        def _replace_mention(m: re.Match[str]) -> str:
            uid = m.group(1)
            if uid.isdigit() and 5 <= len(uid) <= 11:
                name = uid_to_name.get(uid, f"qq_{uid}")
                return f'<user uid="{uid}" name="{name}">{name}</user>'
            return m.group(0)

        return re.sub(r"<(\d{5,11})>", _replace_mention, text)

    # ── LLM 总结生成 ──

    async def _generate_commentary(
        self,
        tracker: TopicTracker,
        rankings: dict[str, list[tuple[str, str, int]]],
        messages: list[dict[str, Any]],
        start_time: datetime,
        end_time: datetime,
        night_owl: NightOwlIndex,
        uid_to_name: dict[str, str],
        top_events: list[dict[str, Any]],
        group_id: str,
    ) -> str:
        participant_map: dict[str, str] = {}
        for entries in rankings.values():
            for uid, name, _count in entries:
                if uid and uid not in participant_map:
                    participant_map[uid] = name
        participant_lines = "\n".join(
            f"  {uid} | {name}" for uid, name in participant_map.items()
        )

        top_words = tracker.top_words(30)
        word_list = "、".join(f"{w}({c}次)" for w, c in top_words[:15])

        active_rank = rankings.get("话痨之王", [])
        active_summary = "、".join(f"{name}({count}条)" for _, name, count in active_rank[:5])

        heatmap = tracker.topic_heatmap()
        heatmap_lines: list[str] = []
        for hour, words in heatmap.items():
            wl = "、".join(f"{w}({c})" for w, c in words)
            heatmap_lines.append(f"  {hour:02d}:00 — {wl}")
        heatmap_text = "\n".join(heatmap_lines[:12])

        night_owl_lines: list[str] = []
        for uid, ratio in night_owl.night_owl_ratio()[:5]:
            name = uid_to_name.get(uid, f"qq_{uid}")
            night_owl_lines.append(f"  {name}: {ratio:.0f}%")
        night_owl_text = "\n".join(night_owl_lines) if night_owl_lines else "（暂无深夜发言数据）"

        sample_msgs: list[dict[str, Any]] = []
        seen_uids: set[str] = set()
        for m in messages:
            uid = str(m.get("user_id", ""))
            if uid not in seen_uids:
                text = m.get("content", "")
                if len(text) >= 6:
                    name = m.get("speaker_name", "")
                    sample_msgs.append({"nickname": name, "text": text[:80]})
                    seen_uids.add(uid)
            if len(sample_msgs) >= 8:
                break
        sample_text = "\n".join(f"  [{m['nickname']}]: {m['text']}" for m in sample_msgs)

        engine = self._get_engine()
        persona = getattr(engine, 'persona', None) if engine else None
        persona_name = getattr(persona, 'name', '') or '我'

        persona_prompt = ""
        if persona and hasattr(persona, 'build_system_prompt'):
            try:
                persona_prompt = persona.build_system_prompt()
            except Exception:
                pass

        prompt_parts: list[str] = []

        if persona_prompt:
            prompt_parts.append(persona_prompt.strip())
        else:
            prompt_parts.append(f"你的名字是【{persona_name}】，你是这个群聊的 AI 成员。")

        event_chain_lines: list[str] = []
        for event in top_events[:3]:
            event_title = event.get("llm_title", "")
            if not event_title:
                topic_kw = event.get("topic_keywords", [])
                event_title = "、".join(topic_kw[:3]) if topic_kw else event.get("topic_label", "群聊讨论")
            event_chain_lines.append(
                f"  [{event['time_range']}] {event_title} "
                f"({event['message_count']}条消息 {event['participant_count']}人)"
            )
        event_chain_text = "\n".join(event_chain_lines) if event_chain_lines else "（暂无）"

        prompt_parts.append(f"""\
【群聊数据总结】时间段：{start_time.strftime('%Y-%m-%d %H:%M')} 至 {end_time.strftime('%Y-%m-%d %H:%M')}
总消息数：{len(messages)} 条
【参与者列表（QQ号 | 群昵称）】{participant_lines or '（暂无数据）'}

【活跃用户排名】{active_summary or '（暂无数据）'}

【高频关键词】{word_list}

【话题热力图】{heatmap_text}

【夜猫子指数（深夜0-6点发言占比，只列出TOP5）】{night_owl_text}

【热门事件链（按讨论热度排序）】{event_chain_text}

【代表性发言】{sample_text}

【任务】请你以自然轻松的群友口吻，对这段时间的群聊做一个总结（200-400 字）。要求：1. 像朋友闲聊一样自然地回顾群里发生了什么 2. 提到 1-2 个具体的话题或有趣瞬间，可以顺便 cue 一下参与的群友 3. 带一点轻松调侃或温馨感，不要用"以上数据显示"这类学术腔 4. 语气要符合你的人格设定 5. 【重要- 用户标记格式】当你提到某个群友时，必须且只能用以下格式标记：
   <user uid="QQ号" name="群昵称">显示名称</user>
   例如：<user uid="123456789" name="小明">小明</user>今天分享了不少有趣的东西
   请务必使用上面【参与者列表】中提供的 QQ 号和昵称
6. 【严禁- XML 标签约束】你的输出中绝对禁止出现除 <user> 之外的任何 XML/HTML 标签：
   - 禁止使用群友名字作为标签名，例如 <yuki>、<小明>、<小张></小张> 等都是非法的
   - 禁止使用 <b>、<i>、<p>、<br>、<div> 等任何 HTML 标签
   - 禁止使用自创的任何尖括号标签
   - 只有 <user uid="数字QQ号" name="群昵称">显示名</user> 是唯一允许的标签格式
   - 如果你不确定某个名字对应的 QQ 号，就直接用纯文字写名字，不要用任何标签""")

        prompt = "\n\n".join(prompt_parts)

        try:
            result = await self.ctx.engine.generate_text(prompt)
            if result:
                commentary = result.strip()
                commentary = self._sanitize_commentary(commentary, participant_map)
                return commentary
        except Exception as exc:
            logger.warning("LLM 总结生成失败: %s", exc)

        return ""

    @staticmethod
    def _sanitize_commentary(text: str, participant_map: dict[str, str]) -> str:
        """清洗 LLM 输出中的非法 XML 标签，只保留合法的 <user> 标签。"""
        _USER_TAG_RE = re.compile(
            r'<user\s+uid="(\d+)"\s+name="([^"]*)"\s*>(.*?)</user>',
            re.DOTALL,
        )
        placeholders: dict[str, str] = {}
        counter = 0

        def _protect(m: re.Match[str]) -> str:
            nonlocal counter
            key = f"__USER_TAG_PLACEHOLDER_{counter}__"
            placeholders[key] = m.group(0)
            counter += 1
            return key

        protected = _USER_TAG_RE.sub(_protect, text)

        _ILLEGAL_TAG_RE = re.compile(r'</?[a-zA-Z\u4e00-\u9fa5][^>]*/?>')
        sanitized = _ILLEGAL_TAG_RE.sub(
            lambda m: m.group(0).replace("<", "&lt;").replace(">", "&gt;"),
            protected,
        )

        for key, value in placeholders.items():
            sanitized = sanitized.replace(key, value)

        return sanitized
