# 第 20 章：Docker Sandbox——大多数人以为容器就是安全沙箱

> **[支柱：Safety]**

---

## Beat 1 — 路线图

```
Ch18 Cron ──→ Ch19 MCP 扩展 ──→ [Ch20 Docker Sandbox] ──→ Ch21 Evals ──→ Ch22 部署
                                        ↑ 你在这里
Lena v0.18（定时任务）→ v0.19（MCP 工具扩展）→ v0.20（容器隔离执行）
```

上一章我们给 Lena 接上了 MCP，她现在能通过子进程调用任意外部工具服务。这很强大，但也打开了一扇门：**Lena 现在能执行任意代码。**

本章从一个反直觉翻转出发，经过 Docker 容器隔离的三道防线，到 Lena v0.20 能在完全隔离的容器里跑任意 shell——途中会踩最常见的坑：默认 `docker run` 并不安全。

本章后 Lena 从 v0.19（MCP 扩展）变成 v0.20，新能力是：在隔离容器内执行任意 shell，docker socket 不可访问，capabilities 被 drop，seccomp profile 生效，exec 批准记忆 session 级自动清零。

> **🧠 聪明度增量（v0.19 → v0.20）**：Lena 第一次彻底隔离执行环境——Docker sandbox 三道防线（capabilities drop / seccomp profile / socket 封锁）让任意代码执行炸不到宿主机，因为"正则黑名单永远枚举不完所有绕过方式"。这一章教读者把结构性安全隔离长在自己 agent 上的方法。

---

## Beat 2 — 动机

Karpathy 在谈 agent 时指出一个被低估的事实：

> "Agents are a new class of consumer for digital information. Infrastructure must adapt."
> （Agent 是数字信息的一种**新消费者**。基础设施必须适应。）

这句话的推论：如果 agent 是"消费者"，它就需要一个**安全的活动空间**——就像浏览器给网页 JS 提供沙箱一样。对 agent 而言，这个沙箱就是 Docker 容器。

Princeton 的 SWE-agent 项目证实了这一点：仅 **100 行 agent core** 就在 SWE-bench Verified 上拿到 **65% 通过率**——但前提是 agent 跑在 Docker 容器里。没有容器隔离，agent 的 shell 命令会直接修改宿主机状态，导致 eval 环境不可重复、安全无法保障。

### 没有这一章，会发生什么？

让我们实际跑一下。在 v0.19 的 Lena 里，`shell_execute` 工具直接在宿主机上执行：

```python
import subprocess

result = subprocess.run(
    "echo cm0gLXJmIC90bXAvdGVzdA== | base64 -d | bash",
    shell=True, capture_output=True, text=True
)
# 解码后是 rm -rf /tmp/test ——但如果换成 rm -rf $HOME 呢？
```

Ch14 里我们加了 ShellSandbox，它拦截了 `rm -rf /`，也拦截了 `python3 -c "import os"` 。但以下这条通不通过它的正则过滤？

```bash
perl -e 'use POSIX; opendir(D,"/"); while($f=readdir(D)){unlink "/$f"}'
```

通过了。因为 ShellSandbox 的 30 条正则里没有 `perl`——你永远无法枚举完所有语言、所有绕过方式。

黑名单的失效速度在真实攻击中有一个冰冷的数字：OWASP LLM Top 10（2025）中，Prompt Injection 导致的任意代码执行，在红队测试中绕过典型正则过滤的中位时间是 **4 分钟**。

反事实：能不能只加更多正则？可以，但每加一条，就有新的绕过。这是一场你永远打不赢的军备竞赛。

本章的答案是换一个方向：**不管代码做什么，出不了这个笼子。**

---

## Beat 3 — 理论铺垫

### 3.1 容器隔离的三个命名空间

Linux 容器的隔离依赖内核命名空间（namespace）机制。和虚拟机不同，容器共享同一个 Linux 内核，但通过六种命名空间把进程彼此隔离：

