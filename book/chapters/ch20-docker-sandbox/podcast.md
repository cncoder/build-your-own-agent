【窦文涛】上一章我们给 Lena 接上了 MCP，她现在能通过子进程调用任意外部工具。这很强大，但随之而来一个根本性的问题：Lena 现在能执行任意代码了。本章要解决的核心命题，就是让她在真正隔离的容器里跑代码，而不是让 shell 命令直接打到宿主机上。从 v0.19 到 v0.20，这一章是 Lena 安全体系的第二根柱子。

【周迅】容器不就是隔离的吗？

【窦文涛】这正是最常见的误解。裸跑 docker run，默认配置下至少有三个已知逃逸面：capabilities 没有 drop、docker socket 没有封锁、seccomp 配置可能被覆盖。今天我们把这三道防线一条一条建起来，让你真正理解默认 docker run 为什么不安全，以及每一行安全配置背后防的是什么具体威胁。

【窦文涛】先从动机讲起。Princeton SWE-agent 项目证实了一件事：100 行 agent core 在 SWE-bench Verified 上能拿 65% 通过率——但前提是 agent 跑在 Docker 容器里。没有容器隔离，shell 命令直接修改宿主机状态，eval 环境不可重复，安全无从保障。Karpathy 谈 agent 时说过，agent 是数字信息的一种新消费者，基础设施必须为它适配出安全的活动空间，就像浏览器给 JS 提供沙箱一样。

【窦文涛】那为什么正则过滤不够？我们在第十四章加了 ShellSandbox，30 条正则能拦住 rm -rf /。但这条能过去吗：perl -e 'use POSIX; opendir(D,"/"); while($f=readdir(D)){unlink "/$f"}' ——过了，因为正则黑名单里没有 perl。OWASP LLM Top 10（2025）数据：Prompt Injection 导致的任意代码执行，红队测试绕过典型正则过滤的中位时间是 4 分钟。黑名单是一场你永远打不赢的军备竞赛，本章的答案是换方向：不管代码做什么，出不了这个笼子。

【周迅】那容器怎么做到隔离的？

【窦文涛】Linux 容器的隔离依赖内核命名空间机制，六种命名空间把进程彼此隔开：PID 隔离进程树、Mount 隔离文件系统挂载点、Network 隔离网络栈、UTS 隔离主机名、IPC 隔离进程间通信、User 做 UID 映射。容器共享宿主机同一个 Linux 内核，但通过这六层把进程资源视图彼此分开。这和虚拟机的区别在于：VM 有独立 guest 内核，容器没有，这是容器速度快的原因，也是容器隔离的根本局限——内核漏洞可能穿透 namespace 边界，VM 不会。

【窦文涛】理解了命名空间，再看 capabilities。传统 Unix 只有 root 和非 root 两档，Linux capabilities 把 root 的特权拆成 64 个独立位。对沙箱影响最大的三个危险位：CAP_SYS_ADMIN 是万能后门，等同完整 root；CAP_NET_ADMIN 允许配置网络接口和路由表，容器可以建隐形通道外传数据；CAP_DAC_OVERRIDE 绕过文件权限检查，有它容器进程可以读写宿主机权限 777 以下的文件，前提是文件系统已经挂载进容器。

【窦文涛】Docker 默认保留 14 个 capability，这 14 个已经足够完成大多数容器逃逸。安全做法是 --cap-drop=ALL 丢掉全部，再用 --cap-add 精细恢复真正需要的。capability drop 是明确列出不应拥有的权限位，与之对应的是在 drop-all 基础上精细恢复部分权限。

【窦文涛】seccomp 是系统调用层面的最后一道墙。Secure Computing Mode 允许为每个进程配置系统调用白名单，超出白名单的调用内核直接 SIGKILL 进程。程序做任何事——读文件、建连接、创进程——最终都要用系统调用 open、connect、fork 等，seccomp 在这一层设白名单，哪怕绕过了 capabilities 超出白名单的调用也会被内核斩断。

