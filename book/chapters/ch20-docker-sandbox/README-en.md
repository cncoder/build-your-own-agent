# Chapter 20: Docker Sandbox — Most People Think Containers Are a Security Sandbox

> **[Pillar: Safety]**

---

## Beat 1 — Roadmap

```
Ch18 Cron ──→ Ch19 MCP Extension ──→ [Ch20 Docker Sandbox] ──→ Ch21 Evals ──→ Ch22 Deploy
                                              ↑ you are here
Lena v0.18 (scheduled tasks) → v0.19 (MCP tool extension) → v0.20 (container-isolated execution)
```

In the previous chapter we connected Lena to MCP; she can now call any external tool service via subprocesses. This is powerful, but it also opens a door: **Lena can now execute arbitrary code.**

This chapter starts with a counterintuitive reversal, moves through Docker container isolation's three lines of defense, and arrives at Lena v0.20 able to run arbitrary shell inside a fully isolated container — along the way we'll hit the most common trap: the default `docker run` is not safe.

After this chapter, Lena goes from v0.19 (MCP extension) to v0.20, with a new capability: executing arbitrary shell inside an isolated container, docker socket inaccessible, capabilities dropped, seccomp profile active, exec approval memory cleared at session level.

> **🧠 Intelligence increment (v0.19 → v0.20)**: Lena completely isolates the execution environment for the first time — Docker sandbox's three lines of defense (capabilities drop / seccomp profile / socket blocking) prevent arbitrary code execution from destroying the host, because "regex blacklists can never enumerate all bypass methods". This chapter teaches readers how to build structural security isolation into their own agents.

---

## Beat 2 — Motivation

Karpathy identified an underappreciated fact when talking about agents:

> "Agents are a new class of consumer for digital information. Infrastructure must adapt."

The corollary: if agents are "consumers", they need a **safe activity space** — just like browsers provide a sandbox for web JavaScript. For agents, that sandbox is a Docker container.

The Princeton SWE-agent project confirmed this: with just **100 lines of agent core**, it achieved a **65% pass rate** on SWE-bench Verified — but only when the agent ran inside a Docker container. Without container isolation, the agent's shell commands directly modified host state, making the eval environment non-reproducible and security impossible to guarantee.

### What Happens Without This Chapter?

Let's actually run it. In v0.19's Lena, `shell_execute` runs directly on the host:

```python
import subprocess

result = subprocess.run(
    "echo cm0gLXJmIC90bXAvdGVzdA== | base64 -d | bash",
    shell=True, capture_output=True, text=True
)
# Decoded: rm -rf /tmp/test — but what if it were rm -rf $HOME?
```

In Ch14 we added ShellSandbox, which blocks `rm -rf /` and also blocks `python3 -c "import os"`. But does this pass its regex filter?

```bash
perl -e 'use POSIX; opendir(D,"/"); while($f=readdir(D)){unlink "/$f"}'
```

It passes. Because ShellSandbox's 30 regexes don't include `perl` — you can never enumerate all languages and all bypass methods.

The rate at which blacklists fail has a cold number from real attacks: in OWASP LLM Top 10 (2025), for arbitrary code execution caused by Prompt Injection, the median time to bypass typical regex filters in red team testing is **4 minutes**.

Counter-argument: could you just add more regexes? Yes, but for every one you add, there's a new bypass. This is an arms race you can never win.

This chapter's answer is to change direction: **no matter what the code does, it can't escape this cage.**

---

## Beat 3 — Theory

### 3.1 The Three Namespaces of Container Isolation

Linux container isolation relies on the kernel namespace mechanism. Unlike virtual machines, containers share the same Linux kernel but isolate processes from each other via six types of namespaces:

| Namespace | Isolated Resources | Sandbox Significance |
|---|---|---|
| **PID** | Process tree | Processes inside the container can't see host processes, can't kill host processes |
| **Mount (mnt)** | Filesystem mount points | Container has an independent root filesystem view, host directories invisible by default |
| **Network (net)** | Network stack, ports | Container has independent network interfaces, can be configured to completely block network (`--network none`) |
| **UTS** | Hostname, domain name | Container has independent hostname, prevents information leakage |
| **IPC** | Inter-process communication | Semaphores, shared memory isolated from host |
| **User** | UID/GID mapping | Root inside container can be mapped to an ordinary host user |

