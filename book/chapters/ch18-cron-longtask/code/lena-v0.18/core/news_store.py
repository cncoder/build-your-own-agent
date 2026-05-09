"""
news_store.py — 新闻数据存储

独立于 checkpoint 的业务存储层：
- articles 表：每小时抓取的文章（按 url 去重）
- summaries 表：凌晨的最终总结
"""

import sqlite3
import json
from datetime import datetime
from config import DB_PATH


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id          TEXT PRIMARY KEY,
                source_id   TEXT NOT NULL,
                title       TEXT NOT NULL,
                url         TEXT NOT NULL,
                fetched_at  TEXT NOT NULL,
                day         TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS summaries (
                day         TEXT PRIMARY KEY,
                content     TEXT NOT NULL,
                article_count INTEGER,
                created_at  TEXT NOT NULL
            );
        """)


def save_articles(source_id: str, articles: list[dict], day: str):
    """保存文章，按 URL 去重（INSERT OR IGNORE）"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO articles
            (id, source_id, title, url, fetched_at, day)
            VALUES (:id, :source_id, :title, :url, :fetched_at, :day)
        """, [
            {
                "id": a["id"],
                "source_id": source_id,
                "title": a["title"],
                "url": a["url"],
                "fetched_at": a["fetched_at"],
                "day": day,
            }
            for a in articles
        ])


def get_articles_for_day(day: str) -> list[dict]:
    """获取某天的所有文章（供凌晨总结使用）"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, source_id, title, url FROM articles WHERE day=? ORDER BY fetched_at",
            (day,)
        ).fetchall()
        return [{"id": r[0], "source_id": r[1], "title": r[2], "url": r[3]} for r in rows]


def save_summary(day: str, content: str, article_count: int):
    now = datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO summaries (day, content, article_count, created_at)
            VALUES (?, ?, ?, ?)
        """, (day, content, article_count, now))


def get_summary(day: str) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT content FROM summaries WHERE day=?", (day,)
        ).fetchone()
        return row[0] if row else None
