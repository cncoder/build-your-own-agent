# Chapter 6 — The Tool System: Every Capability Is a Tool

> **[Pillar: Tool Universality]**
> Lena jumps from `v0.3` (one hardcoded tool) to `v0.6` (four real tools, zero changes to the core loop).

---

## Beat 1 — Roadmap

```
Ch1       Ch2       Ch3       Ch4       Ch5       [Ch6 ← you are here]  Ch7
API call → ReAct → Lena born → LLM internals → Tech selection → Tool system → Streaming
                   v0.3                                           v0.6
```

Ch 3 ended with Lena knowing exactly one trick: `get_time`. That tool is hardcoded — its schema dict lives in `lena.py`, its dispatch branch lives in `lena.py`, and anyone who wants to add a second tool has to open `lena.py` and hope they don't break anything.

This chapter starts from that fragility. We expose the two-file tax problem (Beat 2), understand what a registry actually needs to do and why Pydantic is the right choice for automatically generating JSON Schema from Python types (Beat 3), build the minimal skeleton (Beat 4), progressively assemble four tools (Beat 5), then run Lena v0.6 end-to-end in the terminal (Beat 6).

Along the way we'll hit a non-obvious trap at the code level: tool return values exceeding the LLM's context budget. We'll see why Claude Code uses a `maxResultSizeChars` mechanism (Source: `Tool.ts:466`, `toolResultStorage.ts:30`), and why `FileReadTool` is the only tool in the entire system with that limit set to `Infinity` — preventing a self-referential loop that would deadlock the agent.

By the end of this chapter, Lena has four real tools. Adding a fifth requires zero changes to `lena.py`.

> **🧠 Intelligence increment (v0.5 → v0.6)**: Lena gains its first complete tool system — decorator registration + Pydantic schema auto-generation + unified executor. Adding a new tool requires writing one function; zero changes to the core loop. This chapter teaches you how to put "every capability = a tool," the first pillar of a general agent, into your own agent.

![Tool system architecture](diagrams/tool-system.svg)

---

## Beat 2 — Motivation: The Two-File Tax

Before proposing a solution, verify the problem with actual code.

This is the complete tool wiring in Lena v0.3:

```python
# wrong approach — lena_v03/lena.py (simplified, real v0.3 structure)
TOOLS = [
    {
        "name": "get_time",
        "description": "Return current UTC time",
        "input_schema": {"type": "object", "properties": {}}
    }
]

def run_tool(name: str, args: dict) -> str:
    if name == "get_time":           # ← hardcoded dispatch
        from datetime import datetime
        return datetime.utcnow().isoformat()
    raise ValueError(f"Unknown tool: {name}")
```

Now add a `web_search`. Minimum changes required:

1. **Edit `TOOLS`** — append a new dict around line 12.
2. **Edit `run_tool`** — add an `elif name == "web_search":` branch around line 20.
3. **Edit imports** — add the implementation import around line 1.

Three independent edits, all in the same file that contains the agent loop. After ten tools, `run_tool` looks like this:

```python
# wrong approach — naive dispatch after scaling to 10 tools
def run_tool(name: str, args: dict) -> str:
    if name == "get_time":
        ...
    elif name == "web_search":
        ...
    elif name == "read_file":
        ...
    elif name == "write_file":
        ...
    elif name == "shell":
        ...
    elif name == "send_email":
        ...
    elif name == "list_dir":
        ...
    elif name == "grep_files":
        ...
    elif name == "create_event":
        ...
    elif name == "delete_file":
        ...
    raise ValueError(f"Unknown tool: {name}")
```

Every merge conflict on the team happens in this function. A new engineer adds `delete_file` at line 60, accidentally introduces an off-by-one error in the `read_file` branch at line 40. Tests all pass, because tests don't cover interaction paths.

The deeper problem: **the agent loop should not know which tools exist**. It should ask "what tools are registered?" at runtime and let the registry answer. Claude Code's production implementation registers 40+ built-in tools, plus the open-ended MCP protocol that can add more at runtime — none of that is possible if the loop hardcodes tool names.

