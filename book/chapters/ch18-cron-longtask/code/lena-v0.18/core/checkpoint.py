"""
checkpoint.py — SQLite 持久化引擎

实现 LangGraph Durable Execution 思想的简化版：
- 每步完成后立即落盘
- 崩溃后从最后一个成功 checkpoint 恢复
- UNIQUE(task_id, step_id) 保证幂等性
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from config import DB_PATH


def init_db():
    """初始化数据库，创建表结构（幂等）"""
    db = Path(DB_PATH)
    db.parent.mkdir(exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS task_state (
                task_id      TEXT PRIMARY KEY,
                status       TEXT NOT NULL,
                checkpoint   TEXT,
                progress     INTEGER DEFAULT 0,
                total_steps  INTEGER DEFAULT 0,
                error_msg    TEXT,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_results (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id      TEXT NOT NULL,
                step_id      TEXT NOT NULL,
                result_data  TEXT,
                completed_at TEXT NOT NULL,
                UNIQUE(task_id, step_id)
            );
        """)


def create_task(task_id: str, total_steps: int):
    """创建一个新任务（或复用已有未完成任务）"""
    now = datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO task_state
            (task_id, status, progress, total_steps, created_at, updated_at)
            VALUES (?, 'pending', 0, ?, ?, ?)
        """, (task_id, total_steps, now, now))


def start_task(task_id: str):
    now = datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE task_state SET status='running', updated_at=? WHERE task_id=?
        """, (now, task_id))


def save_checkpoint(task_id: str, step_id: str, data: dict, progress: int):
    """
    保存一个步骤的结果。
    使用 INSERT OR IGNORE 保证幂等性：同一步骤重复写入不报错。
    """
    now = datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO task_results
            (task_id, step_id, result_data, completed_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, step_id, json.dumps(data), now))

        conn.execute("""
            UPDATE task_state
            SET status='checkpoint_saved',
                checkpoint=?,
                progress=?,
                updated_at=?
            WHERE task_id=?
        """, (json.dumps({"last_step": step_id}), progress, now, task_id))


def complete_task(task_id: str):
    now = datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE task_state
            SET status='completed', progress=100, updated_at=?
            WHERE task_id=?
        """, (now, task_id))


def fail_task(task_id: str, error_msg: str):
    now = datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE task_state
            SET status='failed', error_msg=?, updated_at=?
            WHERE task_id=?
        """, (error_msg, now, task_id))


def load_completed_steps(task_id: str) -> set:
    """
    崩溃恢复关键函数：返回已完成的步骤 ID 集合。
    任务重启时遍历步骤前先调用，命中 completed 的步骤直接跳过。
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT step_id FROM task_results WHERE task_id=?",
                (task_id,)
            ).fetchall()
            return {row[0] for row in rows}
    except Exception:
        return set()


def get_task_state(task_id: str) -> dict | None:
    """获取任务当前状态（调试/面板展示用）"""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT * FROM task_state WHERE task_id=?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        cols = ["task_id", "status", "checkpoint", "progress",
                "total_steps", "error_msg", "created_at", "updated_at"]
        return dict(zip(cols, row))
