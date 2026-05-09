# Chapter 12: Skills — Reusable Capability Units

> **[Pillars: Tool universality / Specialization]**

```
Ch 1 → Ch 3 → Ch 6 → Ch 8 → Ch 11 → [Ch 12 ← you are here] → Ch 13 → ...
Tools  Stream  Memory  Planning  MCP       Skills              Security Input Layer
```

This chapter starts with Lena v0.11 (capable of connecting external tools via MCP), moves through "what Skills are → loading mechanism → how to write them → why the industry followed suit," and arrives at Lena v0.12 — able to dynamically load `weather.md` and `pdf-report.md` from a `skills/` directory, triggering a complete SOP with a single `/weather Shanghai`.

Along the way we'll hit a real pitfall: **Skills are not more advanced tools — they are something fundamentally different.** Confusing the two leads you to build a system that's both bloated and hard to use.

> **🧠 Intelligence increment (v0.11 → v0.12)**: Lena loads knowledge on demand for the first time — Skills' three-level progressive disclosure mechanism lets her dynamically read multi-step SOPs from the `skills/` directory; `/weather Shanghai` triggers the complete workflow in one shot, without touching core code to reuse a capability. This chapter teaches you how to build composable "knowledge units" into your own agent.

---

## Beat 2 — Motivation: Are Tools Enough?

Let's start with a concrete failure scenario.

Suppose you want Lena to generate PDF reports. You approach it with tools:

```python
# Approach A: give Lena a PDF tool
@tool
def generate_pdf(content: str, template: str) -> str:
    """Generate a PDF report"""
    ...
```

Then you discover the problem. The tool tells Lena "I can generate PDFs" but doesn't tell her:
- Before generating, which key numbers to extract from the data
- Which template to use (depends on report type)
- How to format numbers in tables (thousands separator? how many decimal places?)
- How to paginate if content is too long
- What the user sees if generation fails

So you pile all that logic into the `generate_pdf` docstring:

```python
@tool
def generate_pdf(content: str, template: str) -> str:
    """
    Generate a PDF report.
    Before use, extract key numbers from the content.
    Template selection: use quarterly for quarterly reports, daily for daily reports, default for others.
    Number format: integers over 1000 get thousands separators, amounts keep two decimal places.
    Pagination: max 3 charts per page, auto-paginate at 500+ words of text.
    Error handling: on render failure, tell the user "report generation encountered an issue" without exposing technical details.
    ...(200 lines omitted)
    """
    ...
```

The docstring becomes 200 lines, and 80% of the tokens in the tool registry are descriptions of "how to use it" rather than "what it can do."

Every time the LLM needs to decide "should I call this tool," it has to read through those 200 lines. Worse: **every time you generate a PDF, regardless of template, those 200 lines are consuming your context.**

This is the ceiling of Tools: **tools describe capabilities, not knowledge.**

In real systems, Claude Code's built-in tools have `FileReadTool` schemas of only 150 lines, while experienced CC users keep 30 skill files in `~/.claude/skills/`, each a "how to approach this type of task" SOP. Loaded on demand — only consuming context when in use.

Skills are where those 200 lines belong.

---

## Beat 3 — Theory

### 3.1 The Essential Difference Between Tool and Skill

Convention: **Tool = function** (declares "I can do X"); **Skill = SOP** (describes "the right way to do X-type tasks"). This definition is used consistently from here on.

At first glance a Skill looks like "a richer tool" — but it's actually more like **a chapter in a new employee handbook**. You don't hard-wire the handbook's content into every workflow; instead you let the employee look it up when needed.

| Dimension | Tool | Skill |
|------|------|-------|
| Form | Function (code) | SOP (Markdown) |
| Describes | A capability | How to approach a type of task |
| Execution | LLM calls → runtime executes | Injected into system prompt on demand |
| Context occupancy | Always (occupies on registration) | Only when triggered |
| How to share | Publish a code package | Share a .md file |
| Readability | Unfriendly to humans (schema) | Friendly to humans (natural language) |
| Cost to modify | Change code + deploy | Edit Markdown |

The longer a tool's docstring gets, the closer you are to needing a Skill.

### 3.2 Progressive Disclosure: The Core Design Principle of Skills

Anthropic's *Equipping Agents for the Real World with Agent Skills* (2025-10-16) compares the Skills loading design to a well-organized manual:

> "Like a well-organized manual that starts with a table of contents, then specific chapters, and finally a detailed appendix."

Three layers, with only the first layer ever in context:

```
Level 1 — Metadata (always in system prompt)
  name + description    ← "table of contents"
  ~20-50 tokens/skill

Level 2 — Full SKILL.md content (loaded when user triggers /skill_name)
  Complete SOP body     ← "open that chapter"
  100-500 tokens/skill

Level 3+ — Linked sub-files (referenced within a Skill on demand)
  External docs, example files  ← "see appendix"
  Only loaded when referenced by the Skill
```

