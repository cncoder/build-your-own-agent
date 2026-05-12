# 第 12 章：Skills——可复用的能力单元

> **[支柱: Tool universality / Specialization]**

```
Ch 1 → Ch 3 → Ch 6 → Ch 8 → Ch 11 → [Ch 12 ← 你在这里] → Ch 13 → ...
工具系统  流式并发  记忆    Planning   MCP        Skills     安全输入层
```

本章从 Lena v0.11（能用 MCP 连外部工具）出发，经过"Skills 是什么 → 加载机制 → 如何写 → 为何行业跟进"，到达 Lena v0.12——能从 `skills/` 目录动态加载 `weather.md` 和 `pdf-report.md`，`/weather 上海` 一键触发完整 SOP。

途中会踩一个坑：**Skills 不是比 Tools 更高级的工具，而是完全不同的东西**——搞混这一点会让你构建出一个既臃肿又难用的系统。

> **🧠 聪明度增量（v0.11 → v0.12）**：Lena 第一次按需加载知识——Skills 三级渐进披露机制让她从 `skills/` 目录动态读取多步 SOP，`/weather 上海` 一键触发完整流程，复用能力不再需要改核心代码。这一章教读者把可组合的"知识单元"能力长在自己 agent 上的方法。

---

## Beat 1 — 本章地图

Lena 到了 v0.11，已经能通过 MCP 连接外部工具。工具系统很强大——但你有没有注意到一个奇怪的现象：**工具越多，系统提示越长，而 LLM 的实际表现却在下降**？

这一章要回答一个具体问题：**当"怎么做某类任务"这类知识越来越多时，把它们放在哪里？**

答案不是更多的工具、更长的系统提示，而是一个完全不同的概念：**Skill**。

本章路线：

```
问题：工具 docstring 膨胀 → 根因：能力 ≠ 知识
  → Skill 是什么（SOP Markdown）
    → 渐进式披露三层结构（元数据 → 全文 → 子文件）
      → Python 骨架实现（Skill 数据类 + 目录加载 + slash 命令）
        → Lena v0.12：/weather 上海 一键触发完整 SOP
```

读完这一章，你的 agent 将第一次拥有"按需加载知识"的能力——复用新 SOP 只需要新建一个 `.md` 文件，不用改核心代码。

---

## Beat 2 — 动机：工具够了吗？

让我们从一个具体的失败场景开始。

假设你想让 Lena 生成 PDF 报告。你用工具的思路来做：

```python
# 方案 A：给 Lena 一个 PDF 工具
@tool
def generate_pdf(content: str, template: str) -> str:
    """生成 PDF 报告"""
    ...
```

然后你发现问题来了。工具告诉 Lena "我能生成 PDF"，却没告诉她：
- 生成之前，应该先提取数据中的关键数字
- 应该用哪个模板（根据报告类型不同）
- 表格里的数字应该如何格式化（千分位？保留几位小数？）
- 如果内容太长，应该如何分页
- 生成失败时，用户看到的是什么

于是你把这些逻辑全部堆进 `generate_pdf` 的 docstring 里：

```python
@tool
def generate_pdf(content: str, template: str) -> str:
    """
    生成 PDF 报告。
    使用前，请先提取内容中的关键数字。
    模板选择规则：季度报告用 quarterly，日报用 daily，其他用 default。
    数字格式：超过 1000 的整数加千分位，金额保留两位小数。
    分页规则：每页最多 3 个图表，文字超过 500 字自动分页。
    错误处理：渲染失败时告知用户"报告生成遇到问题"，不暴露技术细节。
    ...（省略 200 行）
    """
    ...
```

docstring 变成了 200 行，工具注册表里 80% 的 token 全是"怎么用"的说明而不是"能做什么"。

每次 LLM 需要判断"该不该调用这个工具"，都要把这 200 行读一遍。更糟的是：**每一次生成 PDF，无论用什么模板，这 200 行都在消耗你的 context**。

这就是 Tools 的天花板：**工具描述的是能力，不是知识**。

真实系统里，Claude Code 的内置工具里，`FileReadTool` 的 schema 只有 150 行，而有经验的 CC 用户在 `<config>/skills/` 目录里放了 30 个 skill 文件，每个都是 "怎么做这类任务" 的 SOP。按需加载，用的时候才占 context。

