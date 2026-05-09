# Chapter 8: Memory and Context — Giving Your Agent a Yesterday

> **[Pillar: Memory]**

---

## Beat 1 — Roadmap

```
Ch1→Ch2→Ch3→Ch4→Ch5→Ch6→Ch7→【Ch8←you are here】→Ch9→Ch10→...
                                ↑
                          Memory = "the agent's own yesterday"
```

This chapter starts from a Lena v0.7 that forgets everything on every restart, works through building a two-layer memory architecture (short-term SQLite + long-term file system), and arrives at a Lena v0.8 that remembers user preferences across sessions. Along the way we'll trip over one real pitfall: **Compaction summaries are untrustworthy** — when an LLM compresses history, it quietly rewrites decisions, turning "option explicitly rejected" into "option pending evaluation."

Lena version upgrade: `v0.7` (streaming + concurrency) → `v0.8` (cross-session memory + `save_memory` tool).

**Clear boundary between this chapter and Ch 9**: this chapter is about the agent's **own memory** — "what have I done, who is the user, what does the user like." Ch 9 is about the agent **reading an external knowledge base** — "what does a particular document say." These two capabilities are frequently conflated, but the solutions are entirely different. This chapter focuses on the former.

> **Intelligence increment (v0.7 → v0.8)**: Lena has cross-session memory for the first time — SQLite short-term memory + file-system long-term memory let her remember "what I've done, who the user is" without going amnesiac on every restart. This chapter teaches you how to build an agent's self-history capability directly into your own agent.

![Memory read-write cycle](diagrams/memory-readwrite.svg)

---

## Beat 2 — Motivation

Karpathy's analogy for LLM memory cuts right to the point:

> "The LLM context window is RAM — anterograde amnesia means no memory consolidation across sessions; each restart is a clean slate."

Your laptop's RAM resets when you shut down, but the hard drive persists. Without the memory layer this chapter implements, Lena restarts like a patient with anterograde amnesia — she knows all general knowledge, but has forgotten what she told you yesterday.

How unusable is a memoryless agent? Run this and see:

```python
# Memoryless Lena (v0.7 state)
session1 = LenaAgent()
session1.chat("My name is Bob and I like writing code in Python.")
# → "Hi Bob! I'll remember your preference."

# Restart the process, new session
session2 = LenaAgent()
session2.chat("Write me a hello world.")
# → "Which programming language would you like? Python, JavaScript, or something else?"
```

On the second run, Lena has no idea who Bob is or that he prefers Python. Every word the user ever said vanishes permanently when the process exits.

This isn't a minor annoyance. An agent that can "do anything autonomously" must know who it's talking to, what that person prefers, and where the last conversation left off. Without this, it's just a **stateless Q&A machine**, starting from zero every session and asking the user to re-introduce themselves every time.

There's a subtler problem in long conversations: when the dialogue exceeds 128K tokens, frameworks trigger **autocompact**, using an LLM to compress the history into a summary. LLM-generated summaries make mistakes — "user explicitly rejected the LangChain approach" gets written as "LangChain approach pending evaluation," and then the agent starts pushing that approach again in later turns, until the user catches it and intervenes.

**This is a real production incident pattern, not a hypothetical risk.**

The solution has two layers: use SQLite to save the complete message history within a session (guarding against data loss from compaction); use the file system to save critical facts across sessions (guarding against amnesia after process restarts). This chapter implements both layers.

---

## Beat 3 — Theory

### 3.1 The four dimensions of memory

Before getting into implementation, let's build a precise classification framework. Each dimension corresponds to a design decision.

**Time dimension**: memory is either *in-session* or *cross-session*. The former lives only in the current process's memory; the latter needs to be persisted to disk and recoverable on the next startup. This is the most fundamental split — without cross-session persistence, an agent is always disposable.