This design resolves the core tension with Tools: **knowledge needs to be in context, but context is finite.** Skills' answer is "only the knowledge currently in use needs to be in context."

An agent with 30 skills, when none are triggered, occupies only ~600-1500 tokens (metadata). Triggering a skill adds only that one skill's full text.

### 3.3 The Boundary Between Skill and System Prompt

This is an easy design decision to get confused.

Convention: **System Prompt = the agent's identity and global behavioral guidelines** (always in effect); **Skill = the SOP for a specific type of task** (activated on demand). Both are communicated to the LLM through the system prompt, but they activate at different times.

A simple rule of thumb:

> "Does this description apply to all tasks, or only when doing a specific type of task?"

- "You are a code-focused agent that doesn't handle non-technical tasks" → System Prompt (always true)
- "When the user requests a PDF report, follow these steps" → Skill (only true when triggered)

Putting SOPs in the system prompt is a common design anti-pattern: the system prompt keeps growing, and most of its content is irrelevant on any given conversation. Anthropic's Context Engineering article calls this **context pollution** — irrelevant tokens drown out the signal.

> You don't need to read Anthropic's *Context Engineering* paper in full. You just need to know one core conclusion: token quality in context matters more than quantity, and progressive disclosure is the primary mechanism for maintaining quality.

---

## Beat 4 — Scaffold

Let's build the minimum skills loader — just enough to parse a Markdown file and replace `$ARGUMENTS`:

```python
# core/skills.py — v0.12 minimal skeleton
from dataclasses import dataclass
from pathlib import Path
import re, yaml

@dataclass(frozen=True)
class Skill:
    name: str          # slash command name, e.g. "weather" → /weather
    description: str   # metadata layer: "table of contents entry" in context
    content: str       # SOP body, injected into system prompt only when triggered

    def expand(self, arguments: str) -> str:
        """$ARGUMENTS replacement → final text injected into system prompt"""
        return self.content.replace("$ARGUMENTS", arguments)
```

After running this, `skill.expand("Shanghai")` should replace all `$ARGUMENTS` in the body with `Shanghai`, and that text gets appended to the system prompt.

The skeleton can't parse files yet. We'll add that capability incrementally.

---

## Beat 5 — Incremental Assembly

| Extension point | Why needed | How to add |
|--------|---------|--------|
| frontmatter parsing | Skill metadata (name/description) lives in YAML frontmatter | Extract `---` block with `re` + `yaml.safe_load` |
| Directory scanning | In real use, skills is a directory, not a single file | `Path.rglob("*.md")` recursive scan |
| Slash command parsing | User inputs `/weather Shanghai`, need to extract command name and args | `str.split(maxsplit=1)` |
| List display | User inputs `/skills`, need to know what's available | Print all skills' name + description |

**Extension 1: Parse frontmatter**

```python
_FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)

def _parse_skill_file(path: Path) -> Skill | None:
    text = path.read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    if not m:
        return None   # no frontmatter, skip

    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).strip()

    # Filename fallback: use filename if name not provided
    name = fm.get("name") or path.stem.replace(" ", "-").lower()
    return Skill(
        name=name,
        description=fm.get("description", ""),
        content=body,
    )
```

Test: `_parse_skill_file(Path("skills/weather.md"))` should return `Skill(name='weather', description='Query city weather...', content='...')`.

**Extension 2: Directory scanning**

```python
def load_skills_dir(skills_dir: str | Path) -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    base = Path(skills_dir)
    if not base.is_dir():
        return skills
    for md_file in sorted(base.rglob("*.md")):
        skill = _parse_skill_file(md_file)
        if skill:
            skills[skill.name] = skill   # same name: later overwrites earlier (project-level overrides global)
    return skills
```

Print the intermediate result:

```python
skills = load_skills_dir("skills/")
print(f"Loaded {len(skills)} skills: {list(skills.keys())}")
# → Loaded 2 skills: ['pdf-report', 'weather']
```

**Extension 3: Slash command parsing**

```python
def parse_slash_command(text: str) -> tuple[str, str] | None:
    s = text.strip()
    if not s.startswith("/"):
        return None
    parts = s[1:].split(maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else "")

# Tests:
assert parse_slash_command("/weather Shanghai") == ("weather", "Shanghai")
assert parse_slash_command("/pdf-report") == ("pdf-report", "")
assert parse_slash_command("regular conversation") is None
```

**Extension 4: Wire into the agent loop**

Now wire these three pieces into `agent.py`. Only three changes needed:

```python
# agent.py change excerpt (full file in code/lena-v0.12/core/agent.py)
def chat(self, user_input: str) -> str:
    # 1. Check if slash command
    cmd = parse_slash_command(user_input)
    if cmd:
        name, args = cmd
        if name == "skills":          # /skills → list all available skills
            return self._list_skills()
        skill = self.skills.get(name)
        if skill:
            # 2. Inject Skill body into system prompt (temporary override)
            injected_system = self.system_prompt + "\n\n" + skill.expand(args)
            return self._call_llm(user_input, system_override=injected_system)
        return f"Unknown command: /{name}. Type /skills to see available skills."

    # 3. Normal conversation, follow standard flow
    return self._call_llm(user_input)
```

Print the intermediate result:

```
[DEBUG] Triggered Skill: weather | Args: Shanghai
[DEBUG] Injected system prompt append: 247 tokens
```

---

## Beat 6 — Run and Verify

Let's run the complete Lena v0.12 and see what happens:

```bash
cd book/chapters/ch12-skills/code/lena-v0.12
pip install -r requirements.txt
python main.py
```

Expected output (first few turns):

```
Lena v0.12 — Skills Edition
Type /skills to see available skills, /quit to exit

You: /skills
Lena: Currently loaded 2 Skills:
  /weather <city>      — Query city weather and generate a readable briefing
  /pdf-report <topic>  — Generate a structured PDF report (with data extraction and layout rules)

You: /weather Shanghai
[DEBUG] Triggered Skill: weather | Args: Shanghai
Lena: Partly Cloudy Shanghai (2026-05-05 14:00)
Temperature: 22°C (feels like 20°C)
Weather: Partly cloudy
...(full briefing)

You: Is today good for outdoor exercise?
Lena: Based on the Shanghai weather we just looked up, 22°C and partly cloudy is perfect for outdoor exercise...
(Lena remembers context, no need to re-trigger the skill)
```

The entire flow takes approximately 2-4 seconds (depending on API response time).

**Common failure diagnostics:**

- `ModuleNotFoundError: yaml`: run `pip install pyyaml`
- LLM doesn't follow SOP format after `/weather` triggers: check whether `skill.expand()` correctly replaced `$ARGUMENTS`; add `print(injected_system[-300:])` to see what was injected
- `Unknown command: /weather`: the `name` field in `skills/weather.md`'s frontmatter is missing or misspelled

Lena now knows how to "do things," not just "be able to do things." The next chapter gives her the first security gate — when tools have real power, how do we prevent prompt injection from turning that power against us.

---

## Beat 7 — Design Note

> **Why Not Just Put Everything in the System Prompt?**

The obvious alternative: write all SOPs directly into the system prompt, no skill triggering mechanism needed. This is what many early agents did, and it's the root cause of countless "my system prompt is already 8,000 tokens" complaints.

Tradeoffs of the all-in-system-prompt approach:

- **Green light**: simple to implement, zero architectural complexity
- **Red light**: context full of instructions irrelevant to the current task, reducing signal density (Anthropic Context Engineering: "every irrelevant token competes with relevant ones for the model's attention")
- **Red light**: system prompt keeps growing, maintenance cost scales O(n), eventually becomes a "magic file" no one understands
- **Red light**: can't do progressive loading — context window is finite, can't fit a 31st SOP

Rationale for the current choice (Skills directory + on-demand injection): Anthropic's 2025-10-16 article frames Skills as a "signal density maximization" solution, and Simon Willison called the article "a bigger deal than MCP" because knowledge reuse is a harder problem than tool connection standardization.

If you're building a specialized agent with only 3-4 fixed SOPs, all-in-system-prompt is perfectly fine — the rule applies to general-purpose agents with 10+ reusable SOPs.

---

## Anthropic Whitepaper: Skills as Composable Architecture

Anthropic's architecture whitepaper defines the core attribute of Skills at the architectural level: **composability**.

> "Skills can work together on complex tasks and invoke other skills as needed. A compliance skill might call a document analysis skill, which in turn uses a specialized extraction skill." (Source: Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*, 2025, p.11)

This description reveals a not-so-obvious but critically important property of Skills: **Skills can invoke other Skills.** A `compliance-check` Skill's implementation can reference a `document-analysis` Skill, which in turn references an `entity-extraction` Skill — forming a capability pyramid where each layer is an independent reusable unit.

This hierarchical composition lets you build complex capabilities without writing monolithic implementations. Compare two approaches:

- **Monolithic approach**: write all "compliance check" logic (document parsing + entity extraction + rule validation) into a single 5,000-line function. Improving any sub-capability requires modifying the whole, testing complexity O(n²).
- **Composable approach**: each Skill layer ~200 lines, independently testable, independently reusable. Improve the extraction layer and the check layer benefits automatically.