Convention: **Container** = a process group with resources isolated using Linux namespaces; **VM (virtual machine)** = a complete virtual hardware environment running an independent guest kernel. Containers share the host kernel; VMs do not. (Throughout this chapter, "container" means Docker container, "VM" means virtual machine.)

This shared-kernel characteristic is the fundamental limitation of container isolation: **if an attacker can exploit kernel vulnerabilities, the container boundary may be breached** — a problem that VMs don't have. But containers have far lower startup times and resource overhead than VMs, making them an acceptable tradeoff for code execution sandbox scenarios.

### 3.2 Capabilities: A Finer Permission Model Than root

The traditional Unix permission model has only two levels: "root" and "non-root". Linux capabilities split root's permissions into 64 independent bits, and each process can precisely control which ones it has.

Three dangerous capabilities directly relevant to agent sandboxes:

- **CAP_SYS_ADMIN**: The universal backdoor. Allows mounting filesystems, modifying kernel parameters, accessing devices. Almost equivalent to complete root. Not granted to containers by default, but misconfiguration is extremely common — some tutorials add it to "make Docker work properly".
- **CAP_NET_ADMIN**: Allows configuring network interfaces, routing tables, firewall rules. With it, a container can create "invisible channels" to exfiltrate data.
- **CAP_DAC_OVERRIDE**: Bypasses file permission checks (Discretionary Access Control). With it, container processes can read and write any file on the host with permissions below 777 — provided the filesystem has been mounted into the container.

Convention: **capability drop** = explicitly listing permission bits the container should not have; **capability add** = precisely restoring partial permissions on top of a drop-all baseline. The secure approach is `--cap-drop=ALL --cap-add=<only what you need>`.

Reference: Docker's default list of 14 retained capabilities comes from [Linux man 7 capabilities](https://man7.org/linux/man-pages/man7/capabilities.7.html) — no need to read it all, just know: **the capabilities retained by default are still sufficient to complete most container escapes, and must be explicitly dropped**.

### 3.3 seccomp and AppArmor: The Last Wall at the Syscall Level

Even with correct capability configuration, attackers may still escape via syscall vulnerabilities. seccomp and AppArmor add another layer of constraint at the syscall level:

**seccomp** (Secure Computing Mode) is a Linux kernel feature that allows configuring a syscall whitelist for each process. Calls outside the whitelist are immediately killed by the kernel (SIGKILL) or return EPERM.

Intuitive explanation: programs do everything — read files, open connections, create processes — ultimately through syscalls like `open()`, `connect()`, `fork()`. seccomp sets a whitelist at this level. Even if code inside the container bypasses capabilities, syscalls outside the whitelist will be cut off by the kernel.

Docker's default seccomp profile blocks 44 dangerous syscalls, including `ptrace` (process injection), `keyctl` (key operations), `mount` (filesystem mounting), etc.

**AppArmor** is a Linux Mandatory Access Control (MAC) framework that defines allowed file paths, network operations, and capabilities for each process.

Difference from seccomp: seccomp governs "can this kind of syscall be made", AppArmor governs "can this program access this resource". The two complement each other and don't conflict.

Convention: **seccomp profile** = syscall whitelist, configured in JSON format; **AppArmor profile** = resource access rules, configured in text format. (Throughout this chapter, "seccomp" and "AppArmor" refer to these two respectively.)

---

## Beat 4 — Skeleton

At first glance a Docker container looks like a naturally secure sandbox — after all, code runs "inside a box". But in reality, a bare `docker run` command with default configuration has at least 3 escape surfaces: unrestricted capabilities, docker socket not blocked, and security options not verified against bypass.

Let's build the minimal Docker execution skeleton and see exactly what it does and doesn't protect:

