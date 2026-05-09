"""
summarize.py — 凌晨总结任务

汇总当天所有小时抓取的新闻，生成一份每日摘要。
支持 mock 模式（不调用 Bedrock）。
"""

import logging
from datetime import datetime, timedelta

from core.checkpoint import create_task, start_task, complete_task, fail_task
from core.news_store import get_articles_for_day, save_summary
from config import MOCK_MODE, MODEL_ID

logger = logging.getLogger(__name__)


def run():
    """每天凌晨调用一次。总结昨天的文章。"""
    # 凌晨总结昨天
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    task_id = f"summarize-{yesterday}"

    logger.info(f"[summarize] 开始，day={yesterday}")
    create_task(task_id, total_steps=1)
    start_task(task_id)

    try:
        articles = get_articles_for_day(yesterday)
        if not articles:
            logger.warning(f"[summarize] {yesterday} 没有文章，跳过")
            complete_task(task_id)
            return

        summary = _generate_summary(articles, yesterday)
        save_summary(yesterday, summary, len(articles))
        complete_task(task_id)
        logger.info(f"[summarize] 完成：{len(articles)} 篇文章 → {len(summary)} 字摘要")

    except Exception as e:
        fail_task(task_id, str(e))
        logger.error(f"[summarize] 失败: {e}", exc_info=True)
        raise


def _generate_summary(articles: list[dict], day: str) -> str:
    if MOCK_MODE:
        sources = {}
        for a in articles:
            sources.setdefault(a["source_id"], []).append(a["title"])

        lines = [f"# {day} 每日新闻摘要（Mock）\n"]
        lines.append(f"共采集 {len(articles)} 篇文章，来源：{', '.join(sources.keys())}\n")
        for source_id, titles in sources.items():
            lines.append(f"\n## {source_id.upper()}")
            for t in titles[:3]:
                lines.append(f"- {t}")
            if len(titles) > 3:
                lines.append(f"  ... 共 {len(titles)} 篇")
        return "\n".join(lines)

    # 真实实现：调用 Bedrock Converse API
    import boto3
    bedrock = boto3.client("bedrock-runtime", region_name="us-west-2")

    article_list = "\n".join(
        f"[{a['source_id']}] {a['title']} — {a['url']}"
        for a in articles[:50]  # 截断防超出 context window
    )
    prompt = f"""请对以下 {day} 的新闻标题生成简洁的每日摘要（中文，500字以内）：

{article_list}"""

    resp = bedrock.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
    )
    return resp["output"]["message"]["content"][0]["text"]