The whitepaper calls this design a "capability pyramid." The three-level disclosure mechanism in this chapter (metadata → full SOP → sub-files) is that pyramid inside a single Skill; Skills invoking each other is the cross-Skill extension of the pyramid.

## The Anthropic Skills Design Philosophy: Why This Concept Matured in 2025

Before 2025, the industry's common practice was to mix "knowledge" and "tools" together, using docstrings and function comments to describe "how to do it" — most prominently in LangChain's early implementations.

On 2025-10-16, Anthropic's engineering blog published *Equipping Agents for the Real World with Agent Skills*, defining the problem Skills solve in one sentence:

> "Building a skill for an agent is like putting together an onboarding guide for a new hire."

The key to this analogy: a new employee doesn't need to memorize every handbook section on day one; they consult the relevant chapter when they need to perform a specific type of task. Skills bring that "look it up as needed" logic into agent architecture.

Anthropic also gave the quality standard for a Skill: trigger condition precision is the core.

> "Pay special attention to the name and description of your skill. Claude will use these when deciding whether to trigger the skill."

This means a Skill's `description` is not just documentation — it's the LLM's basis for deciding whether to activate that Skill. A vague `description: "handles various tasks"` will cause the LLM to always trigger or never trigger.

In December 2025, OpenAI added a format that's nearly identical to Skills in ChatGPT and Codex CLI. This isn't competitive mimicry — it's the same engineering problem (knowledge reuse and context efficiency) converging to similar answers across different products.

---

## CC's loadSkillsDir.ts Real Loading Mechanism

CC's implementation (`skills/loadSkillsDir.ts`, 887 lines) is much more complex than this chapter's Python skeleton, but the core logic is consistent. Several engineering details worth noting:

**Three-level priority for scan paths** (`loadSkillsDir.ts: getSkillsPath()`):

```
~/.claude/skills/          ← global level (userSettings)
.claude/skills/            ← project level (projectSettings)
/managed/.claude/skills/   ← organization policy level (policySettings)
```

Priority: project level > global level > organization level. Same-named Skill: project level overrides global.

**Progressive disclosure implementation for token estimation** (`loadSkillsDir.ts: estimateSkillFrontmatterTokens()`):

```typescript
export function estimateSkillFrontmatterTokens(skill: Command): number {
  const frontmatterText = [skill.name, skill.description, skill.whenToUse]
    .filter(Boolean)
    .join(' ')
  return roughTokenCountEstimation(frontmatterText)
}
```

CC estimates the metadata token count for each Skill, using it to decide whether to continue loading more Skills' metadata as context approaches its limit. The full SOP body (`content`) is only loaded when `getPromptForCommand()` is called. This is progressive disclosure implemented at the code level.

**Variable substitution beyond `$ARGUMENTS`** (`loadSkillsDir.ts: createSkillCommand()`):

CC also supports two special variables:
- `${CLAUDE_SKILL_DIR}`: replaced with the absolute path of the Skill's own directory, letting the Skill reference scripts or files in the same directory
- `${CLAUDE_SESSION_ID}`: current session ID, for Skills that need to persist state

This chapter's Python skeleton only implements `$ARGUMENTS`, which is sufficient to demonstrate the core mechanism.

**Security fence** (`loadSkillsDir.ts` line ~374):

```typescript
// Security: MCP skills are remote and untrusted — never execute inline
// shell commands (!`…` / ```! … ```) from their markdown body.
if (loadedFrom !== 'mcp') {
  finalContent = await executeShellCommandsInPrompt(...)
}
```

CC Skills support inline shell commands in the body (using the `` !`cmd` `` syntax), but Skills from MCP are not allowed to execute such inline commands — because MCP Skills come from a remote, untrusted source. This is the first appearance of the trust boundary concept that Chapter 13's security chapter will expand on in detail.

---

## Artifact Checklist

`code/lena-v0.12/` directory structure:

```
lena-v0.12/
├── main.py              # entry point, initialize agent + start REPL
├── requirements.txt     # anthropic, pyyaml
├── core/
│   ├── __init__.py
│   ├── agent.py         # AgentLoop + skill injection logic
│   └── skills.py        # Skill dataclass + loadSkillsDir + parse_slash_command
└── skills/
    ├── weather.md       # weather query SOP (with $ARGUMENTS)
    └── pdf-report.md    # PDF report generation SOP (with formatting rules)
```

New capabilities (compared to v0.11):
- `load_skills_dir()` scans the `skills/` directory, returns `{name: Skill}` mapping
- `parse_slash_command()` parses `/name args` format
- `AgentLoop.chat()` recognizes slash commands and injects the corresponding Skill's SOP
- `/skills` command: list all available Skills' names and one-line descriptions

---

Lena can now load skills on demand. But what if a skill's instructions contain malicious directives? Chapter 13 covers input security: how to keep Lena from being hijacked by prompt injection.
