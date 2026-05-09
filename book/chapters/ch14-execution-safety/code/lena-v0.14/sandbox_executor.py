"""
sandbox_executor.py — 沙盒执行器

在受限子进程中执行 shell 命令：
- 只能在 workspace 目录内运行
- 超时自动终止（默认 30 秒）
- 屏蔽已知危险命令前缀
- 清除危险环境变量（避免子进程继承凭证）
"""

import os
import re
import subprocess
from pathlib import Path


class SandboxExecutor:
    """
    防线 1/3 的运行时实现：在受限子进程中跑 shell 命令。
    不依赖 Docker，纯 Python stdlib 实现。
    """

    # workspace 之外不可执行
    ALLOWED_CWD_BASE = Path.cwd() / "workspace"

    # 直接禁止的命令前缀（ExecutionGuard 的补充层）
    BLOCKED_PREFIXES = ["sudo", "su ", "pkill", "kill "]

    # 从子进程环境中移除的危险变量
    SCRUBBED_ENV_KEYS = [
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN", "GH_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "DATABASE_URL", "SECRET_KEY",
    ]

    TIMEOUT_SEC = 30

    def __init__(self, workspace_dir: str | None = None):
        if workspace_dir:
            self.workspace = Path(workspace_dir).resolve()
        else:
            self.workspace = self.ALLOWED_CWD_BASE.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def execute(self, cmd: str) -> dict:
        """
        在沙盒子进程中运行命令。
        返回 {stdout, stderr, exit_code, killed_reason}
        """
        # 一道静态禁令：补充 ExecutionGuard 的正则检查
        for prefix in self.BLOCKED_PREFIXES:
            if cmd.strip().startswith(prefix):
                return {
                    "stdout": "",
                    "stderr": f"SANDBOX_BLOCKED: command starts with '{prefix}'",
                    "exit_code": -1,
                    "killed_reason": "blocked_prefix",
                }

        # 构造干净的环境变量（去除凭证相关 key）
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in self.SCRUBBED_ENV_KEYS}

        killed_reason = None
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SEC,
                cwd=str(self.workspace),  # 强制在 workspace 内运行
                env=clean_env,
            )
            return {
                "stdout": result.stdout[:4096],   # 限制输出大小
                "stderr": result.stderr[:1024],
                "exit_code": result.returncode,
                "killed_reason": killed_reason,
            }
        except subprocess.TimeoutExpired:
            killed_reason = f"timeout_{self.TIMEOUT_SEC}s"
            return {
                "stdout": "",
                "stderr": f"SANDBOX: command killed after {self.TIMEOUT_SEC}s",
                "exit_code": -1,
                "killed_reason": killed_reason,
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": f"SANDBOX_ERROR: {e}",
                "exit_code": -1,
                "killed_reason": "exception",
            }

    def is_safe_path(self, path: str) -> bool:
        """验证路径是否在 workspace 边界内（供外部检查使用）。"""
        try:
            resolved = (self.workspace / path).resolve()
            resolved.relative_to(self.workspace)
            return True
        except (ValueError, OSError):
            return False
