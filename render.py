"""HTML 模板渲染 — 新一代数据可视化 + PNG 截图。

设计语言：星空梦幻可爱风格
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


def _avatar_url(uid: str, uid_to_name: dict[str, str] | None = None) -> str:
    """生成 QQ 头像 URL。

    如果 uid 本身是有效 QQ 号（5-11 位数字），直接使用。
    否则尝试从 uid_to_name 映射中查找对应的 QQ 号。
    """
    if uid and uid.isdigit() and len(uid) >= 5:
        return f"http://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640&img_type=jpg"
    # 尝试从映射中查找：有些 uid 可能不是 QQ 号，但映射中有对应关系
    if uid_to_name and uid in uid_to_name:
        mapped_name = uid_to_name[uid]
        # 如果映射名看起来像 QQ 号
        if mapped_name.isdigit() and len(mapped_name) >= 5:
            return (
                f"http://q.qlogo.cn/headimg_dl?dst_uin={mapped_name}"
                f"&spec=640&img_type=jpg"
            )
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
        sent_label = "积极"
        sent_cls = "teal"
    elif sentiment_avg < -0.1:
        sent_label = "消极"
        sent_cls = "coral"
    else:
        sent_label = "中性"
        sent_cls = ""

    # 响应时间格式化
    if avg_response_sec > 0:
        resp_str = f"{avg_response_sec:.0f}s"
    else:
        resp_str = "--"

    return f"""
    <div class="metric-box">
      <div class="metric-value">{message_count}</div>
      <div class="metric-label">消息总数</div>
    </div>
    <div class="metric-box">
      <div class="metric-value">{unique_users}</div>
      <div class="metric-label">参与人数</div>
    </div>
    <div class="metric-box">
      <div class="metric-value">{peak_velocity}</div>
      <div class="metric-label">峰值/5分钟</div>
    </div>
    <div class="metric-box">
      <div class="metric-value">{resp_str}</div>
      <div class="metric-label">平均响应</div>
    </div>
    <div class="metric-box">
      <div class="metric-value {sent_cls}">{sent_label}</div>
      <div class="metric-label">情感倾向</div>
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
                f'fill="#50507a" font-size="9" text-anchor="middle" '
                f'font-family="Quicksand,sans-serif">{t_str}</text>'
            )

    return f"""
    <svg class="velocity-svg" viewBox="0 0 {svg_w} {svg_h}" preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id="velGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#b48eff" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="#b48eff" stop-opacity="0"/>
        </linearGradient>
        <filter id="velGlow">
          <feGaussianBlur stdDeviation="2" result="blur"/>
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <!-- 网格线 -->
      <line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}"
            stroke="#1a1a50" stroke-width="1"/>
      <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l + plot_w}" y2="{pad_t}"
            stroke="#1a1a50" stroke-width="0.5" stroke-dasharray="4,4"/>
      <!-- 面积 -->
      <path d="{area_path}" fill="url(#velGrad)"/>
      <!-- 折线 -->
      <path d="{line_path}" fill="none" stroke="#b48eff" stroke-width="2" filter="url(#velGlow)"/>
      <!-- 峰值点 -->
      <circle cx="{peak_x:.1f}" cy="{peak_y:.1f}" r="4" fill="#b48eff" filter="url(#velGlow)"/>
      <text x="{peak_x:.1f}" y="{peak_y - 10:.1f}" fill="#b48eff" font-size="10"
            text-anchor="middle" font-family="Quicksand,sans-serif" font-weight="600">
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
    uid_to_name: dict[str, str] | None = None,
) -> str:
    """生成消息排名 HTML（只取第一个分析器的排名）。"""
    if not rankings:
        return '<div class="empty-state">暂无排名数据</div>'

    name_map = uid_to_name or {}
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
        avatar = _avatar_url(uid, name_map)

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
    """根据消息数量返回热力图颜色（青→金双色渐变）。"""
    if max_count <= 0 or count <= 0:
        return "#141420"
    ratio = count / max_count
    # 青色 (45,214,191) → 金色 (255,200,87)
    r = int(45 + ratio * 210)
    g = int(214 - ratio * 14)
    b = int(191 - ratio * 104)
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
    <div style="margin-top:16px;font-size:10px;color:#9090b8;letter-spacing:1px;
                margin-bottom:6px;display:flex;justify-content:space-between;">
      <span style="color:#7dffc2">积极 {pos_pct:.0f}%</span>
      <span>中性 {neutral_pct:.0f}%</span>
      <span style="color:#ff8ec4">消极 {neg_pct:.0f}%</span>
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
        ("文本", text_c, "#b48eff"),
        ("图片", image_c, "#7dffc2"),
        ("链接", link_c, "#9090b8"),
        ("短句", short_c, "#ff8ec4"),
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
    colors = ["#b48eff", "#ff8ec4", "#7dffc2", "#9090b8", "#50507a"]
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
        <text x="{cx}" y="{cy - 4}" text-anchor="middle" fill="#e0e0f0"
              font-size="18" font-weight="700" font-family="Quicksand,sans-serif">
          {total_messages}
        </text>
        <text x="{cx}" y="{cy + 12}" text-anchor="middle" fill="#50507a"
              font-size="8" font-family="Quicksand,sans-serif" letter-spacing="1">
          消息
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
    """生成社交互动图谱 SVG（节点 = 头像，曲线 = 互动关系）。"""
    if not social_pairs:
        return '<div class="empty-state">暂无社交互动数据</div>'

    max_count = social_pairs[0]["count"] if social_pairs else 1

    # 收集所有参与用户，保持出现顺序
    seen: dict[str, str] = {}  # uid -> name
    for pair in social_pairs:
        for uid_key in ("user_a", "user_b"):
            uid = pair[uid_key]
            if uid not in seen:
                seen[uid] = uid_to_name.get(uid, f"qq_{uid}")
    uids = list(seen.keys())
    n = len(uids)
    uid_idx = {uid: i for i, uid in enumerate(uids)}

    # 收集每个用户的总互动次数，用于头像大小
    user_activity: dict[str, int] = {uid: 0 for uid in seen}
    for pair in social_pairs:
        user_activity[pair["user_a"]] += pair["count"]
        user_activity[pair["user_b"]] += pair["count"]
    max_activity = max(user_activity.values()) if user_activity else 1

    # 动态布局参数：根据节点数调整画布大小
    n = min(n, 12)  # 最多显示 12 个节点
    svg_w = max(500, min(800, 300 + n * 40))
    svg_h = max(280, min(400, 200 + n * 20))
    cx, cy = svg_w / 2, svg_h / 2

    # 均匀椭圆布局
    import math

    rx = cx - 60
    ry = cy - 50

    positions: list[tuple[float, float]] = []
    for i in range(n):
        angle = 2 * math.pi * i / n - math.pi / 2  # 均匀分布，顶部开始
        x = cx + rx * math.cos(angle)
        y = cy + ry * math.sin(angle)
        positions.append((x, y))

    # 颜色池
    edge_colors = ["#b48eff", "#ff8ec4", "#7dffc2", "#ffc857", "#9090b8",
                   "#ff9e7a", "#7ac8ff", "#c8a2ff"]

    defs_parts: list[str] = []
    edge_parts: list[str] = []
    node_parts: list[str] = []

    # 画连线（贝塞尔曲线）— 全部关系
    for idx, pair in enumerate(social_pairs):
        a_uid = pair["user_a"]
        b_uid = pair["user_b"]
        count = pair["count"]
        if a_uid not in uid_idx or b_uid not in uid_idx:
            continue
        ax, ay = positions[uid_idx[a_uid]]
        bx, by = positions[uid_idx[b_uid]]
        ratio = count / max_count
        # 粗细差别放大：最细 1px，最粗 8px
        stroke_w = 1 + ratio * 7
        opacity = 0.25 + ratio * 0.6
        color = edge_colors[idx % len(edge_colors)]

        # 贝塞尔控制点：向圆心偏移，形成弧线
        mid_x = (ax + bx) / 2
        mid_y = (ay + by) / 2
        dx = mid_x - cx
        dy = mid_y - cy
        dist = math.sqrt(dx * dx + dy * dy) or 1
        cp_x = mid_x - dx / dist * 35
        cp_y = mid_y - dy / dist * 35

        edge_parts.append(
            f'<path d="M{ax:.0f},{ay:.0f} Q{cp_x:.0f},{cp_y:.0f} {bx:.0f},{by:.0f}" '
            f'fill="none" stroke="{color}" stroke-width="{stroke_w:.1f}" '
            f'opacity="{opacity:.2f}" stroke-linecap="round"/>'
        )

        # 连线中点显示互动次数
        label_x = (ax + 2 * cp_x + bx) / 4
        label_y = (ay + 2 * cp_y + by) / 4
        edge_parts.append(
            f'<text x="{label_x:.0f}" y="{label_y:.0f}" text-anchor="middle" '
            f'dominant-baseline="middle" fill="{color}" font-size="14" '
            f'font-family="Quicksand,sans-serif" font-weight="700" '
            f'opacity="0.9">{count}</text>'
        )

    # 画节点（头像大小随互动次数缩放）
    avatar_r_min = 16
    avatar_r_max = 28
    for i, uid in enumerate(uids):
        x, y = positions[i]
        name = seen[uid]
        avatar = _avatar_url(uid, uid_to_name)
        safe_name = _html_module.escape(name, quote=False)
        activity = user_activity.get(uid, 0)
        ratio = activity / max_activity if max_activity else 0
        avatar_r = avatar_r_min + ratio * (avatar_r_max - avatar_r_min)

        # 头像裁剪圆
        clip_id = f"socialClip{i}"
        defs_parts.append(
            f'<clipPath id="{clip_id}">'
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{avatar_r:.0f}"/>'
            f'</clipPath>'
        )
        node_parts.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{avatar_r + 2:.0f}" '
            f'fill="rgba(157,124,255,0.12)" stroke="rgba(157,124,255,0.25)" '
            f'stroke-width="1.5"/>'
        )
        node_parts.append(
            f'<image href="{avatar}" '
            f'x="{x - avatar_r:.0f}" y="{y - avatar_r:.0f}" '
            f'width="{avatar_r * 2:.0f}" height="{avatar_r * 2:.0f}" '
            f'clip-path="url(#{clip_id})"/>'
        )
        # 名字（节点下方）
        name_y = y + avatar_r + 14
        node_parts.append(
            f'<text x="{x:.0f}" y="{name_y:.0f}" text-anchor="middle" '
            f'fill="#c0b8e0" font-size="12" font-weight="600"'
            f' font-family="LXGW WenKai,Noto Sans SC,sans-serif">'
            f'{safe_name}</text>'
        )

    svg = (
        f'<svg width="100%" viewBox="0 0 {svg_w} {svg_h}" '
        f'preserveAspectRatio="xMidYMid meet">\n'
        f'<defs>{"".join(defs_parts)}</defs>\n'
        f'{"".join(edge_parts)}\n'
        f'{"".join(node_parts)}\n'
        f'</svg>'
    )
    return svg


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
        size = 13
        # 根据频率渐变颜色（星空紫主题）
        if ratio >= 0.7:
            color = "#b48eff"
            border = "rgba(180,142,255,0.3)"
            bg = "rgba(180,142,255,0.08)"
        elif ratio >= 0.4:
            color = "#c0b8e0"
            border = "rgba(180,142,255,0.12)"
            bg = "transparent"
        else:
            color = "#606088"
            border = "rgba(180,142,255,0.06)"
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
    """生成表达风格卡片。"""
    if not vocab_rich:
        return '<div class="empty-state">暂无词汇数据</div>'

    # 丰富度等级标签
    def _richness_label(r: float) -> str:
        if r >= 0.8:
            return "词汇丰富"
        if r >= 0.6:
            return "表达均衡"
        if r >= 0.4:
            return "用语简洁"
        return "言简意赅"

    rows: list[str] = []
    for entry in vocab_rich[:4]:
        uid = entry["uid"]
        name = uid_to_name.get(uid, f"qq_{uid}")
        richness = entry["richness"]
        signature = entry.get("signature", [])
        label = _richness_label(richness)
        avatar = _avatar_url(uid, uid_to_name)

        sig_html = ""
        if signature:
            sig_text = " · ".join(signature)
            sig_html = (
                f'<div style="font-size:10px;color:var(--text-dim);'
                f'text-align:center;margin-top:4px">'
                f'{_html_module.escape(sig_text, quote=False)}</div>'
            )

        rows.append(
            f'<div style="display:flex;flex-direction:column;align-items:center;'
            f'padding:10px 6px;border:1px solid var(--border);border-radius:12px;'
            f'background:var(--surface-2)">'
            f'<img src="{avatar}" style="width:32px;height:32px;border-radius:50%;'
            f'border:1.5px solid var(--border);object-fit:cover;margin-bottom:6px">'
            f'<span style="font-size:12px;color:var(--text);font-weight:500">'
            f'{_html_module.escape(name, quote=False)}</span>'
            f'<span class="event-tag" style="background:var(--mint-soft);color:var(--mint);'
            f'border-color:rgba(110,232,176,0.2);margin-top:4px">{label}</span>'
            f'{sig_html}</div>'
        )

    return (
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">'
        + "".join(rows)
        + "</div>"
    )


# ═══════════════════════════════════════════════════════════════════
# EVENTS — 事件链
# ═══════════════════════════════════════════════════════════════════


def build_events_html(
    top_events: list[dict[str, Any]],
    uid_to_name: dict[str, str] | None = None,
) -> str:
    """生成事件链 HTML。"""
    if not top_events:
        return '<div class="empty-state">暂未分析到事件链</div>'

    name_map = uid_to_name or {}

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
                avatar = _avatar_url(uid, name_map)
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
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
            <span style="display:flex;align-items:center;gap:8px;flex-shrink:0">
              <span class="event-rank">{rank_label}</span>
              <span class="event-title">{_html_module.escape(llm_title, quote=False)}</span>
            </span>
            <span style="flex:1;text-align:center;font-size:10px;color:var(--text-muted);letter-spacing:0.5px;min-width:0">
              ⏰ {event["time_range"]} &nbsp; 💬 {event["message_count"]}条 &nbsp; 👥 {event["participant_count"]}人
            </span>
            <span style="display:flex;gap:4px;flex-shrink:0">{tags_html}</span>
          </div>
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
            avatar = _avatar_url(uid, name_map)
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
# SECTION GRID 排布算法 — 贪心分箱使各列高度最平整
# ═══════════════════════════════════════════════════════════════════

# section-block padding(44) + title 栏(~48) = 每个卡片固定开销
_SEC_OVERHEAD = 92
_LB_ROW = 56        # lb-entry: padding 20 + avatar 36
_HEATMAP = 180       # grid + labels + sentiment bar
_RING = 170          # ring SVG 140 + legend 间距
_CONTENT_MIX = 130   # bars 80 + labels
_SOCIAL_ROW = 48     # social-pair: padding 16 + avatar 28
_WORD_CLOUD = 90     # 词云区域
_VOCAB_ROW = 52      # vocab-entry: padding 20 + bar 8 + 间距
_ECHO_ROW = 60       # echo-card: padding 20 + 内容
_EVENT_CARD = 170    # event-card: header + meta + tags + flow
_COMMENTARY_LINE = 31  # line-height: 2.2 * 14px


def _strip_html_tags(text: str) -> str:
    """去掉 HTML/XML 标签，返回纯文本（用于估算显示字数）。"""
    return _re_module.sub(r"<[^>]+>", "", text)


def _estimate_height(
    name: str,
    *,
    leaderboard_len: int = 0,
    social_len: int = 0,
    vocab_len: int = 0,
    events_len: int = 0,
    echoes_len: int = 0,
    commentary_len: int = 0,
) -> int:
    """根据内容量预估模块像素高度。"""
    if name == "leaderboard":
        return _SEC_OVERHEAD + leaderboard_len * _LB_ROW
    if name == "heatmap":
        return _SEC_OVERHEAD + _HEATMAP
    if name == "ring":
        return _SEC_OVERHEAD + _RING
    if name == "content_mix":
        return _SEC_OVERHEAD + _CONTENT_MIX
    if name == "social":
        return _SEC_OVERHEAD + social_len * _SOCIAL_ROW
    if name == "keywords":
        return _SEC_OVERHEAD + _WORD_CLOUD + vocab_len * _VOCAB_ROW
    if name == "events":
        return _SEC_OVERHEAD + events_len * _EVENT_CARD
    if name == "echoes":
        return _SEC_OVERHEAD + echoes_len * _ECHO_ROW
    if name == "commentary":
        lines = max(1, commentary_len // 18)
        return _SEC_OVERHEAD + lines * _COMMENTARY_LINE
    return 200


def _arrange_grid(
    full_width: list[tuple[int, str]],
    columns: list[list[tuple[int, str]]],
    col_count: int,
    gap_px: int = 12,
) -> str:
    """将全宽模块和已分箱的普通模块组装成 Grid HTML。

    每列用 .grid-col 包裹为独立 flex 列，实现瀑布流效果。
    较短的列底部自动插入装饰占位框补齐高度差。
    full_width: [(插入位置优先级, html), ...]
    columns:    col_count 个列表，每列表内 (height, html)
    """
    full_width.sort(key=lambda x: x[0])

    # 计算每列总高度（含 gap）
    col_heights: list[int] = []
    for col in columns:
        h = sum(item[0] for item in col)
        h += gap_px * max(len(col) - 1, 0)
        col_heights.append(h)
    max_h = max(col_heights) if col_heights else 0

    parts: list[str] = []
    parts.append('<div class="sections-grid">')

    for prio, html in full_width:
        if prio < 1:
            parts.append(html)

    for i, col in enumerate(columns):
        pad = max_h - col_heights[i] - 2 * gap_px
        has_spacer = pad > 10
        justify = "flex-start" if has_spacer else "space-between"
        parts.append(f'<div class="grid-col" style="justify-content:{justify}">')
        mid = len(col) // 2
        for j, (_height, html) in enumerate(col):
            parts.append(html)
            if j == mid and has_spacer:
                parts.append('<div class="grid-spacer"></div>')
        parts.append("</div>")

    for prio, html in full_width:
        if prio >= 1:
            parts.append(html)

    parts.append("</div>")
    return "\n".join(parts)


def build_sections_grid_html(
    *,
    velocity_html: str,
    leaderboard_html: str,
    leaderboard_len: int,
    heatmap_html: str,
    sentiment_html: str,
    ring_html: str,
    content_html: str,
    social_html: str,
    social_len: int,
    word_cloud_html: str,
    vocab_html: str,
    vocab_len: int,
    events_html: str,
    events_len: int,
    echoes_html: str,
    echoes_len: int,
    commentary_html: str,
    commentary_len: int,
    col_count: int = 2,
    measured_heights: dict[str, int] | None = None,
) -> str:
    """生成多栏 Grid 布局 HTML，最优分箱使各列高度最平整。

    measured_heights: Playwright 测得的真实高度 {section_name: px}，
    若提供则优先使用，否则回退到 _estimate_height 预估。
    """

    def _h(name: str, **kwargs: Any) -> int:
        if measured_heights and name in measured_heights:
            return measured_heights[name]
        return _estimate_height(name, **kwargs)

    # ── 全宽模块（固定位置） ──
    full_width = [
        (0, '<div class="section-block col-span-all" data-section="velocity">'
            f'<div class="section-title"><span class="icon">✦</span> 消息速率</div>'
            f'{velocity_html}</div>'),
        (1, '<div class="section-block col-span-all" data-section="events">'
            f'<div class="section-title"><span class="icon">✦</span> 事件链</div>'
            f'{events_html}</div>'),
        (2, '<div class="section-block col-span-all" data-section="commentary">'
            f'<div class="section-title"><span class="icon">☽</span> 叙事摘要</div>'
            f'<div class="commentary">{commentary_html}</div></div>'),
    ]

    # ── 可排列模块：(名称, 高度, HTML) ──
    modules = [
        ("leaderboard", _h("leaderboard", leaderboard_len=leaderboard_len),
         '<div class="section-block" data-section="leaderboard">'
         f'<div class="section-title"><span class="icon">★</span> 排行榜</div>'
         f'{leaderboard_html}</div>'),
        ("heatmap", _h("heatmap"),
         '<div class="section-block" data-section="heatmap">'
         '<div class="section-title" style="justify-content:space-between">'
         '<span style="display:flex;align-items:center;gap:10px">'
         '<span class="icon">✧</span> 时间热力图</span>'
         '<span style="display:flex;align-items:center;gap:6px;font-size:9px;'
         'font-weight:400;letter-spacing:1px;color:var(--text-muted)">'
         '<span>少</span>'
         '<span style="display:inline-block;width:60px;height:8px;border-radius:4px;'
         'background:linear-gradient(90deg,rgb(45,214,191),rgb(255,200,87))"></span>'
         '<span>多</span></span></div>'
         f'{heatmap_html}{sentiment_html}</div>'),
        ("ring", _h("ring"),
         '<div class="section-block" data-section="ring">'
         f'<div class="section-title"><span class="icon">☽</span> 参与度</div>'
         f'{ring_html}</div>'),
        ("content_mix", _h("content_mix"),
         '<div class="section-block" data-section="content_mix">'
         f'<div class="section-title"><span class="icon">❋</span> 内容构成</div>'
         f'{content_html}</div>'),
        ("social", _h("social", social_len=social_len),
         '<div class="section-block" data-section="social">'
         f'<div class="section-title"><span class="icon">✿</span> 社交图谱</div>'
         f'{social_html}</div>'),
        ("keywords", _h("keywords", vocab_len=vocab_len),
         '<div class="section-block" data-section="keywords">'
         f'<div class="section-title"><span class="icon">✎</span> 关键词</div>'
         f'{word_cloud_html}{vocab_html}</div>'),
        ("echoes", _h("echoes", echoes_len=echoes_len),
         '<div class="section-block" data-section="echoes">'
         f'<div class="section-title"><span class="icon">♡</span> 复读金句</div>'
         f'{echoes_html}</div>'),
    ]

    # ── 精确最优分箱：暴力搜索使最高列与最低列的差值最小 ──
    _gap = 12
    n = len(modules)
    best_max_diff = float("inf")
    best_assignment: list[int] = []

    # 枚举每个模块分配到哪一列 (col_count^n 种)
    from itertools import product

    for assignment in product(range(col_count), repeat=n):
        col_h = [0] * col_count
        col_cnt = [0] * col_count
        for i, col_idx in enumerate(assignment):
            if col_cnt[col_idx] > 0:
                col_h[col_idx] += _gap
            col_h[col_idx] += modules[i][1]
            col_cnt[col_idx] += 1
        # 跳过空列
        if min(col_cnt) == 0:
            continue
        diff = max(col_h) - min(col_h)
        if diff < best_max_diff:
            best_max_diff = diff
            best_assignment = list(assignment)

    buckets: list[list[tuple[int, str]]] = [[] for _ in range(col_count)]
    for i, col_idx in enumerate(best_assignment):
        buckets[col_idx].append((modules[i][1], modules[i][2]))

    return _arrange_grid(full_width, buckets, col_count, _gap)


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
    measured_heights: dict[str, int] | None = None,
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
    leaderboard_html = build_leaderboard_html(
        rankings, self_uid=self_uid, uid_to_name=name_map
    )
    heatmap_html = build_heatmap_html(hourly_data)
    sentiment_html = build_sentiment_bar_html(
        sentiment_stats or {}, total_messages
    )
    content_html = build_content_mix_html(content_dist or {})
    ring_html = build_ring_svg_html(rankings, total_messages)
    social_html = build_social_graph_html(social_pairs or [], name_map)
    word_cloud_html = build_word_cloud_html(word_cloud or [])
    vocab_html = build_vocab_html(vocab_rich or [], name_map)
    events_html = build_events_html(top_events or [], uid_to_name=name_map)
    echoes_html = build_echoes_html(top_echoes or [], uid_to_name=name_map)
    commentary_html = build_commentary_html(commentary)

    # 获取各模块内容条数，用于高度预估
    _first_rank = next(iter(rankings), None)
    leaderboard_len = len(rankings[_first_rank]) if _first_rank else 0

    # 三栏贪心排布
    sections_grid_html = build_sections_grid_html(
        velocity_html=velocity_html,
        leaderboard_html=leaderboard_html,
        leaderboard_len=leaderboard_len,
        heatmap_html=heatmap_html,
        sentiment_html=sentiment_html,
        ring_html=ring_html,
        content_html=content_html,
        social_html=social_html,
        social_len=len(social_pairs or []),
        word_cloud_html=word_cloud_html,
        vocab_html=vocab_html,
        vocab_len=len(vocab_rich or []),
        events_html=events_html,
        events_len=len(top_events or []),
        echoes_html=echoes_html,
        echoes_len=len(top_echoes or []),
        commentary_html=commentary_html,
        commentary_len=len(_strip_html_tags(commentary)),
        col_count=2,
        measured_heights=measured_heights,
    )

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
        sections_grid_html=sections_grid_html,
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
    BODY_PADDING = 0
    EXTRA_PADDING = 0

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


async def measure_section_heights(html: str) -> dict[str, int]:
    """用 Playwright 测量每个 [data-section] 元素的真实渲染高度。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {}

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1100, "height": 3000})
            await page.set_content(html, wait_until="load")
            await asyncio.sleep(1.0)
            heights: dict[str, int] = await page.evaluate("""() => {
                const result = {};
                document.querySelectorAll('[data-section]').forEach(el => {
                    result[el.dataset.section] = el.offsetHeight;
                });
                return result;
            }""")
            return heights
        except Exception as exc:
            logger.warning("测量模块高度失败: %s", exc)
            return {}
        finally:
            await browser.close()


async def render_optimal_report(
    render_kwargs: dict[str, Any],
    plugin_version: str,
) -> tuple[str, bytes]:
    """两遍渲染：第一遍测真实高度，第二遍最优分箱，返回 (html, png)。"""

    # ── 第一遍：用预估高度生成初始布局 ──
    html_pass1 = render_report_html(plugin_version=plugin_version, **render_kwargs)

    # ── 测量真实高度 ──
    heights = await measure_section_heights(html_pass1)
    if heights:
        logger.info("测得模块高度: %s", heights)

    # ── 第二遍：用真实高度重新排布 ──
    html_pass2 = render_report_html(
        plugin_version=plugin_version,
        measured_heights=heights or None,
        **render_kwargs,
    )

    # ── 截图 ──
    png = await html_to_png(html_pass2)
    return html_pass2, png