We want to reduce this number to zero: **lines in `lena.py` that must change when a new tool is added**. The target is zero. The registry achieves this by having the loop query the registry at runtime.

---

## Beat 3 — Theory Foundation

### 3.1 Pydantic as a Schema Compiler (no code in this section)

The Anthropic API requires each tool to be described in JSON Schema format — a JSON object specifying parameter names, types, descriptions, and which parameters are required. The model reads this schema so it knows what arguments to produce when calling the tool.

Writing JSON Schema by hand is both tedious and error-prone:

```json
{
  "type": "object",
  "properties": {
    "path": {"type": "string", "description": "File path"},
    "offset": {"type": "integer", "description": "Start line"},
    "limit": {"type": "integer", "description": "Max lines"}
  },
  "required": ["path"]
}
```

Fine with one tool. After ten tools, the problem is schema drift: the JSON Schema dict and the Python handler function are two separate artifacts. Rename a parameter in the function, forget to update the dict, the model sends the old parameter name, the function expects the new one — a silent `TypeError` at runtime.

**Pydantic** solves this by automatically converting Python class annotations into JSON Schema. Declare a class:

```python
class ReadFileInput(BaseModel):
    path: str = Field(description="File path")
    offset: int = Field(default=0, description="Start line (0-indexed)")
    limit: int = Field(default=200, description="Maximum lines to return")
```

Call `ReadFileInput.model_json_schema()` and you get a correct JSON Schema without writing a single line of JSON. The schema and the handler share one source of truth: the Pydantic class. Rename `path` to `file_path`, and the schema auto-updates on the next import.

**Convention: `schema generation`** = converting a Pydantic model class into a JSON Schema dict (done once at startup, `model_json_schema()`); **`schema validation`** = checking whether a specific argument dict from the LLM satisfies the schema (done on every tool call, `model.model_validate(args)`). These two operations happen at different points in the lifecycle and serve different purposes.

This is the Python equivalent of what Claude Code does in TypeScript with Zod. Source shows `readonly inputSchema: Input` (Source: `Tool.ts:396`). Same principle: declare once, derive everywhere.

### 3.2 The Three-Flag Safety Contract (no code in this section)

Every tool must declare three properties. These aren't style suggestions — they determine how the agent loop schedules tool calls, and whether user confirmation is required before running a tool.

**Convention: `is_read_only`** = the tool only observes state, never changes it; **`is_destructive`** = the tool performs irreversible operations (delete, overwrite, send email, charge money); **`is_concurrency_safe`** = the tool can safely run in parallel with other tool calls in the same turn.

Why exactly these three? Each maps to a concrete scheduler decision:

**`is_concurrency_safe`** determines whether the loop can fire this tool before the previous one finishes. Claude Code's `StreamingToolExecutor` uses exactly this signal: as the API response streams in, each `tool_use` block triggers `addTool(block)`. If that block's tool has `isConcurrencySafe = true`, execution starts immediately — even before the model has finished generating the response (Source: `StreamingToolExecutor.ts:40`). That's why `web_search` can overlap with `read_file`: both are read-only and safe to parallelize. `write_file` cannot: two concurrent writes to the same path would interleave, corrupting the file.

**`is_read_only`** enters the permissions layer. In Claude Code's `plan` mode — where the agent can read everything but must ask before writing — the loop automatically approves tools declaring `isReadOnly = true` without prompting the user. The permission decision tree evaluates `isReadOnly` before checking mode-specific rules (Source: `Tool.ts:402-404`).

**`is_destructive`** is a hard override. The source comment is clear: *"Defaults to false. Only set when the tool performs irreversible operations (delete, overwrite, send)"* (Source: `Tool.ts:405-406`). Destructive tools always trigger a confirmation dialog, regardless of permission mode. If `delete_file` is destructive, the loop forces a confirmation step even in `bypassPermissions` mode.

The three flags form a decision matrix:

| Scenario | `is_read_only` | `is_destructive` | `is_concurrency_safe` |
|----------|:-:|:-:|:-:|
| `read_file` | ✓ | — | ✓ |
| `web_search` | ✓ | — | ✓ |
| `write_file` | — | ✓ | — |
| `shell` | — | ✓ | — |
| `list_dir` | ✓ | — | ✓ |
| `send_email` | — | ✓ | — |

