"""
scheduler.py — croniter 调度器

核心：while True 每秒检查是否有任务到期。
设计原则：
- 任务失败不影响调度循环继续运行
- 每次触发后立即计算下次执行时间
- 支持快速测试模式（FAST_MODE=True，每 10 秒触发一次）
"""

import time
import logging
from croniter import croniter
from datetime import datetime

logger = logging.getLogger(__name__)


class TaskScheduler:
    def __init__(self, fast_mode: bool = False):
        """
        fast_mode: True 时覆盖所有 cron 为每 10 秒，用于本地演示
        """
        self.jobs: list[dict] = []
        self.fast_mode = fast_mode

    def add_job(self, cron_expr: str, func, name: str):
        expr = "*/10 * * * * *" if self.fast_mode else cron_expr  # croniter 支持秒级（6字段）
        # fast_mode 用更短间隔，但 croniter 5字段不支持秒，改用简单计时
        self.jobs.append({
            "name": name,
            "cron_expr": cron_expr,
            "func": func,
            "iter": croniter(cron_expr, datetime.now()),
            "next_run": None,
            "interval_sec": 10 if fast_mode else None,  # fast_mode 固定间隔
            "last_run": None,
        })

    def _compute_next(self, job: dict) -> datetime:
        if job["interval_sec"]:
            # fast_mode：固定间隔
            from datetime import timedelta
            base = job["last_run"] or datetime.now()
            return base + timedelta(seconds=job["interval_sec"])
        return job["iter"].get_next(datetime)

    def run_forever(self):
        if not self.jobs:
            logger.warning("没有注册任何任务，调度器退出")
            return

        logger.info(f"调度器启动 {'[FAST MODE]' if self.fast_mode else ''}，共 {len(self.jobs)} 个任务")

        for job in self.jobs:
            job["next_run"] = self._compute_next(job)
            logger.info(f"  [{job['name']}] cron={job['cron_expr']}，下次执行：{job['next_run']}")

        while True:
            now = datetime.now()
            for job in self.jobs:
                if now >= job["next_run"]:
                    logger.info(f"▶ 触发任务：{job['name']}")
                    try:
                        job["func"]()
                        logger.info(f"✓ 任务完成：{job['name']}")
                    except Exception as e:
                        logger.error(f"✗ 任务失败：{job['name']} — {e}")
                    finally:
                        job["last_run"] = now
                        job["next_run"] = self._compute_next(job)
                        logger.info(f"  [{job['name']}] 下次执行：{job['next_run']}")
            time.sleep(1)
