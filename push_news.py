#!/usr/bin/env python3
"""Cloud-based AI news push to WeChat via ilink bot API.
Runs entirely on GitHub Actions - no local computer needed."""

import os, json, hashlib, random, time, urllib.request, urllib.parse, ssl
from datetime import datetime, timezone, timedelta

# --- Config ---
BOT_TOKEN = os.environ["ILINK_BOT_TOKEN"]
TO_USER = os.environ["ILINK_USER_ID"]
BASE_URL = "https://ilinkai.weixin.qq.com"

# --- Helpers ---
def random_wechat_uin():
    return str(random.randint(10000000, 99999999))

def build_client_id():
    return f"cbc-{int(time.time()*1000)}-{random.randint(100000,999999):x}"

def build_headers():
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": random_wechat_uin(),
        "Authorization": f"Bearer {BOT_TOKEN}",
        "iLink-App-Id": "bot",
        "iLink-App-ClientVersion": "132102",
    }

def chunk_text(s, size=4000):
    return [s[i:i+size] for i in range(0, len(s), size)]

def send_to_wechat(text):
    chunks = chunk_text(text)
    ctx = ssl.create_default_context()
    for c in chunks:
        body = json.dumps({
            "base_info": {"channel_version": "2.4.6", "bot_agent": "OpenClaw"},
            "msg": {
                "from_user_id": "", "to_user_id": TO_USER,
                "client_id": build_client_id(),
                "message_type": 2, "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"text": c}}],
                "context_token": "",
            }
        }).encode()
        req = urllib.request.Request(
            f"{BASE_URL}/ilink/bot/sendmessage",
            data=body, headers=build_headers(), method="POST"
        )
        resp = urllib.request.urlopen(req, context=ctx)
        raw = resp.read().decode()
        if resp.status != 200:
            raise Exception(f"HTTP {resp.status}: {raw}")
        try:
            j = json.loads(raw)
            if j.get("ret", 0) != 0:
                raise Exception(f"API ret={j['ret']}")
        except json.JSONDecodeError:
            pass
    return len(chunks)

# --- News Search ---
def fetch_ai_news():
    """Fetch and compose AI news summary focused on AI coding + embodied intelligence."""
    beijing_tz = timezone(timedelta(hours=8))
    today = datetime.now(beijing_tz).strftime("%Y年%m月%d日")

    news_items = []

    # Search for AI coding news
    queries = [
        ("AI coding 最新动态", "AI编程"),
        ("具身智能 最新进展", "具身智能"),
        ("embodied AI robotics news", "具身智能/机器人"),
    ]

    ctx = ssl.create_default_context()
    for query, tag in queries:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://news.google.com/rss/search?q={encoded}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, context=ctx, timeout=15)
            data = resp.read().decode("utf-8", errors="ignore")

            import xml.etree.ElementTree as ET
            root = ET.fromstring(data)
            for item in root.findall(".//item"):
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                pubdate = item.findtext("pubDate", "")
                desc = item.findtext("description", "")
                # Clean description
                if desc:
                    desc = desc.split("</a>")[-1] if "</a>" in desc else desc
                    desc = desc.strip()[:200]
                news_items.append({
                    "title": title, "link": link, "tag": tag,
                    "pubdate": pubdate, "desc": desc
                })
        except Exception as e:
            print(f"  [WARN] Search '{query}' failed: {e}")

    # Deduplicate by title similarity
    seen = set()
    unique = []
    for item in news_items:
        key = item["title"][:40]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # Take top 5
    top = unique[:5]

    # Compose message
    header = f"📰 每日 AI 新闻速报 | {today}\n聚焦：AI Coding × 具身智能\n"
    sep = "─" * 24

    lines = [header, sep, ""]
    for i, item in enumerate(top, 1):
        tag_emoji = "🤖" if "具身" in item["tag"] else "💻"
        lines.append(f"{tag_emoji} {i}. {item['title']}")
        if item["desc"]:
            lines.append(f"   {item['desc']}")
        lines.append(f"   🔗 {item['link']}")
        lines.append("")

    if not top:
        lines.append("⚠️ 今日未能获取到新闻数据，请稍后重试。")
    else:
        lines.append(f"{sep}")
        lines.append(f"共筛选 {len(top)} 条 | 由 GitHub Actions 云端自动推送")

    return "\n".join(lines)

# --- Main ---
if __name__ == "__main__":
    print("🔍 搜索 AI 新闻...")
    msg = fetch_ai_news()
    print(f"📝 新闻整理完成，共 {len(msg)} 字符")
    print("📤 推送至微信...")
    n = send_to_wechat(msg)
    print(f"✅ 已推送 {n} 条消息到微信")
