"""
fetch_news.py — 每小时新闻抓取任务

支持断点续传：
- 已完成的 source 直接跳过（load_completed_steps）
- 新完成的 source 立即落盘（save_checkpoint）
- content-hash 缓存：相同 source+day 不重复抓取
"""

import hashlib
import time
import random
import logging
from datetime import datetime

from core.checkpoint import (
    create_task, start_task, save_checkpoint,
    complete_task, fail_task, load_completed_steps
)
from core.news_store import save_articles
from core.content_hash_cache import ContentHashCache
from config import NEWS_SOURCES, MOCK_MODE

logger = logging.getLogger(__name__)

article_cache = ContentHashCache("data/article_cache")


def run():
    """每小时调用一次。生成 task_id = news-YYYY-MM-DD-HH"""
    now = datetime.now()
    task_id = f"news-{now.strftime('%Y-%m-%d-%H')}"
    day = now.strftime("%Y-%m-%d")

    logger.info(f"[fetch_news] 开始，task_id={task_id}")

    create_task(task_id, total_steps=len(NEWS_SOURCES))
    start_task(task_id)

    # 崩溃恢复：获取已完成步骤
    completed = load_completed_steps(task_id)
    if completed:
        logger.info(f"[fetch_news] 发现 {len(completed)} 个已完成步骤，续传...")

    try:
        for i, source in enumerate(NEWS_SOURCES):
            step_id = f"fetch_{source['id']}"

            if step_id in completed:
                logger.info(f"[skip] {source['name']} 已完成")
                continue

            # content-hash 缓存检查（跨天幂等）
            cache_hit = article_cache.get(source["id"], day)
            if cache_hit:
                logger.info(f"[cache hit] {source['name']} (day={day})")
                articles = cache_hit["data"]
            else:
                logger.info(f"[fetch] 抓取 {source['name']}...")
                articles = _fetch_source(source["id"])
                article_cache.set(articles, source["id"], day)

            save_articles(source["id"], articles, day)

            progress = int((i + 1) / len(NEWS_SOURCES) * 100)
            save_checkpoint(
                task_id=task_id,
                step_id=step_id,
                data={"source": source["id"], "count": len(articles)},
                progress=progress,
            )
            logger.info(f"[checkpoint] {source['name']}: {len(articles)} 篇，进度 {progress}%")

        complete_task(task_id)
        logger.info(f"[fetch_news] 完成，task_id={task_id}")

    except Exception as e:
        fail_task(task_id, str(e))
        logger.error(f"[fetch_news] 失败: {e}", exc_info=True)
        raise


def _fetch_source(source_id: str) -> list[dict]:
    """
    Mock 实现。真实项目替换为：
    - HN: requests.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    - GitHub: requests.get("https://github.com/trending") + BeautifulSoup
    - arXiv: feedparser.parse("https://arxiv.org/rss/cs.AI")
    """
    if MOCK_MODE:
        time.sleep(0.1)  # 模拟网络延迟
        return [
            {
                "id": hashlib.sha256(f"{source_id}-{i}-{time.time()}".encode()).hexdigest()[:12],
                "title": f"[Mock] {source_id} 文章 #{i+1}",
                "url": f"https://example.com/{source_id}/{i}",
                "fetched_at": datetime.now().isoformat(),
            }
            for i in range(random.randint(5, 12))
        ]
    # 真实实现：按 source_id 分支调用对应 API
    raise NotImplementedError(f"真实抓取未实现: {source_id}")