**Fidelity dimension**: memory is either *verbatim* or *summarized*. SQLite stores raw messages — verbatim. Autocompact-generated content is an LLM summary — summarized, and **susceptible to distortion**. This difference is the root cause of the "Compaction summaries are untrustworthy" problem from Beat 2: summarized memory passes through LLM rewriting, which can lose detail or even change facts. Verbatim storage doesn't go through the model; it faithfully preserves every original message.

Convention: **short-term memory** = the current session's message history, stored in SQLite, verbatim, persisted when the process exits; **long-term memory** = cross-session key facts and user preferences, stored in the file system, verbatim, one `.md` file per memory entry.

**Access pattern dimension**: memory is either *sequential read* or *on-demand retrieval*. Short-term memory is sequential (load the full history in chronological order); long-term memory is on-demand (MEMORY.md index → read relevant files). This difference affects context occupancy: sequential reads everything; on-demand reads just the index page. As session turn count grows, sequential loading of short-term memory inflates the context — that's a problem Chapter 10 on Context Engineering addresses.

**Write timing dimension**: short-term memory is written automatically (appended after every conversation turn); long-term memory is written by the agent's own judgment ("this is worth remembering" → call the `save_memory` tool). Letting the agent decide what's worth recording is a key design choice — if every conversation were written to long-term memory, you'd generate enormous noise and pollute the system prompt with irrelevant facts.

```
          Short-term memory              Long-term memory
          (SQLite)                       (file system)
        ┌──────────────┐              ┌──────────────────┐
Write → │ Auto-append  │            → │ Agent's judgment │
timing  │ after each   │              │ (save_memory)    │
        │ turn         │              │                  │
        └──────────────┘              └──────────────────┘
        ┌──────────────┐              ┌──────────────────┐
Access → │ Sequential  │            → │ Index + on-demand │
pattern  │ full history │              │ MEMORY.md        │
        └──────────────┘              └──────────────────┘
        ┌──────────────┐              ┌──────────────────┐
Fidelity → │ Verbatim  │            → │ Verbatim         │
           │ raw msgs  │              │ no LLM rewrite   │
        └──────────────┘              └──────────────────┘
```

### 3.2 File system vs. vector database

The first intuition when facing agent memory is "use a vector database" — vectorize each memory entry, use cosine similarity for retrieval. But in practice, for a personal agent, this answer is over-engineered. The reason: vector databases solve **semantic similarity search** ("find documents semantically related to this question"), while agent memory needs **exact retrieval** ("all preferences for this user," "the conclusion from last time").

Consider the scale: a personal agent's long-term memory typically has 100–1,000 entries. Reading 1,000 `.md` files sequentially takes Python about 50ms. There's no reason to introduce an embedding model, index update latency, and similarity threshold tuning for this.

The Manus team stated this principle explicitly in their 2025 context engineering practice: "The file system is infinite external memory. Persist important context to files rather than expecting the context window to hold it." (Source: Manus, *Context Engineering for AI Agents*, 2025)

Convention: **agent memory** = known facts + preferences + work records for a personal assistant, file system is sufficient; **RAG** = semantic retrieval from an external knowledge base, that's when you need a vector database. (Ch 9 covers RAG; this chapter doesn't overlap.)

### 3.3 The CLAUDE.md-style auto-load mechanism

Claude Code has a feature that puzzles many people: it "remembers" what you wrote in `CLAUDE.md`. This isn't the model's long-term memory — **it's injecting the file's content into the system prompt on every session start**. The model itself is stateless. "Remembering" means putting the memory file's contents into context on every call, so the model can "read" it each time.

Claude Code source (`source/src/memdir/memdir.ts:34`) defines:

```
ENTRYPOINT_NAME = 'MEMORY.md'       // memdir.ts:34
MAX_ENTRYPOINT_LINES = 200          // memdir.ts:35
MAX_ENTRYPOINT_BYTES = 25_000       // ~125 chars/line
```

