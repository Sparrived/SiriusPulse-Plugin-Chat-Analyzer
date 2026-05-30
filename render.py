"""HTML 模板渲染 — 新一代数据可视化 + PNG 截图。

设计语言：暗黑琥珀终端风格
  - SVG 速度线图、参与环图
  - 24 小时情感热力图
  - 社交关系图谱
  - 词汇云 + 丰富度排行
"""

from __future__ import annotations

import asyncio
import html as _html_module
import logging
import math
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


def _avatar_url(uid: str) -> str:
    """生成 QQ 头像 URL。"""
    if uid and uid.isdigit() and len(uid) >= 5:
        return f"http://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=jpg"
    return "https://q1.qlogo.cn/g?b=qq&nk=10000&s=640"


# ═══════════════════════════════════════════════════════════════════
# HERO METRICS — 顶部指标卡
# ═══════════════════════════════════════════════════════════════════


def build_hero_metrics_html(
    message_count: int,
    unique_users: int,
    peak_velocity: int,
    avg_response_sec: float,
    sentiment_avg: float,
) -> str:
    """生成顶部 5 个核心指标卡。"""
    # 情感分数转为人类可读标签
    if sentiment_avg > 0.3:
        sent_label = "positive"
        sent_cls = "teal"
    elif sentiment_avg < -0.1:
        sent_label = "negative"
        sent_cls = "coral"
    else:
        sent_label = "neutral"
        sent_cls = ""

    # 响应时间格式化
    if avg_response_sec > 0:
        resp_str = f"{avg_response_sec:.0f}s"
    else:
        resp_str = "--"

    return f"""
    <div class="metric-box">
      <div class="metric-value">{message_count}</div>
      <div class="metric-label">Total Messages</div>
    </div>
    <div class="metric-box">
      <div class="metric-value">{unique_users}</div>
      <div class="metric-label">Participants</div>
    </div>
    <div class="metric-box">
      <div class="metric-value">{peak_velocity}</div>
      <div class="metric-label">Peak / 5min</div>
    </div>
    <div class="metric-box">
      <div class="metric-value">{resp_str}</div>
      <div class="metric-label">Avg Response</div>
    </div>
    <div class="metric-box">
      <div class="metric-value {sent_cls}">{sentiment_avg:+.2f}</div>
      <div class="metric-label">Sentiment</div>
      <div class="metric-sub">{sent_label}</div>
    </div>"""


# ═══════════════════════════════════════════════════════════════════
# VELOCITY LINE — SVG 面积图
# ═══════════════════════════════════════════════════════════════════