A tool can be neither read-only nor destructive — `create_file` creates a new file but doesn't overwrite or delete anything, so it's not destructive; but it does modify state, so it's not read-only either. The three flags are independent booleans, not a single classification.

### 3.3 The Large-Result Problem (no code in this section)

When a tool returns a large result — say, reading a 500 KB source file — that entire text lands in the conversation history. Every subsequent API call carries those 500 KB of tokens. After a few turns, the context window fills and the agent crashes with a `prompt_too_long` error.

Production-grade agents handle this with a **result budget**: if a tool result exceeds a character threshold, persist it to disk and give the LLM a compact reference instead of the full text. Claude Code calls this threshold `maxResultSizeChars` (Source: `Tool.ts:466`): when a tool result exceeds it, `applyToolResultBudget()` writes the content to a temp file and replaces the conversation message with `<persisted-output path="/tmp/lena-result-abc123.txt"/>` (Source: `toolResultStorage.ts:30`). The model receives the path, not the content.

There is one conspicuous exception: `FileReadTool.maxResultSizeChars = Infinity`. The source comment explains why:

> *"Set to Infinity for tools that cannot have their output persisted (e.g. Read, because persisting would create a Read→file→Read loop cycle, and the tool already self-limits its size through its own limit parameter)."*

Here's what happens if `FileReadTool` had a finite `maxResultSizeChars`:

1. Agent calls `read_file("large_codebase.py")` → returns 600 KB
2. 600 KB > budget → system persists content to `/tmp/result-001.txt`
3. Model receives `<persisted-output path="/tmp/result-001.txt"/>`
4. Model calls `read_file("/tmp/result-001.txt")` to read the persisted content
5. That file contains 600 KB → budget exceeded again → persisted to `/tmp/result-002.txt`
6. Model calls `read_file("/tmp/result-002.txt")` → infinite loop

Setting `maxResultSizeChars = Infinity` breaks this loop by contract: `FileReadTool` results are never externalized. Instead, the tool's own `limit` parameter (default: 200 lines) keeps every result small. The tool is self-limiting and doesn't need external budget management.

In our Lena implementation, `max_result_chars=None` in `ToolMeta` means `Infinity`. The registry only applies truncation when the field is a finite integer.

---

## Beat 4 — Skeleton: Minimal ToolRegistry

Let's implement the smallest working registry — one that can register tools and export schemas — before adding any real tools. This is the skeleton we'll keep building on in Beat 5.

```python
# lena-v0.6/registry.py  (~50 lines, skeleton only)
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel


@dataclass
class ToolMeta:
    """Everything the agent loop needs to know about one tool."""
    name: str
    description: str
    input_model: Type[BaseModel]    # Pydantic class — JSON Schema is derived from this
    handler: Callable               # async def handler(**kwargs) -> str

    # Three-flag safety contract (Source: CC Tool.ts:402-406)
    is_read_only: bool = False
    is_destructive: bool = False
    is_concurrency_safe: bool = False

    # Result budget (Source: CC Tool.ts:466); None = Infinity
    max_result_chars: Optional[int] = 8_000


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolMeta] = {}

    def register(self, meta: ToolMeta) -> None:
        self._tools[meta.name] = meta

    def get(self, name: str) -> Optional[ToolMeta]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Generate Anthropic-format tool schemas. Called by the agent loop."""
        schemas = []
        for meta in self._tools.values():
            schemas.append({
                "name": meta.name,
                "description": meta.description,
                # Pydantic auto-generates JSON Schema — no hand-writing
                "input_schema": meta.input_model.model_json_schema(),
            })
        return schemas
```

Before touching any real tool, verify this skeleton can generate correct schemas:

```python
# verify_registry.py
from pydantic import BaseModel, Field
from registry import ToolRegistry, ToolMeta
import json

class EchoInput(BaseModel):
    message: str = Field(description="Text to echo back")

async def echo_handler(message: str) -> str:
    return f"ECHO: {message}"

registry = ToolRegistry()
registry.register(ToolMeta(
    name="echo",
    description="Echo a message back",
    input_model=EchoInput,
    handler=echo_handler,
    is_read_only=True,
    is_concurrency_safe=True,
))

print(json.dumps(registry.get_schemas(), indent=2))
```

Output:

```json
[
  {
    "name": "echo",
    "description": "Echo a message back",
    "input_schema": {
      "properties": {
        "message": {
          "description": "Text to echo back",
          "title": "Message",
          "type": "string"
        }
      },
      "required": ["message"],
      "title": "EchoInput",
      "type": "object"
    }
  }
]
```

One class, one `register()` call, and `required` is inferred automatically by Pydantic — fields without defaults go into `required`.

Notice what we *didn't* write: no `"required"` list, no `"type": "object"` wrapper, no repeated field names. The Pydantic model is the single source of truth.

Now we're ready to add real tools.

---

## Beat 5 — Progressive Assembly: Four Real Tools

Here are the four tools we'll add, each with concrete motivation:

| Tool | Why Lena needs it | `is_read_only` | `is_destructive` | `is_concurrency_safe` | `max_result_chars` |
|------|------------------|:-:|:-:|:-:|:-:|
| `read_file` | Can't analyze code or data without reading files | ✓ | — | ✓ | None (Infinity) |
| `write_file` | An agent that can only observe is of limited value | — | ✓ | — | 8,000 |
| `shell` | Most real tasks eventually need to run commands | — | ✓ | — | 8,000 |
| `web_search` | Real-time information beyond the model's training cutoff | ✓ | — | ✓ | 8,000 |

**Extension 1: `read_file`**

The `max_result_chars=None` rationale comes directly from §3.3: if we externalize `read_file` results, the agent enters an infinite loop. The tool manages this through its `limit` parameter — it never returns more than `limit` lines, so external budgeting is unnecessary.

```python
# lena-v0.6/tools/read_file.py
import pathlib
from pydantic import BaseModel, Field
from registry import ToolMeta


class ReadFileInput(BaseModel):
    path: str = Field(description="Path to the file to read")
    offset: int = Field(default=0, description="Starting line number (0-indexed)")
    limit: int = Field(default=200, description="Maximum number of lines to return")


async def _read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    p = pathlib.Path(path)
    if not p.exists():
        return f"Error: file not found: {path}"
    if not p.is_file():
        return f"Error: not a file: {path}"
    lines = p.read_text(errors="replace").splitlines()
    total = len(lines)
    chunk = lines[offset : offset + limit]
    result = "\n".join(f"{offset + i + 1}\t{line}" for i, line in enumerate(chunk))
    if offset + limit < total:
        result += f"\n... ({total - offset - limit} more lines, use offset to continue)"
    return result


READ_FILE = ToolMeta(
    name="read_file",
    description="Read lines from a file. Use offset+limit to page through large files.",
    input_model=ReadFileInput,
    handler=_read_file,
    is_read_only=True,
    is_concurrency_safe=True,
    max_result_chars=None,    # Infinity — tool self-limits; see §3.3
)
```

Quick verification:

```python
import asyncio
result = asyncio.run(_read_file("registry.py", offset=0, limit=5))
print(result)
# 1   """
# 2   Lena v0.6 — ToolRegistry
# 3   Pydantic-powered schema generation + three-flag safety contract.
# 4   """
# 5
```

Line numbers let the LLM reference specific lines in subsequent tool calls — a small detail that makes multi-step file editing actionable.

**Extension 2: `write_file`**

`is_destructive=True` because overwriting is irreversible. An agent that writes `""` to `report.md` destroys whatever was in it. The scheduler should pause and confirm before running this in fully autonomous mode.

