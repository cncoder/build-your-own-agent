# 第 23 章：Specialization Pattern——一个 Runtime 派生 N 个 Agent

> **[支柱：Specialization]**

---

## Beat 1 — 路线图

```
Ch1  Ch2  Ch3  Ch4  Ch5  Ch6  Ch7  Ch8  Ch9  Ch10
 ●────●────●────●────●────●────●────●────●────●
Ch11 Ch12 Ch13 Ch14 Ch15 Ch16 Ch17 Ch18 Ch19 Ch20
 ●────●────●────●────●────●────●────●────●────●
Ch21 Ch22  ★Ch23★  Ch24
 ●────●────●────────●
         你在这里
```

**本章脉络**：从一个会部署、会观测、7×24 在线的通用 Lena（Ch22 产物）出发 → 理解三种派生姿势的工作原理与 tradeoff → 通过 Agent Squad SupervisorAgent 模式看多专用 agent 的统一调度 → 对比 CrewAI Crew 与 Flow 两种编排范式 → 用 TradingAgents 四层结构理解"角色扮演多 agent"的通用骨架 → 最终跑通 **Lena-SpecKit（lena-v0.23）**，一行命令 `python -m lena_speckit create trader` 派生出一个完整专用 agent 骨架。

途中会踩一个坑：system prompt 里写的"安全规则"在某个边界输入下会被 LLM 直接绕过——这不是 bug，这是 LLM 的结构性局限，理解它才能知道什么时候该把规则写进代码而不是写进 prompt。

**Lena 版本**：Ch22 结束时是 v0.22（生产可部署），本章结束后是 **v0.23**，新增能力是"可复制性"：一套 runtime，一个命令，N 个专用 agent。

> **🧠 聪明度增量（v0.22 → v0.23）**：Lena 第一次能派生专用版本——Lena-SpecKit 让一套通用 runtime 通过一行命令 `python -m lena_speckit create trader` 分叉出量化 / 播客 / DevOps 专用 agent，共享安全护栏和 memory，只修改 system prompt 与工具集。这一章教读者把"从通用到专用"的分叉模式长在自己 agent 架构上的方法。

---

## Beat 2 — 动机

把 Lena 部署到线上一周后，你会收到三类请求。

第一类："我想要一个只做量化交易的 agent，只看价格和指标，别的功能都不要。"
第二类："帮我做一个播客生产 agent，每天早上自动采集、去重、写脚本、合成音频。"
第三类："做一个 DevOps agent，专门盯 AWS 告警，触发条件自动执行处置流程。"

最直觉的做法：给每类需求重新写一个 agent。

算一下这样做的代价：

```python
# 重新写三个 agent 的实际工作量
from_scratch_costs = {
    "agent_loop":        "3-4 天（重写 ReAct 循环）",
    "tool_registry":     "2 天（重写工具注册机制）",
    "memory":            "2 天（重写 memory 系统）",
    "safety":            "3 天（重写安全护栏）",
    "channel":           "2 天（重新接入 Telegram/Discord）",
    "deploy":            "1 天（重新写 systemd 配置）",
    "per_agent":         "13-15 天 × 3 = 40+ 天",
}
```

40 天后，你有三个 agent——但它们的 memory 实现各不相同，安全护栏各有漏洞，部署脚本三个版本互不兼容。三个月后你改了一个底层工具调用约定，得在三处同步修改。

乍看这像是代码复用问题，解法是"继承"。但实际上它更像是**操作系统与进程的关系**——OS 是不变的内核，每个进程是在内核上运行的专用程序，共享内存管理、系统调用、安全模型。你不会为每个进程重新写一个 OS。

Specialization Pattern 就是这个思路：**通用 Lena runtime 是内核，专用 agent 是运行在这个内核上的进程。** 内核只写一次；进程只配置不重写。

没有这个模式，第一个专用 agent 的开发代价是 15 天。有了 Lena-SpecKit，是 15 分钟。

---