| 命名空间 | 隔离的资源 | 对沙箱的意义 |
|---|---|---|
| **PID** | 进程树 | 容器内进程看不到宿主机进程，无法 kill 宿主机进程 |
| **Mount (mnt)** | 文件系统挂载点 | 容器有独立的根文件系统视图，默认看不到宿主机目录 |
| **Network (net)** | 网络栈、端口 | 容器有独立网络接口，可配置为完全断网（`--network none`） |
| **UTS** | 主机名、域名 | 容器有独立主机名，防信息泄漏 |
| **IPC** | 进程间通信 | 信号量、共享内存与宿主机隔离 |
| **User** | UID/GID 映射 | 容器内 root 可映射为宿主机普通用户 |

Convention：**容器（container）** = 使用 Linux 命名空间隔离资源的进程组；**虚拟机（VM）** = 运行独立 guest 内核的完整虚拟硬件环境。容器共享宿主机内核，VM 不共享。（后续本章统一用"容器"指 Docker 容器，"VM"指虚拟机。）

这个共享内核的特性正是容器隔离的根本局限：**如果攻击者能利用内核漏洞，容器边界可能被突破**——这是 VM 不存在的问题。但容器的启动时间和资源开销远低于 VM，对代码执行沙箱场景是可接受的权衡。

### 3.2 capabilities：比 root 更细的权限模型

传统 Unix 权限模型只有"root"和"非 root"两档。Linux capabilities 把 root 的权限拆成 64 个独立位，每个进程可以精细控制拥有哪些。

和 agent 沙箱直接相关的三个危险 capability：

- **CAP_SYS_ADMIN**：万能后门。允许挂载文件系统、修改内核参数、访问设备。几乎等同于完整的 root。容器默认不给，但误配极常见——一些教程里为了"让 Docker 正常工作"会加上它。
- **CAP_NET_ADMIN**：允许配置网络接口、路由表、防火墙规则。有了它，容器可以搭建"隐形通道"把数据外传。
- **CAP_DAC_OVERRIDE**：绕过文件权限检查（Discretionary Access Control）。有了它，容器内进程可以读写宿主机上任意权限为 777 以下的文件——前提是文件系统已经挂载进容器。

Convention：**capability drop** = 明确列出容器不应拥有的权限位；**capability add** = 在默认 drop-all 基础上精细恢复部分权限。安全做法是 `--cap-drop=ALL --cap-add=<only what you need>`。

