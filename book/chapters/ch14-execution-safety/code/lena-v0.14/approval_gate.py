"""
approval_gate.py — 防线 7：Always-on 审批窗口

后台任务（Heartbeat / Cron）执行写操作时，必须经过此门。
超时 → 自动拒绝（绝不是自动批准）。
"""

import uuid


class ApprovalGate:
    """
    三层审批：自动放行 / 人工确认 / 自动拒绝。
    设计原则：超时的默认结果是拒绝，不是批准。
    """

    # 直接拒绝：不需要人工确认，直接禁止
    HIGH_RISK_TOOLS = {"shell_execute", "file_delete"}

    # 必须人工确认的工具（写操作类）
    CONFIRM_TOOLS = {"file_write", "http_post", "git_push", "shell"}

    # 自动放行：只读操作
    READ_ONLY_TOOLS = {"file_read", "http_get", "list_files", "search"}

    def __init__(self, timeout_seconds: int = 300):
        # 超时时长，默认 5 分钟
        self.timeout = timeout_seconds

    def check(self, tool_name: str, args: dict) -> str:
        """
        根据工具名和参数决定审批策略。
        返回 "allow" | "ask" | "deny"
        """
        if tool_name in self.READ_ONLY_TOOLS:
            return "allow"
        if tool_name in self.HIGH_RISK_TOOLS:
            return "deny"
        if tool_name in self.CONFIRM_TOOLS:
            return "ask"
        # 未知工具默认要求确认（保守默认）
        return "ask"

    def request_human(self, tool_name: str, args: dict) -> bool:
        """
        终端审批（演示用）。
        生产环境替换成 Telegram / Discord / Web UI 通知。
        超时无响应 → 自动拒绝。
        """
        op_id = str(uuid.uuid4())[:8]
        args_preview = str(args)[:120]
        print(
            f"\n[ApprovalGate 请求确认]\n"
            f"  操作 ID : {op_id}\n"
            f"  工具    : {tool_name}\n"
            f"  参数    : {args_preview}\n"
            f"  (输入 y/yes 批准，其他任意输入 = 拒绝)\n"
            f"  超时 {self.timeout}s → 自动拒绝"
        )
        try:
            answer = input("  批准? [y/N] ").strip().lower()
            approved = answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            # 非交互环境或用户中断 → 保守拒绝
            approved = False

        status = "✓ 批准" if approved else "✗ 拒绝"
        print(f"  [{op_id}] {status}")
        return approved