```python
# lena-v0.20/sandbox/docker_executor.py
# Minimal skeleton: can run code, but not secure with default config
# We add defenses one by one in Beat 5

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecResult:
    """Container execution result."""
    stdout: str
    stderr: str
    exit_code: int
    container_id: str  # for debugging


class DockerExecutor:
    """
    Skeleton for executing shell commands inside a Docker container.

    Default parameter explanation:
    - image: python:3.12-slim  -- lightweight image, ~150MB
    - timeout: 30              -- prevents infinite loops, unit: seconds
    - memory_limit: "256m"     -- prevents memory explosion, units can be k/m/g
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
        Execute a command in a container, destroy container immediately after (--rm).
        This version is a bare skeleton; Beat 5 adds security defenses.
        """
        container_name = f"lena-sandbox-{uuid.uuid4().hex[:8]}"

        cmd = [
            "docker", "run",
            "--rm",                              # auto-delete container after execution
            "--name", container_name,
            "--memory", self.memory_limit,       # memory limit
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
            # Timeout: force stop the container
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

Running `asyncio.run(DockerExecutor().execute("echo hello"))` should yield `stdout="hello", exit_code=0`. Now we add defenses to this skeleton step by step.

---

## Beat 5 — Progressive Assembly

### Defense Line 1: Block docker socket mounting

| Extension Point | Why Needed | How to Add |
|---|---|---|
| Block docker socket mounting | If the container can access `/var/run/docker.sock`, it can call the Docker API to create new containers, which can mount host `/`, equivalent to complete escape | Check `--volume` arguments before startup, reject socket paths |
| Drop all capabilities | The 14 default retained capabilities are enough to escape (e.g., `CAP_NET_BIND_SERVICE`+`CAP_SYS_RAWIO` combination) | `--cap-drop=ALL` |
| Read-only root filesystem | Prevents code from modifying system files inside the container (some escapes require writing to `/etc/ld.so.preload`) | `--read-only` + `--tmpfs /tmp` |
| No network | Code execution sandbox should not have outbound internet access, prevents data exfiltration | `--network=none` |

Any of these four extension points missing leaves a known escape path. Let's add them one by one and verify:

```python
# Extension 1: docker socket blocking + capabilities drop + read-only root filesystem + no network
# Replace the cmd construction part in execute()

BLOCKED_SOCKET_PATHS = [
    "/var/run/docker.sock",
    "/run/docker.sock",
    # path used by some rootless Docker installations
    "/run/user/1000/docker.sock",
]


class DockerExecutor:
    # ... __init__ unchanged ...

    def _validate_no_socket_mount(self, extra_mounts: list[str]) -> None:
        """
        Reject any request to mount the docker socket.
        This is the most critical defense: blocking the docker-in-docker escape path.
        """
        for mount in extra_mounts:
            # mount format is "src:dst" or "src:dst:options"
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
        """Build docker run command with complete security options."""
        mounts = extra_mounts or []
        self._validate_no_socket_mount(mounts)

        cmd = [
            "docker", "run",
            "--rm",
            "--name", container_name,
            # === Resource limits ===
            "--memory", self.memory_limit,
            "--cpus", "0.5",                    # CPU limit: half a core
            "--pids-limit", "64",               # process limit: prevents fork bomb
            # === Network isolation ===
            "--network=none",                   # complete network cut
            # === Filesystem restrictions ===
            "--read-only",                      # root filesystem read-only
            "--tmpfs", "/tmp:size=64m",         # temp dir writable, max 64MB
            # === Capabilities ===
            "--cap-drop=ALL",                   # drop all capabilities
            # === Security options (Beat 5 defense line 2) ===
            # --security-opt added in next step
        ]

        # Extra mounts (already validated, no socket)
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

Verify blocking is effective:

```python
import asyncio

executor = DockerExecutor()

# Normal execution
result = asyncio.run(executor.execute("echo 'hello from container'"))
print(result.stdout)
# Expected output: hello from container

# Attempt to mount docker socket — should raise ValueError
try:
    asyncio.run(executor.execute(
        "docker ps",
        extra_mounts=["/var/run/docker.sock:/var/run/docker.sock"]
    ))
except ValueError as e:
    print(f"BLOCKED: {e}")
# Expected: BLOCKED: SECURITY: Mounting docker socket is forbidden...
```

---

### Defense Line 2: Verify seccomp/AppArmor Configuration Not Bypassed

