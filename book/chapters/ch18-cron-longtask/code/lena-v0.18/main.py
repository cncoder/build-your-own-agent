#!/usr/bin/env python3
"""
lena-v1.4 — 每小时抓新闻，凌晨总结

本章产物：跨天长任务，croniter 调度 + SQLite checkpoint + content-hash 缓存

运行方式：
  python3 main.py              # 生产模式（按真实 cron 触发）
  python3 main.py --fast       # 快速演示（每 10 秒触发一次）
  python3 main.py --once fetch # 立即执行一次 fetch_news
  python3 main.py --once summarize  # 立即执行一次总结
  python3 main.py --status     # 查看所有任务状态
"""

import sys
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    args = sys.argv[1:]
    fast_mode = "--fast" in args

    # 初始化数据库
    from core.checkpoint import init_db as init_checkpoint_db
    from core.news_store import init_db as init_news_db
    init_checkpoint_db()
    init_news_db()

    # 一次性执行模式
    if "--once" in args:
        idx = args.index("--once")
        target = args[idx + 1] if idx + 1 < len(args) else "fetch"
        if target == "fetch":
            logger.info("立即执行 fetch_news...")
            from tasks.fetch_news import run
            run()
        elif target == "summarize":
            logger.info("立即执行 summarize...")
            from tasks.summarize import run
            run()
        return

    # 状态查看模式
    if "--status" in args:
        _print_status()
        return

    # 正常调度模式
    from scheduler import TaskScheduler
    from tasks.fetch_news import run as fetch_run
    from tasks.summarize import run as summarize_run
    from config import CRON_FETCH_NEWS, CRON_SUMMARIZE

    scheduler = TaskScheduler(fast_mode=fast_mode)
    scheduler.add_job(CRON_FETCH_NEWS, fetch_run, name="fetch_news")
    scheduler.add_job(CRON_SUMMARIZE, summarize_run, name="summarize")

    if fast_mode:
        logger.info("⚡ 快速演示模式：每 10 秒触发一次任务")

    scheduler.run_forever()


def _print_status():
    """打印所有任务状态"""
    from config import DB_PATH
    if not Path(DB_PATH).exists():
        print("数据库不存在，还没有任何任务记录")
        return

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT task_id, status, progress, total_steps, updated_at, error_msg
            FROM task_state ORDER BY updated_at DESC LIMIT 20
        """).fetchall()

    if not rows:
        print("没有任务记录")
        return

    print(f"\n{'TASK ID':<30} {'STATUS':<20} {'PROGRESS':<10} {'UPDATED':<20}")
    print("-" * 85)
    for r in rows:
        task_id, status, progress, total, updated, err = r
        progress_str = f"{progress}/{total * 100 // 100 if total else 0}%" if total else f"{progress}%"
        err_str = f" [{err[:30]}]" if err else ""
        print(f"{task_id:<30} {status:<20} {progress_str:<10} {updated[:19]}{err_str}")


if __name__ == "__main__":
    main()
