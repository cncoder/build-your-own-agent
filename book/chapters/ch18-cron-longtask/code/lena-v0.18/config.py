"""lena-v1.4 配置"""

# Mock 模式：True = 不调用真实 API，适合本地演示
MOCK_MODE = True

# Bedrock 模型（真实模式下使用）
MODEL_ID = "us.anthropic.claude-sonnet-4-6"

# 数据存储路径
DB_PATH = "data/lena.db"
TTS_CACHE_DIR = "data/tts_cache"

# Cron 表达式
CRON_FETCH_NEWS = "0 * * * *"     # 每小时整点抓新闻
CRON_SUMMARIZE = "0 0 * * *"     # 每天凌晨总结

# 新闻源
NEWS_SOURCES = [
    {"id": "hn",     "name": "Hacker News",    "url": "https://hacker-news.firebaseio.com/v0/topstories.json"},
    {"id": "github", "name": "GitHub Trending", "url": "https://github.com/trending"},
    {"id": "arxiv",  "name": "arXiv ML",        "url": "https://arxiv.org/list/cs.AI/recent"},
]