Skills 就是那 200 行应该去的地方。

---

## Beat 3 — 理论铺垫

### 3.1 Tool 与 Skill 的本质差异

Convention：**Tool = 函数**（声明"我能做 X"）；**Skill = SOP**（描述"做 X 类任务的正确方法"）。后续统一用此定义。

乍看 Skill 像是一个"更丰富的工具"——但实际上它更像 **新员工入职手册里的某一章**。你不会把手册里的内容硬塞进每一个工作流程，而是让员工在需要时翻开查阅。

| 维度 | Tool | Skill |
|------|------|-------|
| 形态 | 函数（代码） | SOP（Markdown） |
| 描述的是 | 一个能力 | 一类任务的做法 |
| 执行方式 | LLM 调用 → runtime 执行 | 按需注入 system prompt |
| 何时占 context | 始终（注册即占用） | 仅触发时 |
| 共享方式 | 发布代码包 | 分享 .md 文件 |
| 可读性 | 对人不友好（schema） | 对人友好（自然语言） |
| 修改成本 | 改代码 + 部署 | 改 Markdown |

工具的 docstring 越长，你就越接近一个 Skill 的需求。

### 3.2 渐进式披露：Skills 的核心设计原则

Anthropic 在 *Equipping Agents for the Real World with Agent Skills*（2025-10-16）中把 Skills 的加载设计比作一本结构良好的手册：

> "Like a well-organized manual that starts with a table of contents, then specific chapters, and finally a detailed appendix."

三层结构，始终只有第一层在 context 里：

```
Level 1 — 元数据（始终在 system prompt 中）
  name + description    ← "手册目录"
  约 20-50 tokens/skill

Level 2 — 完整 SKILL.md 内容（用户触发 /skill_name 时加载）
  完整的 SOP 正文        ← "打开该章节"
  100-500 tokens/skill

Level 3+ — 链接的子文件（Skill 内部按需引用）
  外部文档、示例文件      ← "查看附录"
  仅当 Skill 引用时加载
```

这个设计解决了 Tools 的核心矛盾：**知识需要在 context 里，但 context 是有限的**。Skills 的答案是"只有正在用的知识才需要在 context 里"。

一个有 30 个 skill 的 agent，在没有触发任何 skill 时，这 30 个 skill 只占约 600-1500 tokens（元数据）。触发某个 skill 时，只增加那一个 skill 的全文。

### 3.3 Skill vs System Prompt 的边界

这是一个容易混淆的设计问题。

Convention：**System Prompt = agent 的身份和全局行为规范**（始终有效）；**Skill = 特定类型任务的 SOP**（按需激活）。两者都通过 system prompt 传达给 LLM，但激活时机不同。

一个简单的判断标准：

> "这段描述，是对所有任务都成立的，还是只在做某类特定任务时成立？"

- "你是一个专注代码的 agent，不做非技术任务" → System Prompt（始终成立）
- "当用户要求生成 PDF 报告时，按以下步骤处理" → Skill（只在触发时成立）

把 SOP 放进 system prompt 是一种常见的设计反模式：system prompt 会越来越长，而其中大部分内容在每次对话里都是无关的。Anthropic Context Engineering 原文称这种情况为 **context pollution**——无关 token 淹没焦点信号。

> 不需要读完 Anthropic 的 *Context Engineering* 论文，只需要知道一个核心结论：context 里的 token 质量比数量更重要，渐进式披露是保持质量的主要手段。

---

## Beat 4 — 脚手架

下面构建最小的 skills loader——只需能解析 Markdown 文件并替换 `$ARGUMENTS`：

```python
# core/skills.py — v0.12 最小骨架
from dataclasses import dataclass
from pathlib import Path
import re, yaml

@dataclass(frozen=True)
class Skill:
    name: str          # slash 命令名，如 "weather" → /weather
    description: str   # 元数据层：在 context 里的"目录条目"
    content: str       # SOP 正文，仅触发时注入 system prompt

    def expand(self, arguments: str) -> str:
        """$ARGUMENTS 替换 → 注入 system prompt 的最终文本"""
        return self.content.replace("$ARGUMENTS", arguments)
```

运行后，`skill.expand("上海")` 应该把正文里所有 `$ARGUMENTS` 替换为 `上海`，然后这段文本会追加到 system prompt 里。

