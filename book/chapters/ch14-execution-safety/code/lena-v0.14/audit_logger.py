"""
audit_logger.py — 防线 8：append-only 结构化审计日志

设计要点：
- append-only（不修改已有记录）
- 立即 flush（防止进程崩溃丢失最后几条）
- 完整输入（事故复盘时知道"当时传了什么参数"）
"""

import json
import time
from pathlib import Path
from typing import Any


class AuditLogger:
    """
    结构化审计日志，写入 JSONL 格式文件。
    每条记录独立完整，支持按 session_id 过滤回放。
    """

    def __init__(self, log_path: str = "audit.jsonl"):
        self.log_path = Path(log_path)

    def record(
        self,
        session_id: str,
        tool_name: str,
        tool_input: dict,
        decision: str,           # "allowed" | "blocked" | "approved" | "denied"
        decision_reason: str,
        tool_output: Any = None,
    ) -> None:
        entry = {
            "ts": round(time.time(), 3),
            "session_id": session_id,
            "tool": tool_name,
            "input": tool_input,
            "decision": decision,
            "reason": decision_reason,
            # 输出只保留前 500 字符，避免日志膨胀
            "output_preview": str(tool_output)[:500] if tool_output is not None else None,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()   # 立即落盘，防止进程崩溃丢日志

    def replay(self, session_id: str) -> list[dict]:
        """回放指定 session 的完整调用链，用于事故复盘。"""
        if not self.log_path.exists():
            return []
        results = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if entry.get("session_id") == session_id:
                    results.append(entry)
            except json.JSONDecodeError:
                pass
        return results

    def stats(self) -> dict:
        """汇总统计：各 decision 类型数量。"""
        if not self.log_path.exists():
            return {}
        counts: dict[str, int] = {}
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                d = entry.get("decision", "unknown")
                counts[d] = counts.get(d, 0) + 1
            except json.JSONDecodeError:
                pass
        return counts
