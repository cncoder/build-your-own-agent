"""
creator.py：lena-spec create 命令实现

功能：根据模板生成完整专用 agent 目录结构。
三种派生姿势全部在这里组装：
  ① system_prompt.md（system prompt 特化）
  ② tool_profile.json（工具集裁剪）
  ③ skills/xxx-sop.md（skills 注入）
"""

from __future__ import annotations

import json
from pathlib import Path

from .tool_profiles import TOOL_PROFILES, get_tools_for_profile


# ── 模板内容 ──────────────────────────────────────────────────────────────

SYSTEM_PROMPTS = {
    "trading": """\
你是 {agent_name}，一个专用量化交易 agent。

## 职责

1. **市场分析**：每 5 分钟扫描 BTC/ETH/SOL 的价格和技术指标（RSI/MACD/BB）
2. **信号决策**：≥2/3 指标共振才考虑开仓
3. **风控优先**：每笔交易前必须通过硬编码风控检查，不可跳过
4. **执行记录**：每次决策记录理由到日志，方便事后复盘

## 性格

- 决策果断，不犹豫
- 风控第一，收益第二
- 数字说话，不讲故事
- 宏观决策，不做微操（止损/止盈由代码执行）

## 约束

- 只能操作白名单交易对
- 不可绕过 _validate_risk_limits()
- 连续亏损 3 笔自动熔断 24h
""",
    "podcaster": """\
你是 {agent_name}，一个专用播客生产 agent。

## 职责

1. **采集**：每天 04:30 从 15 个 collector 采集资讯，去重
2. **脚本**：生成双主播对话脚本（窦文涛风格 A + 梁文道风格 B）
3. **合成**：调用 TTS proxy（port 8880）合成双声道音频
4. **推送**：合成完成后推送飞书通知

## 脚本规范

- 每期 25000-30000 字
- 双主播交替，每段 150-300 字
- 主播 A：低沉稳健，从故事切入
- 主播 B：理性温和，提供背景和分析

## 质量门控

- 内容字数 < 25000 字重跑（最多 3 次）
- 来源多样性：≥5 个不同媒体
""",
    "devops": """\
你是 {agent_name}，一个专用 DevOps 监控 agent。

## 职责

1. **告警监控**：实时检查 AWS CloudWatch ALARM 状态
2. **日志分析**：收到告警后立即拉取相关日志
3. **自动恢复**：符合白名单的故障自动重启服务
4. **通知**：所有告警和处置动作发 Discord 通知

## 自动恢复白名单

- ECS 服务 OOM → 自动重启
- Pod CrashLoopBackOff → 自动重启（≤3次）
- 其他情况 → 告警 + 人工确认

## 约束

- 不可自动扩缩容（需要人工确认）
- 每次操作前发告警，操作后发结果
""",
}

