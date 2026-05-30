"""HTML 模板渲染 — 读取模板文件并替换占位符生成完整 HTML + PNG。"""

from __future__ import annotations

import asyncio
import html as _html_module
import logging
import re as _re_module
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent


def _load_template() -> str:
    """加载 HTML 模板文件。"""
    template_path = _TEMPLATE_DIR / "template.html"
    if not template_path.exists():
        raise FileNotFoundError(f"模板文件不存在: {template_path}")
    return template_path.read_text(encoding="utf-8")


def _replace(template: str, **kwargs: str) -> str:
    """将模板中的 {{key}} 替换为对应值。"""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{{" + key + "}}", value)
    return result


# ═══════════════════════════════════════════════════════════════════════
# HTML 片段生成
# ═══════════════════════════════════════════════════════════════════════


def _build_rank_card(
    index: int,
    uid: str,
    name: str,
    count: int,
    unit: str,
    self_uid: str,
) -> str:
    """生成单个排名字卡 HTML。"""
    rank_classes = ["gold", "silver", "bronze", "", ""]
    emojis = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    rc = rank_classes[index]
    emoji_or_rank = emojis[index]

    if uid == self_uid and self_uid:
        avatar_url = f"http://q.qlogo.cn/headimg_dl?dst_uin={self_uid}&spec=640&img_type=jpg"
        avatar_html = f'<img class="rank-avatar" src="{avatar_url}" alt="头像">'
    elif uid.isdigit():
        avatar_url = f"http://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=jpg"
        avatar_html = f'<img class="rank-avatar" src="{avatar_url}" alt="头像">'
    else:
        avatar_url = "https://q1.qlogo.cn/g?b=qq&nk=10000&s=640"
        avatar_html = f'<img class="rank-avatar" src="{avatar_url}" alt="默认头像">'

    return f"""\
            <div class="rank-card {rc}">
              <div class="rank-num {rc}">{emoji_or_rank}</div>
              {avatar_html}
              <div class="rank-name" title="{name}">{name}</div>
              <div class="rank-count">{count} {unit}</div>
            </div>"""


def _build_others_item(
    index: int,
    uid: str,
    name: str,
    count: int,
    unit: str,
    self_uid: str,
) -> str:
    """生成单个列表项 HTML。"""
    if uid == self_uid and self_uid:
        avatar_url = f"http://q.qlogo.cn/headimg_dl?dst_uin={self_uid}&spec=640&img_type=jpg"
        avatar_html = f'<img class="others-avatar" src="{avatar_url}" alt="头像">'
    elif uid.isdigit():
        avatar_url = f"http://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=jpg"
        avatar_html = f'<img class="others-avatar" src="{avatar_url}" alt="头像">'
    else:
        avatar_url = "https://q1.qlogo.cn/g?b=qq&nk=10000&s=640"
        avatar_html = f'<img class="others-avatar" src="{avatar_url}" alt="默认头像">'

    return f"""\
            <div class="others-item">
              <span class="rank">#{index + 1}</span>
              {avatar_html}
              <span class="name">{name}</span>
              <span class="count">{count} {unit}</span>
            </div>"""


def build_rankings_html(
    rankings: dict[str, list[tuple[str, str, int]]],
    self_uid: str = "",
) -> str:
    """根据排名数据生成排名字卡 HTML 片段。"""
    sections: list[str] = []

    _UNITS: dict[str, str] = {
        "话痨之王": "条",
        "长文写手": "字",
        "图片分享达人": "张",
    }

    for analyzer_name, entries in rankings.items():
        unit = _UNITS.get(analyzer_name, "条")

        top_three: list[str] = []
        others: list[str] = []

        for i in range(5):
            if i < len(entries):
                uid, name, count = entries[i]
            else:
                uid, name, count = "", "虚位以待", 0

            if i < 3:
                top_three.append(
                    _build_rank_card(i, uid, name, count, unit, self_uid)
                )
            else:
                others.append(
                    _build_others_item(i, uid, name, count, unit, self_uid)
                )

        top_three_html = f'<div class="top-three">{"".join(top_three)}</div>'
        others_html = f'<div class="others-list">{"".join(others)}</div>'

        sections.append(
            f"""\
        <div class="section">
          <h2>📊 {analyzer_name}</h2>
          <div class="ranking">
            {top_three_html}
            {others_html}
          </div>
        </div>"""
        )

    if not sections:
        sections.append(
            """\
        <div class="section">
          <h2>📊 暂无数据</h2>
          <div class="ranking">
            <div class="top-three">
              <div class="rank-card" style="max-width:100%;">
                <div class="rank-avatar rank-avatar-default">🍃</div>
                <div class="rank-name">该时段暂无聊天记录</div>
              </div>
            </div>
          </div>
        </div>"""
        )
    return "\n".join(sections)


