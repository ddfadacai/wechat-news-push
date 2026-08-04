# 每日 AI 新闻 → 微信推送

云端自动化：每天 8:30 搜索 AI 新闻，推送到微信 ClawBot。

## 原理

GitHub Actions 定时运行 → 搜索 AI 新闻 → 通过 ilink API 推送微信。

**无需电脑开机。**

## 部署

```bash
# 1. 在 GitHub 创建新仓库 (如 wechat-news-push)，不要勾选初始化

# 2. 推送代码
git remote add origin https://github.com/YOUR_USERNAME/wechat-news-push.git
git push -u origin main

# 3. 在仓库 Settings → Secrets and variables → Actions 添加两个 Secrets:
#    ILINK_BOT_TOKEN = d68518f37021@im.bot:0600001f8da3af0f7d2816477d70bd549486c1
#    ILINK_USER_ID   = o9cq80-jGIQ1Akh7YFqTmk1mjCvc@im.wechat

# 4. 手动触发一次测试: Actions → 每日AI新闻推送 → Run workflow
```