【窦文涛】Docker 默认 seccomp profile 阻断 44 个危险系统调用，包括 ptrace（进程注入）、keyctl（密钥操作）、mount（挂载文件系统）。AppArmor 在资源访问层面做 MAC 约束，两者互补：seccomp 管能不能发起这种系统调用，AppArmor 管程序能不能访问这个资源路径。seccomp profile 是系统调用白名单 JSON，AppArmor profile 是资源访问规则文本，两者都不能设成 unconfined。

【周迅】那怎么把这些组合进代码？

【窦文涛】先看最小骨架。DockerExecutor 初始化接三个参数：image 默认 python:3.12-slim、timeout 默认 30 秒、memory_limit 默认 256m。execute 方法构造 docker run 命令，带 --rm 执行完自动删除容器，--name 用 UUID 前八位，捕获 stdout 和 stderr，超时就调 docker stop 强制停掉。这个骨架能跑代码，但安全配置还没加，我们在防线一里逐一补上。

【窦文涛】防线一：四个关键扩展点加进 _build_secure_cmd 方法。第一，--network=none 完全断网，防数据外传。第二，--read-only 根文件系统只读，配合 --tmpfs /tmp:size=64m 给可写临时目录，大小上限 64MB，容器销毁后消失。第三，--cap-drop=ALL 丢掉所有特权位。第四，--pids-limit 64 防 fork bomb，--cpus 0.5 限制半核。

【窦文涛】docker socket 阻断写在 _validate_no_socket_mount 方法里，检查三个路径：/var/run/docker.sock、/run/docker.sock、rootless Docker 的 /run/user/1000/docker.sock，发现就抛 ValueError 并说明原因。mount 格式 src:dst 或 src:dst:options，取第一段做路径检查。

【窦文涛】为什么 docker socket 要单独强调？容器内只要能访问 /var/run/docker.sock，就可以调用 Docker API 创建新容器，新容器可以挂载宿主机根目录 /，等同完全逃逸到宿主机 root 权限。这是最典型的 docker-in-docker 逃逸路径，_validate_no_socket_mount 方法就是专门封锁这条路。

【窦文涛】防线二：validate_docker_security_opts 函数校验 security-opt 参数，SandboxSecurityError 专门的异常类。三种被阻断的配置：seccomp=unconfined 关掉系统调用过滤，攻击者可用 ptrace 注入宿主机进程；apparmor=unconfined 关掉 MAC 策略，文件访问限制全失效；--privileged 等同给 ALL capabilities 并同时关闭 seccomp 和 AppArmor，等同宿主机 root。这三种配置是容器逃逸的经典入口，在命令构造阶段拦截，不等到运行时。

【周迅】第三道防线是什么？

【窦文涛】防线三是 exec-approvals 的 session 级记忆。场景是这样的：用户让 Lena 处理 50 张图片，每张跑一段 Python 脚本，每次都弹"允许执行吗"体验极差，但完全不问则注入的恶意脚本也静默执行。ExecApprovalStore 这个类用 { session_id: set(command_pattern) } 存批准记录。_extract_pattern 方法从命令提取模式 key，策略是取第一个 token 的二进制名，比如 python3 process_001.jpg 提取出 python3，下次 python3 process_002.py 就自动通过，不再询问。

【窦文涛】关键在 clear_session 方法：session 结束时 del approvals[session_id]，清零所有批准记录。为什么不做永久记忆？永久记忆的问题在于信任边界跨越了对话。每次新对话 Lena 面对的可能是全新上下文：不同任务目标、不同系统提示、不同工具集，甚至系统被 prompt injection 污染后的对话。上一次对 python3 的批准不应自动流入这次对话。session 级记忆在会话内便利性和跨会话信任隔离之间取得平衡——和浏览器的 session cookie 逻辑一致。