def build_hourly_section(
    hourly_data: list[tuple[int, int]],
    hourly_top_users: dict[str, dict[str, str]] | None = None,
    self_uid: str = "",
) -> tuple[str, str, str]:
    """生成时段活跃度色条 HTML + 标签 + 每时段最活跃用户头像。"""
    if not hourly_data:
        return "", "", ""

    max_hourly = max(c for _, c in hourly_data) if hourly_data else 1

    bars: list[str] = []
    peeps: list[str] = []
    top_users = hourly_top_users or {}
    for hour, count in hourly_data:
        ratio = count / max_hourly if max_hourly > 0 else 0
        if ratio >= 0.8:
            color = "#00E5FF"
        elif ratio >= 0.6:
            color = "#00B8D4"
        elif ratio >= 0.4:
            color = "#0097A7"
        elif ratio >= 0.2:
            color = "#006978"
        elif count > 0:
            color = "#1a3a4a"
        else:
            color = "#0d1a26"
        width_pct = 100 / len(hourly_data)
        bars.append(
            f'<div class="hourly-col" style="width:{width_pct}%;background:{color}"'
            f' title="{hour:02d}:00 — {count}条"></div>'
        )

        top_info = top_users.get(str(hour), {})
        top_uid = top_info.get("uid", "")
        top_name = top_info.get("name", "")
        if top_uid and top_name:
            if top_uid == self_uid and self_uid:
                avatar_url = f"http://q.qlogo.cn/headimg_dl?dst_uin={self_uid}&spec=640&img_type=jpg"
            elif top_uid.isdigit():
                avatar_url = f"http://q.qlogo.cn/headimg_dl?dst_uin={top_uid}&spec=640&img_type=jpg"
            else:
                avatar_url = "https://q1.qlogo.cn/g?b=qq&nk=10000&s=640"
            peeps.append(
                f'<div class="hourly-peep" style="width:{width_pct}%" title="{hour:02d}:00 最活跃: {top_name}">'
                f'<img class="hourly-peep-avatar" src="{avatar_url}" alt="{top_name}">'
                f'<span class="hourly-peep-name">{top_name}</span>'
                f"</div>"
            )
        else:
            peeps.append(f'<div class="hourly-peep" style="width:{width_pct}%"></div>')

    label_indices = set()
    for i, (hour, _) in enumerate(hourly_data):
        if i == 0 or hour % 3 == 0:
            label_indices.add(i)
    labels = "".join(
        f"<span>{hour:02d}</span>" if i in label_indices else "<span></span>"
        for i, (hour, _) in enumerate(hourly_data)
    )

    return "".join(bars), labels, "".join(peeps)


_USER_TAG_RE = _re_module.compile(
    r"<user\s+uid=\"([^\"]*)\"\s+name=\"([^\"]*)\"\s*>(.*?)</user>"
)

_HTML_TAG_RE = _re_module.compile(
    r"<(/?)(\w+)([^>]*)>"
)


def _escape_except_tags(text: str, safe_tags: set[str]) -> str:
    """对文本做 HTML 转义，但保留指定标签族不被转义。"""
    parts: list[str] = []
    cursor = 0

    for m in _HTML_TAG_RE.finditer(text):
        tag_start = m.start()
        tag_name = m.group(2)
        if cursor < tag_start:
            parts.append(_html_module.escape(text[cursor:tag_start], quote=False))
        if tag_name in safe_tags:
            parts.append(m.group(0))
        else:
            parts.append(_html_module.escape(m.group(0), quote=False))
        cursor = m.end()

    if cursor < len(text):
        parts.append(_html_module.escape(text[cursor:], quote=False))

    return "".join(parts)


def _render_user_tags_in_text(text: str) -> str:
    """将文本中的 <user uid="QQ" name="昵称">文本</user> 替换为内嵌头像卡片。"""
    def _render_tag(match: _re_module.Match[str]) -> str:
        uid = match.group(1)
        name = match.group(2)
        display_text = match.group(3)

        if uid and uid.isdigit() and len(uid) >= 5:
            avatar_url = f"http://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=jpg"
        else:
            avatar_url = "https://q1.qlogo.cn/g?b=qq&nk=10000&s=640"

        safe_display = _html_module.escape(display_text, quote=False)

        return (
            f'<span class="inline-user-card" title="QQ: {uid}">'
            f'<img class="inline-avatar" src="{avatar_url}" alt="{safe_display}">'
            f'<span class="inline-name">{safe_display}</span>'
            f"</span>"
        )

    result = _USER_TAG_RE.sub(_render_tag, text)
    return _escape_except_tags(result, {"span", "img", "br"})