目前骨架还不能解析文件。接下来我们逐步加上解析能力。

---

## Beat 5 — 渐进组装

| 扩展点 | 为何需要 | 如何加 |
|--------|---------|--------|
| frontmatter 解析 | Skill 的元数据（name/description）存在 YAML frontmatter 里 | `re` 提取 `---` 块 + `yaml.safe_load` |
| 目录扫描 | 实际使用中，skills 是一个目录，不是单个文件 | `Path.rglob("*.md")` 递归扫描 |
| slash 命令解析 | 用户输入 `/weather 上海`，需要提取命令名和参数 | `str.split(maxsplit=1)` |
| 列表展示 | 用户输入 `/skills`，需要知道有哪些可用 | 输出所有 skill 的 name + description |

**扩展 1：解析 frontmatter**

```python
_FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)

def _parse_skill_file(path: Path) -> Skill | None:
    text = path.read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    if not m:
        return None   # 没有 frontmatter，跳过

    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).strip()

    # 文件名兜底：没写 name 就用文件名
    name = fm.get("name") or path.stem.replace(" ", "-").lower()
    return Skill(
        name=name,
        description=fm.get("description", ""),
        content=body,
    )
```

测试：`_parse_skill_file(Path("skills/weather.md"))` 应返回 `Skill(name='weather', description='查询城市天气...', content='...')`。

**扩展 2：目录扫描**

```python
def load_skills_dir(skills_dir: str | Path) -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    base = Path(skills_dir)
    if not base.is_dir():
        return skills
    for md_file in sorted(base.rglob("*.md")):
        skill = _parse_skill_file(md_file)
        if skill:
            skills[skill.name] = skill   # 同名后者覆盖（项目级优先全局级）
    return skills
```

打印中间结果：

```python
skills = load_skills_dir("skills/")
print(f"已加载 {len(skills)} 个 skill: {list(skills.keys())}")
# → 已加载 2 个 skill: ['pdf-report', 'weather']
```

**扩展 3：slash 命令解析**

```python
def parse_slash_command(text: str) -> tuple[str, str] | None:
    s = text.strip()
    if not s.startswith("/"):
        return None
    parts = s[1:].split(maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else "")

# 测试：
assert parse_slash_command("/weather 上海") == ("weather", "上海")
assert parse_slash_command("/pdf-report") == ("pdf-report", "")
assert parse_slash_command("普通对话") is None
```

**扩展 4：接入 agent loop**

现在把这三块接入 `agent.py`。关键改动只有三处：

```python
# agent.py 改动片段（完整文件见 code/lena-v0.12/core/agent.py）
def chat(self, user_input: str) -> str:
    # 1. 检查是否 slash 命令
    cmd = parse_slash_command(user_input)
    if cmd:
        name, args = cmd
        if name == "skills":          # /skills → 列出所有可用 skill
            return self._list_skills()
        skill = self.skills.get(name)
        if skill:
            # 2. 把 Skill 正文注入 system prompt（临时覆盖）
            injected_system = self.system_prompt + "\n\n" + skill.expand(args)
            return self._call_llm(user_input, system_override=injected_system)
        return f"未知命令: /{name}。输入 /skills 查看可用技能。"

    # 3. 普通对话，走正常流程
    return self._call_llm(user_input)
```

打印中间结果：

```
[DEBUG] 触发 Skill: weather | 参数: 上海
[DEBUG] 注入 system prompt 追加 247 tokens
```

---

## Beat 6 — 运行验证

下面运行完整的 Lena v0.12，看看实际效果：

```bash
cd book/chapters/ch12-skills/code/lena-v0.12
pip install -r requirements.txt
python main.py
```

预期输出（前几轮对话）：

```
Lena v0.12 — Skills 版本
输入 /skills 查看可用技能，输入 /quit 退出

你: /skills
Lena: 当前已加载 2 个 Skill:
  /weather <城市名>   — 查询城市天气并生成易读简报
  /pdf-report <主题> — 生成结构化 PDF 报告（含数据提取和排版规则）

你: /weather 上海
[DEBUG] 触发 Skill: weather | 参数: 上海
Lena: 🌤 上海天气（2026-05-05 14:00）
温度：22°C（体感 20°C）
天气：多云
...（完整简报）

你: 今天适合户外运动吗？
Lena: 根据刚才查询的上海天气，22°C 多云，非常适合户外运动...
（Lena 记住了上下文，无需重新触发 skill）
```

