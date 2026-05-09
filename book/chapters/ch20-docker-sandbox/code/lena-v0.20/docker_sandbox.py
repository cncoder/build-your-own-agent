"""
docker_sandbox.py — Docker 容器执行沙箱

功能：
- 创建独立容器执行代码（每次独立，执行后立即销毁）
- docker socket 隔离（通过 sandbox_validator 校验）
- seccomp profile 校验
- 资源限制（CPU 0.5 core / 内存 256MB / 超时 30s）
- 多语言支持（Python / Shell / JavaScript）

对应 OpenClaw agents/sandbox/docker.ts
"""

import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from sandbox_validator import ContainerConfig, validate, SecurityError


LANGUAGE_CONFIG = {
    "python": {
        "image": "python:3.12-slim",
        "file_ext": ".py",
        "run_cmd": lambda f: ["python3", f],
    },
    "shell": {
        "image": "alpine:latest",
        "file_ext": ".sh",
        "run_cmd": lambda f: ["sh", f],
    },
    "javascript": {
        "image": "node:20-slim",
        "file_ext": ".js",
        "run_cmd": lambda f: ["node", f],
    },
}


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    container_id: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def __str__(self) -> str:
        if self.timed_out:
            return "[超时] 执行超过时间限制，容器已强制销毁。"
        result = ""
        if self.stdout:
            result += f"[stdout]\n{self.stdout}\n"
        if self.stderr:
            result += f"[stderr]\n{self.stderr}\n"
        if not result:
            result = f"[完成，exit code={self.exit_code}]"
        return result.strip()


class DockerSandbox:
    """
    Docker 沙箱执行器。

    每次 execute() 创建独立容器，执行完毕后立即销毁（--rm）。
    容器启动前通过 sandbox_validator 校验安全配置。
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._verify_docker()

    def _verify_docker(self) -> None:
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, timeout=5
            )
            if result.returncode != 0:
                raise RuntimeError("Docker daemon 未运行，请先启动 Docker Desktop。")
        except FileNotFoundError:
            raise RuntimeError("未找到 docker 命令，请先安装 Docker。")

    def execute(self, code: str, language: str = "python") -> ExecutionResult:
        """
        在隔离 Docker 容器中执行代码。

        参数:
            code: 要执行的代码字符串
            language: "python" / "shell" / "javascript"

        返回:
            ExecutionResult（含 stdout/stderr/exit_code）
        """
        lang_cfg = LANGUAGE_CONFIG.get(language)
        if not lang_cfg:
            raise ValueError(f"不支持的语言：{language}，支持：{list(LANGUAGE_CONFIG.keys())}")

        # 把代码写入临时文件，挂载进容器
        with tempfile.NamedTemporaryFile(
            suffix=lang_cfg["file_ext"],
            mode="w",
            delete=False,
            encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            tmp_path = Path(tmp.name)

        container_name = f"lena-sandbox-{uuid.uuid4().hex[:8]}"
        container_path = f"/sandbox/code{lang_cfg['file_ext']}"

        # 构建容器配置
        config = ContainerConfig(
            image=lang_cfg["image"],
            command=lang_cfg["run_cmd"](container_path),
            mounts=[f"{tmp_path}:{container_path}:ro"],  # 只读挂载
            security_opts=[],   # 不禁用 seccomp/AppArmor
            privileged=False,   # 绝不 privileged
            network_mode="none", # 断网
            timeout=self.timeout,
        )

        # 安全校验（对应 validate-sandbox-security.ts:311-322）
        validate(config)

        cmd = [
            "docker", "run",
            "--rm",                              # 执行后立即销毁
            "--name", container_name,
            "--network", config.network_mode,    # 断网
            "--cpus", "0.5",                     # CPU 限制
            f"--memory={config.mem_limit}",      # 内存限制
            "--read-only",                       # 根文件系统只读
            "--tmpfs", "/tmp:size=64m",          # /tmp 可写（有大小限制）
            "--no-healthcheck",
            "--user", "nobody",                  # 非 root 用户执行
        ]

        # 挂载代码文件（只读）
        for mount in config.mounts:
            cmd.extend(["-v", mount])

        cmd.append(config.image)
        cmd.extend(config.command)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout + 5,  # 比容器内超时多 5 秒，防止 docker 本身卡住
            )
            return ExecutionResult(
                stdout=proc.stdout[:50_000],  # 截断超大输出
                stderr=proc.stderr[:10_000],
                exit_code=proc.returncode,
                container_id=container_name,
            )
        except subprocess.TimeoutExpired:
            # 强制杀掉容器
            subprocess.run(["docker", "kill", container_name], capture_output=True)
            return ExecutionResult(
                stdout="", stderr="",
                exit_code=-1, timed_out=True,
                container_id=container_name,
            )
        finally:
            # 清理临时文件（容器已 --rm 自动销毁）
            tmp_path.unlink(missing_ok=True)