def build_commentary_html(commentary: str) -> str:
    """生成群聊总结区 HTML 片段。"""
    if not commentary:
        return ""
    return _render_user_tags_in_text(commentary)


def build_events_html(top_events: list[dict[str, Any]], self_uid: str = "") -> str:
    """生成事件链 HTML 片段。"""
    if not top_events:
        return """\
        <div class="section">
          <h2>📝 事件链</h2>
          <div class="events-container empty">暂未分析到事件...</div>
        </div>"""

    rank_labels = ["TOP 1", "TOP 2", "TOP 3"]

    event_cards: list[str] = []
    for event in top_events:
        rank_idx = event["rank"] - 1
        rank_label = rank_labels[rank_idx] if rank_idx < len(rank_labels) else f"话题 #{event['rank']}"

        llm_title = event.get("llm_title", "")
        llm_tags = event.get("llm_tags", [])
        llm_flow = event.get("llm_flow", "")

        if not llm_title:
            llm_title = event.get("topic_label", "") or "群聊讨论"

        if llm_tags:
            tags_html = "".join(
                f'<span class="event-tag">{_html_module.escape(str(t), quote=False)}</span>'
                for t in llm_tags[:5]
            )
        else:
            topic_kw = event.get("topic_keywords", [])
            if topic_kw:
                tags_html = "".join(
                    f'<span class="event-tag">{_html_module.escape(str(t), quote=False)}</span>'
                    for t in topic_kw[:3]
                )
            else:
                tags_html = ""

        if llm_flow:
            flow_html = _render_user_tags_in_text(llm_flow)
        else:
            sample_msgs_html = ""
            for msg in event.get("sample_messages", [])[:2]:
                uid = msg.get("uid", "")
                nickname = _html_module.escape(msg.get("nickname", "未知"), quote=False)
                text = _html_module.escape(msg.get("text", ""), quote=False)
                if uid and uid.isdigit() and len(uid) >= 5:
                    avatar = f'<img src="http://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=jpg" class="event-msg-avatar">'
                else:
                    avatar = '<img src="https://q1.qlogo.cn/g?b=qq&nk=10000&s=640" class="event-msg-avatar">'
                sample_msgs_html += f"""\
            <div class="event-msg">
              {avatar}
              <div class="event-msg-content">
                <span class="event-msg-nick">{nickname}</span>
                <span class="event-msg-text">{text}</span>
              </div>
            </div>"""
            flow_html = f'<div class="event-samples">{sample_msgs_html}</div>'

        event_cards.append(f"""\
        <div class="event-card">
          <div class="event-header">
            <span class="event-rank">{rank_label}</span>
            <span class="event-title">{_html_module.escape(llm_title, quote=False)}</span>
          </div>
          <div class="event-meta-line">
            <span>⏰ {event["time_range"]}</span>
            <span>💬 {event["message_count"]}条消息</span>
            <span>👥 {event["participant_count"]}人参与</span>
          </div>
          {f'<div class="event-tags">{tags_html}</div>' if tags_html else ''}
          {f'<div class="event-flow">{flow_html}</div>' if llm_flow else ''}
        </div>""")

    return f"""\
        <div class="section">
          <h2>📌 热门事件</h2>
          <div class="events-container">{"".join(event_cards)}</div>
        </div>"""


def build_echoes_html(
    top_echoes: list[dict[str, Any]],
    uid_to_name: dict[str, str] | None = None,
) -> str:
    """生成复读金句 HTML 片段。"""
    if not top_echoes:
        return """\
        <div class="section">
          <h2>🗣️ 复读金句</h2>
          <div class="echoes-container empty">暂未找到金句...</div>
        </div>"""

    name_map = uid_to_name or {}
    cards: list[str] = []
    for i, echo in enumerate(top_echoes):
        text = _html_module.escape(echo["text"], quote=False)
        count = echo["count"]
        uids = echo.get("uids", [])

        avatars_html = ""
        for uid in uids[:5]:
            if uid and uid.isdigit() and len(uid) >= 5:
                avatar_url = f"http://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=jpg"
            else:
                avatar_url = "https://q1.qlogo.cn/g?b=qq&nk=10000&s=640"
            name = name_map.get(uid, f"qq_{uid}")
            avatars_html += (
                f'<div class="echo-avatar-wrap" title="{name}">'
                f'<img class="echo-avatar" src="{avatar_url}" alt="{name}">'
                f"</div>"
            )

        cards.append(f"""\
        <div class="echo-card">
          <div class="echo-rank">#{i + 1}</div>
          <div class="echo-text">「{text}」</div>
          <div class="echo-meta">
            <span class="echo-count">🔥 复读 {count} 次</span>
            <div class="echo-avatars">{avatars_html}</div>
          </div>
        </div>""")

    return f"""\
        <div class="section">
          <h2>🗣️ 复读金句</h2>
          <div class="echoes-container">{"".join(cards)}</div>
        </div>"""