## Beat 3 — 理论铺垫

### 3.1 什么是"派生"

Specialization Pattern 在 agent 工程实践里已经有了清晰的定义。Anthropic *Building Effective Agents*（2024-12-19）把这个思路描述为 orchestrator-worker 分层：负责推理的层（LLM 推理能力 + 记忆系统 + ReAct 循环）保持通用；负责执行的层（工具集 + 操作流程）按需替换，即所谓"大脑通用，手可替换"。

Convention：**runtime** = agent 的不变内核（LLM 调用、工具执行框架、内存管理、安全护栏）；**配置层** = 可替换的角色定义（system prompt、工具集、skills）。派生 = 保持 runtime 不变，替换配置层。

理解这个区分，才能知道三种派生姿势各自操作的是哪一层：

```
┌─────────────────────────────────────────────┐
│              Runtime（不变）                  │
│  LLM Provider · Tool 执行框架 · Memory       │
│  AgentLoop · 安全护栏 · Channel 接入         │
├─────────────────────────────────────────────┤
│              配置层（可替换）                  │
│  姿势①  System Prompt（角色、限制、风格）    │
│  姿势②  Tool Profile（允许哪些工具）         │
│  姿势③  Skills（领域 SOP + 操作规范）        │
└─────────────────────────────────────────────┘
```

三种姿势不是互斥的——生产级专用 agent 通常三者叠加。区别在于：当你只有 30 分钟，姿势①够用；当你有半天，姿势①②叠加；当你要把 agent 变成真正的领域专家，需要姿势③。

### 3.2 SupervisorAgent：agent-as-tools 模式

当派生出多个专用 agent 后，出现第二个问题：用户用哪个入口？

硬编码路由（"包含'交易'关键字 → TradingBot，包含'告警'关键字 → DevOpsBot"）的问题是——用户不会按你设计的关键字说话。"BTC 现在怎么样" 里没有"交易"，但显然应该路由给 TradingBot。

Agent Squad（`2FastLabs/agent-squad`，8k stars）提出的 SupervisorAgent 解法：把每个专用 agent 包装成一个 **tool**，让一个具备 LLM 推理能力的 meta-agent 来做路由决策。

Convention：**SupervisorAgent** = 一个以其他 agent 为工具的 meta-agent，负责意图理解和任务委托；**leaf agent** = 被包装成工具的专用 agent，只负责执行，不负责路由。

这个模式来自 OpenAI Agents SDK 的"Handoffs"概念（2025 年）和 Anthropic *Building Effective Agents*（2024-12-19）里的 orchestrator 模式——两者本质相同：把 agent 的调度决策本身也交给 LLM 来完成，而非规则引擎。

### 3.3 CrewAI 双范式：自主协作 vs 事件驱动

多专用 agent 的编排方式有两种根本不同的哲学。

**Crew（自主协作）**：把一组 agent 和一组 task 定义好，让框架根据任务依赖自动编排。用餐厅打比方：厨师、侍者、收银各司其职，一个点单（任务）触发整条服务链。

**Flow（事件驱动）**：定义一个状态机，每个 agent 的输出是下一个 agent 的触发条件。用生产线打比方：传感器 → 质检机器 → 包装机，每个环节的产出是下一个环节的输入，整条线持续运行。

Convention：**Crew** = 一次性任务的角色协作模式（项目制）；**Flow** = 持续运行的状态机编排模式（产品制）。

论文 *Role-Play Prompting Elicits Complex Reasoning in Large Language Models*（Kong et al., 2023）验证了一个反直觉的发现：给 LLM 明确的角色身份（"你是一个量化分析师"）比无角色的通用指令在需要专业推理的任务上准确率提升 9-12%。不需要读完这篇论文，只需要知道核心结论：**role prompt 有效，不是迷信，是实验证明的效果。**

---

## Beat 4 — 脚手架

现在我们来建 Lena-SpecKit 的骨架。它做一件事：给定角色名称和工具集，生成一个完整的专用 agent 目录。

