"""
sandbox_validator.py — 容器安全配置校验

对应 OpenClaw validate-sandbox-security.ts:311-322
校验两类危险：
1. 阻挂 docker socket（防容器逃逸）
2. 阻 seccomp/AppArmor 绕过（防系统调用级逃逸）
"""

from dataclasses import dataclass, field


class SecurityError(ValueError):
    """安全配置违规，容器不应启动"""


BLOCKED_MOUNTS = frozenset({
    "/var/run/docker.sock",   # docker socket — 挂载后容器可创建新容器，实现逃逸
    "/run/docker.sock",       # 备用路径
    "/var/run/docker.pid",    # docker PID 文件
    "//./pipe/docker_engine", # Windows 路径（防跨平台边缘情况）
})

BLOCKED_SECURITY_OPTS = frozenset({
    "seccomp=unconfined",  # 禁用 seccomp — 允许所有系统调用
    "apparmor=unconfined", # 禁用 AppArmor — 允许所有资源访问
})


@dataclass
class ContainerConfig:
    """容器启动配置（类型安全）"""
    image: str
    command: list[str]
    mounts: list[str] = field(default_factory=list)   # host:container 格式
    security_opts: list[str] = field(default_factory=list)
    privileged: bool = False
    network_mode: str = "none"
    cpu_period: int = 100_000
    cpu_quota: int = 50_000      # 0.5 core
    mem_limit: str = "256m"
    timeout: int = 30            # 秒


def validate(config: ContainerConfig) -> None:
    """
    校验容器配置，违规时抛出 SecurityError。

    对应 docker.ts:30-32（阻挂 socket）
    和 validate-sandbox-security.ts:311-322（阻 seccomp/AppArmor 绕过）
    """
    # 1. 阻挂 docker socket（docker.ts:30-32 对应逻辑）
    for mount in config.mounts:
        host_path = mount.split(":")[0].rstrip("/")
        if host_path in BLOCKED_MOUNTS:
            raise SecurityError(
                f"禁止挂载 docker socket：{host_path}\n"
                "原因：容器内访问 docker daemon 可创建新容器并挂载宿主机文件系统，实现完全逃逸。"
            )

    # 2. 阻 seccomp/AppArmor 绕过（validate-sandbox-security.ts:311-322 对应逻辑）
    for opt in config.security_opts:
        if opt in BLOCKED_SECURITY_OPTS:
            raise SecurityError(
                f"禁止安全选项：{opt}\n"
                f"原因：{'禁用 seccomp 允许所有系统调用' if 'seccomp' in opt else '禁用 AppArmor 允许所有资源访问'}，可能导致逃逸。"
            )

    # 3. 阻 --privileged（超级权限，包含所有 capabilities）
    if config.privileged:
        raise SecurityError(
            "禁止 privileged 模式\n"
            "原因：privileged 容器拥有宿主机 root 的几乎所有权限，等同于无沙箱。"
        )