# ═══════════════════════════════════════════════════════════════════════
# 主渲染入口
# ═══════════════════════════════════════════════════════════════════════


def render_report_html(
    group_name: str,
    group_id: str,
    start_time: datetime,
    end_time: datetime,
    rankings: dict[str, list[tuple[str, str, int]]],
    hourly_data: list[tuple[int, int]],
    commentary: str,
    plugin_version: str,
    self_uid: str = "",
    top_events: list[dict[str, Any]] | None = None,
    hourly_top_users: dict[str, dict[str, str]] | None = None,
    top_echoes: list[dict[str, Any]] | None = None,
    uid_to_name: dict[str, str] | None = None,
) -> str:
    """加载模板并替换所有占位符，返回完整 HTML 字符串。"""
    template = _load_template()

    rankings_html = build_rankings_html(rankings, self_uid=self_uid)
    bars_html, labels_html, peeps_html = build_hourly_section(
        hourly_data, hourly_top_users=hourly_top_users, self_uid=self_uid
    )
    commentary_html = build_commentary_html(commentary)
    events_html = build_events_html(top_events or [], self_uid=self_uid)
    echoes_html = build_echoes_html(top_echoes or [], uid_to_name=uid_to_name)

    time_range = f"{start_time.strftime('%m/%d %H:%M')} — {end_time.strftime('%m/%d %H:%M')}"
    generated_at = end_time.strftime("%Y-%m-%d %H:%M")

    return _replace(
        template,
        group_name=group_name,
        group_id=group_id,
        time_range=time_range,
        rankings_html=rankings_html,
        hourly_bars=bars_html,
        hourly_labels=labels_html,
        hourly_peeps=peeps_html,
        commentary_html=commentary_html,
        events_html=events_html,
        echoes_html=echoes_html,
        plugin_version=plugin_version,
        generated_at=generated_at,
    )


async def html_to_png(html: str) -> bytes:
    """将 HTML 渲染为 PNG 字节（playwright headless chromium）。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "需要安装 playwright 才能渲染报告图片: "
            "uv pip install playwright && playwright install chromium"
        )

    REPORT_WIDTH = 1100
    INITIAL_HEIGHT = 3000
    BODY_PADDING = 24
    EXTRA_PADDING = 30

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(
                viewport={"width": REPORT_WIDTH, "height": INITIAL_HEIGHT}
            )
            await page.set_content(html, wait_until="load")
            await asyncio.sleep(1.5)

            content_height = await page.evaluate("""() => {
                const card = document.querySelector('.card');
                if (card) {
                    return card.offsetTop + card.offsetHeight;
                }
                const body = document.body;
                const docEl = document.documentElement;
                return Math.max(
                    body.scrollHeight, body.offsetHeight,
                    docEl.scrollHeight, docEl.offsetHeight,
                    docEl.clientHeight, 0
                );
            }""")

            target_height = max(content_height, 600) + BODY_PADDING + EXTRA_PADDING

            if abs(target_height - INITIAL_HEIGHT) > 100:
                await page.set_viewport_size({"width": REPORT_WIDTH, "height": target_height})
                await asyncio.sleep(0.5)

                content_height = await page.evaluate("""() => {
                    const card = document.querySelector('.card');
                    if (card) {
                        return card.offsetTop + card.offsetHeight;
                    }
                    const body = document.body;
                    const docEl = document.documentElement;
                    return Math.max(
                        body.scrollHeight, body.offsetHeight,
                        docEl.scrollHeight, docEl.offsetHeight,
                        docEl.clientHeight, 0
                    );
                }""")
                target_height = max(content_height, 600) + BODY_PADDING + EXTRA_PADDING
                await page.set_viewport_size({"width": REPORT_WIDTH, "height": target_height})
                await asyncio.sleep(0.3)

            screenshot = await page.screenshot(full_page=True, type="png")
            return screenshot
        except Exception as exc:
            logger.warning("playwright 截图失败: %s", exc)
            raise RuntimeError(f"HTML 渲染失败: {exc}") from exc
        finally:
            await browser.close()