| Extension Point | Why Needed | How to Add |
|---|---|---|
| Block `seccomp=unconfined` | Disabling seccomp allows `ptrace` to inject into host processes | Check security-opt arguments in `_build_secure_cmd` |
| Block `apparmor=unconfined` | Disabling AppArmor removes MAC constraints, file access rules no longer apply | Same as above |
| Block `--privileged` | Equivalent to granting ALL capabilities and disabling seccomp/AppArmor | Check if `--privileged` is passed |

These three configuration combinations are classic entry points for container escapes:

```python
# BAD: any one of these three lines breaks the sandbox
# docker run --security-opt seccomp=unconfined ...
# docker run --security-opt apparmor=unconfined ...
# docker run --privileged ...
```

Add startup validation to `DockerExecutor`:

```python
class SandboxSecurityError(Exception):
    """Sandbox security configuration violation."""
    pass


def validate_docker_security_opts(security_opts: list[str]) -> None:
    """
    Validate docker run --security-opt arguments,
    reject any configuration that weakens isolation.

    Corresponds to the logic at validate-sandbox-security.ts:311-322 (TypeScript reference implementation).
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
    """Reject the --privileged flag."""
    if "--privileged" in args:
        raise SandboxSecurityError(
            "FORBIDDEN: --privileged grants ALL capabilities and disables seccomp/AppArmor.\n"
            "This is equivalent to root on the host."
        )
```

Print one intermediate verification result:

```python
# Verify validation functions work correctly
try:
    validate_docker_security_opts(["seccomp=unconfined"])
except SandboxSecurityError as e:
    print(f"✓ Validation blocked successfully:\n{e}")

try:
    validate_no_privileged(["docker", "run", "--privileged", "ubuntu"])
except SandboxSecurityError as e:
    print(f"✓ privileged blocked successfully:\n{e}")
# Expected: both ✓ lines output
```

---

### Defense Line 3: exec-approvals Session-Level Memory

In a complete agent execution flow, a user might ask Lena to process 50 images, each requiring a Python script to run. Asking "allow execution?" every single time is a terrible experience; never asking means injected malicious scripts also execute silently.

| Extension Point | Why Needed | How to Add |
|---|---|---|
| Session-level approval memory | Repeated similar commands within a session should not repeatedly interrupt the user | Use session_id + command pattern as key, stored in memory |
| Clear on session end | Prevents approvals from "contaminating" across sessions, each new conversation resets trust boundary | `del approvals[session_id]` when session closes |
| Pattern rather than exact match | Approving `python3 process.py` should auto-pass `python3 process2.py` | Extract command prefix as pattern key |

```python
# sandbox/exec_approvals.py
import re
from typing import Callable, Awaitable


class ExecApprovalStore:
    """
    Session-level command approval memory.

    Approve once → same-type commands in session auto-pass
    Session ends → all approval records cleared

    This is the Python equivalent of exec-approvals.ts.
    """

    def __init__(self) -> None:
        # { session_id: set(command_pattern) }
        self._approvals: dict[str, set[str]] = {}

    def _extract_pattern(self, command: str) -> str:
        """
        Extract pattern key from command.
        e.g.: 'python3 process_001.jpg' → 'python3'
              'curl https://docs.anthropic.com/data' → 'curl'
        Strategy: take the first token (the command name itself)
        """
        token = command.strip().split()[0] if command.strip() else command
        # Remove path prefix, keep only binary name
        return token.rsplit("/", 1)[-1]

    def is_approved(self, session_id: str, command: str) -> bool:
        """Check if this command pattern has been approved in this session."""
        pattern = self._extract_pattern(command)
        return pattern in self._approvals.get(session_id, set())

    def approve(self, session_id: str, command: str) -> None:
        """Record approval."""
        pattern = self._extract_pattern(command)
        if session_id not in self._approvals:
            self._approvals[session_id] = set()
        self._approvals[session_id].add(pattern)

    def clear_session(self, session_id: str) -> None:
        """Clear on session end."""
        self._approvals.pop(session_id, None)

    def session_approved_count(self, session_id: str) -> int:
        """View the number of approved patterns in current session (for debugging)."""
        return len(self._approvals.get(session_id, set()))


# Global singleton
_approval_store = ExecApprovalStore()


def get_approval_store() -> ExecApprovalStore:
    return _approval_store
```

