"""
四要素 Prompt 构造器
Scope / Goal / Constraints / Output

来源：本书第 11 章提炼自 CC 工程实践。
四要素解决的问题：Worker 接到裸指令时输出格式不可预测，汇总困难。
"""
from dataclasses import dataclass


@dataclass
class SubagentPrompt:
    scope: str          # 精确的作战区域
    goal: str           # 用可验证结果表达的目标
    constraints: str    # "不能做什么"和"怎么做"
    output: str         # 明确返回格式，方便 Orchestrator 汇总

    def build(self) -> str:
        return f"""### Scope（范围）
{self.scope}

### Goal（目标）
{self.goal}

### Constraints（约束）
{self.constraints}

### Output（输出格式）
{self.output}"""


def make_research_prompt(target: str) -> str:
    """
    通用调研 Worker prompt。
    target 是调研对象（框架名、技术名、产品名等）。
    """
    return SubagentPrompt(
        scope=f"""只调研 {target}。
- 官方文档和 GitHub repo 为主要来源
- 不调研其他框架或产品""",

        goal=f"""生成一份 {target} 评估报告，包含：
1. 核心 API / 用法（关键类/方法，带简短代码示例）
2. 适用场景（2-3 个典型用例）
3. 生产就绪度评估（checkpoint / 错误处理 / 可观测性）
4. 优缺点各 2-3 条""",

        constraints="""- 最多访问 3 个外部页面
- 报告限 600 字以内
- 信息不足时标注"待确认"，不猜测""",

        output=f"""返回 Markdown：

## {target} 评估

### 核心 API
（代码示例）

### 适用场景
1. ...

### 生产就绪度
评分：X/5
原因：...

### 优点
- ...

### 缺点
- ...
""",
    ).build()


# Orchestrator planner 的 system prompt
ORCHESTRATOR_SYSTEM_PROMPT = """你是 Lena，一个擅长任务规划的 AI Agent。
分析用户任务，判断是否可以拆分为独立并发子任务。
独立 = 子任务之间没有数据依赖，可以同时执行。

输出 JSON（只输出 JSON，不加任何说明）：
{
  "can_parallelize": true,
  "subtasks": [
    {"id": "1", "task": "任务描述", "target": "调研目标名称"},
    {"id": "2", "task": "任务描述", "target": "调研目标名称"}
  ],
  "reason": "一句话说明拆分理由"
}

如果任务不需要拆分：
{"can_parallelize": false, "subtasks": [{"id": "1", "task": "完整任务", "target": ""}], "reason": "理由"}"""