整个流程运行耗时约 2-4 秒（取决于 API 响应速度）。

**常见失败诊断**：

- `ModuleNotFoundError: yaml`：执行 `pip install pyyaml`
- `/weather` 触发后 LLM 不按 SOP 格式输出：检查 `skill.expand()` 是否正确替换了 `$ARGUMENTS`，可加 `print(injected_system[-300:])` 看注入内容
- `未知命令: /weather`：说明 `skills/weather.md` 的 frontmatter 里 `name` 字段缺失或拼写有误

现在 Lena 会"做事"了，不只是"能做事"。下一章，我们给她加上第一道安全门——当工具拥有真实权力时，如何防止 prompt injection 把这种权力用在错误的地方。

---

## Beat 7 — Design Note

> **Why Not Just Put Everything in the System Prompt?**

明显的替代方案：把所有 SOP 全部写进 system prompt，不需要 skill 触发机制。这是很多早期 agent 的做法，也是大量"我的 system prompt 已经 8000 tokens"问题的根源。

全量 system prompt 方案的 tradeoffs：

- **绿灯**: 实现简单，零架构复杂度
- **红灯**: context 里充满当前任务不需要的指令，降低信号密度（Anthropic Context Engineering 原文："every irrelevant token competes with relevant ones for the model's attention"）
- **红灯**: system prompt 越来越长，维护成本按 O(n) 增长，最终变成任何人都看不懂的"魔法文件"
- **红灯**: 无法实现渐进式加载——context 窗口有限，加不了第 31 个 SOP

当前选择（Skills 目录 + 按需注入）的理由：Anthropic 在 2025-10-16 的文章里把 Skills 设计为"信号密度最大化"的方案，而 Simon Willison 评价这篇文章 "a bigger deal than MCP"，因为知识复用比工具连接标准化更难解决。

如果你在构建一个只有 3-4 个固定 SOP 的专用 agent，全量 system prompt 完全够用——规则适用于有 10+ 可复用 SOP 的通用 agent。

---

## Anthropic 关于 Skills 可组合架构的阐述

Anthropic 在 *Equipping Agents for the Real World with Agent Skills*（2025-10-16，https://www.anthropic.com/research/building-effective-agents）中从架构层面定义了 Skills 的核心属性：**可组合性（composability）**。

> "Skills can work together on complex tasks and invoke other skills as needed. A compliance skill might call a document analysis skill, which in turn uses a specialized extraction skill."（来源：Anthropic, *Equipping Agents for the Real World with Agent Skills*, 2025-10-16）

这个描述揭示了 Skills 的一个不那么显眼但极为重要的特性：**Skill 可以调用其他 Skill**。一个 `compliance-check` Skill 的内部实现可以引用 `document-analysis` Skill，后者再引用 `entity-extraction` Skill——形成一个能力金字塔，每一层都是独立的可复用单元。

这种层级组合让你不用写单体实现就能构建复杂能力。对比两种实现方式：

- **单体方案**：把"合规检查"的所有逻辑（文档解析 + 实体提取 + 规则验证）写进一个 5000 行的函数。任何子能力的改进需要修改整体，测试难度 O(n²)。
- **可组合方案**：每层 Skill 各 200 行，独立测试，独立复用。改进提取层，检查层自动受益。

这种设计可以理解为"能力金字塔"（capability pyramid）。本章实现的三层披露机制（元数据 → 完整 SOP → 子文件）正是这个金字塔在单个 Skill 内部的体现；而 Skill 之间的互相调用，则是金字塔在跨 Skill 层面的扩展。

## Anthropic Skills 设计哲学：为什么 2025 年这个概念才成熟

在 2025 年之前，业界普遍的做法是把"知识"和"工具"混在一起，用 docstring 和函数注释来描述"怎么做"——这在 LangChain 的早期实现里最为明显。

2025-10-16，Anthropic 工程博客发布了 *Equipping Agents for the Real World with Agent Skills*，用一句话定义了 Skills 要解决的问题：

> "Building a skill for an agent is like putting together an onboarding guide for a new hire."

这个类比的关键是：一个新员工不需要在第一天就把所有手册都背下来，而是在需要执行某类任务时去查阅对应的章节。Skills 把这个"按需查阅"的逻辑引入了 agent 架构。