Verify session memory behavior:

```python
store = ExecApprovalStore()

# session A: approve python3, same-type auto-pass afterward
store.approve("session-A", "python3 process_001.py")
print(store.is_approved("session-A", "python3 process_002.py"))  # True
print(store.is_approved("session-A", "curl https://evil.com"))   # False

# session B is independent
print(store.is_approved("session-B", "python3 anything.py"))    # False

# session A ends, cleared
store.clear_session("session-A")
print(store.is_approved("session-A", "python3 process_001.py")) # False
print(f"✓ Session memory verification passed: 3 True, 2 False, all as expected")
```

---

## Beat 6 — Run Verification

Combine all three defense lines into a complete Lena tool call flow. Complete deliverable in `code/lena-v0.20/`.

```python
# lena-v0.20/tools/docker_shell.py  —  Lena's docker_execute tool
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
    Lena's code execution tool: run arbitrary shell inside a Docker container.
    Three defense lines:
    1. docker socket already blocked internally by DockerExecutor
    2. seccomp/AppArmor bypasses blocked by validate_docker_security_opts
    3. exec-approvals session-level memory controls approval frequency
    """
    # Defense line 3: check if already approved
    if not _approvals.is_approved(session_id, command):
        allowed = await ask_user(
            f"Lena wants to execute (inside container):\n`{command}`\n\nAllow? (y/n) "
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

Run verification:

```bash
cd code/lena-v0.20
pip install -r requirements.txt  # only needs anthropic
docker pull python:3.12-slim     # ~150MB, pulled once then cached

python main.py
```

You should see output like:

```
Lena v0.20 started, Docker sandbox ready
> Run a Python snippet to check system info

Lena wants to execute (inside container):
`python3 -c "import platform; print(platform.uname())"`
Allow? (y/n) y

✓ Executed (container lena-sandbox-a3f91b2c, took 1.2s)
uname_result(system='Linux', node='lena-sandbox-a3f91b2c', ...)

> Check system info again

✓ Auto-passed (python3 already approved in session, container lena-sandbox-77e4cd10, took 0.9s)
uname_result(system='Linux', ...)
```

The second execution auto-passes without asking — exec-approvals is working.

Troubleshooting:
- `docker: command not found` → confirm Docker Desktop is running (`docker ps` to verify)
- `Unable to find image 'python:3.12-slim'` → run `docker pull python:3.12-slim` to pull the image first
- Container takes more than 5 seconds to start → first startup needs image unpack, subsequent starts take ~0.3-0.5 seconds

> Lena can now run arbitrary shell in a completely isolated container, but she doesn't yet know how to judge whether she's doing well — next chapter, we add Evals to give every iteration a quantified quality signal.

---

## Beat 7 — Design Note

> **Why Not gVisor or Firecracker for Maximum Safety?**

If Docker containers sharing the host kernel creates potential kernel vulnerability escape routes, do stronger alternatives exist? Two do:

**gVisor** (Google open source) implements a lean Linux kernel in user space (syscall interception layer); syscalls from inside the container don't reach the host kernel directly but first pass through gVisor's runsc. Even if the container escapes, it at most reaches gVisor's user space, unable to touch the host kernel. The `--runtime=runsc` flag lets you replace Docker's default runc without any code changes.

**Firecracker** (AWS open source, underlying technology for Lambda and Fargate) uses lightweight microVMs for strong isolation, with each function running in an independent VM, boot time ~125ms. Complete kernel isolation, security boundary equivalent to a VM.

**Why doesn't this chapter use either of them?**

1. gVisor's runsc and Docker's default runc have incomplete syscall compatibility — roughly 5-10% of Linux programs behave abnormally under gVisor. For a teaching code execution sandbox, this compatibility cost isn't worth bearing.

2. Firecracker requires KVM hardware virtualization support, which isn't directly available on macOS or most personal developer machines; installation complexity is far higher than `docker run`.

3. This chapter's threat model is "prevent code executed by the agent from damaging the host", not "defend against professional security researchers exploiting kernel vulnerabilities". Docker + cap-drop + seccomp + AppArmor is sufficient for the former; the latter requires gVisor or Firecracker, but that's a cloud provider infrastructure problem, not a personal agent's problem.

If you're providing code execution capabilities to multiple tenants in production, you should consider gVisor (one flag to switch the runtime). If it's a personal assistant that only you use, the three defense lines in this chapter are sufficient.

---

## On Why exec-approvals Is Session-Level, Not Global

A reasonable question: why not permanently remember "the user once approved python3"?

The problem with permanent memory is **trust boundary crossing across conversations**. Each new conversation, Lena faces potentially completely new context: different task goals, different system prompts, different tool sets — even a conversation whose system has been contaminated by prompt injection. Approval of `python3` from the previous conversation should not automatically flow into this conversation.

Session-level memory strikes a balance between "in-session convenience" and "cross-session trust isolation": approve once, no more interruptions in the session; session ends, trust resets to zero. This is the same logic as browser session cookies.

---

## Appendix: Regex Filtering vs Docker Sandbox Decision Tree

```
What is my scenario?
├── Personal development agent, only I use it
│   ├── Code comes from me (trusted source)
│   │   → ✅ ShellSandbox three-layer filtering (Ch14) is enough
│   │      Fast, no dependencies, 200 lines of Python
│   └── Will process code from LLM generation or third parties
│       → ⚠ Recommended to use Docker sandbox
│
├── Internal team tool (10-100 people, employees trusted)
│   └── Will process user-provided code or externally scraped content
│       → ✅ Docker sandbox
│
└── Production multi-tenant (serving external users, users untrusted)
    → ✅ Docker sandbox is the minimum baseline
       Regex filtering as the first gate (quickly reject obvious malicious input),
       Docker isolation as the main defense line