下面实现最小的 SpecKit 骨架——只包含 `create` 命令，暂不包含模板：

```python
# lena_speckit/creator.py（30 行骨架，只处理最小情况）
import os
import json
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class AgentSpec:
    """专用 agent 的完整规格"""
    name: str                      # agent 名称，也是目录名
    role: str                      # 角色描述，注入 system prompt
    tools: list[str] = field(default_factory=list)  # 允许的工具列表
    skills: list[str] = field(default_factory=list) # 注入的 skill 文件列表
    output_dir: Path = field(default_factory=lambda: Path("agents"))

def create_agent(spec: AgentSpec) -> Path:
    """根据 AgentSpec 生成专用 agent 目录结构"""
    agent_dir = spec.output_dir / spec.name
    agent_dir.mkdir(parents=True, exist_ok=True)

    # 生成 system_prompt.md（姿势①）
    (agent_dir / "system_prompt.md").write_text(
        f"你是 {spec.name}，{spec.role}。\n\n"
        f"你的工具：{', '.join(spec.tools) or '继承通用工具集'}\n"
    )

    # 生成 tool_profile.json（姿势②）
    (agent_dir / "tool_profile.json").write_text(
        json.dumps({"allowed_tools": spec.tools}, ensure_ascii=False, indent=2)
    )

    # 生成 config.json（基础配置）
    (agent_dir / "config.json").write_text(
        json.dumps({"agent_id": spec.name, "version": "0.23"}, indent=2)
    )

    return agent_dir
```

运行 `create_agent(AgentSpec(name="trader", role="crypto analyst", tools=["get_price"]))` 后，`agents/trader/` 目录里应该有三个文件：`system_prompt.md`、`tool_profile.json`、`config.json`。这是最小骨架——还不能运行，但目录结构已经确定。接下来我们在这个骨架上逐步增加能力。

---

## Beat 5 — 渐进组装

从骨架出发，依次添加三个真实系统需要的特性：

| 扩展点 | 为何需要 | 如何加 |
|--------|---------|--------|
| Skills 注入（姿势③） | system prompt 只能写"性格"，领域 SOP 需要结构化文档 | 生成 `skills/` 目录，写入 skill markdown |
| CLI 入口 | 让用户一行命令触发，而不是手写 Python | `argparse` 包装 `create_agent` |
| SupervisorAgent | 多专用 agent 需要统一的智能路由入口 | 把每个 agent 包装成 tool |

**扩展 1：Skills 注入**

下面扩展 `create_agent`，同时写入 skills 目录：

```python
# lena_speckit/creator.py（扩展 skills 注入）
SKILL_TEMPLATES = {
    "risk_checker": """# Risk Checker Skill
## 触发条件
每笔交易前调用此 skill。
## 检查清单
- [ ] 单笔风险敞口 ≤ 总资金 2%
- [ ] 今日累计亏损 ≤ 总资金 5%
- [ ] 连续亏损次数 < 3
## 结论输出
APPROVED / REJECTED（含原因）
""",
    "position_sizer": """# Position Sizer Skill
## 输入
- 总资金（USDT）
- 当前价格
- 止损距离（%）
## 计算
仓位大小 = (总资金 × 风险比例) / 止损距离
## 输出
建议开仓数量（精确到小数点后 4 位）
""",
}

def create_agent(spec: AgentSpec) -> Path:
    agent_dir = spec.output_dir / spec.name
    agent_dir.mkdir(parents=True, exist_ok=True)

    (agent_dir / "system_prompt.md").write_text(
        f"你是 {spec.name}，{spec.role}。\n\n"
        f"你的工具：{', '.join(spec.tools) or '继承通用工具集'}\n"
        f"你的 skills：{', '.join(spec.skills) or '无'}\n"
    )
    (agent_dir / "tool_profile.json").write_text(
        json.dumps({"allowed_tools": spec.tools}, ensure_ascii=False, indent=2)
    )
    (agent_dir / "config.json").write_text(
        json.dumps({"agent_id": spec.name, "version": "0.23"}, indent=2)
    )

    # 姿势③：生成 skills 目录
    if spec.skills:
        skills_dir = agent_dir / "skills"
        skills_dir.mkdir(exist_ok=True)
        for skill_name in spec.skills:
            content = SKILL_TEMPLATES.get(skill_name, f"# {skill_name} Skill\n\n待填写。\n")
            (skills_dir / f"{skill_name}.md").write_text(content)

    return agent_dir
```