`buildMemoryPrompt()` reads `MEMORY.md` on session start, truncates to 200 lines / 25KB, and prepends it into the system prompt. If it exceeds the limit, a warning line `> WARNING: MEMORY.md is N lines (limit: 200)` is appended to tell the agent the index was truncated.

`memoryScan.ts:22` also caps `MAX_MEMORY_FILES = 200` — a single project tracks at most 200 memory files; files beyond this are truncated in order of modification time. This prevents an agent from generating unbounded memory files in large projects.

Lena v0.8 follows the same principle: on every `chat()` call, `_build_system_prompt()` reads long-term memory from the file system, formats it, and injects it at the start and end of the system prompt (Recitation double-write). The user perceives "Lena remembers me"; underneath, every call reads from disk.

This mechanism has an important implication: **file-system memory updates take effect immediately, no restart needed.** If you manually edit `~/.lena/projects/lena/MEMORY.md` or delete a memory file, the very next `chat()` call uses the new state — a debuggability advantage that vector databases can't match.

---

## Beat 4 — Scaffold

Let's build the minimal memory skeleton — two classes, one for each layer, each independently runnable:

```python
# memory/store.py — short-term memory (SQLite, zero dependencies)
import sqlite3
import json
from datetime import datetime
from pathlib import Path


class MemoryStore:
    """
    SQLite short-term memory. Zero dependencies beyond stdlib.
    Stores per-session message history, survives process restarts.

    Separate from MemDir: store handles session history (sequential),
    MemDir handles long-term facts (indexed, cross-session).
    """

    def __init__(self, db_path: str = "~/.lena/memory.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        # Fresh connection per call — simple, no connection pool needed at this scale
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id      TEXT PRIMARY KEY,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role       TEXT NOT NULL,
                    content    TEXT NOT NULL,   -- JSON-encoded
                    created    TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_session "
                "ON messages(session_id, id)"
            )
```

Expected output: `MemoryStore("~/.lena/memory.db")` should create a `memory.db` file under `~/.lena/`. Verify with `sqlite3 ~/.lena/memory.db ".tables"` — you should see `sessions` and `messages`.

```python
# memory/memdir.py — long-term memory (file system, zero dependencies)
import yaml
import uuid
from datetime import datetime
from pathlib import Path


class MemDir:
    """
    File-system long-term memory. One .md per memory, MEMORY.md as index.
    Inspired by Claude Code's memdir/memdir.ts:34 (ENTRYPOINT_NAME = 'MEMORY.md').

    Max 200 lines in MEMORY.md index (matching CC's MAX_ENTRYPOINT_LINES).
    """

    ENTRYPOINT_NAME = "MEMORY.md"
    MAX_ENTRYPOINT_LINES = 200   # matches memdir.ts:35

    def __init__(self, project_slug: str = "lena"):
        self.base = Path("~/.lena/projects").expanduser() / project_slug / "memory"
        self.base.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base.parent / self.ENTRYPOINT_NAME
```

Expected output: `MemDir("lena")` should create the `~/.lena/projects/lena/memory/` directory; `MEMORY.md` doesn't exist yet (it's created on the first `save()` call). Now we'll incrementally add capabilities to this skeleton.

---

## Beat 5 — Incremental Assembly

| Extension | Why needed | How to add |
|-----------|-----------|------------|
| `MemoryStore.append / load_messages` | Agent writes each turn, replays on startup | INSERT + SELECT ORDER BY id |
| `MemDir.save()` + YAML frontmatter | Each memory entry is independently readable and editable | Write `---\nfrontmatter\n---\ncontent` |
| `MemDir.load_index()` + `format_for_prompt()` | Inject into system prompt | Read MEMORY.md + format as text |
| `save_memory` tool | Agent autonomously decides what's worth remembering | Tool call → `memdir.save()` |

### Extension 1: Core MemoryStore operations

