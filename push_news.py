#!/usr/bin/env python3
"""Daily AI news → WeChat push. Multi-source: search + RSS, content extraction, summarization."""

import os, json, random, re, time, ssl, html as html_mod, sys
import urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["ILINK_BOT_TOKEN"]
TO_USER   = os.environ["ILINK_USER_ID"]
BASE_URL  = "https://ilinkai.weixin.qq.com"

# ── WeChat push ──────────────────────────────────────────────────

def push_wechat(text: str):
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
            "iLink-App-Id": "bot", "iLink-App-ClientVersion": "132102",
        }
        req = urllib.request.Request(f"{BASE_URL}/ilink/bot/sendmessage", data=body, headers=headers, method="POST")
        urllib.request.urlopen(req, context=ctx)
    return len(chunks)

# ── Web helpers ──────────────────────────────────────────────────

def http_get(url: str, timeout=12) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    resp = urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=timeout)
    return resp.read().decode("utf-8", errors="replace")

def clean_html(html: str) -> str:
    """Strip HTML tags and entities, return clean text."""
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_mod.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# ── News sources ─────────────────────────────────────────────────

def search_duckduckgo(query: str, n=5) -> list[dict]:
    """Search DuckDuckGo using duckduckgo_search library."""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=n, region="cn-zh"):
                results.append({"title": r["title"], "url": r["href"], "snippet": r["body"]})
        return results
    except Exception as e:
        print(f"   DuckDuckGo搜索失败: {e}")
        return []


def fetch_rss_feeds() -> list[dict]:
    """Fetch AI news from known Chinese tech RSS feeds."""
    feeds = [
        ("https://www.jiqizhixin.com/rss", "机器之心"),
        ("https://feedx.net/rss/qbitai.xml", "量子位"),
        ("https://www.36kr.com/feed", "36氪"),
    ]

    articles = []
    try:
        import feedparser
    except ImportError:
        print("   feedparser未安装，跳过RSS")
        return articles

    for url, source in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                title = entry.get("title", "").strip()
                if not title or len(title) < 5:
                    continue
                link = entry.get("link", "")
                summary = clean_html(entry.get("summary", entry.get("description", "")))
                summary = summary[:300]
                # Filter: only AI-related
                ai_kw = ["AI", "人工智能", "大模型", "GPT", "Claude", "DeepSeek", "Copilot",
                          "机器人", "具身", "编程", "代码", "Agent", "LLM", "开源", "人形"]
                if not any(kw.lower() in (title + summary).lower() for kw in ai_kw):
                    continue
                articles.append({"title": title, "url": link, "snippet": summary, "source": source})
        except Exception as e:
            print(f"   RSS {source} 失败: {e}")

    return articles


def extract_article_content(url: str) -> str | None:
    """Fetch article and extract clean text."""
    try:
        html = http_get(url, timeout=10)
    except Exception:
        return None
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=False,
                                    favor_precision=True)
        if text and len(text) > 150:
            return text.strip()
    except Exception:
        pass
    # Fallback
    return clean_html(html)[:2500]


def discover_news() -> list[dict]:
    """Multi-source news discovery. Returns list of {title, url, snippet, content, source}."""
    all_articles = []
    seen = set()

    def add_articles(items):
        for a in items:
            key = a["title"][:40]
            if key not in seen and len(a["title"]) > 5:
                seen.add(key)
                all_articles.append(a)

    # 1. DuckDuckGo search
    print("   [1/3] DuckDuckGo 搜索...")
    for q in ["AI编程 最新进展", "具身智能 机器人 最新动态", "大模型 Agent 开源 发布"]:
        results = search_duckduckgo(q, n=4)
        add_articles(results)
        print(f"        「{q}」→ {len(results)} 条")

    # 2. RSS feeds
    print("   [2/3] RSS 源抓取...")
    rss_articles = fetch_rss_feeds()
    add_articles(rss_articles)
    print(f"        RSS → {len(rss_articles)} 条")

    if not all_articles:
        print("   [3/3] 无新闻源可用")
        return []

    # Score and rank
    ai_kw = ["AI", "编程", "代码", "Copilot", "Claude", "GPT", "DeepSeek", "Qwen",
             "具身", "机器人", "人形", "Figure", "Tesla", "灵巧手", "大模型",
             "开源", "融资", "发布", "Agent", "MCP", "具身智能", "Coding"]
    scored = []
    for a in all_articles:
        score = sum(1 for kw in ai_kw if kw.lower() in (a["title"] + a.get("snippet", "")).lower())
        scored.append((score, a))
    scored.sort(key=lambda x: x[0], reverse=True)

    # Extract content for top articles
    print(f"   [3/3] 爬取正文 (top {min(6, len(scored))})...")
    articles = []
    for score, a in scored[:6]:
        print(f"        {a['title'][:40]}...", end="")
        if not a.get("content"):
            a["content"] = extract_article_content(a["url"])
        if a.get("content"):
            print(f" ✓ ({len(a['content'])}字)")
        else:
            print(" ✗ (无内容)")
        articles.append(a)

    return articles


