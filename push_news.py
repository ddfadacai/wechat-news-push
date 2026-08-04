#!/usr/bin/env python3
"""Daily AI news → WeChat push. Crawls articles, extracts content, summarizes."""

import os, json, random, re, time, ssl, html as html_mod
import urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["ILINK_BOT_TOKEN"]
TO_USER   = os.environ["ILINK_USER_ID"]
BASE_URL  = "https://ilinkai.weixin.qq.com"
GROQ_KEY  = os.environ.get("GROQ_API_KEY", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# ── WeChat push ──────────────────────────────────────────────────

def push_wechat(text: str):
    """Push text to WeChat ClawBot via ilink API."""
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

def fetch_url(url: str, timeout=10) -> str:
    """Fetch URL and return text content."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)",
        "Accept": "text/html,application/xhtml+xml",
    })
    resp = urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=timeout)
    return resp.read().decode("utf-8", errors="replace")

def search_ddg(query: str, n=8) -> list[dict]:
    """Search DuckDuckGo HTML and return list of {title, url, snippet}."""
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    html = fetch_url(url, timeout=15)
    results = []
    # Parse DDG HTML results
    # Each result is in <a class="result__a"> for title/url and <a class="result__snippet"> for snippet
    title_pattern = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)

    titles = title_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (href, title) in enumerate(titles[:n]):
        title = re.sub(r'<[^>]+>', '', title).strip()
        if not title:
            continue
        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
        # DDG URLs are wrapped in redirect
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        real_url = qs.get('uddg', [href])[0]
        results.append({"title": title, "url": real_url, "snippet": snippet})
    return results

# ── Content extraction ───────────────────────────────────────────

def extract_article(url: str) -> str | None:
    """Fetch article and extract clean text content."""
    try:
        html = fetch_url(url, timeout=12)
    except Exception:
        return None

    # Try trafilatura first
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text and len(text) > 200:
            return text.strip()
    except ImportError:
        pass

    # Fallback: basic HTML text extraction
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_mod.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:3000] if text else None

# ── Summarization ────────────────────────────────────────────────

def summarize_articles(articles: list[dict]) -> str:
    """Summarize articles using AI (if key available) or extractive method."""
    # Build combined content
    combined = []
    for i, a in enumerate(articles):
        content = a.get("content", a.get("snippet", ""))
        if content:
            combined.append(f"[{i+1}] 标题：{a['title']}\n内容：{content[:1000]}")
    full_text = "\n\n---\n\n".join(combined)

    # Try AI summarization
    ai_summary = _try_ai_summary(articles, full_text)
    if ai_summary:
        return ai_summary

    # Fallback: extractive summary using textrank
    return _extractive_summary(articles)


def _try_ai_summary(articles: list[dict], full_text: str) -> str | None:
    """Try AI summarization via Groq or DeepSeek."""
    prompt = f"""你是AI领域资深编辑。以下是今日AI领域（侧重AI编程、具身智能）的新闻原文，请筛选3-5条最重要的，用中文撰写精炼快讯。

要求：
- 每条1个小标题 + 用2-3句话说明核心内容 + 1句话点出「为什么值得关注」
- 语言精简，适合手机微信阅读，不要输出任何URL
- 用「## 」开头作为分隔，如「## 标题」
- 全文不超过800字

新闻原文：
{full_text[:4000]}"""

    api_configs = [
        # Try Groq first
        (GROQ_KEY, "https://api.groq.com/openai/v1/chat/completions",
         {"model": "llama-3.3-70b-versatile", "messages": [
             {"role": "system", "content": "你是专业科技编辑，用简洁中文提炼AI新闻。"},
             {"role": "user", "content": prompt}
         ], "temperature": 0.5, "max_tokens": 1200}),
        # Try DeepSeek
        (DEEPSEEK_KEY, "https://api.deepseek.com/chat/completions",
         {"model": "deepseek-chat", "messages": [
             {"role": "system", "content": "你是专业科技编辑，用简洁中文提炼AI新闻。"},
             {"role": "user", "content": prompt}
         ], "temperature": 0.5, "max_tokens": 1200}),
    ]

    for api_key, endpoint, payload in api_configs:
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
            content = result["choices"][0]["message"]["content"]
            return content.strip()
        except Exception as e:
            print(f"   AI API ({endpoint}) 失败: {e}")

    return None


def _extractive_summary(articles: list[dict]) -> str:
    """Extractive summarization: extract key sentences from articles."""
    lines = []
    for i, a in enumerate(articles[:5], 1):
        content = a.get("content", a.get("snippet", ""))
        if not content or len(content) < 30:
            continue

        # Extract 2-3 key sentences
        sentences = re.split(r'[。！？\n]', content)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 15]

        tag_emoji = "🤖" if any(kw in a['title'] for kw in ["机器人","具身","人形","机械臂","Figure","Tesla"]) else "💻"
        lines.append(f"\n{tag_emoji} {a['title']}")

        # Pick sentences: first + longest meaningful
        key_sentences = []
        if sentences:
            key_sentences.append(sentences[0])
        # Add 1-2 more informative sentences
        for s in sentences[1:]:
            if len(key_sentences) >= 3:
                break
            if len(s) > 25 and s not in key_sentences:
                # Prefer sentences with numbers, names, or key terms
                if re.search(r'[\d万亿%亿美元]|[A-Z][a-z]{3,}|发布|推出|突破|融资|开源|收购', s):
                    key_sentences.append(s)

        for s in key_sentences:
            lines.append(f"  {s}")

    return "\n".join(lines)


# ── News discovery ───────────────────────────────────────────────

def discover_articles(queries: list[str]) -> list[dict]:
    """Search for articles, deduplicate, extract content."""
    all_articles = []
    seen_urls = set()

    for query in queries:
        print(f"   搜索: {query}")
        results = search_ddg(query, n=5)
        for r in results:
            if r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            all_articles.append(r)

    if not all_articles:
        return []

    # Score and rank: prefer articles with meaningful titles
    scored = []
    for a in all_articles:
        score = 0
        title = a["title"]
        # Prefer Chinese content
        if re.search(r'[\u4e00-\u9fff]', title):
            score += 3
        # Prefer AI-coding / embodied intelligence related
        keywords = ["AI", "编程", "代码", "Copilot", "Claude", "GPT", "DeepSeek", "Qwen",
                     "具身", "机器人", "人形", "Figure", "Tesla Bot", "灵巧手", "大模型",
                     "开源", "融资", "发布", "Agent", "MCP", "具身智能"]
        for kw in keywords:
            if kw.lower() in title.lower():
                score += 1
        # Penalize generic titles
        if len(title) < 8:
            score -= 2
        scored.append((score, a))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Extract content for top articles
    articles = []
    for score, a in scored[:8]:
        print(f"   爬取: {a['title'][:40]}...")
        content = extract_article(a["url"])
        a["content"] = content
        articles.append(a)
        if len(articles) >= 6:
            break

    return articles


# ── Main ─────────────────────────────────────────────────────────

def main():
    beijing = timezone(timedelta(hours=8))
    today = datetime.now(beijing).strftime("%m月%d日")

    queries = [
        "AI编程 最新进展 2026",
        "具身智能 机器人 最新动态",
        "AI coding agent 大模型 发布 开源",
    ]

    print("🔍 搜索...")
    articles = discover_articles(queries)

    if not articles:
        print("❌ 未获取到新闻")
        push_wechat(f"📰 AI 日报 | {today}\n\n⚠️ 今日暂无AI新闻数据。")
        return

    print(f"\n📝 总结中 ({len(articles)} 篇文章)...")
    summary = summarize_articles(articles)

    # Build final message
    has_ai = bool(GROQ_KEY or DEEPSEEK_KEY)
    label = "🤖 AI 精编" if has_ai else "📋 智能提取"

    msg = f"📰 AI 日报 | {today}\n聚焦 AI Coding × 具身智能 | {label}\n"
    msg += summary
    msg += f"\n\n── 云端自动推送 · 无需电脑开机 ──"

    print(f"   {len(msg)} 字符")
    print("📤 推送微信...")
    n = push_wechat(msg)
    print(f"✅ 已推送 {n} 条消息")


if __name__ == "__main__":
    main()