```python
# lena-v0.6/tools/write_file.py
import pathlib
from pydantic import BaseModel, Field
from registry import ToolMeta


class WriteFileInput(BaseModel):
    path: str = Field(description="Path to write to (parent dirs created if needed)")
    content: str = Field(description="Content to write — overwrites existing file")


async def _write_file(path: str, content: str) -> str:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {len(content)} characters to {path}"


WRITE_FILE = ToolMeta(
    name="write_file",
    description="Create or overwrite a file with the given content.",
    input_model=WriteFileInput,
    handler=_write_file,
    is_read_only=False,
    is_destructive=True,         # overwriting is irreversible
    is_concurrency_safe=False,   # two concurrent writes to the same path corrupt the file
)
```

**Extension 3: `shell`**

`shell` is the most powerful and most dangerous tool in this set. `is_destructive=True` because it can delete files, make network requests, or modify system state — the agent and the user may have very different understandings of "run a command." `is_concurrency_safe=False` because two shell commands touching shared paths or environment variables can interfere.

The `timeout` parameter is critical: without it, a long-running process (infinite loop, hung network request) blocks the agent loop indefinitely. Default is 30 seconds.

```python
# lena-v0.6/tools/shell.py
import asyncio
from pydantic import BaseModel, Field
from registry import ToolMeta

DEFAULT_TIMEOUT = 30


class ShellInput(BaseModel):
    command: str = Field(description="Shell command to run")
    timeout: int = Field(default=DEFAULT_TIMEOUT, description="Timeout in seconds")


async def _shell(command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace")
        return f"exit_code={proc.returncode}\n{output}"
    except asyncio.TimeoutError:
        return f"Error: command timed out after {timeout} seconds"
    except Exception as e:
        return f"Error: {e}"


SHELL = ToolMeta(
    name="shell",
    description="Run a shell command, return combined stdout+stderr and exit code.",
    input_model=ShellInput,
    handler=_shell,
    is_read_only=False,
    is_destructive=True,         # shell can delete files, modify system state
    is_concurrency_safe=False,
)
```

Verification:

```python
result = asyncio.run(_shell("echo hello && python3 --version"))
print(result)
# exit_code=0
# hello
# Python 3.14.4
```

Note the `exit_code` in the result string. The model needs it to determine whether the command succeeded. An agent that calls `git commit` without knowing the exit code may happily continue when the commit actually failed.

**Extension 4: `web_search`**

`is_concurrency_safe=True` because independent network reads don't conflict. If the model issues three `web_search` calls in one turn — say, it's researching multiple subtopics simultaneously — they can all fire at once with no risk of data corruption. This flag unlocks parallel execution in Ch 7.

```python
# lena-v0.6/tools/web_search.py
import json
import urllib.parse
import urllib.request
from pydantic import BaseModel, Field
from registry import ToolMeta

# DuckDuckGo instant answers API — no API key required
DDG_URL = "https://api.duckduckgo.com/"


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query")


async def _web_search(query: str) -> str:
    params = urllib.parse.urlencode({"q": query, "format": "json", "no_html": "1"})
    url = f"{DDG_URL}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        abstract = data.get("AbstractText", "")
        topics = [r.get("Text", "") for r in data.get("RelatedTopics", [])[:5]]
        combined = "\n".join(filter(None, [abstract] + topics))
        return combined or "No results found."
    except Exception as e:
        return f"Search error: {e}"


WEB_SEARCH = ToolMeta(
    name="web_search",
    description="Search the web using DuckDuckGo and return the most relevant results.",
    input_model=WebSearchInput,
    handler=_web_search,
    is_read_only=True,
    is_concurrency_safe=True,
)
```

**Wiring up the registry:**

With all four tools defined, here's how they plug into the registry. The key point: `lena.py` only imports the `ToolMeta` instances — it never directly references `_read_file`, `_write_file`, `_shell`, or `_web_search`. Dispatch is entirely encapsulated inside `registry.execute()`.

```python
# lena-v0.6/lena.py — registry setup section
from registry import ToolRegistry
from tools.read_file import READ_FILE
from tools.write_file import WRITE_FILE
from tools.shell import SHELL
from tools.web_search import WEB_SEARCH

registry = ToolRegistry()
for tool in [READ_FILE, WRITE_FILE, SHELL, WEB_SEARCH]:
    registry.register(tool)

print(f"Registered {len(registry.names())} tools: {registry.names()}")
# Registered 4 tools: ['read_file', 'write_file', 'shell', 'web_search']
```

