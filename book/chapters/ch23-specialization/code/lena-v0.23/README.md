# lena-v1.9：Lena-SpecKit 脚手架

> 一行命令从通用 Lena 派生专用 agent

## 快速开始

```bash
pip install -r requirements.txt

# 创建量化交易 agent（3 步）
python -m spec_kit.cli create trader --role "crypto trader" --template trading
vim agents/trader/config.json  # 填入 API 密钥
python -m spec_kit.cli test trader

# 查看所有已创建的 agent
python -m spec_kit.cli list

# 运行 SupervisorAgent 演示
python examples/supervisor_demo.py
```

## 文件结构

```
spec_kit/
├── cli.py           # lena-spec 命令行
├── creator.py       # create 命令：模板 → agent 目录
├── forker.py        # fork 命令：继承 + 裁剪
├── tool_profiles.py # 工具集配置（三种模板）
└── supervisor.py    # SupervisorAgent（agent-as-tools）

examples/
├── trading_bot.py   # 完整量化交易 agent（含熔断器 + 风控）
└── supervisor_demo.py  # 多 agent 路由演示
```

## 三种派生姿势

| 姿势 | 文件 | 适用 |
|------|------|------|
| ① System Prompt 特化 | `system_prompt.md` | 改性格/重点 |
| ② 工具集裁剪 | `tool_profile.json` | 减幻觉/安全隔离 |
| ③ Skills 注入 | `skills/*.md` | 领域专家化 |

## 可用模板

- `trading`：7 工具，量化交易（价格 + 指标 + 下单 + 风控）
- `podcaster`：4 工具，播客生产（采集 + 脚本 + TTS + 推送）
- `devops`：3 工具，DevOps 监控（告警 + 重启 + 通知）