def build_velocity_svg_html(
    velocity_series: list[tuple[int, int]],
) -> str:
    """生成消息速度线 SVG 面积图。"""
    if not velocity_series or len(velocity_series) < 2:
        return '<div class="empty-state">暂无速度数据</div>'

    # SVG 参数
    svg_w = 900
    svg_h = 180
    pad_l = 40
    pad_r = 10
    pad_t = 10
    pad_b = 30
    plot_w = svg_w - pad_l - pad_r
    plot_h = svg_h - pad_t - pad_b

    max_count = max(c for _, c in velocity_series) or 1
    n = len(velocity_series)

    # 生成数据点
    points: list[tuple[float, float]] = []
    for i, (ts, count) in enumerate(velocity_series):
        x = pad_l + i * plot_w / max(n - 1, 1)
        y = pad_t + plot_h - (count / max_count) * plot_h
        points.append((x, y))

    # 折线路径
    line_parts = [f"M{points[0][0]:.1f},{points[0][1]:.1f}"]
    for px, py in points[1:]:
        line_parts.append(f"L{px:.1f},{py:.1f}")
    line_path = " ".join(line_parts)

    # 面积填充路径
    area_path = (
        f"{line_path} "
        f"L{points[-1][0]:.1f},{pad_t + plot_h:.1f} "
        f"L{points[0][0]:.1f},{pad_t + plot_h:.1f} Z"
    )

    # 峰值标记
    peak_idx = max(range(n), key=lambda i: velocity_series[i][1])
    peak_x, peak_y = points[peak_idx]
    peak_ts, peak_count = velocity_series[peak_idx]
    peak_time = datetime.fromtimestamp(peak_ts).strftime("%H:%M")

    # 时间标签（每 4 个点显示一个）
    labels_svg: list[str] = []
    for i, (ts, _) in enumerate(velocity_series):
        if i % max(1, n // 6) == 0 or i == n - 1:
            x = points[i][0]
            t_str = datetime.fromtimestamp(ts).strftime("%H:%M")
            labels_svg.append(
                f'<text x="{x:.0f}" y="{pad_t + plot_h + 18}" '
                f'fill="#3f3f46" font-size="9" text-anchor="middle" '
                f'font-family="JetBrains Mono,monospace">{t_str}</text>'
            )

    return f"""
    <svg class="velocity-svg" viewBox="0 0 {svg_w} {svg_h}" preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id="velGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#e8a849" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="#e8a849" stop-opacity="0"/>
        </linearGradient>
        <filter id="velGlow">
          <feGaussianBlur stdDeviation="2" result="blur"/>
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <!-- 网格线 -->
      <line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}"
            stroke="#1f1f28" stroke-width="1"/>
      <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l + plot_w}" y2="{pad_t}"
            stroke="#1f1f28" stroke-width="0.5" stroke-dasharray="4,4"/>
      <!-- 面积 -->
      <path d="{area_path}" fill="url(#velGrad)"/>
      <!-- 折线 -->
      <path d="{line_path}" fill="none" stroke="#e8a849" stroke-width="2" filter="url(#velGlow)"/>
      <!-- 峰值点 -->
      <circle cx="{peak_x:.1f}" cy="{peak_y:.1f}" r="4" fill="#e8a849" filter="url(#velGlow)"/>
      <text x="{peak_x:.1f}" y="{peak_y - 10:.1f}" fill="#e8a849" font-size="10"
            text-anchor="middle" font-family="JetBrains Mono,monospace" font-weight="600">
        {peak_count} @ {peak_time}
      </text>
      <!-- 时间标签 -->
      {"".join(labels_svg)}
    </svg>"""


# ═══════════════════════════════════════════════════════════════════
# LEADERBOARD — 消息排名
# ═══════════════════════════════════════════════════════════════════


def build_leaderboard_html(
    rankings: dict[str, list[tuple[str, str, int]]],
    self_uid: str = "",
) -> str:
    """生成消息排名 HTML（只取第一个分析器的排名）。"""
    if not rankings:
        return '<div class="empty-state">暂无排名数据</div>'

    # 取第一个分析器
    _first_name = next(iter(rankings))
    entries = rankings[_first_name]
    if not entries:
        return '<div class="empty-state">暂无排名数据</div>'

    max_count = entries[0][2] if entries else 1
    rank_classes = ["gold", "silver", "bronze", "normal", "normal"]

    rows: list[str] = []
    for i, (uid, name, count) in enumerate(entries[:5]):
        rc = rank_classes[i] if i < len(rank_classes) else "normal"
        bar_width = (count / max_count * 100) if max_count > 0 else 0
        avatar = _avatar_url(uid)

        rows.append(f"""
    <div class="lb-entry">
      <div class="lb-rank {rc}">{i + 1}</div>
      <img class="lb-avatar {rc}" src="{avatar}" alt="{_html_module.escape(name, quote=False)}">
      <div class="lb-name">{_html_module.escape(name, quote=False)}</div>
      <div class="lb-bar-wrap">
        <div class="lb-bar {rc}" style="width:{bar_width:.0f}%"></div>
      </div>
      <div class="lb-count">{count}<span class="lb-unit">{_first_name}</span></div>
    </div>""")

    return "".join(rows)


# ═══════════════════════════════════════════════════════════════════
# HOURLY HEATMAP — 24 小时热力图
# ═══════════════════════════════════════════════════════════════════


def _heatmap_color(count: int, max_count: int) -> str:
    """根据消息数量返回热力图颜色。"""
    if max_count <= 0 or count <= 0:
        return "#111116"
    ratio = count / max_count
    # 从暗到亮的琥珀色梯度
    r = int(17 + ratio * 215)
    g = int(17 + ratio * 151)
    b = int(22 + ratio * 51)
    return f"rgb({r},{g},{b})"


def build_heatmap_html(
    hourly_data: list[tuple[int, int]],
) -> str:
    """生成 24 小时热力图。"""
    # 构建完整的 24 小时数据
    hour_map: dict[int, int] = {h: c for h, c in hourly_data}
    max_count = max(hour_map.values()) if hour_map else 1

    cells: list[str] = []
    labels: list[str] = []
    for h in range(24):
        count = hour_map.get(h, 0)
        color = _heatmap_color(count, max_count)
        cells.append(
            f'<div class="heatmap-cell" style="background:{color}" '
            f'title="{h:02d}:00 — {count}条"></div>'
        )
        label = f"{h:02d}" if h % 3 == 0 else ""
        labels.append(
            f'<div class="heatmap-hour">{label}</div>'
        )

    return f"""
    <div class="heatmap-grid">{"".join(cells)}</div>
    <div class="heatmap-labels">{"".join(labels)}</div>"""


# ═══════════════════════════════════════════════════════════════════
# SENTIMENT BAR — 情感分布条
# ═══════════════════════════════════════════════════════════════════


def build_sentiment_bar_html(
    sentiment_stats: dict[str, Any],
    total_messages: int,
) -> str:
    """生成情感分布三色条。"""
    if total_messages <= 0:
        return ""

    pos = sentiment_stats.get("positive_count", 0)
    neg = sentiment_stats.get("negative_count", 0)
    neutral = total_messages - pos - neg

    pos_pct = pos / total_messages * 100
    neg_pct = neg / total_messages * 100
    neutral_pct = neutral / total_messages * 100

    return f"""
    <div style="margin-top:16px;font-size:10px;color:#71717a;letter-spacing:1px;
                margin-bottom:6px;display:flex;justify-content:space-between;">
      <span style="color:#3ae8c7">POSITIVE {pos_pct:.0f}%</span>
      <span>NEUTRAL {neutral_pct:.0f}%</span>
      <span style="color:#ff6b5a">NEGATIVE {neg_pct:.0f}%</span>
    </div>
    <div class="sentiment-bar">
      <div class="sentiment-pos" style="width:{pos_pct:.1f}%"></div>
      <div class="sentiment-neutral" style="width:{neutral_pct:.1f}%"></div>
      <div class="sentiment-neg" style="width:{neg_pct:.1f}%"></div>
    </div>"""


# ═══════════════════════════════════════════════════════════════════
# CONTENT MIX — 内容分类柱状图
# ═══════════════════════════════════════════════════════════════════


def build_content_mix_html(content_dist: dict[str, int]) -> str:
    """生成内容类型柱状图。"""
    text_c = content_dist.get("text", 0)
    image_c = content_dist.get("image", 0)
    link_c = content_dist.get("link", 0)
    short_c = content_dist.get("short", 0)
    total = content_dist.get("total", 1) or 1

    categories = [
        ("Text", text_c, "#e8a849"),
        ("Image", image_c, "#3ae8c7"),
        ("Link", link_c, "#71717a"),
        ("Short", short_c, "#ff6b5a"),
    ]
    max_val = max(v for _, v, _ in categories) or 1

    cols: list[str] = []
    for label, val, color in categories:
        h = val / max_val * 60 if max_val > 0 else 0
        cols.append(f"""
    <div class="content-col">
      <div class="content-bar-count">{val}</div>
      <div class="content-bar" style="height:{h:.0f}px;background:{color}"></div>
      <div class="content-bar-label">{label}</div>
    </div>""")

    return f'<div class="content-bars">{"".join(cols)}</div>'


# ═══════════════════════════════════════════════════════════════════
# PARTICIPATION RING — SVG 环图
# ═══════════════════════════════════════════════════════════════════


def build_ring_svg_html(
    rankings: dict[str, list[tuple[str, str, int]]],
    total_messages: int,
) -> str:
    """生成参与度环形图 SVG。"""
    if not rankings:
        return '<div class="empty-state">暂无数据</div>'

    _first_name = next(iter(rankings))
    entries = rankings[_first_name]

    if not entries or total_messages <= 0:
        return '<div class="empty-state">暂无数据</div>'

    # 计算比例：前 4 名 + 其他
    top4 = entries[:4]
    top4_total = sum(c for _, _, c in top4)
    other_total = total_messages - top4_total

    # 环图参数
    cx, cy, r, stroke = 70, 70, 50, 12
    circumference = 2 * math.pi * r

    segments: list[str] = []
    legend_items: list[str] = []
    colors = ["#e8a849", "#3ae8c7", "#ff6b5a", "#71717a", "#3f3f46"]
    offset = 0.0

    items = [(n, c) for _, n, c in top4]
    if other_total > 0:
        items.append(("Others", other_total))

    for i, (name, count) in enumerate(items):
        ratio = count / total_messages
        seg_len = ratio * circumference
        color = colors[i % len(colors)]
        dasharray = f"{seg_len:.2f} {circumference:.2f}"
        segments.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" '
            f'stroke-dasharray="{dasharray}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'stroke-linecap="butt" transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += seg_len
        pct = ratio * 100
        legend_items.append(f"""
    <div class="ring-legend-item">
      <div class="ring-dot" style="background:{color}"></div>
      <span>{_html_module.escape(name, quote=False)} {pct:.0f}%</span>
    </div>""")

    return f"""
    <div class="ring-container">
      <svg class="ring-svg" width="140" height="140" viewBox="0 0 140 140">
        {"".join(segments)}
        <text x="{cx}" y="{cy - 4}" text-anchor="middle" fill="#d4d4d8"
              font-size="18" font-weight="700" font-family="JetBrains Mono,monospace">
          {total_messages}
        </text>
        <text x="{cx}" y="{cy + 12}" text-anchor="middle" fill="#3f3f46"
              font-size="8" font-family="JetBrains Mono,monospace" letter-spacing="1">
          MESSAGES
        </text>
      </svg>
      <div class="ring-legend">{"".join(legend_items)}</div>
    </div>"""


# ═══════════════════════════════════════════════════════════════════
# SOCIAL GRAPH — 社交关系条
# ═══════════════════════════════════════════════════════════════════


def build_social_graph_html(
    social_pairs: list[dict[str, Any]],
    uid_to_name: dict[str, str],
) -> str:
    """生成社交互动排行。"""
    if not social_pairs:
        return '<div class="empty-state">暂无社交互动数据</div>'

    max_count = social_pairs[0]["count"] if social_pairs else 1

    rows: list[str] = []
    for pair in social_pairs[:6]:
        a_uid = pair["user_a"]
        b_uid = pair["user_b"]
        count = pair["count"]
        a_name = uid_to_name.get(a_uid, f"qq_{a_uid}")
        b_name = uid_to_name.get(b_uid, f"qq_{b_uid}")
        bar_w = (count / max_count * 100) if max_count > 0 else 0

        rows.append(f"""
    <div class="social-pair">
      <div class="social-avatars">
        <img class="social-avatar" src="{_avatar_url(a_uid)}"
             alt="{_html_module.escape(a_name, quote=False)}">
        <img class="social-avatar" src="{_avatar_url(b_uid)}"
             alt="{_html_module.escape(b_name, quote=False)}">
      </div>
      <div class="social-bar-wrap">
        <div class="social-bar" style="width:{bar_w:.0f}%"></div>
      </div>
      <div class="social-count">{count}</div>
    </div>""")

    return "".join(rows)


# ═══════════════════════════════════════════════════════════════════
# WORD CLOUD — 高频词云
# ═══════════════════════════════════════════════════════════════════


def build_word_cloud_html(word_cloud: list[tuple[str, int]]) -> str:
    """生成高频词云。"""
    if not word_cloud:
        return '<div class="empty-state">暂无词汇数据</div>'

    max_count = word_cloud[0][1] if word_cloud else 1

    tags: list[str] = []
    for word, count in word_cloud:
        ratio = count / max_count
        size = int(11 + ratio * 10)
        # 根据频率渐变颜色
        if ratio >= 0.7:
            color = "#e8a849"
            border = "rgba(232,168,73,0.3)"
            bg = "rgba(232,168,73,0.08)"
        elif ratio >= 0.4:
            color = "#d4d4d8"
            border = "rgba(212,212,216,0.15)"
            bg = "transparent"
        else:
            color = "#71717a"
            border = "rgba(255,255,255,0.04)"
            bg = "transparent"

        tags.append(
            f'<span class="word-cloud-tag" style="'
            f'--wc-size:{size}px;--wc-color:{color};'
            f'--wc-border:{border};--wc-bg:{bg}">'
            f'{_html_module.escape(word, quote=False)}</span>'
        )

    return f'<div class="word-cloud">{"".join(tags)}</div>'


# ═══════════════════════════════════════════════════════════════════
# VOCABULARY RICHNESS — 词汇丰富度排行
# ═══════════════════════════════════════════════════════════════════


def build_vocab_html(
    vocab_rich: list[dict[str, Any]],
    uid_to_name: dict[str, str],
) -> str:
    """生成词汇丰富度排行。"""
    if not vocab_rich:
        return '<div class="empty-state">暂无词汇数据</div>'

    max_richness = vocab_rich[0]["richness"] if vocab_rich else 1.0

    rows: list[str] = []
    for entry in vocab_rich:
        uid = entry["uid"]
        name = uid_to_name.get(uid, f"qq_{uid}")
        richness = entry["richness"]
        bar_w = (richness / max_richness * 100) if max_richness > 0 else 0
        signature = entry.get("signature", [])
        sig_html = ""
        if signature:
            sig_text = " · ".join(signature)
            sig_html = (
                f'<div class="vocab-sig">'
                f'📌 {_html_module.escape(sig_text, quote=False)}</div>'
            )

        rows.append(f"""
    <div>
      <div class="vocab-entry">
        <div class="vocab-name">{_html_module.escape(name, quote=False)}</div>
        <div class="vocab-bar-wrap">
          <div class="vocab-bar" style="width:{bar_w:.0f}%"></div>
        </div>
        <div class="vocab-ratio">{richness:.2f}</div>
      </div>
      {sig_html}
    </div>""")

    return "".join(rows)


# ═══════════════════════════════════════════════════════════════════
# EVENTS — 事件链
# ═══════════════════════════════════════════════════════════════════


def build_events_html(top_events: list[dict[str, Any]]) -> str:
    """生成事件链 HTML。"""
    if not top_events:
        return '<div class="empty-state">暂未分析到事件链</div>'

    rank_labels = ["TOP 1", "TOP 2", "TOP 3"]
    cards: list[str] = []

    for event in top_events:
        rank_idx = event["rank"] - 1
        rank_label = rank_labels[rank_idx] if rank_idx < len(rank_labels) else f"#{event['rank']}"

        llm_title = event.get("llm_title", "") or event.get("topic_label", "") or "群聊讨论"
        llm_tags = event.get("llm_tags", [])
        llm_flow = event.get("llm_flow", "")

        # 标签
        if llm_tags:
            tags_html = "".join(
                f'<span class="event-tag">{_html_module.escape(str(t), quote=False)}</span>'
                for t in llm_tags[:5]
            )
        else:
            topic_kw = event.get("topic_keywords", [])
            tags_html = "".join(
                f'<span class="event-tag">{_html_module.escape(str(t), quote=False)}</span>'
                for t in topic_kw[:3]
            ) if topic_kw else ""

        # 流程描述或示例消息
        if llm_flow:
            flow_html = _render_user_tags_in_text(llm_flow)
        else:
            sample_html = ""
            for msg in event.get("sample_messages", [])[:2]:
                uid = msg.get("uid", "")
                nick = _html_module.escape(msg.get("nickname", "未知"), quote=False)
                text = _html_module.escape(msg.get("text", ""), quote=False)
                avatar = _avatar_url(uid)
                sample_html += f"""
            <div class="event-msg">
              <img class="event-msg-avatar" src="{avatar}">
              <div class="event-msg-content">
                <span class="event-msg-nick">{nick}</span>
                <span class="event-msg-text">{text}</span>
              </div>
            </div>"""
            flow_html = f'<div class="event-samples">{sample_html}</div>'

        cards.append(f"""
        <div class="event-card">
          <div class="event-header">
            <span class="event-rank">{rank_label}</span>
            <span class="event-title">{_html_module.escape(llm_title, quote=False)}</span>
          </div>
          <div class="event-meta">
            <span>⏰ {event["time_range"]}</span>
            <span>💬 {event["message_count"]}条</span>
            <span>👥 {event["participant_count"]}人</span>
          </div>
          {f'<div class="event-tags">{tags_html}</div>' if tags_html else ''}
          {f'<div class="event-flow">{flow_html}</div>' if llm_flow else flow_html}
        </div>""")

    return "".join(cards)


# ═══════════════════════════════════════════════════════════════════
# ECHOES — 复读金句
# ═══════════════════════════════════════════════════════════════════


def build_echoes_html(
    top_echoes: list[dict[str, Any]],
    uid_to_name: dict[str, str] | None = None,
) -> str:
    """生成复读金句 HTML。"""
    if not top_echoes:
        return '<div class="empty-state">暂未找到复读金句</div>'

    name_map = uid_to_name or {}
    cards: list[str] = []

    for i, echo in enumerate(top_echoes):
        text = _html_module.escape(echo["text"], quote=False)
        count = echo["count"]
        uids = echo.get("uids", [])

        avatars_html = ""
        for uid in uids[:5]:
            avatar = _avatar_url(uid)
            name = name_map.get(uid, f"qq_{uid}")
            avatars_html += (
                f'<img class="echo-avatar" src="{avatar}" '
                f'title="{_html_module.escape(name, quote=False)}">'
            )

        cards.append(f"""
      <div class="echo-card">
        <div class="echo-rank">#{i + 1}</div>
        <div class="echo-text">「{text}」</div>
        <div class="echo-meta">
          <span class="echo-count">×{count}</span>
          <div class="echo-avatars">{avatars_html}</div>
        </div>
      </div>""")

    return "".join(cards)


# ═══════════════════════════════════════════════════════════════════
# USER TAG RENDERING — LLM 输出的 <user> 标签渲染
# ═══════════════════════════════════════════════════════════════════

_USER_TAG_RE = _re_module.compile(
    r"<user\s+uid=\"([^\"]*)\"\s+name=\"([^\"]*)\"\s*>(.*?)</user>"
)

_HTML_TAG_RE = _re_module.compile(r"<(/?)(\w+)([^>]*)>")


def _escape_except_tags(text: str, safe_tags: set[str]) -> str:
    """对文本做 HTML 转义，但保留指定标签不被转义。"""
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
    """将 <user uid="QQ" name="昵称">文本</user> 替换为内嵌头像卡片。"""
    def _render_tag(match: _re_module.Match[str]) -> str:
        uid = match.group(1)
        name = match.group(2)
        display_text = match.group(3)
        avatar = _avatar_url(uid)
        safe_display = _html_module.escape(display_text, quote=False)

        return (
            f'<span class="inline-user-card" title="QQ: {uid}">'
            f'<img class="inline-avatar" src="{avatar}" alt="{safe_display}">'
            f'<span class="inline-name">{safe_display}</span>'
            f"</span>"
        )

    result = _USER_TAG_RE.sub(_render_tag, text)
    return _escape_except_tags(result, {"span", "img", "br"})


def build_commentary_html(commentary: str) -> str:
    """生成群聊总结区 HTML。"""
    if not commentary:
        return ""
    return _render_user_tags_in_text(commentary)


# ═══════════════════════════════════════════════════════════════════
# 主渲染入口
# ═══════════════════════════════════════════════════════════════════


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
    # 新增参数
    velocity_series: list[tuple[int, int]] | None = None,
    peak_velocity: tuple[int, int] | None = None,
    avg_response_sec: float = 0.0,
    sentiment_stats: dict[str, Any] | None = None,
    social_pairs: list[dict[str, Any]] | None = None,
    word_cloud: list[tuple[str, int]] | None = None,
    vocab_rich: list[dict[str, Any]] | None = None,
    content_dist: dict[str, int] | None = None,
    total_messages: int = 0,
    unique_users: int = 0,
) -> str:
    """加载模板并替换所有占位符，返回完整 HTML 字符串。"""
    template = _load_template()
    name_map = uid_to_name or {}
    peak = peak_velocity or (0, 0)

    # 构建所有 HTML 片段
    hero_html = build_hero_metrics_html(
        total_messages, unique_users, peak[1], avg_response_sec,
        (sentiment_stats or {}).get("average", 0.0),
    )
    velocity_html = build_velocity_svg_html(velocity_series or [])
    leaderboard_html = build_leaderboard_html(rankings, self_uid=self_uid)
    heatmap_html = build_heatmap_html(hourly_data)
    sentiment_html = build_sentiment_bar_html(
        sentiment_stats or {}, total_messages
    )
    content_html = build_content_mix_html(content_dist or {})
    ring_html = build_ring_svg_html(rankings, total_messages)
    social_html = build_social_graph_html(social_pairs or [], name_map)
    word_cloud_html = build_word_cloud_html(word_cloud or [])
    vocab_html = build_vocab_html(vocab_rich or [], name_map)
    events_html = build_events_html(top_events or [])
    echoes_html = build_echoes_html(top_echoes or [], uid_to_name=name_map)
    commentary_html = build_commentary_html(commentary)

    time_range = (
        f"{start_time.strftime('%m/%d %H:%M')} — {end_time.strftime('%m/%d %H:%M')}"
    )
    generated_at = end_time.strftime("%Y-%m-%d %H:%M")

    return _replace(
        template,
        group_name=group_name,
        group_id=group_id,
        time_range=time_range,
        hero_metrics_html=hero_html,
        velocity_svg_html=velocity_html,
        leaderboard_html=leaderboard_html,
        heatmap_html=heatmap_html,
        sentiment_bar_html=sentiment_html,
        content_mix_html=content_html,
        ring_svg_html=ring_html,
        social_graph_html=social_html,
        word_cloud_html=word_cloud_html,
        vocab_html=vocab_html,
        events_html=events_html,
        echoes_html=echoes_html,
        commentary_html=commentary_html,
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
                await page.set_viewport_size(
                    {"width": REPORT_WIDTH, "height": target_height}
                )
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
                target_height = (
                    max(content_height, 600) + BODY_PADDING + EXTRA_PADDING
                )
                await page.set_viewport_size(
                    {"width": REPORT_WIDTH, "height": target_height}
                )
                await asyncio.sleep(0.3)

            screenshot = await page.screenshot(full_page=True, type="png")
            return screenshot
        except Exception as exc:
            logger.warning("playwright 截图失败: %s", exc)
            raise RuntimeError(f"HTML 渲染失败: {exc}") from exc
        finally:
            await browser.close()