Anthropic 同时给出了 Skill 的质量标准：触发条件的精确性是核心。

> "Pay special attention to the name and description of your skill. Claude will use these when deciding whether to trigger the skill."

这说明 Skill 的 `description` 不只是文档注释，它是 LLM 决策是否激活这个 Skill 的依据。一个模糊的 `description: "处理各种任务"` 会让 LLM 总是触发或从不触发。

OpenAI 也推出了类似功能，在 ChatGPT 和相关 CLI 工具里加入了格式上高度相似的可复用能力单元机制。这不是竞争式跟随，而是同一个工程问题（知识复用和 context 效率）在不同产品里收敛到了相似答案。

---

## CC loadSkillsDir.ts 真实加载机制

CC 的实现（`skills/loadSkillsDir.ts`，887 行）比本章的 Python 骨架复杂很多，但核心逻辑是一致的。几个值得关注的工程细节：

**扫描路径的三层优先级**（`loadSkillsDir.ts: getSkillsPath()`）：

```
<config>/skills/            ← 全局级（userSettings）
.claude/skills/            ← 项目级（projectSettings）
/managed/skills/           ← 组织策略级（policySettings）
```

优先级：项目级 > 全局级 > 组织级。同名 Skill，项目级覆盖全局级。

**token 预估的渐进披露实现**（`loadSkillsDir.ts: estimateSkillFrontmatterTokens()`）：

```typescript
export function estimateSkillFrontmatterTokens(skill: Command): number {
  const frontmatterText = [skill.name, skill.description, skill.whenToUse]
    .filter(Boolean)
    .join(' ')
  return roughTokenCountEstimation(frontmatterText)
}
```

CC 会估算每个 Skill 的元数据 token 数，用于在 context 接近上限时决定是否继续加载更多 Skill 的元数据。完整 SOP 正文（`content`）只在 `getPromptForCommand()` 被调用时才加载。这就是渐进式披露在代码层的实现。

**`$ARGUMENTS` 之外的变量替换**（`loadSkillsDir.ts: createSkillCommand()`）：

CC 还支持两个特殊变量：
- `${CLAUDE_SKILL_DIR}`：被替换为 Skill 自身所在目录的绝对路径，让 Skill 能引用同目录下的脚本或文件
- `${CLAUDE_SESSION_ID}`：当前会话 ID，用于需要持久化状态的 Skill

本章的 Python 骨架只实现了 `$ARGUMENTS`，这已足够演示核心机制。

**安全防线**（`loadSkillsDir.ts` line ~374）：

```typescript
// Security: MCP skills are remote and untrusted — never execute inline
// shell commands (!`…` / ```! … ```) from their markdown body.
if (loadedFrom !== 'mcp') {
  finalContent = await executeShellCommandsInPrompt(...)
}
```

CC 的 Skill 支持在正文里内联 shell 命令（用 `` !`cmd` `` 语法），但来自 MCP 的 Skill 不允许执行这类内联命令——因为 MCP Skill 是远端不可信来源。这是 Ch 13 安全章会详细展开的信任边界概念的第一次亮相。

---

## 产物清单

`code/lena-v0.12/` 目录结构：

```
lena-v0.12/
├── main.py              # 入口，初始化 agent + 启动 REPL
├── requirements.txt     # anthropic, pyyaml
├── core/
│   ├── __init__.py
│   ├── agent.py         # AgentLoop + skill 注入逻辑
│   └── skills.py        # Skill 数据类 + loadSkillsDir + parse_slash_command
└── skills/
    ├── weather.md       # 天气查询 SOP（含 $ARGUMENTS）
    └── pdf-report.md    # PDF 报告生成 SOP（含格式规范）
```

新增能力（相比 v0.11）：
- `load_skills_dir()` 扫描 `skills/` 目录，返回 `{name: Skill}` 映射
- `parse_slash_command()` 解析 `/name args` 格式
- `AgentLoop.chat()` 识别 slash 命令并注入对应 Skill 的 SOP
- `/skills` 命令：列出所有可用 Skill 的名称和一行描述

---

Lena 现在能按需加载 skill 了。但如果某个 skill 的 instructions 里藏着恶意指令呢？第 13 章我们讲输入安全：如何让 Lena 不被 prompt injection 劫持。