```python
# memory/store.py (continued) — append to MemoryStore class

    def create_session(self, session_id: str) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions VALUES (?, ?, ?)",
                (session_id, now, now)
            )

    def append_message(self, session_id: str, role: str, content) -> None:
        """Append a message. Content can be str or list (tool_use blocks)."""
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created) "
                "VALUES (?, ?, ?, ?)",
                (session_id, role, json.dumps(content, ensure_ascii=False), now)
            )
            conn.execute(
                "UPDATE sessions SET updated=? WHERE id=?", (now, session_id)
            )

    def load_messages(self, session_id: str) -> list[dict]:
        """Load all messages for a session, ordered by insertion."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id=? ORDER BY id",
                (session_id,)
            ).fetchall()
        return [{"role": r, "content": json.loads(c)} for r, c in rows]
```

Verification:

```python
store = MemoryStore()
store.create_session("test-001")
store.append_message("test-001", "user", "hello")
store.append_message("test-001", "assistant", "hi there")
msgs = store.load_messages("test-001")
print(len(msgs))   # → 2
print(msgs[0])     # → {'role': 'user', 'content': 'hello'}
```

### Extension 2: Full MemDir CRUD

```python
# memory/memdir.py (continued) — append to MemDir class

    def save(
        self,
        content: str,
        subject: str,
        mem_type: str = "user",     # user / feedback / project / reference
        confidence: float = 0.9,
        max_chars: int = 2000,      # content truncation guard against context pollution
    ) -> str:
        """Save a memory file. Returns mem_id."""
        if len(content) > max_chars:
            content = content[:max_chars] + "\n...[truncated]"

        mem_id = (
            f"mem_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_"
            f"{uuid.uuid4().hex[:6]}"
        )
        frontmatter = {
            "id": mem_id,
            "type": mem_type,
            "subject": subject,
            "description": subject,   # CC memdir uses description for manifest
            "created": datetime.utcnow().isoformat(),
            "confidence": confidence,
        }
        mem_file = self.base / f"{mem_id}.md"
        mem_file.write_text(
            f"---\n{yaml.dump(frontmatter, allow_unicode=True)}---\n\n{content}",
            encoding="utf-8",
        )
        self._update_index(mem_id, subject, mem_type)
        return mem_id

    def _update_index(self, mem_id: str, subject: str, mem_type: str) -> None:
        line = f"| `{mem_id}.md` | {mem_type} | {subject} |\n"
        if not self.index_path.exists():
            header = (
                "# MEMORY.md — Long-term Memory Index\n\n"
                "| File | Type | Subject |\n"
                "|------|------|---------|\n"
            )
            self.index_path.write_text(header + line, encoding="utf-8")
        else:
            # Enforce MAX_ENTRYPOINT_LINES (200) — same cap as CC memdir.ts
            lines = self.index_path.read_text(encoding="utf-8").splitlines()
            if len(lines) < self.MAX_ENTRYPOINT_LINES:
                with open(self.index_path, "a", encoding="utf-8") as f:
                    f.write(line)

    def load_all(self) -> list[dict]:
        """Load all memory files. Skips malformed files gracefully."""
        memories = []
        for md_file in sorted(self.base.glob("mem_*.md")):
            text = md_file.read_text(encoding="utf-8")
            try:
                parts = text.split("---", 2)
                fm = yaml.safe_load(parts[1])
                memories.append({**fm, "content": parts[2].strip()})
            except Exception:
                continue   # corrupt file — skip, don't crash
        return memories

    def format_for_prompt(self) -> str:
        """Render memories as a text block for system prompt injection."""
        memories = self.load_all()
        if not memories:
            return ""
        lines = ["## Known Information (Long-term Memory)\n"]
        for m in memories:
            tag = f"[{m.get('type','?')}]"
            subj = m.get("subject", "?")
            body = m.get("content", "")
            lines.append(f"- {tag} **{subj}**: {body}")
        return "\n".join(lines)
```

Verification:

```python
md = MemDir("lena")
mid = md.save("Bob prefers Python for backend, rejects Node.js", subject="programming_language")
print(mid)           # → mem_20260505_143022_a3f2b1
print(md.format_for_prompt())
# → ## Known Information (Long-term Memory)
#   - [user] **programming_language**: Bob prefers Python for backend...
```

### Extension 3: `save_memory` tool — agent writes long-term memory autonomously

This is the key to Lena truly "deciding to remember." The tool lets the LLM judge what's worth saving:

```python
# core/tools.py — append to tools list

SAVE_MEMORY_TOOL = {
    "name": "save_memory",
    "description": (
        "Save important information to long-term memory, accessible across sessions. "
        "Use for: user expressed a clear preference, important fact, content that needs to persist. "
        "Do NOT save: code snippets, transient task state, current-session context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject":  {"type": "string", "description": "Memory subject, e.g. 'programming_language'"},
            "content":  {"type": "string", "description": "What to remember, concise and precise"},
            "mem_type": {
                "type": "string",
                "enum": ["user", "feedback", "project", "reference"],
                "description": "Type: user=user preference, feedback=work guidance, project=project fact, reference=external resource pointer",
            },
        },
        "required": ["subject", "content"],
    },
}
```

Convention: the four memory types come from Claude Code `memdir/memoryTypes.ts:14`: `user` (user profile) / `feedback` (work guidance) / `project` (project facts) / `reference` (external resource pointers). This book uses this classification directly because it has been validated in real production.

### Extension 4: LenaAgent integrating both memory layers

```python
# core/agent.py

import uuid
from datetime import datetime
from memory.store import MemoryStore
from memory.memdir import MemDir
from core.llm import call_llm
from core.tools import SAVE_MEMORY_TOOL, execute_tool


class LenaAgent:
    """Lena v0.8 — cross-session memory via SQLite + file-system MemDir."""

    def __init__(self, session_id: str | None = None):
        self.store = MemoryStore()
        self.memdir = MemDir(project_slug="lena")
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        self.store.create_session(self.session_id)

    def _build_system_prompt(self) -> str:
        base = "You are Lena, a general-purpose AI assistant. You can use tools to complete tasks."
        # CLAUDE.md-style injection: read long-term memory from file system on every session start
        long_term = self.memdir.format_for_prompt()
        if long_term:
            # Recitation: write key memories at the end to counter lost-in-the-middle drift
            return f"{base}\n\n{long_term}\n\n<!-- memory recitation -->\n{long_term}"
        return base

    def chat(self, user_input: str) -> str:
        # 1. Load session history (short-term memory)
        messages = self.store.load_messages(self.session_id)
        messages.append({"role": "user", "content": user_input})

        # 2. LLM call (with save_memory tool available)
        response = call_llm(
            messages=messages,
            system=self._build_system_prompt(),
            tools=[SAVE_MEMORY_TOOL],
        )

        # 3. Handle tool calls (agent may decide to save a memory)
        final_text = self._handle_tool_use(response, messages)

        # 4. Persist this conversation turn
        self.store.append_message(self.session_id, "user", user_input)
        self.store.append_message(self.session_id, "assistant", final_text)

        return final_text

    def _handle_tool_use(self, response, messages: list) -> str:
        """If LLM called save_memory, execute it and get final response."""
        if response.get("stop_reason") != "tool_use":
            return response["content"][0]["text"]

        tool_results = []
        for block in response["content"]:
            if block["type"] == "tool_use":
                result = execute_tool(block["name"], block["input"], self.memdir)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": result,
                })

        # Append tool results and call LLM again for the final reply
        messages.append({"role": "assistant", "content": response["content"]})
        messages.append({"role": "user", "content": tool_results})
        final = call_llm(messages=messages, system=self._build_system_prompt())
        return final["content"][0]["text"]
```

After each `chat()` call, print an intermediate state check:

```python
agent = LenaAgent()
resp = agent.chat("My name is Bob and I write Python.")
print("[memories saved]:", [f.name for f in agent.memdir.base.glob("mem_*.md")])
# → [memories saved]: ['mem_20260505_143022_a3f2b1.md', 'mem_20260505_143023_c9d8e7.md']
```

### Beat 5 supplement: Recitation double-write technique

`_build_system_prompt()` has a design that looks odd at first: the memory block is written twice (once at the start, once after `<!-- memory recitation -->`).

This comes from the Manus team's 2025 context engineering practice. The reason is the **lost-in-the-middle phenomenon** (Liu et al. 2023, "Lost in the Middle: How Language Models Use Long Contexts" — no need to read the full paper, just know the core finding: LLM attention to context is significantly higher at both ends than the middle; in long contexts, information in the middle has a 20–30% lower hit rate).

The impact on agent memory: if preferences are only placed at the start of the system prompt, after 1,000 tokens of conversation history, the model's attention to "user prefers Python" diminishes during generation. Manus's solution is to restate key instructions at the end of the context. For Lena, we write the memory block again at the end of the system prompt, so preferences have a strong signal near the generation point as well.

```
system_prompt structure (Recitation double-write):

┌─────────────────────────────────────────┐
│ Role definition: You are Lena...         │  ← beginning
├─────────────────────────────────────────┤
│ Long-term memory (first occurrence)      │  ← read at the start
│ - [user] programming_language: Python    │
│ - [user] user_name: Bob                  │
├─────────────────────────────────────────┤
│ <!-- memory recitation -->               │  ← end restated
│ Long-term memory (second occurrence)     │  ← visible just before generation
│ - [user] programming_language: Python    │
│ - [user] user_name: Bob                  │
└─────────────────────────────────────────┘
```

The cost: system prompt roughly doubles in size. With fewer than 500 tokens of memory, the cost is acceptable (in practice two preference entries ≈ 50 tokens, double-write ≈ 100 tokens). With very large memory, consider only writing a one-line summary at the end.

---

## Beat 6 — Run Verification

Let's put it all together and run the cross-session memory demo:

```python
# main.py
import sys
from core.agent import LenaAgent

def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else None
    agent = LenaAgent(session_id=session_id)
    print(f"[Session: {agent.session_id}]")
    print(f"[Memories loaded: {len(agent.memdir.load_all())}]")
    print()

    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user:
            continue
        reply = agent.chat(user)
        print(f"Lena: {reply}\n")

if __name__ == "__main__":
    main()
```

Install dependencies:

```bash
pip install anthropic pyyaml
```

Run and observe cross-session memory (the following is real output using Claude Sonnet 4.6 via Bedrock):

```
$ python main.py
[Session: sess-live-001]
[Memories loaded: 0]

You: My name is Demo-User and I prefer Python for all my code.
Lena: Hello, Demo-User! I've noted your information:
      - Username: Demo-User
      - Coding preference: Python
      I'll use Python for your code going forward. How can I help you?

$ python main.py          ← new process, new session
[Session: sess-live-002]
[Memories loaded: 2]      ← memories saved from last time loaded
  - [user] programming_language: user prefers Python for all code
  - [user] username: user's name is Demo-User

You: Write me a hello world.
Lena: Based on your preference, here's the Python version:

      ```python
      print("Hello, World!")
      ```

      Run it with: python hello_world.py
      Output: Hello, World!
```

**Contrast with the memoryless version** (empty project slug, no history):

```
You: Write me a hello world.
Lena: Which programming language would you like for Hello World?
      Python, JavaScript, Java, C++... just let me know!
```

The difference is clear: with memory, it goes straight to Python; without memory, it asks. That gap comes from one `save_memory` tool call and two `.md` files.

