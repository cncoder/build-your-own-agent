"""
exec_approvals.py — session 级批准记忆

对应 OpenClaw infra/exec-approvals.ts
设计原则：
- 首次执行请求用户审批
- session 内相同命令模式自动通过
- session 结束（或显式 clear）后重置
"""

import hashlib
import re
from dataclasses import dataclass, field


@dataclass
class ApprovalStore:
    """
    session 级批准记忆。
    使用命令模式（去掉具体参数中的变量部分）作为 key，
    避免"批准了 process_image_001.jpg 不代表批准了 rm -rf"的混淆。
    """
    _approvals: dict[str, set[str]] = field(default_factory=dict)

    def _pattern_key(self, command: str) -> str:
        """
        提取命令模式。
        例：
          "python3 process_image_001.jpg" → "python3 *.jpg"
          "python3 analyze.py"            → "python3 *.py"
          "ls /tmp/output"                → "ls /tmp/*"
        粗粒度归一化，减少重复审批次数。
        """
        # 路径参数归一化：/tmp/xxx → /tmp/*
        cmd = re.sub(r'/\S+', lambda m: re.sub(r'/[^/]+$', '/*', m.group()), command)
        # 文件名归一化：foo_001.jpg → *.jpg
        cmd = re.sub(r'\b\w+\.\w+\b', lambda m: '*.' + m.group().rsplit('.', 1)[-1], cmd)
        # 数字参数归一化
        cmd = re.sub(r'\b\d+\b', 'N', cmd)
        return cmd

    def is_approved(self, session_id: str, command: str) -> bool:
        pattern = self._pattern_key(command)
        return pattern in self._approvals.get(session_id, set())

    def approve(self, session_id: str, command: str) -> None:
        pattern = self._pattern_key(command)
        if session_id not in self._approvals:
            self._approvals[session_id] = set()
        self._approvals[session_id].add(pattern)
        print(f"[exec-approvals] 已记忆：session={session_id[:8]}… pattern={pattern!r}")

    def clear_session(self, session_id: str) -> None:
        self._approvals.pop(session_id, None)
        print(f"[exec-approvals] session={session_id[:8]}… 批准记录已清除")

    def approved_patterns(self, session_id: str) -> list[str]:
        return sorted(self._approvals.get(session_id, set()))


def ask_user_approval(command: str, language: str) -> bool:
    """终端交互：向用户展示命令并请求确认"""
    print(f"\n{'='*60}")
    print(f"⚠  Lena 要在 Docker 沙箱内执行以下代码：")
    print(f"   语言：{language}")
    print(f"   命令：{command[:200]}{'…' if len(command) > 200 else ''}")
    print(f"{'='*60}")
    answer = input("允许执行？[y/N/always(本次会话始终允许)] ").strip().lower()
    return answer in ("y", "yes", "always"), answer == "always"