【窦文涛】把三道防线组合进 docker_execute 工具函数，逻辑是：先检查 is_approved，没批准就 await ask_user 弹提示，用户拒绝直接返回 denied；批准后调 _executor.execute，捕获 SandboxSecurityError 和 ValueError 返回 blocked 状态；正常执行返回 exit_code、stdout、stderr。这是 Lena 对外暴露的 docker_execute 工具的完整实现。

【窦文涛】运行验证的关键输出：第一次执行 python3 命令，系统弹提示等待 y/n；第二次执行同类 python3 命令，显示"自动通过（session 内已批准 python3）"，不再询问。容器名用 lena-sandbox-{uuid8} 格式，方便调试时 docker inspect 跟踪。失败路径三种：docker command not found 说明 Docker Desktop 没运行，Unable to find image 需要先 docker pull，容器启动超过 5 秒是首次镜像 unpack，后续约 0.3-0.5 秒。

【窦文涛】最后讲一个延伸问题：为什么本章不直接用 gVisor 或 Firecracker？gVisor 是 Google 开源的用户态内核，--runtime=runsc 一行切换，容器内系统调用不直接到宿主机内核而先经过 gVisor 的 runsc，即使逃逸也触达不了宿主机内核。Firecracker 是 AWS 开源的轻量级 microVM，Lambda 和 Fargate 底层技术，boot time 约 125ms，完整内核隔离安全边界等同 VM。两者都比 Docker 容器安全。

【窦文涛】但有具体原因不用。gVisor 的 runsc 与 Docker 默认 runc 系统调用兼容性不完全一致，约 5-10% 的 Linux 程序在 gVisor 下行为异常，教学场景里这个兼容成本不值得承担。Firecracker 需要 KVM 硬件虚拟化，macOS 和大多数个人开发机无法直接用，部署复杂度远高于 docker run。

【窦文涛】更根本的是威胁模型差异：本章防的是"agent 执行的代码破坏宿主机"，不是"专业安全研究员的内核漏洞利用"。Docker + cap-drop + seccomp + AppArmor 组合对前者已足够；后者需要 gVisor 或 Firecracker，那是云厂商基础设施问题。生产多租户场景应当考虑 gVisor 一行切换，个人 assistant 场景三道防线已够。

【周迅】本章的决策树是什么？

【窦文涛】三类场景的判断标准：个人开发 agent、代码来自自己可信来源，ShellSandbox 三层过滤就够，快速无依赖；会处理 LLM 生成或第三方代码，建议 Docker sandbox；团队内部工具处理用户提供代码，Docker sandbox；生产多租户对外服务用户不可信，Docker sandbox 是底线，正则过滤做第一道门快速拒绝明显恶意，Docker 隔离做主力防线。两者的核心维度对比：隔离原理一个是黑名单拦截一个是环境隔离；绕过难度一个低一个高；启动延迟一个近 0ms 一个约 300-500ms；依赖一个无一个需要 Docker；多租户隔离一个无一个强。

【窦文涛】本章小结。容器隔离是共享内核但独立命名空间，比 VM 快，比正则安全。docker socket 阻断是最优先的防线，容器内访问 socket 可逃逸到宿主机 root。capabilities 用 --cap-drop=ALL 丢弃全部，尤其 CAP_SYS_ADMIN 这个万能后门。seccomp 和 AppArmor 绝不能 unconfined，关掉等于打开逃逸通道。

【窦文涛】exec-approvals 是 session 级记忆：批准一次会话内同类自动通过，会话结束清零。Lena 从 v0.19 到 v0.20，第一次彻底隔离执行环境，能跑任意代码而不危及宿主机。Docker 官方安全文档、Linux capabilities man page、gVisor 文档、OWASP LLM Top 10 2025 是延伸阅读的四个入口。下一章给 Lena 加 Evals，让每次迭代都有量化质量信号。