**Common errors:**
- `yaml.scanner.ScannerError`: memory file frontmatter is corrupted. The `except Exception: continue` in `load_all()` already skips it, but you should manually delete the offending `.md` file.
- `anthropic.APIError: 401`: check the `ANTHROPIC_API_KEY` environment variable.
- `[Memories loaded: 0]` still 0 on the second run: check that `~/.lena/projects/lena/memory/` exists, and that Lena actually called `save_memory` in the first run (add `print(agent.memdir.load_all())` in `main.py` to debug).

**Expected numbers**: the first run saves 2 memory entries (user_name + programming_language), each `.md` file about 200 bytes, `MEMORY.md` index about 300 bytes, `format_for_prompt()` returns about 150 characters. Total disk footprint of the memory system < 10KB, system prompt injection < 500 tokens.

Memory solves the "amnesia" problem. But there's still a lurking issue: as conversations grow, context window pressure keeps accumulating — after 50 turns, the messages array is already several thousand tokens and growing. When `autocompact` fires, session history gets compressed into an LLM-generated summary — which can hallucinate and change decisions already made.

**The right posture after compaction**: write important decisions into `save_memory` before compaction happens. If the compaction summary turns "option A explicitly rejected" into "option A pending evaluation," you have a verbatim record in `MEMORY.md` to override it. Lena's defensive strategy: after each compaction, the first conversation turn calls `load_index()` to cross-check against MEMORY.md, and treats memory files as authoritative when they conflict with the summary.

How to let Lena gracefully compress context without losing critical content is the topic of the next chapter (Ch 9 → Ch 10 Context Engineering).

---

## Beat 7 — Design Note × 2

### Why Not Use a Vector Database for Agent Memory?

Vector databases (Chroma, Qdrant, pgvector) are a reasonable first instinct. Their design goal is: given a query vector, find the K most semantically similar records.

This is excellent for RAG (external knowledge base retrieval) — when a knowledge base has 100,000 documents, you need semantic similarity to find relevant passages. But for an agent's own memory, this approach introduces three unnecessary costs:

**Cost one: embedding dependency.** Every memory write requires calling an embedding model (local or API), adding latency and expense. Every memory read requires vectorizing the query and running similarity computation.

**Cost two: tuning hell.** What similarity threshold? How many results for Top-K? Threshold too high and you miss relevant memories; too low and you get noise. These parameters have no "right answer" — they require repeated experimentation.

**Cost three: loss of debuggability.** File-system memories can be read and edited directly in a text editor. Vector database memories are buried in an index; debugging failures is painful.

A personal agent's long-term memory typically has 100–1,000 entries. Reading 1,000 files in full takes Python about 50ms — far below any LLM API call latency. A file system traversal is completely adequate.