```

| Dimension | ShellSandbox Regex Filtering (Ch14) | Docker Sandbox (this chapter) |
|---|---|---|
| Isolation principle | Blacklist blocking | Environment isolation |
| Bypass difficulty | Low (base64/perl/ruby and many other bypasses) | High (requires kernel exploit or docker socket) |
| Startup latency | ~0ms | ~300-500ms (after image is pulled) |
| Dependencies | None | Docker environment |
| Multi-tenant isolation | None (same process) | Strong (independent containers) |
| Use case | Local development, single user | Production, multi-tenant, arbitrary code |

---

## Chapter Summary

| Concept | One Line |
|---|---|
| Container isolation | Shared kernel but independent namespaces — faster than VMs, more secure than regex |
| docker socket blocking | Container must not access `/var/run/docker.sock`, or it can escape to host root |
| capabilities drop | `--cap-drop=ALL` drops all privilege bits, especially CAP_SYS_ADMIN/CAP_NET_ADMIN/CAP_DAC_OVERRIDE |
| seccomp/AppArmor must not be unconfined | Disabling either opens an escape channel; validate in security-opt arguments |
| exec-approvals | Approve once in session, same-type commands auto-pass; session ends, cleared |
| Regex vs Docker | Use regex for local development, production multi-tenant must use Docker |

**Further reading**:
- [Docker Security Documentation](https://docs.docker.com/engine/security/) — official explanation of capabilities, seccomp, AppArmor
- [Linux capabilities(7) man page](https://man7.org/linux/man-pages/man7/capabilities.7.html) — complete capability list
- [gVisor](https://gvisor.dev/docs/) — user-space kernel container sandbox, switch with `--runtime=runsc`
- [OWASP LLM Top 10 2025](https://owasp.org/www-project-top-10-for-large-language-model-applications/) — LLM Insecure Code Execution is one of the top three threats

---

Lena learned "executing code within a secure boundary" in this chapter — Docker container isolation, minimal capabilities, and exec-approvals session memory as three defense lines let her run arbitrary code without endangering the host.

But sandboxing guarantees "nothing goes wrong", not "the right thing is done". Lena might execute incorrect logic inside a correct sandbox, might have tool selection bias, might see task completion rate quietly drop between versions — and you'd have no idea. To continuously improve an agent, you must first be able to measure it. **Chapter 21, we build an eval system for Lena — from code verification to model judging, making "Lena got better" a quantifiable claim.**

---

*Chapter deliverable: lena-v0.20 — Docker sandbox + exec-approvals session memory, three defense lines fully implemented*