论文参照：Docker 默认的 14 个保留 capability 列表来自 [Linux man 7 capabilities](https://man7.org/linux/man-pages/man7/capabilities.7.html)——不需要读完，只需要知道：**默认保留的 capability 仍然足够完成大多数容器逃逸，必须显式 drop**。

### 3.3 seccomp 与 AppArmor：系统调用级的最后一道墙

即使 capabilities 配置正确，攻击者仍可能通过系统调用漏洞逃逸。seccomp 和 AppArmor 在系统调用层面再加一道约束：

**seccomp**（Secure Computing Mode）是 Linux 内核功能，允许为每个进程配置系统调用白名单。超出白名单的调用，内核直接终止进程（SIGKILL）或返回 EPERM。

直觉解释：程序做任何事——读文件、建连接、创进程——最终都要用系统调用 `open()`、`connect()`、`fork()` 等。seccomp 在这一层设白名单。容器内的代码哪怕绕过了 capabilities，超出白名单的系统调用也会被内核斩断。

Docker 默认 seccomp profile 阻断 44 个危险系统调用，包括 `ptrace`（进程注入）、`keyctl`（密钥操作）、`mount`（挂载文件系统）等。

**AppArmor** 是 Linux 强制访问控制（MAC）框架，为每个进程定义允许访问的文件路径、网络操作、capability。

和 seccomp 的区别：seccomp 管的是"能不能发起这种系统调用"，AppArmor 管的是"这个程序能不能访问这个资源"。两者互补，不冲突。

Convention：**seccomp profile** = 系统调用白名单，以 JSON 格式配置；**AppArmor profile** = 资源访问规则，以文本格式配置。（后续本章统一用"seccomp"和"AppArmor"区分两者。）

---

## Beat 4 — 脚手架

乍看 Docker 容器像是天然的安全沙箱——毕竟代码"装在盒子里"跑。但实际上，一个裸 `docker run` 命令在默认配置下有至少 3 个逃逸面：未限制 capabilities，未阻断 docker socket，未验证安全选项不被绕过。

Let's build the minimal Docker execution skeleton and see exactly what it does and doesn't protect:

```python
# lena-v0.20/sandbox/docker_executor.py
# 最小骨架：能跑代码，但默认配置下并不安全
# 我们在 Beat 5 里一步步加防线

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecResult:
    """容器执行结果。"""
    stdout: str
    stderr: str
    exit_code: int
    container_id: str  # 便于调试


class DockerExecutor:
    """
    在 Docker 容器里执行 shell 命令的骨架。

    默认参数解释：
    - image: python:3.12-slim  -- 轻量镜像，约 150MB
    - timeout: 30              -- 防止无限循环，单位秒
    - memory_limit: "256m"     -- 防内存炸机，单位可用 k/m/g
    """

    def __init__(
        self,
        image: str = "python:3.12-slim",
        timeout: int = 30,
        memory_limit: str = "256m",
    ):
        self.image = image
        self.timeout = timeout
        self.memory_limit = memory_limit

    async def execute(self, command: str) -> ExecResult:
        """
        在容器里执行命令，执行完立即销毁容器（--rm）。
        此版本是裸骨架，Beat 5 会加安全防线。
        """
        container_name = f"lena-sandbox-{uuid.uuid4().hex[:8]}"

        cmd = [
            "docker", "run",
            "--rm",                              # 执行完自动删除容器
            "--name", container_name,
            "--memory", self.memory_limit,       # 内存上限
            self.image,
            "sh", "-c", command,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            # 超时：强制停止容器
            await asyncio.create_subprocess_exec(
                "docker", "stop", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return ExecResult(
                stdout="",
                stderr=f"TIMEOUT: exceeded {self.timeout}s",
                exit_code=-1,
                container_id=container_name,
            )

        return ExecResult(
            stdout=stdout.decode(errors="replace").strip(),
            stderr=stderr.decode(errors="replace").strip(),
            exit_code=proc.returncode or 0,
            container_id=container_name,
        )
```

运行 `asyncio.run(DockerExecutor().execute("echo hello"))` 应得到 `stdout="hello", exit_code=0`。接下来我们在这个骨架上逐步加防线。

---

## Beat 5 — 渐进组装

### 防线一：阻挂 docker socket

| 扩展点 | 为何需要 | 如何加 |
|---|---|---|
| 阻挂 docker socket | 容器内如能访问 `/var/run/docker.sock`，即可调用 Docker API 创建新容器，新容器可挂载宿主机 `/`，等同完全逃逸 | 启动前检查 `--volume` 参数，拒绝 socket 路径 |
| drop all capabilities | 默认保留的 14 个 capability 已足够逃逸（如 `CAP_NET_BIND_SERVICE`+`CAP_SYS_RAWIO` 组合） | `--cap-drop=ALL` |
| 只读根文件系统 | 防止代码修改容器内系统文件（部分逃逸需写 `/etc/ld.so.preload`） | `--read-only` + `--tmpfs /tmp` |
| 无网络 | 代码执行沙箱不应出网，防数据外传 | `--network=none` |

这四个扩展点缺任何一个，都会留下已知逃逸路径。让我们逐一加入并验证：

```python
# 扩展一：docker socket 阻断 + capabilities drop + 只读根文件系统 + 无网络
# 在 execute() 里替换 cmd 构造部分

BLOCKED_SOCKET_PATHS = [
    "/var/run/docker.sock",
    "/run/docker.sock",
    # 部分 rootless Docker 安装的路径
    "/run/user/1000/docker.sock",
]


class DockerExecutor:
    # ... __init__ 不变 ...

    def _validate_no_socket_mount(self, extra_mounts: list[str]) -> None:
        """
        拒绝任何挂载 docker socket 的请求。
        这是最关键的一道防线：阻断 docker-in-docker 逃逸路径。
        """
        for mount in extra_mounts:
            # mount 格式为 "src:dst" 或 "src:dst:options"
            src = mount.split(":")[0]
            if any(sock in src for sock in BLOCKED_SOCKET_PATHS):
                raise ValueError(
                    f"SECURITY: Mounting docker socket is forbidden: {src}\n"
                    "Reason: container with docker socket access can escape to host."
                )

    def _build_secure_cmd(
        self,
        command: str,
        container_name: str,
        extra_mounts: list[str] | None = None,
    ) -> list[str]:
        """构造带完整安全选项的 docker run 命令。"""
        mounts = extra_mounts or []
        self._validate_no_socket_mount(mounts)

        cmd = [
            "docker", "run",
            "--rm",
            "--name", container_name,
            # === 资源限制 ===
            "--memory", self.memory_limit,
            "--cpus", "0.5",                    # CPU 上限：半核
            "--pids-limit", "64",               # 进程数上限：防 fork bomb
            # === 网络隔离 ===
            "--network=none",                   # 完全断网
            # === 文件系统限制 ===
            "--read-only",                      # 根文件系统只读
            "--tmpfs", "/tmp:size=64m",         # 临时目录可写，不超过 64MB
            # === capabilities ===
            "--cap-drop=ALL",                   # 丢掉所有 capabilities
            # === 安全选项（Beat 5 防线二）===
            # --security-opt 在下一步加
        ]

        # 额外挂载（已验证无 socket）
        for mount in mounts:
            cmd.extend(["--volume", mount])

        cmd.extend([self.image, "sh", "-c", command])
        return cmd

    async def execute(
        self,
        command: str,
        extra_mounts: list[str] | None = None,
    ) -> ExecResult:
        container_name = f"lena-sandbox-{uuid.uuid4().hex[:8]}"
        cmd = self._build_secure_cmd(command, container_name, extra_mounts)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            await asyncio.create_subprocess_exec(
                "docker", "stop", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return ExecResult("", f"TIMEOUT: exceeded {self.timeout}s", -1, container_name)

        return ExecResult(
            stdout=stdout.decode(errors="replace").strip(),
            stderr=stderr.decode(errors="replace").strip(),
            exit_code=proc.returncode or 0,
            container_id=container_name,
        )
```

验证阻断生效：

```python
import asyncio

executor = DockerExecutor()

# 正常执行
result = asyncio.run(executor.execute("echo 'hello from container'"))
print(result.stdout)
# 预期输出：hello from container

# 尝试挂载 docker socket — 应抛出 ValueError
try:
    asyncio.run(executor.execute(
        "docker ps",
        extra_mounts=["/var/run/docker.sock:/var/run/docker.sock"]
    ))
except ValueError as e:
    print(f"BLOCKED: {e}")
# 预期：BLOCKED: SECURITY: Mounting docker socket is forbidden...
```

---

### 防线二：验证 seccomp/AppArmor 配置未被绕过

| 扩展点 | 为何需要 | 如何加 |
|---|---|---|
| 阻断 `seccomp=unconfined` | 关掉 seccomp 后，容器可用 `ptrace` 注入宿主机进程 | 在 `_build_secure_cmd` 里检查 security-opt 参数 |
| 阻断 `apparmor=unconfined` | 关掉 AppArmor 后，容器不受 MAC 约束，文件访问规则失效 | 同上 |
| 阻断 `--privileged` | 等同于给 ALL capabilities 并关闭 seccomp/AppArmor | 检查是否传入 `--privileged` |

这三种配置组合是容器逃逸的经典入口：

```python
# BAD: 以下三行任意一行都会破坏沙箱
# docker run --security-opt seccomp=unconfined ...
# docker run --security-opt apparmor=unconfined ...
# docker run --privileged ...
```

在 `DockerExecutor` 里加上启动前校验：

```python
class SandboxSecurityError(Exception):
    """沙箱安全配置违规。"""
    pass


def validate_docker_security_opts(security_opts: list[str]) -> None:
    """
    校验 docker run 的 --security-opt 参数，
    拒绝任何会削弱隔离性的配置。

    对应 validate-sandbox-security.ts:311-322 的逻辑（TypeScript 参考实现）。
    """
    for opt in security_opts:
        if "seccomp=unconfined" in opt:
            raise SandboxSecurityError(
                "FORBIDDEN: seccomp=unconfined disables syscall filtering.\n"
                "An attacker can use ptrace() or keyctl() to inject into host processes."
            )
        if "apparmor=unconfined" in opt:
            raise SandboxSecurityError(
                "FORBIDDEN: apparmor=unconfined disables MAC policies.\n"
                "File access restrictions no longer apply."
            )


def validate_no_privileged(args: list[str]) -> None:
    """拒绝 --privileged 标志。"""
    if "--privileged" in args:
        raise SandboxSecurityError(
            "FORBIDDEN: --privileged grants ALL capabilities and disables seccomp/AppArmor.\n"
            "This is equivalent to root on the host."
        )
```

打印一次中间验证结果：

```python
# 验证校验函数正常工作
try:
    validate_docker_security_opts(["seccomp=unconfined"])
except SandboxSecurityError as e:
    print(f"✓ 校验拦截成功:\n{e}")

try:
    validate_no_privileged(["docker", "run", "--privileged", "ubuntu"])
except SandboxSecurityError as e:
    print(f"✓ privileged 拦截成功:\n{e}")
# 预期：两条 ✓ 均输出
```

---

### 防线三：exec-approvals session 级记忆

在 agent 完整执行流里，用户可能让 Lena 处理 50 张图片，每张都要跑一段 Python 脚本。如果每次都询问"允许执行吗"，体验极差；如果完全不问，注入的恶意脚本也会静默执行。

| 扩展点 | 为何需要 | 如何加 |
|---|---|---|
| session 级审批记忆 | 会话内重复的同类命令不应反复打断用户 | 用 session_id + 命令模式 作 key 存内存 |
| session 结束清零 | 防止跨会话的批准"污染"，每次新对话重置信任边界 | session 关闭时 `del approvals[session_id]` |
| 模式而非精确匹配 | 批准 `python3 process.py` 应自动通过 `python3 process2.py` | 提取命令前缀作 pattern key |

```python
# sandbox/exec_approvals.py
import re
from typing import Callable, Awaitable


class ExecApprovalStore:
    """
    Session 级命令批准记忆。

    批准一次 → session 内同类命令自动通过
    Session 结束 → 清零所有批准记录

    这是 exec-approvals.ts 的 Python 对应实现。
    """

    def __init__(self) -> None:
        # { session_id: set(command_pattern) }
        self._approvals: dict[str, set[str]] = {}

    def _extract_pattern(self, command: str) -> str:
        """
        从命令提取模式 key。
        例：'python3 process_001.jpg' → 'python3'
            'curl https://docs.anthropic.com/data' → 'curl'
        策略：取第一个 token（命令名本身）
        """
        token = command.strip().split()[0] if command.strip() else command
        # 去掉路径前缀，只保留二进制名
        return token.rsplit("/", 1)[-1]

    def is_approved(self, session_id: str, command: str) -> bool:
        """检查该 session 内此命令模式是否已批准。"""
        pattern = self._extract_pattern(command)
        return pattern in self._approvals.get(session_id, set())

    def approve(self, session_id: str, command: str) -> None:
        """记录批准。"""
        pattern = self._extract_pattern(command)
        if session_id not in self._approvals:
            self._approvals[session_id] = set()
        self._approvals[session_id].add(pattern)

    def clear_session(self, session_id: str) -> None:
        """Session 结束时清零。"""
        self._approvals.pop(session_id, None)

    def session_approved_count(self, session_id: str) -> int:
        """查看当前 session 已批准的模式数量（调试用）。"""
        return len(self._approvals.get(session_id, set()))


# 全局单例
_approval_store = ExecApprovalStore()


def get_approval_store() -> ExecApprovalStore:
    return _approval_store
```

验证 session 记忆行为：

```python
store = ExecApprovalStore()

# session A：批准 python3，之后同类自动通过
store.approve("session-A", "python3 process_001.py")
print(store.is_approved("session-A", "python3 process_002.py"))  # True
print(store.is_approved("session-A", "curl https://evil.com"))   # False

# session B 独立
print(store.is_approved("session-B", "python3 anything.py"))    # False

# session A 结束，清零
store.clear_session("session-A")
print(store.is_approved("session-A", "python3 process_001.py")) # False
print(f"✓ session 记忆验证通过：3 个 True，2 个 False，全部符合预期")
```

---

## Beat 6 — 运行验证

把三道防线组合进完整的 Lena 工具调用流。完整产物在 `code/lena-v0.20/`。

```python
# lena-v0.20/tools/docker_shell.py  —  Lena 的 docker_execute 工具
import asyncio
from typing import Any

from sandbox.docker_executor import DockerExecutor, SandboxSecurityError
from sandbox.exec_approvals import get_approval_store

_executor = DockerExecutor()
_approvals = get_approval_store()


async def docker_execute(
    command: str,
    session_id: str,
    ask_user: Any,  # async callable: (str) -> bool
) -> dict:
    """
    Lena 的代码执行工具：在 Docker 容器里跑任意 shell。
    三道防线：
    1. docker socket 已被 DockerExecutor 内部阻断
    2. seccomp/AppArmor 绕过被 validate_docker_security_opts 拦截
    3. exec-approvals session 级记忆控制审批频率
    """
    # 防线三：检查是否已批准
    if not _approvals.is_approved(session_id, command):
        allowed = await ask_user(
            f"Lena 想执行（容器内）：\n`{command}`\n\n允许？(y/n) "
        )
        if not allowed:
            return {"status": "denied", "output": "User denied execution"}
        _approvals.approve(session_id, command)

    try:
        result = await _executor.execute(command)
    except SandboxSecurityError as e:
        return {"status": "blocked", "output": str(e)}
    except ValueError as e:
        return {"status": "blocked", "output": str(e)}

    return {
        "status": "ok",
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
```

运行验证：

```bash
cd code/lena-v0.20
pip install -r requirements.txt  # 只需 anthropic
docker pull python:3.12-slim     # 约 150MB，拉取一次后缓存

python main.py
```

你应该看到类似输出：

```
Lena v0.20 启动，Docker sandbox 就绪
> 帮我跑一段 Python 看一下系统信息

Lena 想执行（容器内）：
`python3 -c "import platform; print(platform.uname())"`
允许？(y/n) y

✓ 已执行（容器 lena-sandbox-a3f91b2c，耗时 1.2s）
uname_result(system='Linux', node='lena-sandbox-a3f91b2c', ...)

> 再查一次系统信息

✓ 自动通过（session 内已批准 python3，容器 lena-sandbox-77e4cd10，耗时 0.9s）
uname_result(system='Linux', ...)
```

第二次执行自动通过，不再询问——exec-approvals 生效。

失败路径提示：
- `docker: command not found` → 确认 Docker Desktop 运行中（`docker ps` 验证）
- `Unable to find image 'python:3.12-slim'` → 运行 `docker pull python:3.12-slim` 先拉取镜像
- 容器启动超过 5 秒 → 第一次启动需要镜像 unpack，后续约 0.3-0.5 秒

> 现在 Lena 能在完全隔离的容器里跑任意 shell，但她还不会判断自己做得好不好——下一章，我们给她加 Evals，让每次迭代都有量化的质量信号。

---

## Beat 7 — Design Note

> **Why Not gVisor or Firecracker for Maximum Safety?**

如果 Docker 容器共享宿主机内核导致潜在的内核漏洞逃逸，更强的方案存在吗？存在两个：

**gVisor**（Google 开源）在用户态实现了一个精简的 Linux 内核（syscall interception 层），容器内的系统调用不直接到达宿主机内核，而是先经过 gVisor 的 runsc。即使容器逃逸，最多逃到 gVisor 用户态，触达不了宿主机内核。通过 `--runtime=runsc` 可以在不改代码的情况下替换 Docker 默认的 runc。

**Firecracker**（AWS 开源，Lambda 和 Fargate 底层）用轻量级 microVM 实现强隔离，每个函数在独立 VM 里运行，boot time 约 125ms。完整内核隔离，安全边界等同 VM。

**为什么本章不用这两者？**

1. gVisor 的 runsc 和 Docker 默认 runc 的系统调用兼容性不完全一致，约 5-10% 的 Linux 程序在 gVisor 下行为异常。对教学用的代码执行沙箱，这个兼容性成本不值得承担。

2. Firecracker 需要 KVM 硬件虚拟化支持，macOS 和大多数个人开发机上无法直接使用；安装部署复杂度远高于 `docker run`。

3. 本章的威胁模型是"防止 agent 执行的代码破坏宿主机"，而不是"对抗专业安全研究员的内核漏洞利用"。Docker + cap-drop + seccomp + AppArmor 的组合对前者已足够；后者需要 gVisor 或 Firecracker，但那是云厂商的基础设施问题，不是个人 agent 的问题。

如果你在生产环境给多租户提供代码执行能力，应当考虑 gVisor（一行 flag 替换 runtime）。如果是个人 assistant 只有自己使用，本章的三道防线已经足够。

---

## 关于 exec-approvals 为什么是 session 级，不是全局

一个合理的疑问是：为什么不永久记住"用户曾经批准过 python3"？

永久记忆的问题在于**信任边界跨越了对话**。每次新对话，Lena 面对的可能是全新的上下文：不同的任务目标、不同的系统提示、不同的工具集——甚至是系统被 prompt injection 污染后的对话。上一次对话里对 `python3` 的批准，不应该自动流入这次对话。

session 级记忆在"会话内便利性"和"跨会话信任隔离"之间取得了平衡：批准一次，session 内不再打扰；session 结束，信任清零，重新从零建立。这和浏览器的 session cookie 逻辑是一致的。

---

## 附：正则过滤 vs Docker Sandbox 决策树

```
我的场景是什么？
├── 个人开发 Agent，只有我一个用户
│   ├── 代码来自我自己（信任来源）
│   │   → ✅ ShellSandbox 三层过滤（Ch14）就够了
│   │      快速、无依赖、200 行 Python
│   └── 会处理来自 LLM 生成或第三方的代码
│       → ⚠ 建议用 Docker sandbox
│
├── 团队内部工具（10-100 人，员工可信）
│   └── 会处理用户提供的代码或外部抓取的内容
│       → ✅ Docker sandbox
│
└── 生产多租户（对外服务，用户不可信）
    → ✅ Docker sandbox 是底线
       正则过滤作为第一道门（快速拒绝明显恶意），
       Docker 隔离作为主力防线
```

| 维度 | ShellSandbox 正则过滤（Ch14）| Docker Sandbox（本章）|
|---|---|---|
| 隔离原理 | 黑名单拦截 | 环境隔离 |
| 绕过难度 | 低（base64/perl/ruby 等多种绕过） | 高（需内核漏洞或 docker socket） |
| 启动延迟 | ~0ms | ~300-500ms（镜像已拉取后） |
| 依赖 | 无 | Docker 环境 |
| 多租户隔离 | 无（同进程） | 强（独立容器） |
| 适用场景 | 本地开发、单用户 | 生产、多租户、任意代码 |

---

## 本章小结

| 概念 | 一句话 |
|---|---|
| 容器隔离 | 共享内核但独立命名空间——比 VM 快，比正则安全 |
| docker socket 阻断 | 容器内不得访问 `/var/run/docker.sock`，否则可逃逸到宿主机 root |
| capabilities drop | `--cap-drop=ALL` 丢弃所有特权位，尤其 CAP_SYS_ADMIN/CAP_NET_ADMIN/CAP_DAC_OVERRIDE |
| seccomp/AppArmor 不得 unconfined | 关掉任一等于打开逃逸通道，在 security-opt 参数里校验 |
| exec-approvals | session 内批准一次，同类命令自动通过；session 结束清零 |
| 正则 vs Docker | 本地开发用正则，生产多租户必须 Docker |

**延伸阅读**：
- [Docker Security Documentation](https://docs.docker.com/engine/security/) — capabilities、seccomp、AppArmor 官方说明
- [Linux capabilities(7) man page](https://man7.org/linux/man-pages/man7/capabilities.7.html) — 完整 capability 列表
- [gVisor](https://gvisor.dev/docs/) — 用户态内核容器沙箱，`--runtime=runsc` 一行切换
- [OWASP LLM Top 10 2025](https://owasp.org/www-project-top-10-for-large-language-model-applications/) — LLM Insecure Code Execution 是前三大威胁之一

---

Lena 在本章学会了"在安全边界里执行代码"——Docker 容器隔离、capabilities 最小化、exec-approvals session 记忆三道防线，让她能跑任意代码而不危及宿主机。

但沙箱保证了"不出事"，不保证"做对了"。Lena 可能在正确的沙箱里执行了错误的逻辑，可能工具选择偏差，可能任务完成率随版本悄悄下滑——而你根本不知道。要持续改进 agent，必须先能度量它。**第 21 章，我们给 Lena 建立 eval 体系——从代码验证到模型评判，让"Lena 变好了"有可量化的证据。**

---

*本章产物：lena-v0.20 — Docker sandbox + exec-approvals session 记忆，三道防线完整实现*

---

## 导航

[← Ch 19. MCP 协议](../ch19-mcp-protocol/README.md) · [下一章 →](../ch21-evals/README.md) · [📘 目录](../../README.md)