SKILLS = {
    "trading": """\
# Trading SOP（trading-sop.md）

## Step 1：市场扫描（每 5 分钟）

- 调用 get_price 获取实时价格
- 调用 get_indicators 获取 RSI(14)、MACD(12/26/9)、BB(20,2)
- 记录到 scan_log

## Step 2：信号确认

**多头信号**（≥2 满足）：
- RSI < 60（不超买）
- MACD 金叉（MACD 线上穿 Signal 线）
- 价格在 BB 中轨以上

**空头信号**（≥2 满足）：
- RSI > 40（不超卖）
- MACD 死叉（MACD 线下穿 Signal 线）
- 价格在 BB 中轨以下

## Step 3：风控检查（代码层硬编码，不可绕过）

```
单笔风险敞口 ≤ 总资金 2%
最大回撤：连续亏损 3 笔 → 熔断 24h
每日最大亏损 ≤ 总资金 5%
```

## Step 4：执行

1. 记录决策理由到 trade_log.jsonl
2. 调用 place_order
3. 设置止损（-1.5%）+ 止盈（+3%）

## 熔断状态机

```
CLOSED（正常）
  ↓ 连续亏损 3 次
OPEN（熔断）
  ↓ 冷却 24h 后自动转入
HALF_OPEN（试探）
  ↓ 1 笔盈利
CLOSED（恢复）
```

## 血泪教训

- AI 负责宏观决策，不做微操
- 止损/止盈由代码执行，不由 AI 决定
- 空头浮亏不要轻易平仓（会错失后续走势）
""",
    "podcaster": """\
# Podcaster SOP（podcaster-sop.md）

## Phase 1：采集（04:30 触发）

15 个 collector 并行采集，超时 60s：
- twitter_collector（X/Twitter 热门）
- hk_news（香港各大媒体）
- crypto_collector（链上数据 + 加密新闻）
- 其他 12 个 collector...

去重规则：标题相似度 > 0.85 → 保留最新来源

## Phase 2：质量门控

- 总字数 < 25000 → 补充采集，最多 3 次
- 来源多样性 < 5 → 启动备用 collector

## Phase 3：脚本生成

模板：
```
开篇（3 分钟）→ 主题 1（8 分钟）→ 主题 2（8 分钟）→
主题 3（8 分钟）→ 结语（3 分钟）
```

主播对话规范：
- 每个主题 A 先引入，B 深挖，A 总结
- 避免连续同一主播超过 400 字

## Phase 4：TTS 合成

- Qwen3-TTS via Rust proxy（port 8880）
- host_a 声音：低沉（L7 4-bit）
- host_b 声音：理性（L7 8-bit）
- 断点续传：_tts_chunks/ + _progress.json
- 哈希缓存：sha256(voice+text) → WAV

## 量化指标

- PlaybackRTF 目标：< 0.55（当前 0.49）
- 合成时间：25-45 分钟
- 成品时长：30-35 分钟
""",
    "devops": """\
# DevOps SOP（devops-sop.md）

## 告警处理流程

### 收到告警时

1. 立即调用 list_alarms 获取完整状态
2. 根据 alarm_name 判断故障类型
3. 执行对应的处置 SOP（见下方）
4. 发 Discord 通知（告警 + 处置 + 结果）

### ECS 服务异常

- OOM Killed → restart_service（等待 60s 确认恢复）
- Task stopped → 查日志 → 判断是否自动恢复

### K8s Pod 异常

- CrashLoopBackOff（≤3 次）→ restart_service
- CrashLoopBackOff（>3 次）→ 告警 + 等待人工
- Pending 超 5 分钟 → 检查资源配额

### 数据库异常

- 不自动处理，立即告警 + 升级

## 通知模板

```
🚨 [ALARM] {alarm_name}
状态：ALARM → {状态变化}
时间：{timestamp}
处置：{action}
结果：{result}
```
""",
}

DEFAULT_CONFIG = {
    "agent_name": "{agent_name}",
    "model": "us.anthropic.claude-sonnet-4-6",
    "max_tokens": 4096,
    "channel": "discord",
    "api_keys": {
        "note": "在此填入对应 API 密钥",
    },
}


# ── 核心函数 ──────────────────────────────────────────────────────────────

def create_agent(
    name: str,
    role: str,
    template: str,
    output_dir: Path | None = None,
) -> Path:
    """
    创建专用 agent 目录（三种派生姿势全部组装）。

    Args:
        name: agent 名称（如 "trader"）
        role: agent 角色描述（如 "crypto quantitative trader"）
        template: 模板类型（"trading" / "podcaster" / "devops"）
        output_dir: 输出目录（默认为 ./agents/{name}）

    Returns:
        生成的 agent 目录路径
    """
    if output_dir is None:
        output_dir = Path(f"agents/{name}")

    output_dir.mkdir(parents=True, exist_ok=True)
    skills_dir = output_dir / "skills"
    skills_dir.mkdir(exist_ok=True)

    # ① system prompt 特化
    system_prompt = SYSTEM_PROMPTS.get(template, SYSTEM_PROMPTS["trading"])
    (output_dir / "system_prompt.md").write_text(
        system_prompt.format(agent_name=name, role=role),
        encoding="utf-8",
    )

    # ② 工具集裁剪
    tools = get_tools_for_profile(template)
    (output_dir / "tool_profile.json").write_text(
        json.dumps({"profile": template, "tools": [t["name"] for t in tools]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ③ skills 注入
    skill_content = SKILLS.get(template, "")
    if skill_content:
        skill_filename = f"{template}-sop.md"
        (skills_dir / skill_filename).write_text(skill_content, encoding="utf-8")

    # config
    config = {**DEFAULT_CONFIG, "agent_name": name, "role": role, "template": template}
    (output_dir / "config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # README
    tool_list = "\n".join(f"- {t}" for t in TOOL_PROFILES.get(template, []))
    readme = f"""\
# {name} Agent（派生自 Lena-SpecKit）

**角色**：{role}
**模板**：{template}

## 工具集（{len(TOOL_PROFILES.get(template, []))} 个）

{tool_list}

## 快速启动

```bash
# 1. 填入 API 密钥
vim config.json

# 2. 测试
python -m spec_kit.cli test {name}

# 3. 部署
python -m spec_kit.cli deploy {name}
```

## 文件说明

- `system_prompt.md` — 角色性格 + 职责（姿势 ①）
- `tool_profile.json` — 工具集裁剪配置（姿势 ②）
- `skills/` — 领域 SOP 文档（姿势 ③）
- `config.json` — API 密钥 + 模型配置
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    return output_dir