中间验证：`create_agent(AgentSpec(name="trader", role="crypto analyst", tools=["get_price"], skills=["risk_checker"]))` 应该生成：

```
agents/trader/
├── system_prompt.md       # 含角色 + 工具 + skills 列表
├── tool_profile.json      # {"allowed_tools": ["get_price"]}
├── config.json            # {"agent_id": "trader", "version": "0.23"}
└── skills/
    └── risk_checker.md    # 风控 SOP
```

**扩展 2：CLI 入口**

下面接入命令行入口：

```python
# lena_speckit/__main__.py
import argparse
from pathlib import Path
from .creator import AgentSpec, create_agent

def main():
    parser = argparse.ArgumentParser(prog="lena_speckit")
    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", help="创建新的专用 agent")
    p_create.add_argument("name", help="agent 名称")
    p_create.add_argument("--role", required=True, help="角色描述")
    p_create.add_argument("--tools", default="", help="逗号分隔的工具列表")
    p_create.add_argument("--skills", default="", help="逗号分隔的 skill 列表")
    p_create.add_argument("--output-dir", default="agents", help="输出目录")

    args = parser.parse_args()
    if args.command == "create":
        spec = AgentSpec(
            name=args.name,
            role=args.role,
            tools=[t for t in args.tools.split(",") if t],
            skills=[s for s in args.skills.split(",") if s],
            output_dir=Path(args.output_dir),
        )
        agent_dir = create_agent(spec)
        print(f"✓ Created agent: {spec.name}")
        print(f"  Directory: {agent_dir}")
        print(f"  Tools: {len(spec.tools)}")
        print(f"  Skills: {len(spec.skills)}")

if __name__ == "__main__":
    main()
```

这时候 CLI 已经可以跑了：

```
$ python -m lena_speckit create trader \
    --role "crypto market analyst" \
    --tools "price_feed,orderbook,news_search" \
    --skills "risk_checker,position_sizer"

✓ Created agent: trader
  Directory: agents/trader
  Tools: 3
  Skills: 2
```

**扩展 3：SupervisorAgent**

当有了多个专用 agent，需要一个智能路由层。核心思路是 agent-as-tools：把每个专用 agent 包装成一个工具，让 SupervisorAgent 的 LLM 来决定调用哪个。