Quick check on the safety flags:

```python
for meta in [READ_FILE, WRITE_FILE, SHELL, WEB_SEARCH]:
    print(f"{meta.name:15} read_only={meta.is_read_only!s:5} destructive={meta.is_destructive!s:5} "
          f"concurrency_safe={meta.is_concurrency_safe!s:5} max_result_chars={meta.max_result_chars}")
```

Output:

```
read_file       read_only=True  destructive=False concurrency_safe=True  max_result_chars=None
write_file      read_only=False destructive=True  concurrency_safe=False max_result_chars=8000
shell           read_only=False destructive=True  concurrency_safe=False max_result_chars=8000
web_search      read_only=True  destructive=False concurrency_safe=True  max_result_chars=8000
```

The pattern is clear: for read-only tools, `is_read_only` and `is_concurrency_safe` move together. `is_destructive` is exclusive to write-capable tools, forcing sequential execution.

Now add an `execute()` method to `ToolRegistry` that applies the result budget:

```python
# Add to ToolRegistry class in registry.py
async def execute(self, name: str, args: dict[str, Any]) -> str:
    meta = self._tools.get(name)
    if meta is None:
        return f"Error: unknown tool '{name}'"
    try:
        result = str(await meta.handler(**args))
    except TypeError as e:
        return f"Error: wrong arguments for '{name}': {e}"
    except Exception as e:
        return f"Error: tool '{name}' execution failed: {e}"

    # Apply result budget (None = Infinity, never truncate)
    if meta.max_result_chars is not None and len(result) > meta.max_result_chars:
        result = result[: meta.max_result_chars] + "\n...[truncated]"

    return result
```

Catching `TypeError` matters. LLMs occasionally send `{"path": 42}` when the schema says `path` is a string. Without this catch, the handler raises a useless `TypeError: expected str, got int`. The caught error message gets fed back to the model as the tool result, giving it a chance to retry with correct arguments.

---

## Beat 6 — Running: Lena v0.6 End-to-End

Let's assemble the complete `lena.py` and run a live demo. Task: read a Python file and describe what a specific class stores.

```python
# lena-v0.6/lena.py  (complete, ~80 lines)
import asyncio
import json
import os
import sys

import anthropic

from registry import ToolRegistry
from tools.read_file import READ_FILE
from tools.write_file import WRITE_FILE
from tools.shell import SHELL
from tools.web_search import WEB_SEARCH


def build_registry() -> ToolRegistry:
    r = ToolRegistry()
    for tool in [READ_FILE, WRITE_FILE, SHELL, WEB_SEARCH]:
        r.register(tool)
    return r


async def run(task: str, max_steps: int = 10) -> None:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    registry = build_registry()

    print(f"Tools: {registry.names()}")
    print(f"Task: {task}\n{'─' * 60}")

    messages: list[dict] = [{"role": "user", "content": task}]

    for step in range(1, max_steps + 1):
        print(f"\n[Step {step}] Calling model...")
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            tools=registry.get_schemas(),
            messages=messages,
        )

        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "end_turn":
            for block in resp.content:
                if hasattr(block, "text"):
                    print(f"\n[Lena] {block.text}")
            break

        if resp.stop_reason != "tool_use":
            print(f"[Unexpected stop_reason: {resp.stop_reason}]")
            break

        # Execute tool calls; concurrent version in Ch 7
        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            args_str = json.dumps(block.input)
            preview = args_str[:80] + ("..." if len(args_str) > 80 else "")
            print(f"  → {block.name}({preview})")

            result_text = await registry.execute(block.name, block.input)

            result_preview = result_text[:120].replace("\n", " ")
            print(f"  ← {result_preview}{'...' if len(result_text) > 120 else ''}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
            })

        messages.append({"role": "user", "content": tool_results})
    else:
        print(f"\n[Stopped: max_steps={max_steps} reached]")


if __name__ == "__main__":
    task = (sys.argv[1] if len(sys.argv) > 1
            else "Read registry.py and describe what ToolMeta stores.")
    asyncio.run(run(task))
```