# ── Summarization ────────────────────────────────────────────────

def summarize(articles: list[dict]) -> str:
    """Generate summary. Tries AI first, falls back to extractive."""
    # Collect article content
    items_text = []
    for i, a in enumerate(articles):
        content = a.get("content") or a.get("snippet", "")
        if content:
            items_text.append(f"[{i+1}] {a['title']}\n{content[:800]}")

    if not items_text:
        return "⚠️ 今日未能获取有效内容。"

    full_text = "\n\n---\n\n".join(items_text)

    # Try AI
    ai_result = _ai_summarize(articles, full_text)
    if ai_result:
        return ai_result

    # Fallback: extractive
    return _extractive_summarize(articles)


def _ai_summarize(articles: list[dict], full_text: str) -> str | None:
    """Try Groq or DeepSeek API for quality summary."""
    prompt = f"""你是AI领域资深编辑。请从以下新闻原文中筛选3-5条最重要的，撰写精炼中文快讯。

格式（严格按此）：
## 标题1
发生了什么：（2-3句话）
为什么重要：（1句话）

## 标题2
发生了什么：（2-3句话）
为什么重要：（1句话）

要求：
- 聚焦AI编程(AI coding)和具身智能(embodied AI)
- 语言精炼，适合手机阅读
- 不输出任何URL
- 全文不超过600字

新闻原文：
{full_text[:5000]}"""

    configs = [
        (os.environ.get("GROQ_API_KEY"), "https://api.groq.com/openai/v1/chat/completions",
         {"model": "llama-3.3-70b-versatile", "messages": [
             {"role": "system", "content": "你是专业AI科技编辑，擅长用简洁中文提炼科技新闻要点。"},
             {"role": "user", "content": prompt}
         ], "temperature": 0.4, "max_tokens": 1000}),
        (os.environ.get("DEEPSEEK_API_KEY"), "https://api.deepseek.com/chat/completions",
         {"model": "deepseek-chat", "messages": [
             {"role": "system", "content": "你是专业AI科技编辑，擅长用简洁中文提炼科技新闻要点。"},
             {"role": "user", "content": prompt}
         ], "temperature": 0.4, "max_tokens": 1000}),
    ]

    for api_key, endpoint, payload in configs:
        if not api_key:
            continue
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                endpoint, data=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json; charset=utf-8"},
                method="POST"
            )
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"   AI API 失败: {e}")

    return None


def _extractive_summarize(articles: list[dict]) -> str:
    """Extractive: pick key sentences per article."""
    lines = []
    for a in articles[:5]:
        content = a.get("content") or a.get("snippet", "")
        if not content or len(content) < 30:
            continue

        # Classify
        title_lower = a["title"].lower()
        if any(kw in title_lower for kw in ["机器人","具身","人形","机械臂","figure","tesla","灵巧"]):
            emoji = "🤖"
        elif any(kw in title_lower for kw in ["融资","收购","市值","股价","亿"]):
            emoji = "💰"
        elif any(kw in title_lower for kw in ["开源","发布","推出"]):
            emoji = "🚀"
        else:
            emoji = "💻"

        lines.append(f"\n{emoji} {a['title']}")

        # Extract key sentences
        sentences = re.split(r'[。！？\n]', content)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 12]
        picked = []
        for s in sentences:
            if len(picked) >= 3:
                break
            if s not in picked and len(s) > 15:
                # Prefer sentences with data or key terms
                if re.search(r'[\d万亿%亿美元倍]|[A-Z][a-z]{3,}|发布|推出|突破|首次|融资|开源', s):
                    picked.append(s)
        # If not enough, just take first sentences
        if len(picked) < 2:
            picked = sentences[:3]

        for s in picked:
            lines.append(f"  · {s}")

    return "\n".join(lines) if lines else "⚠️ 今日未能获取有效内容。"


# ── Main ─────────────────────────────────────────────────────────

def main():
    beijing = timezone(timedelta(hours=8))
    today = datetime.now(beijing).strftime("%m月%d日")

    print("🔍 收集新闻...")
    articles = discover_news()

    if not articles:
        push_wechat(f"📰 AI 日报 | {today}\n\n⚠️ 今日暂无AI领域重要新闻。")
        return

    print(f"\n📝 生成摘要 ({len(articles)} 篇)...")
    summary = summarize(articles)

    label = "🤖 AI精编" if (os.environ.get("GROQ_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")) else "📋 智能提取"

    msg = f"📰 AI 日报 | {today} | {label}\n聚焦 AI Coding × 具身智能\n"
    msg += summary
    msg += f"\n\n── 云端自动 · 电脑关机也能收 ──"

    print(f"   {len(msg)} 字符 → 推送微信")
    n = push_wechat(msg)
    print(f"✅ 已推送 {n} 条消息")

if __name__ == "__main__":
    main()