```python
# lena_speckit/supervisor.py
import json
from pathlib import Path
from anthropic import Anthropic

class SupervisorAgent:
    """
    agent-as-tools 模式。
    每个专用 agent 被包装成一个工具，supervisor 的 LLM 负责路由。
    """
    def __init__(self, agents_dir: Path = Path("agents")):
        self.client = Anthropic()
        self.agents_dir = agents_dir
        self.agents = self._load_agents()    # {name: system_prompt}
        self.tools = self._build_tools()     # Anthropic tool schema 列表

    def _load_agents(self) -> dict[str, str]:
        agents = {}
        for agent_dir in self.agents_dir.iterdir():
            prompt_file = agent_dir / "system_prompt.md"
            if prompt_file.exists():
                agents[agent_dir.name] = prompt_file.read_text()
        return agents

    def _build_tools(self) -> list[dict]:
        tools = []
        for name, prompt in self.agents.items():
            # 取 system prompt 第一行作为工具描述
            description = prompt.split("\n")[0].lstrip("# ")
            tools.append({
                "name": f"delegate_to_{name}",
                "description": f"委托给 {name} 专用 agent：{description}",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "要委托的具体任务"}
                    },
                    "required": ["task"],
                },
            })
        return tools

    def _run_leaf_agent(self, agent_name: str, task: str) -> str:
        """调用叶子 agent 完成单一任务"""
        system_prompt = self.agents[agent_name]
        resp = self.client.messages.create(
            model="us.anthropic.claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": task}],
        )
        return resp.content[0].text

    def handle(self, user_message: str) -> str:
        """主入口：LLM 路由 + 委托执行"""
        messages = [{"role": "user", "content": user_message}]
        while True:
            resp = self.client.messages.create(
                model="us.anthropic.claude-sonnet-4-6",
                max_tokens=4096,
                system="你是一个任务路由 agent。分析用户意图，委托给最合适的专用 agent 完成任务。",
                tools=self.tools,
                messages=messages,
            )
            if resp.stop_reason == "end_turn":
                return resp.content[0].text

            # 处理工具调用（委托给叶子 agent）
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    agent_name = block.name.replace("delegate_to_", "")
                    result = self._run_leaf_agent(agent_name, block.input["task"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
```

中间验证：创建两个专用 agent，然后测试路由。

```python
# 创建两个 agent
from lena_speckit.creator import AgentSpec, create_agent
create_agent(AgentSpec(name="trader", role="量化交易分析师，专注技术指标分析", tools=["get_price"]))
create_agent(AgentSpec(name="devops", role="DevOps 工程师，专注 AWS 运维告警", tools=["list_alarms"]))

# 启动 supervisor
from lena_speckit.supervisor import SupervisorAgent
sup = SupervisorAgent()
print(f"已加载 agent：{list(sup.agents.keys())}")
# 输出：已加载 agent：['trader', 'devops']
```

---

## Beat 6 — 运行验证

下面组装最终可运行的演示，端到端跑通：

```bash
# 安装
pip install anthropic  # 唯一依赖

# 克隆本章代码
# code/lena-v0.23/

# 创建一个 trader agent
python -m lena_speckit create trader \
  --role "crypto market analyst" \
  --tools "price_feed,orderbook,news_search" \
  --skills "risk_checker,position_sizer"
```

预期输出：

```
✓ Created agent: trader
  Directory: agents/trader
  Tools: 3
  Skills: 2
```

生成的目录结构：

```
agents/trader/
├── config.json
├── system_prompt.md
├── tool_profile.json
└── skills/
    ├── risk_checker.md
    └── position_sizer.md
```

接下来创建第二个 agent 并测试 SupervisorAgent 路由（需要有效的 `ANTHROPIC_API_KEY`）：

```python
# examples/supervisor_demo.py
from pathlib import Path
from lena_speckit.creator import AgentSpec, create_agent
from lena_speckit.supervisor import SupervisorAgent

# 准备两个 agent
create_agent(AgentSpec(
    name="trader",
    role="量化交易分析师，专注技术指标和市场信号分析",
    tools=["get_price", "get_indicators"],
    skills=["risk_checker"],
))
create_agent(AgentSpec(
    name="devops",
    role="DevOps 工程师，专注 AWS 告警监控和运维处置",
    tools=["list_alarms", "get_logs"],
    skills=[],
))

# 启动 supervisor
sup = SupervisorAgent()
print(f"已加载专用 agent：{list(sup.agents.keys())}\n")

# 测试路由
response = sup.handle("BTC 最近的 RSI 趋势如何，适合进场吗？")
print("路由结果：")
print(response)
```

预期输出（不需要真实 price_feed，supervisor 会把任务委托给 trader 的 system prompt 处理）：

```
已加载专用 agent：['trader', 'devops']

路由结果：
[trader agent 基于 system prompt 给出的分析回复...]
```

**常见失败诊断**：

