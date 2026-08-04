#!/usr/bin/env python3
"""Daily AI news → WeChat push. Runs on GitHub Actions, zero local dependency."""

import os, json, random, time, ssl
import urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["ILINK_BOT_TOKEN"]
TO_USER   = os.environ["ILINK_USER_ID"]
BASE_URL  = "https://ilinkai.weixin.qq.com"

# ── WeChat ilink push ────────────────────────────────────────────

def send_to_wechat(text: str) -> int:
    """Push text to WeChat ClawBot via ilink API. Returns chunk count."""
    chunks = [text[i:i+3800] for i in range(0, len(text), 3800)]
    ctx = ssl.create_default_context()
    for c in chunks:
        body = json.dumps({
            "base_info": {"channel_version": "2.4.6", "bot_agent": "OpenClaw"},
            "msg": {
                "from_user_id": "", "to_user_id": TO_USER,
                "client_id": f"cbc-{int(time.time()*1000)}-{random.randint(100000,999999):x}",
                "message_type": 2, "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"text": c}}],
                "context_token": "",
            }
        }, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": str(random.randint(10000000, 99999999)),
            "Authorization": f"Bearer {BOT_TOKEN}",
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": "132102",
        }
        req = urllib.request.Request(f"{BASE_URL}/ilink/bot/sendmessage", data=body, headers=headers, method="POST")
        resp = urllib.request.urlopen(req, context=ctx)
        raw = resp.read().decode()
        if resp.status != 200:
            raise Exception(f"HTTP {resp.status}: {raw}")
    return len(chunks)

# ── News gathering ───────────────────────────────────────────────

def fetch_rss(query: str) -> list[dict]:
    """Fetch items from Google News RSS for given query."""
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=15)
        data = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    import xml.etree.ElementTree as ET
    items = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []

    for item in root.findall(".//item"):
        title = (item.findtext("title", "") or "").strip()
        desc  = (item.findtext("description", "") or "")
        # Strip HTML tags from description
        if desc:
            import re
            desc = re.sub(r'<[^>]+>', '', desc)
            desc = re.sub(r'&[a-z]+;', ' ', desc)
            desc = re.sub(r'\s+', ' ', desc).strip()[:200]
        source = ""
        if " - " in title:
            parts = title.rsplit(" - ", 1)
            title = parts[0].strip()
            source = parts[1].strip() if len(parts) > 1 else ""

        if title and len(title) > 5:
            items.append({"title": title, "desc": desc, "source": source})
    return items

# ── AI summarization (optional, uses Groq free tier) ─────────────

def summarize_with_ai(items: list[dict]) -> tuple[str, list[str]]:
    """Use Groq API to curate and summarize news. Falls back to basic mode."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return _basic_summary(items)

    # Build prompt
    items_text = "\n".join(
        f"{i+1}. [{t['title']}] {t['desc'][:150]}" for i, t in enumerate(items[:12])
    )
    prompt = f"""你是AI领域资深编辑。请从以下新闻中筛选3-5条最重要、与「AI编程(AI coding)」或「具身智能(embodied AI)」相关的，用中文撰写简要快讯。

格式要求：
- 每条包含：标题 + 2-3句话说明「发生了什么」+ 1句话说明「为什么值得关注」
- 语言精炼，适合手机微信阅读
- 不输出链接或URL
- 每条控制在150字以内

今日AI新闻列表：
{items_text}"""

    body = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "你是专业的AI科技编辑，擅长用简洁中文提炼科技新闻要点。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 1500,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode())
        content = result["choices"][0]["message"]["content"]
        used = True
    except Exception:
        content, used = _basic_summary(items)
        used = False

    return content, used


def _basic_summary(items: list[dict]) -> str:
    """Fallback: simple formatting without AI."""
    lines = []
    for i, item in enumerate(items[:5], 1):
        tag = "🤖" if any(kw in item["title"] for kw in ["机器人","具身","机械","人形","Galbot","Figure","Tesla"]) else "💻"
        lines.append(f"\n{tag} {item['title']}")
        if item["desc"]:
            lines.append(f"   {item['desc'][:120]}")
    return "\n".join(lines)

# ── Main ─────────────────────────────────────────────────────────

def main():
    beijing = timezone(timedelta(hours=8))
    today = datetime.now(beijing).strftime("%m月%d日")

    print("🔍 搜索 AI 新闻...")
    all_items = []
    for q in ["AI编程 最新动态", "具身智能 机器人 最新进展", "AI coding agent 2026"]:
        all_items.extend(fetch_rss(q))

    # Deduplicate
    seen = set()
    unique = []
    for item in all_items:
        key = item["title"][:30]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    print(f"   获取 {len(unique)} 条候选新闻")

    # Summarize
    summary, used_ai = summarize_with_ai(unique)
    label = "🤖 AI精编" if used_ai else "📋 自动摘录"

    # Build final message
    header  = f"📰 AI 日报 | {today}\n"
    header += f"聚焦 AI Coding × 具身智能 | {label}\n"
    header += "─" * 22

    msg = header + summary + f"\n\n─" * 22 + "\n云端自动推送 · 电脑关机也能收"

    print(f"📝 消息共 {len(msg)} 字符")
    print("📤 推送微信...")
    n = send_to_wechat(msg)
    print(f"✅ 已推送 {n} 条消息")

if __name__ == "__main__":
    main()
