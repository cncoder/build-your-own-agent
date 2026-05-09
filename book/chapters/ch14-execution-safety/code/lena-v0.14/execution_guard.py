"""
execution_guard.py — 八道防线统一入口（防线 1/3/4）

每次工具调用必须经过 ExecutionGuard.check()，通过后才执行。
调用方模式：
    decision = guard.check(call)
    if not decision.allowed: raise SecurityError(decision.reason)
    if decision.requires_approval: await approval_gate.request(...)
    else: execute(call)
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ToolCall:
    tool_name: str       # 工具名，如 "shell"、"file_write"
    tool_input: dict     # 工具参数
    session_id: str      # 当前会话 ID，用于链式追踪
    timestamp: float = field(default_factory=time.time)


@dataclass
class GuardDecision:
    allowed: bool
    reason: str              # 拒绝原因，或 "ok"
    requires_approval: bool  # True = 需要人类确认后才执行
    risk_level: str          # "low" | "medium" | "high" | "critical"


class ExecutionGuard:
    """
    八道防线的统一入口（防线 1、3、4 在此实现）。
    其余防线（2、5、6、7、8）通过组合独立模块实现。
    """

    # 防线 1：高危 shell 模式（立即拒绝，无需人工审批）
    BLOCKED_SHELL_PATTERNS = [
        r"curl.*\|\s*(ba)?sh",             # 下载并执行
        r"wget.*\|\s*(ba)?sh",
        r"/var/run/docker\.sock",           # docker socket 挂载 → 容器逃逸
        r"--privileged",                    # 容器特权模式
        r"--cap-add\s+SYS_ADMIN",          # 危险 Linux capability
        r"--security-opt.*seccomp=unconfined",  # 禁用 seccomp
        r"base64.*\|\s*(ba)?sh",           # base64 编码后执行
        r"/proc/self/environ",             # 通过 /proc 读取环境变量
    ]

    # 防线 1（软）：需要人工确认的 shell 操作
    CONFIRM_SHELL_PATTERNS = [
        r"\brm\s",       # 任何删除
        r">\s",          # 输出重定向（覆盖文件）
        r"git\s+push",   # 推送代码
        r"docker\s+run", # 启动容器
    ]

    # 防线 3：敏感路径组件（文件路径含这些字符串 → 立即拒绝）
    SENSITIVE_PATH_COMPONENTS = [
        ".env", ".ssh", ".aws", ".kube", ".gnupg", ".docker",
        "credentials", "id_rsa", "id_ed25519", "private_key",
    ]

    def __init__(self, workspace_dir: str, session_id: str):
        # workspace 必须是绝对路径，防止相对路径绕过
        self.workspace = Path(workspace_dir).resolve()
        self.session_id = session_id
        self._call_chain: list[ToolCall] = []   # 防线 4：执行链历史
        self.workspace.mkdir(parents=True, exist_ok=True)

    def check(self, call: ToolCall) -> GuardDecision:
        """统一检查入口，依次经过各道防线。"""
        self._call_chain.append(call)            # 防线 4：先记录再检查

        if call.tool_name == "shell":
            decision = self._check_shell(call)
        elif call.tool_name in ("file_read", "file_write", "file_delete"):
            decision = self._check_file(call)
        else:
            decision = GuardDecision(True, "ok", False, "low")

        # 防线 4：单步通过后，再做链式风险检测
        if decision.allowed:
            chain_dec = self._check_chain_risk()
            if not chain_dec.allowed:
                return chain_dec

        return decision

    def _check_shell(self, call: ToolCall) -> GuardDecision:
        cmd = call.tool_input.get("command", "")
        for p in self.BLOCKED_SHELL_PATTERNS:
            if re.search(p, cmd, re.IGNORECASE):
                return GuardDecision(False, f"BLOCKED: {p}", False, "critical")
        for p in self.CONFIRM_SHELL_PATTERNS:
            if re.search(p, cmd, re.IGNORECASE):
                return GuardDecision(True, "ok", True, "high")
        return GuardDecision(True, "ok", False, "low")

    def _check_file(self, call: ToolCall) -> GuardDecision:
        path_str = call.tool_input.get("path", "")

        # null byte 截断攻击
        if "\x00" in path_str:
            return GuardDecision(False, "BLOCKED: null byte in path", False, "critical")

        # 敏感路径检测（统一用 / 分隔符再匹配）
        normalized = path_str.lower().replace("\\", "/")
        for comp in self.SENSITIVE_PATH_COMPONENTS:
            if comp in normalized:
                return GuardDecision(
                    False, f"BLOCKED: sensitive path '{comp}'", False, "critical"
                )

        # 路径逃逸检测（防止 ../../ 穿越 workspace）
        try:
            resolved = (self.workspace / path_str).resolve()
            resolved.relative_to(self.workspace)
        except (ValueError, OSError):
            return GuardDecision(
                False, "BLOCKED: path escapes workspace", False, "critical"
            )

        return GuardDecision(True, "ok", False, "low")

    def _check_chain_risk(self) -> GuardDecision:
        """
        防线 4：最近 10 步中，读凭证文件 + 网络请求 = 潜在数据外泄链。
        每步单独合法，组合起来是完整攻击链。
        """
        recent = self._call_chain[-10:]
        tools = {c.tool_name for c in recent}

        if "http_request" not in tools:
            return GuardDecision(True, "ok", False, "low")

        # 检查是否有凭证相关的文件读取
        sensitive_keywords = (".aws", ".env", ".ssh", "token", "secret", "credentials")
        sensitive_read = any(
            c.tool_name == "file_read"
            and any(kw in c.tool_input.get("path", "").lower() for kw in sensitive_keywords)
            for c in recent
        )
        if sensitive_read:
            return GuardDecision(
                False, "BLOCKED: credential-read + network chain detected",
                False, "critical"
            )
        return GuardDecision(True, "ok", False, "low")