- `ModuleNotFoundError: No module named 'anthropic'` → 运行 `pip install anthropic`
- `AuthenticationError` → 检查 `ANTHROPIC_API_KEY` 环境变量是否设置
- `agents/` 目录为空 → SupervisorAgent 找不到任何 agent，先运行 `create` 命令
- 路由结果总是同一个 agent → 检查两个 agent 的 `system_prompt.md` 第一行描述是否有足够的差异化

**system prompt 的边界**：值得停下来测试一个失败场景。

```python
# BAD：把安全规则写在 system prompt 里
bad_prompt = """
你是 TradingBot。
安全规则：单笔风险敞口不得超过总资金的 2%。
"""

# 测试：传入一个空字符串的 symbol
response = client.messages.create(
    system=bad_prompt,
    messages=[{"role": "user", "content": '下单，symbol=""，数量=10000'}],
    ...
)
# LLM 可能直接回复"好的，已下单"——它忽略了规则
```

这不是 `bad_prompt` 写得不好——**LLM 在处理边界输入时会忽略 prompt 里的规则**，这是结构性局限，不是 prompt 工程问题。正确做法是把风控写进代码：

```python
# GOOD：风控写进代码，不可绕过
def place_order(symbol: str, qty: float, total_capital: float) -> dict:
    if not symbol:
        raise ValueError("symbol 不能为空")  # 代码级硬拦截
    max_position = total_capital * 0.02
    if qty * current_price(symbol) > max_position:
        raise ValueError(f"风险敞口超限：{qty * current_price(symbol):.2f} > {max_position:.2f}")
    return _execute_order(symbol, qty)
```

规则的位置决定了可靠性：**性格和风格写 prompt，安全和护栏写代码**。

下一章，我们把 Lena 派生成一个具体的 Browser Agent——她不只能用工具，还能控制真实的浏览器完成端到端的自动化任务，这是通用 agent 能力的最终压力测试。

---

## Beat 7 — Design Note

### Why Not Always Specialize?（什么时候不该派生）

有了 Lena-SpecKit，很容易陷入"一切皆专用 agent"的陷阱——遇到新需求就 `lena_speckit create`，最终维护着 20 个专用 agent 的配置文件。

这是过度工程的常见形态。

**替代方案**：保持通用 agent，通过 context 注入临时角色。

```python
# 通用 agent + 临时角色注入
response = client.messages.create(
    system="你是 Lena，一个通用 agent。",
    messages=[
        {"role": "user", "content": "接下来你扮演量化分析师，分析 BTC 技术面。"},
        {"role": "user", "content": "BTC RSI 当前 42，MACD 刚金叉，如何判断？"},
    ],
)
```

这种做法的 tradeoff：

- 🟢 零维护成本，不需要管理 agent 目录
- 🟢 角色可以在对话中灵活切换
- 🔴 上下文污染：这次对话的"量化分析师角色"会渗透到后续对话
- 🔴 工具集无法按角色隔离（通用 agent 的所有工具都暴露着）
- 🔴 无法做角色级别的 skills 注入（每次对话都要重新说明 SOP）

**什么时候该派生**：

| 条件 | 建议 |
|------|------|
| 需要持久运行（heartbeat / cron） | 派生 — 临时角色无法持久 |
| 需要工具集隔离（安全需要） | 派生 — 通用 agent 的工具过多 |
| 需要稳定的领域 SOP（不变的操作流程） | 派生 — skills 注入比每次口述 SOP 更可靠 |
| 一次性任务，用完即弃 | 不派生 — 通用 agent 够用 |
| 快速原型，还不确定角色定义 | 不派生 — 先跑通，确认后再固化 |

当前 SpecKit 实现有一个已知局限：skills 模板是硬编码的，没有从文件目录动态加载的能力。如果在生产系统里，会考虑让 skills 来自 Git 管理的 markdown 目录，通过 `git pull` 更新策略而不需要重新生成 agent 配置——这是 Anthropic *Equipping Agents for the Real World with Agent Skills*（2025-10-16）文章里描述的"共享 skills 生态"方向。

