"""测试数据脚本 — 生成模板预览图片。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path

from render import render_report_html, html_to_png, render_optimal_report


def generate_test_data() -> dict:
    """生成模拟测试数据。"""
    now = datetime.now()
    start = now - timedelta(hours=24)

    # 模拟用户数据
    users = [
        ("10001", "星尘旅人"),
        ("10002", "月光下的猫"),
        ("10003", "银河收集者"),
        ("10004", "深海探险家"),
        ("10005", "极光观测员"),
    ]
    uid_to_name = {uid: name for uid, name in users}

    # 消息排名
    rankings = {
        "消息数": [
            ("10001", "星尘旅人", 156),
            ("10002", "月光下的猫", 132),
            ("10003", "银河收集者", 98),
            ("10004", "深海探险家", 76),
            ("10005", "极光观测员", 54),
        ]
    }

    # 每小时数据
    hourly_data = []
    base_ts = int(start.timestamp())
    for h in range(24):
        ts = base_ts + h * 3600
        # 模拟活跃时段：下午和晚上更活跃
        if 14 <= h <= 22:
            count = 30 + (h - 14) * 8
        elif 0 <= h <= 6:
            count = 5 + h * 2
        else:
            count = 15 + (h - 7) * 5
        hourly_data.append((h, count))

    # 速度序列
    velocity_series = []
    for i in range(48):
        ts = int(start.timestamp()) + i * 1800
        # 模拟高峰
        hour = (i * 30) // 60
        if 14 <= hour <= 22:
            count = 20 + (hour - 14) * 12 + (i % 3) * 5
        else:
            count = 5 + (i % 5) * 3
        velocity_series.append((ts, count))

    # 社交配对
    social_pairs = [
        {"user_a": "10001", "user_b": "10002", "count": 45},
        {"user_a": "10001", "user_b": "10003", "count": 38},
        {"user_a": "10002", "user_b": "10004", "count": 32},
        {"user_a": "10003", "user_b": "10005", "count": 28},
        {"user_a": "10001", "user_b": "10005", "count": 22},
    ]

    # 词云
    word_cloud = [
        ("星空", 89), ("猫咪", 76), ("银河", 65), ("探险", 58),
        ("极光", 52), ("深海", 48), ("月亮", 42), ("旅行", 38),
        ("摄影", 35), ("音乐", 32), ("美食", 28), ("游戏", 25),
        ("电影", 22), ("阅读", 18), ("绘画", 15),
    ]

    # 词汇丰富度
    vocab_rich = [
        {"uid": "10001", "richness": 0.85, "signature": ["创意", "表达"]},
        {"uid": "10002", "richness": 0.72, "signature": ["幽默", "温暖"]},
        {"uid": "10003", "richness": 0.68, "signature": ["深度", "思考"]},
        {"uid": "10004", "richness": 0.55, "signature": ["简洁", "直接"]},
        {"uid": "10005", "richness": 0.48, "signature": ["友好", "热情"]},
    ]

    # 内容分布
    content_dist = {
        "text": 420,
        "image": 156,
        "link": 45,
        "short": 89,
        "total": 710,
    }

    # 情感统计
    sentiment_stats = {
        "average": 0.25,
        "positive_count": 280,
        "negative_count": 45,
    }

    # 事件链
    top_events = [
        {
            "rank": 1,
            "llm_title": "星空摄影分享会",
            "llm_tags": ["摄影", "星空", "分享"],
            "llm_flow": (
                "<user uid=\"10001\" name=\"星尘旅人\">发起话题</user> 分享了昨晚拍摄的星空照片，"
                "<user uid=\"10002\" name=\"月光下的猫\">热烈回应</user> 并询问拍摄参数，"
                "<user uid=\"10003\" name=\"银河收集者\">补充分享</user> 了自己的拍摄经验。"
            ),
            "time_range": "14:30 - 15:45",
            "message_count": 45,
            "participant_count": 4,
        },
        {
            "rank": 2,
            "llm_title": "周末探险计划讨论",
            "llm_tags": ["探险", "计划", "周末"],
            "llm_flow": (
                "<user uid=\"10004\" name=\"深海探险家\">提议</user> 周末去郊外露营观星，"
                "<user uid=\"10005\" name=\"极光观测员\">积极响应</user>，"
                "大家开始讨论装备和路线。"
            ),
            "time_range": "18:20 - 19:15",
            "message_count": 38,
            "participant_count": 5,
        },
        {
            "rank": 3,
            "llm_title": "美食推荐交流",
            "llm_tags": ["美食", "推荐", "餐厅"],
            "llm_flow": (
                "<user uid=\"10002\" name=\"月光下的猫\">推荐</user> 了一家新开的咖啡店，"
                "引发了大家对美食的热烈讨论。"
            ),
            "time_range": "20:00 - 20:45",
            "message_count": 28,
            "participant_count": 3,
        },
    ]

    # 复读金句
    top_echoes = [
        {
            "text": "今晚的星空真美啊",
            "count": 12,
            "uids": ["10001", "10002", "10003", "10004"],
        },
        {
            "text": "猫咪是最可爱的生物",
            "count": 8,
            "uids": ["10002", "10005"],
        },
        {
            "text": "一起去探险吧",
            "count": 6,
            "uids": ["10001", "10003", "10004"],
        },
    ]

    # 叙事摘要
    commentary = (
        "今天的群聊氛围温馨而活跃。<user uid=\"10001\" name=\"星尘旅人\">作为群里的"
        "摄影达人，分享了许多令人惊叹的星空作品，引发了大家的热烈讨论。"
        "<user uid=\"10002\" name=\"月光下的猫\">用温暖的语言带动了整个群聊的氛围，"
        "而<user uid=\"10003\" name=\"银河收集者\">则以深入的见解为大家提供了新的视角。"
        "下午的探险计划讨论让群聊达到了高潮，大家纷纷响应，期待周末的到来。"
        "傍晚时分，<user uid=\"10005\" name=\"极光观测员\">分享的极光照片更是让群聊"
        "充满了诗意与浪漫。整体而言，这是一个充满分享与互动的美好一天。"
    )

    return {
        "group_name": "星空观测站",
        "group_id": "123456789",
        "start_time": start,
        "end_time": now,
        "rankings": rankings,
        "hourly_data": hourly_data,
        "commentary": commentary,
        "plugin_version": "1.1.0",
        "self_uid": "10001",
        "top_events": top_events,
        "top_echoes": top_echoes,
        "uid_to_name": uid_to_name,
        "velocity_series": velocity_series,
        "peak_velocity": (int(now.timestamp()), 85),
        "avg_response_sec": 42.5,
        "sentiment_stats": sentiment_stats,
        "social_pairs": social_pairs,
        "word_cloud": word_cloud,
        "vocab_rich": vocab_rich,
        "content_dist": content_dist,
        "total_messages": 710,
        "unique_users": 5,
    }


async def main():
    """生成测试报告图片（两遍渲染：测量真实高度后最优分箱）。"""
    print("正在生成测试数据...")
    data = generate_test_data()
    plugin_version = data.pop("plugin_version")

    output_dir = Path(__file__).parent

    print("第一遍渲染：生成初始布局 + 测量模块高度...")
    try:
        html, png_bytes = await render_optimal_report(data, plugin_version)
    except RuntimeError as e:
        print(f"渲染失败: {e}")
        print("回退到单遍渲染...")
        html = render_report_html(plugin_version=plugin_version, **data)
        png_bytes = None

    html_path = output_dir / "test_output.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"HTML 已保存: {html_path}")

    if png_bytes:
        png_path = output_dir / "test_output.png"
        png_path.write_bytes(png_bytes)
        print(f"PNG 已保存: {png_path}")
        print(f"图片大小: {len(png_bytes) / 1024:.1f} KB")
    else:
        print("PNG 未生成（playwright 不可用）")


if __name__ == "__main__":
    asyncio.run(main())
