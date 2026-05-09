# lena-v1.6 — Docker Sandbox

## 前提条件

```bash
# 安装 Docker（Mac）
brew install --cask docker
open /Applications/Docker.app  # 启动 Docker Desktop

# 验证
docker --version   # Docker version 27.x.x

# 安装依赖
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

## 架构

```
main.py                    — 主入口，Lena 对话循环
docker_sandbox.py          — Docker 容器创建/执行/销毁
exec_approvals.py          — session 级批准记忆
sandbox_validator.py       — 安全配置校验（阻 socket 挂载/seccomp 绕过）
```

## 版本历史

- v1.0：安全基线（Ch10：ShellSandbox + PromptGuard + HITL）
- v1.1：工具系统（Ch4）
- v1.2：流式响应（Ch5）
- v1.3：文件记忆（Ch6）
- v1.4：Cron + Heartbeat（Ch13）
- v1.5：MCP 三服务接入（Ch15）
- **v1.6：Docker sandbox + exec-approvals（本章）**