### 动态 Agent 生成：Lena-spawn 的思想基础

SpecKit 的"一行命令派生专用 agent"模式，与 Anthropic 白皮书里描述的**动态 Agent 生成（Dynamic Agent Generation）**新兴模式在思想上高度吻合。白皮书将这种模式定义为（p.22）：

> "agents created at runtime by assembling components from libraries of prompts, tools, and configurations, then dissolved after task completion."

翻译过来就是：不预先建好固定的专用 agent，而是在运行时按需从组件库（prompt 库 + 工具库 + 配置库）动态组装，任务完成后即解散。这正是 Lena-spawn 的核心思路——`lena_speckit create trader` 这条命令在本质上就是一次运行时组装：从 `DOMAIN_CONFIGS` 里取出 trader 的工具列表和 skills，写入配置文件，形成一个新的专用 agent 实例。

（来源：Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.22）

动态生成与静态派生的核心区别在于**生命周期**：静态派生的专用 agent 是持久的（你创建了它，它就在那里等待任务）；动态生成的 agent 是临时的（任务来了才组装，任务结束即销毁）。对于需要长期运行的 heartbeat agent（如量化交易监控），静态派生更合适；对于一次性的高复杂度任务（如分析一份 100 页的合同），动态生成的临时专用 agent 反而更经济——用完即销毁，不占用常驻资源。

### 电商场景演进：从 Single Agent 到 Multi-agent 的 5 阶段路径

Anthropic 白皮书用一个电商客服的实际演进案例（p.24-25），展示了 Specialization Pattern 在真实业务里的发展轨迹。这条路径有普适性——几乎所有把 agent 用于规模化业务的团队，都会经历类似的阶段：

| 阶段 | 做法 | 价值 |
|------|------|------|
| **Phase 1** | 单 agent 回答客户咨询 | 验证可行性，建立信心 |
| **Phase 2** | 加入 Routing 分流（订单查询 / 产品咨询 / 投诉处理） | 提升准确率，减少错误路由 |
| **Phase 3** | 每类路由后连接一个 Specialized agent | 专业化带来深度，每个 agent 可独立优化 |
| **Phase 4** | Multi-agent 编排（库存系统 + 支付系统 + 物流系统协调） | 处理跨系统的复杂请求 |
| **Phase 5** | 加入 Evaluator agents 持续质量改进 | 系统自我监测，形成闭环 |

注意这个演进的节奏：从第 1 阶段到第 5 阶段，每一步都在前一步验证有效的基础上才推进。没有 Phase 1 的单 agent 证明价值，就不会有 Phase 2 的路由；没有 Phase 2 的准确率数据，就不知道哪些类别值得专门建一个 Phase 3 的专用 agent。

这就是白皮书那句话的工程含义："**your architecture should evolve with your needs. Start simple, measure everything, add complexity only when it delivers measurable value.**"

---

## 附：Lena 演进路线回顾

```
v0.1  打印一次模型回复（Ch1）
v0.3  REPL + 单工具（Ch3）
v0.6  4 工具并发（Ch6）
v0.14 RAG search_knowledge_base（Ch9 + Ch14）
v0.16 MessageBus + Channel（Ch16）
v0.18 Cron + 断点续传（Ch18）
v0.22 可观测性 + 部署（Ch22）
★ v0.23 Specialization + SpecKit（本章）
```

---

---

Lena 在本章学会了"从通用变专用"——SpecKit 三件套（专用 system prompt + 工具子集 + 记忆过滤器）让同一个 runtime 派生出不同领域的专家 agent，而不需要重写核心逻辑。

但 Specialization 模式的终极考场，是一个需要同时用到六大支柱的真实任务：浏览互联网。Browser Agent 要感知 DOM、生成点击序列、应对动态加载、处理登录态、在反爬限制下设计 fallback——这比任何单一支柱都复杂。**第 24 章，我们用前 23 章全部积累，搭建 lena-v0.24 Browser Agent——通用 agent 的终极压力测试。**