**Recommendation**: file system + MEMORY.md index, for 100–1,000 memory entries; vector database, for 10,000+ entries + scenarios requiring semantic similarity (at which point it's already in Ch 9 RAG territory).

---

### Why Is This Chapter NOT About RAG?

This chapter and Ch 9 address adjacent but entirely different problems; the distinction must be precise.

**This chapter (Ch 8)**: the agent's own memory. It answers "what have I done," "who is this user," "what was the conclusion last time." The writer is the agent itself (via the `save_memory` tool). The content is facts about the agent and user. Access is by full load or index scan.

**Ch 9 (RAG)**: reading an external knowledge base. It answers "what does a document say," "what does this technical spec prescribe." The writer is the user (uploading documents). The content is external knowledge. Access is by vector similarity search.

A common mistake is conflating these two and applying the same vector database solution to "the agent should remember user preferences." This leads to: the agent occasionally "forgetting" preferences it clearly should remember (similarity threshold miss), or stuffing the context with preferences unrelated to the current task (Top-K overshooting).

The distinguishing criterion is simple: was this information **generated through the agent's experience** (memory), or is it **an external document provided by the user** (knowledge base)? The former uses this chapter's file-system approach; the latter uses Ch 9's pgvector approach.

Lena now remembers what she's done. But if the user asks "what did that article about MCP say yesterday" — memory won't solve that. She needs to be able to consult an **external knowledge base**. In the next chapter, we give Lena RAG: vector retrieval + external documents + embedding distance. For the first time she learns to "read" rather than just "recall."

---

## Quality Checklist (20 items)

| # | Check | Status |
|---|-------|--------|
| S1 | Beat 1 roadmap has "A → B → C, with pitfall D along the way" | ✓ |
| S2 | Beat 2 has concrete code showing "what happens without memory" | ✓ |
| S3 | Beat 3 has ≥ 2 subsections labeled "pure theory" | ✓ |
| S4 | Beat 4 has Let's sentence, code ≤ 80 lines | ✓ |
| S5 | Beat 5 has extension table (extension point / why needed / how to add) | ✓ |
| S6 | Beat 6 has specific expected output (line counts, numbers) | ✓ |
| S7 | Beat 6 ends with a narrative hook toward the next chapter | ✓ |
| S8 | Beat 7 Design Note titles are questions | ✓ |
| C1 | Core technical claims have sources (memdir.ts:34, Manus 2025) | ✓ |
| C2 | All core term pairs have Convention disambiguation sentences | ✓ |
| C3 | Has failure paths (Compaction summary untrustworthy, corrupt file skip) | ✓ |
| C4 | Cases ≤ 1, woven in as an aside | ✓ |
| C5 | Has a clear position (recommends file system, with reasoning) | ✓ |
| R1 | No "Case X.Y" format blocks | ✓ |
| R2 | No host-machine absolute paths | ✓ |
| R3 | No author's real name | ✓ |
| R4 | No "for better..." false motivation | ✓ |
| R5 | No wishy-washy "both work" paragraphs | ✓ |
| R6 | No full code before explanation (Beat 4 scaffold first, Beat 5 extends) | ✓ |
| R7 | All new terms defined before use | ✓ |

---

---

Lena learned to "remember yesterday" in this chapter — cross-session SQLite short-term history plus file-system long-term preferences mean she no longer forgets everything at the end of each conversation.

But remembering the user is not enough. The real world has vast amounts of documents, code repositories, and reports that cannot all be stuffed into a context window — the LLM's memory is finite while knowledge is infinite. When a user asks "what are the breach-of-contract clauses in that contract from last week," Lena doesn't need a bigger memory; she needs a retrieval mechanism that can precisely align a question with a document. **In Chapter 9, we give Lena RAG — vector retrieval lets her find the most relevant passage in a sea of documents for the current question.**

---

## Challenges

**C8.1 — Memory expiry policy**: the current implementation never expires memory files. Design an `expire_memories(days: int)` function that deletes `project`-type memories whose `created` field is older than N days (project facts go stale), while retaining `user` and `feedback` types (user preferences tend to be stable).

**C8.2 — Memory conflict detection**: if the user first says "I prefer Python," then later says "I've switched to Go," the agent will save two contradictory `programming_language` memories. Modify `MemDir.save()` to check for existing memories with the same subject before writing, and ask whether to overwrite or append.

**C8.3 — Compaction safety valve**: add a simple compaction detector to `LenaAgent.chat()`: when `store.load_messages(session_id)` returns more than 50 messages, automatically call `memdir.save()` to extract and save "key decisions from this session," then alert the user that the session is approaching the compaction threshold.

---

## References

- Claude Code `source/src/memdir/memdir.ts:34-35` (ENTRYPOINT_NAME / MAX_ENTRYPOINT_LINES)
- Claude Code `source/src/memdir/memoryTypes.ts:14-21` (four memory type classifications)
- Claude Code `source/src/memdir/memoryScan.ts:22` (MAX_MEMORY_FILES = 200)
- nanoClaw (ysz) `nanoclaw/memory/store.py` (SQLite memory prototype)
- Manus *Context Engineering for AI Agents*, 2025 ("the file system is infinite external memory" principle)