Run:

```bash
$ python lena.py
```

Expected output (actual model text will vary; structure won't):

```
Tools: ['read_file', 'write_file', 'shell', 'web_search']
Task:  Read registry.py and describe what ToolMeta stores.
────────────────────────────────────────────────────────────

[Step 1] Calling model...
  → read_file({"path": "registry.py", "offset": 0, "limit": 200})
  ← 1   """  2   Lena v0.6 — ToolRegistry  3   Pydantic-powered schema generation...

[Step 2] Calling model...

[Lena] `ToolMeta` is a dataclass that stores everything needed to describe a single
tool: `name` and `description` (used in the JSON Schema sent to the model),
`input_model` (a Pydantic class from which the schema is auto-generated), and
`handler` (an async function called with keyword arguments when the tool runs).
It also holds three boolean safety flags — `is_read_only`, `is_destructive`,
and `is_concurrency_safe` — that control scheduling and permission decisions,
plus `max_result_chars` for result budgeting (None means no limit).
```

Two steps: one to read the file, one to synthesize the answer. The model doesn't need to know how many tools exist, or which tool "reads files" — it receives the schema list and autonomously chose `read_file`.

**Common failure diagnostics:**

`AuthenticationError: invalid x-api-key` — the `ANTHROPIC_API_KEY` environment variable is not set. `export ANTHROPIC_API_KEY=sk-ant-...` and re-run.

`TypeError: handler() got an unexpected keyword argument` — the model sent an argument name the handler doesn't accept. This usually means the Pydantic model field name and the handler function parameter name don't match. Check that `ReadFileInput.path` corresponds to `_read_file(path: str, ...)`. This is the most common integration error when building tools.

`stop_reason='max_tokens'` instead of `end_turn` — the model's reply was truncated. Increase `max_tokens` in the `messages.create()` call, or shorten the system prompt.

**What adding a fifth tool looks like:**

```python
# tools/list_dir.py
import pathlib
from pydantic import BaseModel, Field
from registry import ToolMeta

class ListDirInput(BaseModel):
    path: str = Field(default=".", description="Directory path to list")

async def _list_dir(path: str = ".") -> str:
    p = pathlib.Path(path)
    if not p.is_dir():
        return f"Error: not a directory: {path}"
    entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
    return "\n".join(
        f"{'[dir]' if e.is_dir() else '[file]'} {e.name}" for e in entries
    )

LIST_DIR = ToolMeta(
    name="list_dir",
    description="List files and directories at the given path.",
    input_model=ListDirInput,
    handler=_list_dir,
    is_read_only=True,
    is_concurrency_safe=True,
)
```

Then in `lena.py`:

```python
from tools.list_dir import LIST_DIR
# ... add LIST_DIR to the registration loop
```

**Zero changes to any existing file.** One new file, two new import lines. This is what "add tools without touching the core loop" means in practice.

---

## Beat 7 — Design Note

> **Why Pydantic Schema Generation Instead of Hand-Written JSON Schema?**

The most obvious alternative is hand-writing JSON Schema dicts — many tutorials do this, and it looks fine for a three-tool demo:

```python
# wrong pattern — common in tutorials, breaks at scale
TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "offset": {"type": "integer", "description": "Start line"},
                "limit": {"type": "integer", "description": "Max lines"},
            },
            "required": ["path"],
        }
    }
]
```

This pattern has three concrete failure modes at scale:

**1. Schema drift.** The JSON Schema dict and the handler function are two separate artifacts. When you rename `path` to `file_path` in the function (to align with a new naming convention), Python provides no mechanism to prevent you from forgetting to update the dict. The model sends `file_path=...` (because the schema says `file_path`); the old handler crashes because it expects `path=...`. With Pydantic, the class is both the schema *and* the validation interface — they can't drift.

**2. No runtime validation.** A hand-written dict doesn't validate arguments the LLM sends. A hallucinating model might send `{"path": 42}` when the schema says `path` is a string; the integer silently flows into a function expecting a string. `pathlib.Path(42)` throws a `TypeError` deep inside the handler, and the stack trace tells you nothing useful beyond which model sent the wrong type. With Pydantic, `model.model_validate(args)` catches type errors before the handler is called and returns a structured error to the model, letting it retry.

**3. Maintenance cost scales linearly with tool count.** Manually maintaining 40 JSON Schema dicts — each with a `required` list, type annotations, `description` strings, and nested `$ref` references for complex types — is a massive error surface. Every new developer who adds a tool has to learn the schema format, not just Python. Pydantic reduces the cognitive load to "know Python type hints." Claude Code has 40+ built-in tools; that scale is only feasible because schema generation is automatic.

**Trade-off:** Pydantic adds a dependency and roughly 20ms of import overhead at cold start. For a CLI agent, this is invisible. For high-request-volume serverless functions, pre-compute `get_schemas()` at module load time and cache the result — the `ToolRegistry` class supports this naturally: call `get_schemas()` once, store the result, reuse it.

**In production systems:** add `model_config = ConfigDict(strict=True)` to each input model. Strict mode rejects coercions like int→string, catching more hallucinated-argument errors before they reach the handler. Claude Code implements the equivalent through Zod's `.strict()` option (Source: `Tool.ts:472`, `readonly strict?: boolean`).

**The recommendation is clear:** use Pydantic. Only hand-write JSON Schema when you don't control the input type definition — for example, wrapping a third-party MCP tool whose schema arrives as a raw JSON blob. In that case, use Claude Code's `inputJSONSchema?` escape hatch (Source: `Tool.ts:397`), which bypasses Zod/Pydantic and passes the raw schema directly to the API.

---

## Challenges

1. **Add `list_dir`** as a fifth tool, following the `list_dir.py` snippet in Beat 6. Register it and verify that Lena can answer "what files are in the current directory?" with zero changes to `lena.py`.

2. **Simulate a large result budget:** modify `web_search` to return a 20,000-character string (simulate with `"X" * 20_000`). Observe `registry.execute()` truncating it to 8,000 characters. Then add a `persist_to_disk` path to `execute()`: instead of truncating, write the full result to `/tmp/lena-result-{name}-{hash[:8]}.txt` and return `<persisted-output path="..."/>`. This is what `toolResultStorage.ts:30` does in Claude Code.

3. **Concurrent execution preview:** in the current `run()` loop, tool calls execute sequentially. Modify the loop to use `asyncio.gather()` for all tool calls where `meta.is_concurrency_safe == True`, while continuing to execute unsafe tools sequentially. Run `lena.py "Search for Python asyncio best practices, and also search for Pydantic v2 features"` and measure wall-clock time with and without concurrency.

---

Lena can now read files, write files, run shell commands, and search the web — all routed through one registry, with the agent loop addressing everything by name at runtime. No `elif` chains, no hardcoded tool list, no two-file tax. But she executes tools one at a time, waiting for each result before asking the model what to do next. In production, the model frequently issues multiple tool calls in a single turn — five `web_search` calls at once, or interleaving `read_file` with `shell` — and waiting for them sequentially makes the agent feel sluggish. The next chapter tackles streaming output and concurrent tool execution: the mechanism for firing a tool the moment its call block arrives in the streaming response, even before the model has finished generating.

---

## References

- `Tool.ts:362–472` — `Tool` interface definition, three safety flags, `maxResultSizeChars`
- `Tool.ts:396` — `readonly inputSchema: Input` (Zod equivalent of Pydantic)
- `Tool.ts:466` — `maxResultSizeChars` field, with comment explaining the Infinity case
- `toolResultStorage.ts:30` — `applyToolResultBudget()`, `<persisted-output>` format
- `StreamingToolExecutor.ts:40` — using `isConcurrencySafe` to fire tools mid-stream
- Pydantic v2 `model_json_schema()` — official docs: https://docs.pydantic.dev/latest/concepts/json_schema/

All source references point to the Claude Code open-source repository `source/src/`. Pydantic version: ≥ 2.0. If using Pydantic v1, replace `model_json_schema()` with `.schema()`.
